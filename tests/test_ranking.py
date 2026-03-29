from decimal import Decimal

from estate_scraper.ai.ranking import _format_items
from estate_scraper.models import Listing


class TestFormatItems:
    def test_empty_list(self):
        assert _format_items([]) == ""

    def test_single_listing(self):
        listing = Listing(
            listing_id="42",
            title="Vintage Watch",
            current_price=Decimal("100"),
            bid_count=5,
        )
        result = _format_items([listing])
        assert "ID: 42" in result
        assert "Title: Vintage Watch" in result
        assert "$100" in result
        assert "Bids: 5" in result

    def test_long_description_truncated(self):
        listing = Listing(
            listing_id="1",
            title="Item",
            description="A" * 300,
        )
        result = _format_items([listing])
        assert "..." in result
        # Description portion should be truncated to ~203 chars (200 + "...")
        desc_part = result.split("Description: ")[1]
        assert len(desc_part) <= 210

    def test_missing_optional_fields(self):
        listing = Listing(listing_id="1", title="Basic Item")
        result = _format_items([listing])
        assert "ID: 1" in result
        assert "Title: Basic Item" in result
        # Should not contain price or bids since they're missing/default
        assert "Price" not in result

    def test_multiple_listings(self):
        listings = [
            Listing(listing_id="1", title="Item A"),
            Listing(listing_id="2", title="Item B"),
        ]
        result = _format_items(listings)
        lines = result.strip().split("\n")
        assert len(lines) == 2
