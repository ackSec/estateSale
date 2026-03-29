from __future__ import annotations

from abc import ABC, abstractmethod

from estate_scraper.config import SiteConfig
from estate_scraper.models import Listing


class BaseScraper(ABC):
    def __init__(self, site_config: SiteConfig):
        self.config = site_config

    @abstractmethod
    async def scrape_listings(self, url: str) -> list[Listing]:
        """Scrape all listings from a sale/store page, including pagination."""
        ...

    @abstractmethod
    async def scrape_listing_detail(self, listing: Listing) -> Listing:
        """Visit a listing's detail page and enrich with description + full images."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Clean up browser resources."""
        ...
