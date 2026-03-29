from decimal import Decimal
from pathlib import Path

import pytest

from estate_scraper.models import Listing, ListingImage, RankedListing, Valuation, ScrapeSession


@pytest.fixture
def sample_listing() -> Listing:
    return Listing(
        listing_id="123",
        title="14k Gold Ring with Diamond",
        description="Beautiful vintage ring",
        current_price=Decimal("45.00"),
        bid_count=3,
        status="open",
        time_remaining="2h 30m",
        url="https://www.bidmaxpro.com/listing/123",
        detail_url="https://www.bidmaxpro.com/listing/123/details",
        images=[ListingImage(url="https://example.com/img1.jpg")],
        category="jewelry",
    )


@pytest.fixture
def sample_ranked(sample_listing) -> RankedListing:
    return RankedListing(
        listing=sample_listing,
        rank=1,
        estimated_value_low=Decimal("800"),
        estimated_value_high=Decimal("1200"),
        value_reasoning="Significantly undervalued gold jewelry",
        category_tags=["jewelry", "gold", "vintage"],
    )


@pytest.fixture
def sample_valuation(sample_listing) -> Valuation:
    return Valuation(
        listing=sample_listing,
        recommendation="BUY",
        authenticity_assessment="Appears genuine based on hallmarks",
        comparable_sales=["Similar ring sold for $900 on eBay"],
        special_valuations={"gold_melt_value": "$650"},
        max_bid_recommendation=Decimal("500"),
        confidence="HIGH",
        detailed_analysis="This is a genuine 14k gold ring.",
    )
