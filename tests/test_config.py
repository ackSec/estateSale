import pytest

from estate_scraper.config import detect_site, load_site_config


class TestDetectSite:
    def test_bidmaxpro(self):
        assert detect_site("https://www.bidmaxpro.com/index.php?foo=bar") == "bidmaxpro"

    def test_bidmaxpro_no_www(self):
        assert detect_site("https://bidmaxpro.com/listings") == "bidmaxpro"

    def test_unknown_domain(self):
        with pytest.raises(ValueError, match="Unknown site"):
            detect_site("https://www.ebay.com/listing/123")


class TestLoadSiteConfig:
    def test_load_bidmaxpro(self):
        config = load_site_config("bidmaxpro")
        assert config.name == "BidMaxPro"
        assert config.base_url == "https://www.bidmaxpro.com"
        assert config.selectors.listing_container == "[data-listing-id]"
        assert config.pagination.max_per_page == 80

    def test_load_nonexistent(self):
        with pytest.raises(FileNotFoundError):
            load_site_config("nonexistent_site")
