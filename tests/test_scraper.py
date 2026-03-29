from decimal import Decimal

from estate_scraper.config import load_site_config
from estate_scraper.scrapers.bidmaxpro import BidMaxProScraper


class TestParsePrice:
    def test_dollar_amount(self):
        assert BidMaxProScraper._parse_price("$1,234.56") == Decimal("1234.56")

    def test_no_currency_symbol(self):
        assert BidMaxProScraper._parse_price("1234.56") == Decimal("1234.56")

    def test_whole_number(self):
        assert BidMaxProScraper._parse_price("$50") == Decimal("50")

    def test_empty_string(self):
        assert BidMaxProScraper._parse_price("") is None

    def test_no_numbers(self):
        assert BidMaxProScraper._parse_price("No price") is None

    def test_zero(self):
        assert BidMaxProScraper._parse_price("$0.00") == Decimal("0.00")


class TestBuildPageUrl:
    def setup_method(self):
        config = load_site_config("bidmaxpro")
        self.scraper = BidMaxProScraper(config)

    def test_first_page(self):
        url = "https://www.bidmaxpro.com/index.php?module=listings&action=store&store_slug=test"
        result = self.scraper._build_page_url(url, 1)
        assert "show=80" in result
        assert "page=" not in result

    def test_second_page(self):
        url = "https://www.bidmaxpro.com/index.php?module=listings&action=store&store_slug=test"
        result = self.scraper._build_page_url(url, 2)
        assert "show=80" in result
        assert "page=2" in result

    def test_preserves_existing_params(self):
        url = "https://www.bidmaxpro.com/index.php?module=listings&store_slug=test"
        result = self.scraper._build_page_url(url, 1)
        assert "module=listings" in result
        assert "store_slug=test" in result
