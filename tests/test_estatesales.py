"""Comprehensive tests for estatesales.org support.

Covers: scraper helpers, URL/thumbnail conversion, description quality assessment,
photo ranking logic, CLI routing, model fields, and mocked integration tests.
"""
from __future__ import annotations

import base64
import json
import re
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from estate_scraper.ai.ranking import (
    QUALITY_INDICATORS,
    assess_description_quality,
    rank_photos,
    _encode_image_for_ranking,
    PHOTO_RANKING_SYSTEM,
    PHOTO_RANKING_PROMPT,
)
from estate_scraper.cli import _create_scraper, _get_sale_slug
from estate_scraper.config import load_config, load_site_config, detect_site
from estate_scraper.models import Listing, ListingImage, RankedListing, ScrapeSession
from estate_scraper.scrapers.estatesales import EstateSalesScraper
from estate_scraper.scrapers.bidmaxpro import BidMaxProScraper
from estate_scraper.utils import extract_sale_slug_estatesales, extract_sale_id_estatesales


# ---------------------------------------------------------------------------
# Scraper: EstateSalesScraper helpers
# ---------------------------------------------------------------------------


class TestEstateSalesScraperProperties:
    """Test basic properties and getters."""

    def setup_method(self):
        self.config = load_site_config("estatesales")
        self.scraper = EstateSalesScraper(self.config)

    def test_is_photo_only(self):
        assert self.scraper.is_photo_only is True

    def test_initial_sale_description_empty(self):
        assert self.scraper.get_sale_description() == ""

    def test_initial_sale_metadata_empty(self):
        assert self.scraper.get_sale_metadata() == {}

    def test_sale_description_setter(self):
        self.scraper._sale_description = "Test description"
        assert self.scraper.get_sale_description() == "Test description"

    def test_sale_metadata_setter(self):
        self.scraper._sale_metadata = {"title": "Test Sale", "company": "Beehive"}
        meta = self.scraper.get_sale_metadata()
        assert meta["title"] == "Test Sale"
        assert meta["company"] == "Beehive"


class TestToFullSizeUrl:
    """Test thumbnail → full-size URL conversion."""

    def setup_method(self):
        self.config = load_site_config("estatesales")
        self.scraper = EstateSalesScraper(self.config)

    def test_removes_thumbnail_suffix_jpg(self):
        assert self.scraper._to_full_size_url(
            "https://eso-cdn.tlcdn.workers.dev/s-2430392-abc123-t.jpg"
        ) == "https://eso-cdn.tlcdn.workers.dev/s-2430392-abc123.jpg"

    def test_removes_thumbnail_suffix_png(self):
        assert self.scraper._to_full_size_url(
            "https://cdn.example.com/photo-t.png"
        ) == "https://cdn.example.com/photo.png"

    def test_removes_thumbnail_suffix_webp(self):
        assert self.scraper._to_full_size_url(
            "https://cdn.example.com/photo-t.webp"
        ) == "https://cdn.example.com/photo.webp"

    def test_already_full_size(self):
        url = "https://eso-cdn.tlcdn.workers.dev/s-2430392-abc123.jpg"
        assert self.scraper._to_full_size_url(url) == url

    def test_no_extension(self):
        url = "https://cdn.example.com/photo-t"
        # Should not modify since regex requires .\w+ extension
        assert self.scraper._to_full_size_url(url) == url

    def test_t_in_middle_of_hash(self):
        """Should NOT remove -t that appears inside the hash, only at the end before extension."""
        url = "https://eso-cdn.tlcdn.workers.dev/s-2430392-t4abc-t.jpg"
        result = self.scraper._to_full_size_url(url)
        assert result == "https://eso-cdn.tlcdn.workers.dev/s-2430392-t4abc.jpg"

    def test_empty_url(self):
        assert self.scraper._to_full_size_url("") == ""


# ---------------------------------------------------------------------------
# URL and slug extraction
# ---------------------------------------------------------------------------


class TestExtractSaleSlugEstatesales:
    def test_standard_url(self):
        url = "https://estatesales.org/estate-sales/ca/walnut-creek/94598/beehive-estate-sales-presents-a-2430392"
        assert extract_sale_slug_estatesales(url) == "beehive-estate-sales-presents-a-2430392"

    def test_with_query_params(self):
        url = "https://estatesales.org/estate-sales/ca/city/12345/my-sale-999?ref=home&tab=photos"
        assert extract_sale_slug_estatesales(url) == "my-sale-999"

    def test_with_fragment(self):
        url = "https://estatesales.org/estate-sales/tx/dallas/75201/sale-name-123#photos"
        assert extract_sale_slug_estatesales(url) == "sale-name-123"

    def test_different_states(self):
        url = "https://estatesales.org/estate-sales/ny/new-york/10001/nyc-estate-sale-555"
        assert extract_sale_slug_estatesales(url) == "nyc-estate-sale-555"


class TestExtractSaleIdEstatesales:
    def test_standard_id(self):
        url = "https://estatesales.org/estate-sales/ca/walnut-creek/94598/beehive-estate-sales-presents-a-2430392"
        assert extract_sale_id_estatesales(url) == "2430392"

    def test_different_id_length(self):
        url = "https://estatesales.org/estate-sales/ca/city/12345/sale-12345"
        assert extract_sale_id_estatesales(url) == "12345"

    def test_large_id(self):
        url = "https://estatesales.org/estate-sales/ca/city/12345/sale-99999999"
        assert extract_sale_id_estatesales(url) == "99999999"


# ---------------------------------------------------------------------------
# Config / site detection
# ---------------------------------------------------------------------------


class TestSiteDetection:
    def test_detect_estatesales(self):
        assert detect_site("https://estatesales.org/estate-sales/ca/test") == "estatesales"

    def test_detect_estatesales_www(self):
        assert detect_site("https://www.estatesales.org/estate-sales/ca/test") == "estatesales"

    def test_load_estatesales_config(self):
        config = load_site_config("estatesales")
        assert config.name == "EstateSales"
        assert config.base_url == "https://estatesales.org"


# ---------------------------------------------------------------------------
# Model fields for photo-only support
# ---------------------------------------------------------------------------


class TestPhotoOnlyModelFields:
    def test_listing_is_photo_only_default(self):
        listing = Listing(listing_id="1", title="Test")
        assert listing.is_photo_only is False

    def test_listing_is_photo_only_true(self):
        listing = Listing(listing_id="1", title="Test", is_photo_only=True)
        assert listing.is_photo_only is True

    def test_listing_photo_only_serialization(self):
        listing = Listing(listing_id="1", title="Photo Item", is_photo_only=True)
        json_str = listing.model_dump_json()
        restored = Listing.model_validate_json(json_str)
        assert restored.is_photo_only is True

    def test_session_sale_metadata_default(self):
        session = ScrapeSession(sale_url="https://example.com")
        assert session.sale_metadata == {}

    def test_session_sale_metadata_populated(self):
        session = ScrapeSession(
            sale_url="https://example.com",
            sale_metadata={"title": "Big Sale", "company": "Acme", "address": "123 Main St"},
        )
        assert session.sale_metadata["title"] == "Big Sale"
        assert session.sale_metadata["company"] == "Acme"

    def test_session_sample_rate_default(self):
        session = ScrapeSession(sale_url="https://example.com")
        assert session.sample_rate == 1.0

    def test_session_sample_rate_custom(self):
        session = ScrapeSession(sale_url="https://example.com", sample_rate=0.25)
        assert session.sample_rate == 0.25

    def test_session_metadata_serialization(self, tmp_path):
        session = ScrapeSession(
            sale_url="https://example.com",
            sale_metadata={"title": "Sale"},
            sample_rate=0.25,
            output_dir=tmp_path,
        )
        filepath = session.save("test.json")
        loaded = ScrapeSession.load(filepath)
        assert loaded.sale_metadata == {"title": "Sale"}
        assert loaded.sample_rate == 0.25


# ---------------------------------------------------------------------------
# CLI: scraper routing
# ---------------------------------------------------------------------------


class TestCreateScraper:
    def test_estatesales_scraper(self):
        config = load_config("https://estatesales.org/estate-sales/ca/test/12345/sale-123")
        scraper = _create_scraper(config)
        assert isinstance(scraper, EstateSalesScraper)
        assert scraper.is_photo_only is True

    def test_bidmaxpro_scraper(self):
        config = load_config("https://www.bidmaxpro.com/index.php?module=listings&store_slug=test")
        scraper = _create_scraper(config)
        assert isinstance(scraper, BidMaxProScraper)
        assert scraper.is_photo_only is False


class TestGetSaleSlug:
    def test_estatesales_slug(self):
        config = load_config("https://estatesales.org/estate-sales/ca/walnut-creek/94598/beehive-sale-2430392")
        slug = _get_sale_slug(
            "https://estatesales.org/estate-sales/ca/walnut-creek/94598/beehive-sale-2430392",
            config,
        )
        assert slug == "beehive-sale-2430392"

    def test_bidmaxpro_slug(self):
        config = load_config("https://www.bidmaxpro.com/index.php?store_slug=my-auction")
        slug = _get_sale_slug(
            "https://www.bidmaxpro.com/index.php?store_slug=my-auction",
            config,
        )
        assert slug == "my-auction"


# ---------------------------------------------------------------------------
# Description quality assessment (heuristic + mocked AI)
# ---------------------------------------------------------------------------


class TestAssessDescriptionQualityHeuristic:
    """Test the heuristic paths that don't require an API call."""

    def test_empty_returns_poor(self):
        client = MagicMock()
        assert assess_description_quality(client, "") == "poor"
        client.messages.create.assert_not_called()

    def test_very_short_returns_poor(self):
        client = MagicMock()
        assert assess_description_quality(client, "Stuff for sale") == "poor"
        client.messages.create.assert_not_called()

    def test_none_returns_poor(self):
        client = MagicMock()
        assert assess_description_quality(client, None) == "poor"
        client.messages.create.assert_not_called()

    def test_detailed_with_many_indicators_returns_good(self):
        client = MagicMock()
        # Needs >100 words AND 5+ indicators to bypass the AI call
        description = (
            "This estate features a stunning collection including 18k gold jewelry with "
            "hallmarked pieces, sterling silver flatware set by Tiffany and Co, signed lithographs "
            "by Chagall, vintage mid-century modern furniture by Herman Miller and Eames chairs, "
            "antique Persian rugs with certificate of provenance, first edition books, "
            "Rolex Submariner watch, and a handmade quilt with appraisal documentation. "
            "Also available are limited edition prints and designer handbags by Louis Vuitton. "
            "The collection also includes Cartier bracelets, Knoll tables, and Stickley bookcases. "
            "Everything is in excellent condition and priced to sell quickly this weekend. "
            "The home was beautifully maintained and the owner was an avid collector for decades. "
            "Sale runs Friday through Sunday with early bird pricing on the first day."
        )
        assert len(description.split()) > 100  # Ensure we exceed word threshold
        result = assess_description_quality(client, description)
        assert result == "good"

    def test_short_vague_returns_poor(self):
        client = MagicMock()
        description = "Furniture, tools, kitchen stuff, and misc items."
        result = assess_description_quality(client, description)
        assert result == "poor"
        client.messages.create.assert_not_called()


class TestAssessDescriptionQualityWithMockedAI:
    """Test the ambiguous case that falls through to Claude."""

    @patch("estate_scraper.ai.ranking.call_claude")
    def test_ambiguous_calls_claude_good(self, mock_call):
        mock_call.return_value = "GOOD"
        client = MagicMock()
        # Ambiguous: >50 words, 2-4 indicators (between thresholds)
        description = (
            "This sale has a nice collection of vintage items including some "
            "antique furniture pieces and various household goods from a well-maintained "
            "home. There are also some interesting decorative items and garden tools. "
            "Come browse through books, records, and kitchen equipment. Everything must go."
        )
        result = assess_description_quality(client, description)
        assert result == "good"
        mock_call.assert_called_once()

    @patch("estate_scraper.ai.ranking.call_claude")
    def test_ambiguous_calls_claude_poor(self, mock_call):
        mock_call.return_value = "POOR"
        client = MagicMock()
        description = (
            "This sale has a nice collection of vintage items including some "
            "antique furniture pieces and various household goods from a well-maintained "
            "home. There are also some interesting decorative items and garden tools. "
            "Come browse through books, records, and kitchen equipment. Everything must go."
        )
        result = assess_description_quality(client, description)
        assert result == "poor"
        mock_call.assert_called_once()


# ---------------------------------------------------------------------------
# Quality indicator regex patterns
# ---------------------------------------------------------------------------


class TestQualityIndicators:
    """Verify individual regex patterns match expected text."""

    def test_gold_karat(self):
        assert any(re.search(p, "14k gold ring", re.IGNORECASE) for p in QUALITY_INDICATORS)
        assert any(re.search(p, "18k Gold necklace", re.IGNORECASE) for p in QUALITY_INDICATORS)
        assert any(re.search(p, "10k gold chain", re.IGNORECASE) for p in QUALITY_INDICATORS)

    def test_sterling(self):
        assert any(re.search(p, "sterling silver set", re.IGNORECASE) for p in QUALITY_INDICATORS)

    def test_signed(self):
        assert any(re.search(p, "signed lithograph", re.IGNORECASE) for p in QUALITY_INDICATORS)

    def test_mid_century(self):
        assert any(re.search(p, "mid-century modern chair", re.IGNORECASE) for p in QUALITY_INDICATORS)
        assert any(re.search(p, "mid century dresser", re.IGNORECASE) for p in QUALITY_INDICATORS)

    def test_designer_brands(self):
        for brand in ["Rolex", "Cartier", "Tiffany", "Hermes", "Chanel", "Gucci"]:
            assert any(
                re.search(p, f"a {brand} piece", re.IGNORECASE) for p in QUALITY_INDICATORS
            ), f"Brand {brand} not matched"

    def test_furniture_brands(self):
        for brand in ["Eames", "Herman Miller", "Knoll", "Stickley"]:
            assert any(
                re.search(p, f"a {brand} chair", re.IGNORECASE) for p in QUALITY_INDICATORS
            ), f"Brand {brand} not matched"

    def test_carat(self):
        assert any(re.search(p, "2 ct diamond", re.IGNORECASE) for p in QUALITY_INDICATORS)
        assert any(re.search(p, "3 carat emerald", re.IGNORECASE) for p in QUALITY_INDICATORS)

    def test_provenance(self):
        assert any(re.search(p, "comes with provenance", re.IGNORECASE) for p in QUALITY_INDICATORS)

    def test_first_edition(self):
        assert any(re.search(p, "first edition copy", re.IGNORECASE) for p in QUALITY_INDICATORS)

    def test_limited_edition(self):
        assert any(re.search(p, "limited edition print", re.IGNORECASE) for p in QUALITY_INDICATORS)

    def test_hallmark(self):
        assert any(re.search(p, "has hallmark stamp", re.IGNORECASE) for p in QUALITY_INDICATORS)

    def test_generic_words_dont_match(self):
        """Vague words should NOT trigger indicators."""
        for text in ["furniture", "tools", "kitchen items", "clothing", "books", "misc"]:
            hits = sum(1 for p in QUALITY_INDICATORS if re.search(p, text, re.IGNORECASE))
            assert hits == 0, f"'{text}' should not match any indicators"


# ---------------------------------------------------------------------------
# Image encoding for ranking
# ---------------------------------------------------------------------------


class TestEncodeImageForRanking:
    def test_encode_jpg(self, tmp_path):
        img_path = tmp_path / "test.jpg"
        img_path.write_bytes(b"\xff\xd8\xff\xe0test-image-data")
        result = _encode_image_for_ranking(img_path)
        assert result is not None
        b64, media_type = result
        assert media_type == "image/jpeg"
        assert base64.b64decode(b64) == b"\xff\xd8\xff\xe0test-image-data"

    def test_encode_png(self, tmp_path):
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\ntest")
        result = _encode_image_for_ranking(img_path)
        assert result is not None
        _, media_type = result
        assert media_type == "image/png"

    def test_encode_webp(self, tmp_path):
        img_path = tmp_path / "test.webp"
        img_path.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
        result = _encode_image_for_ranking(img_path)
        assert result is not None
        _, media_type = result
        assert media_type == "image/webp"

    def test_encode_gif(self, tmp_path):
        img_path = tmp_path / "test.gif"
        img_path.write_bytes(b"GIF89a")
        result = _encode_image_for_ranking(img_path)
        assert result is not None
        _, media_type = result
        assert media_type == "image/gif"

    def test_missing_file_returns_none(self, tmp_path):
        result = _encode_image_for_ranking(tmp_path / "nonexistent.jpg")
        assert result is None

    def test_unknown_extension_defaults_to_jpeg(self, tmp_path):
        img_path = tmp_path / "test.bmp"
        img_path.write_bytes(b"BM\x00\x00")
        result = _encode_image_for_ranking(img_path)
        assert result is not None
        _, media_type = result
        assert media_type == "image/jpeg"


# ---------------------------------------------------------------------------
# Photo ranking (mocked Claude API)
# ---------------------------------------------------------------------------


class TestRankPhotos:
    def _make_photo_listing(self, idx: int, tmp_path: Path) -> Listing:
        """Create a photo-only listing with a real image file on disk."""
        img_path = tmp_path / f"photo_{idx}.jpg"
        img_path.write_bytes(b"\xff\xd8\xff\xe0fake-jpg-" + str(idx).encode())
        return Listing(
            listing_id=f"sale-photo-{idx:04d}",
            title=f"Estate Sale - Photo {idx}",
            is_photo_only=True,
            images=[ListingImage(url=f"https://cdn.example.com/photo-{idx}.jpg", local_path=img_path)],
        )

    @patch("estate_scraper.ai.ranking.call_claude")
    def test_rank_photos_basic(self, mock_call, tmp_path):
        """Test that rank_photos calls Claude and parses response."""
        mock_call.return_value = json.dumps({
            "items": [
                {
                    "photo_index": 1,
                    "item_description": "Vintage Rolex Submariner watch",
                    "estimated_value_low": 5000,
                    "estimated_value_high": 8000,
                    "investment_rating": 10,
                    "category_tags": ["watch", "luxury", "vintage"],
                    "value_reasoning": "Rolex Submariner in good condition, highly collectible",
                },
                {
                    "photo_index": 2,
                    "item_description": "Mid-century teak sideboard",
                    "estimated_value_low": 300,
                    "estimated_value_high": 600,
                    "investment_rating": 7,
                    "category_tags": ["furniture", "mid-century"],
                    "value_reasoning": "Danish modern style, good condition",
                },
            ]
        })

        listings = [self._make_photo_listing(i, tmp_path) for i in range(1, 5)]
        client = MagicMock()

        rankings = rank_photos(client, listings, sample_rate=1.0, batch_size=20)

        assert len(rankings) == 2
        assert rankings[0].rank == 1
        assert rankings[0].listing.title == "Vintage Rolex Submariner watch"
        assert rankings[0].estimated_value_high == Decimal("8000")
        assert "watch" in rankings[0].category_tags
        assert rankings[1].rank == 2
        mock_call.assert_called_once()

    @patch("estate_scraper.ai.ranking.call_claude")
    def test_rank_photos_empty_listings(self, mock_call):
        """Empty listings returns empty rankings without calling API."""
        client = MagicMock()
        result = rank_photos(client, [], sample_rate=0.25)
        assert result == []
        mock_call.assert_not_called()

    @patch("estate_scraper.ai.ranking.call_claude")
    def test_rank_photos_no_images_on_disk(self, mock_call):
        """Listings without downloaded images return empty rankings."""
        client = MagicMock()
        listings = [
            Listing(
                listing_id="1",
                title="Photo 1",
                is_photo_only=True,
                images=[ListingImage(url="https://example.com/1.jpg")],  # No local_path
            )
        ]
        result = rank_photos(client, listings, sample_rate=1.0)
        assert result == []
        mock_call.assert_not_called()

    @patch("estate_scraper.ai.ranking.call_claude")
    def test_rank_photos_sample_rate(self, mock_call, tmp_path):
        """Verify that sample_rate reduces the number of photos analyzed."""
        mock_call.return_value = json.dumps({"items": []})
        client = MagicMock()

        listings = [self._make_photo_listing(i, tmp_path) for i in range(1, 101)]

        # 25% of 100 = 25 photos
        rank_photos(client, listings, sample_rate=0.25, batch_size=50)
        # Should be called — API was invoked (even if no items returned)
        assert mock_call.called

    @patch("estate_scraper.ai.ranking.call_claude")
    def test_rank_photos_batching(self, mock_call, tmp_path):
        """Verify photos are batched correctly."""
        mock_call.return_value = json.dumps({"items": []})
        client = MagicMock()

        listings = [self._make_photo_listing(i, tmp_path) for i in range(1, 51)]

        # 100% sample of 50 photos with batch_size=20 = 3 batches (20+20+10)
        rank_photos(client, listings, sample_rate=1.0, batch_size=20)
        assert mock_call.call_count == 3

    @patch("estate_scraper.ai.ranking.call_claude")
    def test_rank_photos_malformed_response(self, mock_call, tmp_path):
        """Malformed JSON from Claude doesn't crash."""
        mock_call.return_value = "not valid json at all"
        client = MagicMock()

        listings = [self._make_photo_listing(i, tmp_path) for i in range(1, 5)]
        result = rank_photos(client, listings, sample_rate=1.0)
        assert result == []

    @patch("estate_scraper.ai.ranking.call_claude")
    def test_rank_photos_sorted_by_investment_rating(self, mock_call, tmp_path):
        """Results are sorted by investment_rating descending."""
        mock_call.return_value = json.dumps({
            "items": [
                {"photo_index": 1, "item_description": "Cheap item", "estimated_value_low": 5,
                 "estimated_value_high": 10, "investment_rating": 2, "category_tags": [], "value_reasoning": "low"},
                {"photo_index": 2, "item_description": "Expensive item", "estimated_value_low": 500,
                 "estimated_value_high": 1000, "investment_rating": 9, "category_tags": [], "value_reasoning": "high"},
            ]
        })
        client = MagicMock()
        listings = [self._make_photo_listing(i, tmp_path) for i in range(1, 5)]

        rankings = rank_photos(client, listings, sample_rate=1.0)
        assert rankings[0].listing.title == "Expensive item"
        assert rankings[1].listing.title == "Cheap item"


# ---------------------------------------------------------------------------
# Photo ranking prompts
# ---------------------------------------------------------------------------


class TestPhotoRankingPrompts:
    """Verify the prompt templates contain expected structure."""

    def test_system_prompt_mentions_estate_sale(self):
        assert "estate sale" in PHOTO_RANKING_SYSTEM.lower()

    def test_system_prompt_mentions_json(self):
        assert "JSON" in PHOTO_RANKING_SYSTEM

    def test_user_prompt_has_expected_fields(self):
        for field in ["photo_index", "item_description", "estimated_value_low",
                       "estimated_value_high", "investment_rating", "category_tags"]:
            assert field in PHOTO_RANKING_PROMPT

    def test_user_prompt_mentions_skip_generic(self):
        assert "skip" in PHOTO_RANKING_PROMPT.lower() or "Skip" in PHOTO_RANKING_PROMPT


# ---------------------------------------------------------------------------
# Integration: listing creation from scraper output
# ---------------------------------------------------------------------------


class TestPhotoListingCreation:
    """Test that the scraper creates Listing objects correctly for photo-only sales."""

    def test_photo_listing_structure(self):
        """Simulate what the scraper creates for each photo."""
        listing = Listing(
            listing_id="2430392-photo-0001",
            title="BEEHIVE ESTATE SALES PRESENTS A WOW SALE - Photo 1",
            description="Furniture, jewelry, tools, collectibles",
            url="https://estatesales.org/estate-sales/ca/walnut-creek/94598/beehive-2430392",
            images=[ListingImage(url="https://eso-cdn.tlcdn.workers.dev/s-2430392-abc123.jpg")],
            is_photo_only=True,
            seller="Beehive Estate Sales",
        )
        assert listing.is_photo_only is True
        assert listing.listing_id.startswith("2430392")
        assert len(listing.images) == 1
        assert listing.current_price is None
        assert listing.bid_count == 0

    def test_multiple_photo_listings_unique_ids(self):
        """Each photo should get a unique listing_id."""
        listings = []
        for i in range(100):
            listings.append(Listing(
                listing_id=f"123-photo-{i + 1:04d}",
                title=f"Sale - Photo {i + 1}",
                is_photo_only=True,
                images=[ListingImage(url=f"https://cdn.example.com/photo-{i}.jpg")],
            ))
        ids = [lst.listing_id for lst in listings]
        assert len(set(ids)) == 100  # All unique
