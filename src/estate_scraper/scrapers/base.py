from __future__ import annotations

from abc import ABC, abstractmethod

from estate_scraper.config import SiteConfig
from estate_scraper.models import Listing


class BaseScraper(ABC):
    def __init__(self, site_config: SiteConfig):
        self.config = site_config

    @property
    def is_photo_only(self) -> bool:
        """Return True if this scraper produces photo-only listings (no item-level data)."""
        return False

    @abstractmethod
    async def scrape_listings(self, url: str) -> list[Listing]:
        """Scrape all listings from a sale/store page, including pagination."""
        ...

    async def scrape_listing_detail(self, listing: Listing) -> Listing:
        """Visit a listing's detail page and enrich with description + full images.
        Default no-op for sites without detail pages."""
        return listing

    async def scrape_all_details(self, listings: list[Listing], concurrency: int = 3) -> list[Listing]:
        """Scrape detail pages for all listings. Default no-op for photo-only scrapers."""
        return listings

    def get_sale_description(self) -> str:
        """Return the sale-level description text, if any. Used for quality assessment."""
        return ""

    @abstractmethod
    async def close(self) -> None:
        """Clean up browser resources."""
        ...
