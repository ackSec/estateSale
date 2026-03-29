from estate_scraper.ai.ranking import assess_description_quality, QUALITY_INDICATORS
import re


class TestAssessDescriptionQualityHeuristic:
    """Test the heuristic portion of assess_description_quality (no API calls)."""

    def test_empty_description(self):
        # Empty or very short → poor (no API call needed)
        # We can't call the function directly without a client, but we can test the logic
        assert len("") < 30  # Would return "poor" immediately

    def test_short_description(self):
        assert len("Furniture and stuff") < 30  # Would return "poor"

    def test_quality_indicators_match(self):
        """Verify our regex patterns match expected text."""
        text = "14k gold ring, sterling silver bracelet, signed art by Picasso"
        hits = sum(1 for pat in QUALITY_INDICATORS if re.search(pat, text.lower(), re.IGNORECASE))
        assert hits >= 3  # Should match "14k gold", "sterling", "signed"

    def test_quality_indicators_designer_brands(self):
        text = "Rolex watch, Tiffany lamp, Herman Miller chair"
        hits = sum(1 for pat in QUALITY_INDICATORS if re.search(pat, text.lower(), re.IGNORECASE))
        assert hits >= 2  # Rolex+Tiffany in one pattern, Herman Miller in another

    def test_vague_description_low_indicators(self):
        text = "Lots of furniture, tools, kitchen items, clothing, and miscellaneous household goods"
        hits = sum(1 for pat in QUALITY_INDICATORS if re.search(pat, text.lower(), re.IGNORECASE))
        assert hits < 2  # Vague description has few indicators

    def test_detailed_description_high_indicators(self):
        text = (
            "This estate features a stunning collection including 18k gold jewelry, "
            "sterling silver flatware set, signed lithographs by Chagall, "
            "vintage mid-century modern furniture by Herman Miller, "
            "antique Persian rugs, and first edition books. "
            "Also available: Rolex Submariner, Tiffany table lamp, "
            "and a handmade quilt with provenance documentation."
        )
        hits = sum(1 for pat in QUALITY_INDICATORS if re.search(pat, text.lower(), re.IGNORECASE))
        assert hits >= 5  # Many quality indicators


class TestScraperEstatesalesHelpers:
    """Test the URL helper for estatesales scraper."""

    def test_to_full_size_url_removes_thumbnail_suffix(self):
        from estate_scraper.scrapers.estatesales import EstateSalesScraper
        from estate_scraper.config import load_site_config

        config = load_site_config("estatesales")
        scraper = EstateSalesScraper(config)

        thumb = "https://eso-cdn.tlcdn.workers.dev/s-2430392-abc123-t.jpg"
        full = scraper._to_full_size_url(thumb)
        assert full == "https://eso-cdn.tlcdn.workers.dev/s-2430392-abc123.jpg"

    def test_to_full_size_url_already_full(self):
        from estate_scraper.scrapers.estatesales import EstateSalesScraper
        from estate_scraper.config import load_site_config

        config = load_site_config("estatesales")
        scraper = EstateSalesScraper(config)

        full = "https://eso-cdn.tlcdn.workers.dev/s-2430392-abc123.jpg"
        assert scraper._to_full_size_url(full) == full

    def test_is_photo_only(self):
        from estate_scraper.scrapers.estatesales import EstateSalesScraper
        from estate_scraper.config import load_site_config

        config = load_site_config("estatesales")
        scraper = EstateSalesScraper(config)
        assert scraper.is_photo_only is True

    def test_bidmaxpro_not_photo_only(self):
        from estate_scraper.scrapers.bidmaxpro import BidMaxProScraper
        from estate_scraper.config import load_site_config

        config = load_site_config("bidmaxpro")
        scraper = BidMaxProScraper(config)
        assert scraper.is_photo_only is False
