from decimal import Decimal
from pathlib import Path

import pytest

from estate_scraper.models import Listing, ListingImage, RankedListing, Valuation, ScrapeSession


class TestListing:
    def test_create_with_defaults(self):
        listing = Listing(listing_id="1", title="Test Item")
        assert listing.bid_count == 0
        assert listing.images == []
        assert listing.description == ""
        assert listing.current_price is None

    def test_create_with_all_fields(self, sample_listing):
        assert sample_listing.listing_id == "123"
        assert sample_listing.current_price == Decimal("45.00")
        assert len(sample_listing.images) == 1

    def test_json_roundtrip(self, sample_listing):
        json_str = sample_listing.model_dump_json()
        restored = Listing.model_validate_json(json_str)
        assert restored.listing_id == sample_listing.listing_id
        assert restored.title == sample_listing.title
        assert restored.current_price == sample_listing.current_price


class TestValuation:
    def test_valid_recommendations(self):
        for rec in ["BUY", "INVESTIGATE FURTHER", "PASS"]:
            v = Valuation(
                listing=Listing(listing_id="1", title="Test"),
                recommendation=rec,
            )
            assert v.recommendation == rec

    def test_invalid_recommendation_rejected(self):
        with pytest.raises(Exception):
            Valuation(
                listing=Listing(listing_id="1", title="Test"),
                recommendation="MAYBE",
            )

    def test_valid_confidence_levels(self):
        for conf in ["HIGH", "MEDIUM", "LOW"]:
            v = Valuation(
                listing=Listing(listing_id="1", title="Test"),
                recommendation="BUY",
                confidence=conf,
            )
            assert v.confidence == conf


class TestScrapeSession:
    def test_save_and_load(self, tmp_path, sample_listing):
        session = ScrapeSession(
            sale_url="https://example.com",
            sale_slug="test-sale",
            output_dir=tmp_path,
            listings=[sample_listing],
        )
        filepath = session.save("test.json")
        assert filepath.exists()

        loaded = ScrapeSession.load(filepath)
        assert loaded.sale_url == session.sale_url
        assert len(loaded.listings) == 1
        assert loaded.listings[0].title == sample_listing.title

    def test_save_creates_directories(self, tmp_path, sample_listing):
        session = ScrapeSession(
            sale_url="https://example.com",
            output_dir=tmp_path / "nested" / "dir",
            listings=[sample_listing],
        )
        filepath = session.save("data.json")
        assert filepath.exists()
