from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urljoin

from playwright.async_api import Browser, Page, async_playwright
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from estate_scraper.config import SiteConfig
from estate_scraper.models import Listing, ListingImage
from estate_scraper.scrapers.base import BaseScraper

console = Console()


class EstateSalesScraper(BaseScraper):
    def __init__(self, site_config: SiteConfig):
        super().__init__(site_config)
        self._playwright = None
        self._browser: Browser | None = None
        self._sale_description: str = ""
        self._sale_metadata: dict[str, str] = {}

    @property
    def is_photo_only(self) -> bool:
        return True

    def get_sale_description(self) -> str:
        return self._sale_description

    def get_sale_metadata(self) -> dict[str, str]:
        return self._sale_metadata

    async def _ensure_browser(self) -> Browser:
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
        return self._browser

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _extract_sale_metadata(self, page: Page) -> dict[str, str]:
        """Extract sale-level metadata from the page."""
        metadata: dict[str, str] = {}

        # Title
        try:
            title_el = await page.query_selector("h1")
            if title_el:
                metadata["title"] = (await title_el.inner_text()).strip()
        except Exception:
            pass

        # Try to extract from window.pageData if available
        try:
            page_data = await page.evaluate("() => window.pageData || null")
            if page_data and isinstance(page_data, dict):
                if "listing_id" in page_data:
                    metadata["listing_id"] = str(page_data["listing_id"])
                if "listing_member_id" in page_data:
                    metadata["member_id"] = str(page_data["listing_member_id"])
        except Exception:
            pass

        # Dates
        try:
            date_els = await page.query_selector_all("li")
            dates = []
            for el in date_els:
                text = (await el.inner_text()).strip()
                if any(day in text for day in ["Mon,", "Tue,", "Wed,", "Thu,", "Fri,", "Sat,", "Sun,"]):
                    dates.append(text)
            if dates:
                metadata["dates"] = " | ".join(dates[:5])
        except Exception:
            pass

        # Address
        try:
            # Look for structured address data
            address_text = await page.evaluate("""
                () => {
                    const els = document.querySelectorAll('[class*="address"], .address, [itemprop="address"]');
                    for (const el of els) {
                        const text = el.innerText.trim();
                        if (text.length > 5) return text;
                    }
                    return null;
                }
            """)
            if address_text:
                metadata["address"] = address_text
        except Exception:
            pass

        # Company
        try:
            company_text = await page.evaluate("""
                () => {
                    const els = document.querySelectorAll('[class*="company"], a[href*="/companies/"]');
                    for (const el of els) {
                        const text = el.innerText.trim();
                        if (text.length > 2) return text;
                    }
                    return null;
                }
            """)
            if company_text:
                metadata["company"] = company_text
        except Exception:
            pass

        # Description
        try:
            desc_text = await page.evaluate("""
                () => {
                    const selectors = [
                        '.sale-description', '.description', '[class*="description"]',
                        '.listing-description', '#description'
                    ];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el) {
                            const text = el.innerText.trim();
                            if (text.length > 20) return text;
                        }
                    }
                    // Fallback: look for long text blocks in the main content
                    const paragraphs = document.querySelectorAll('p');
                    for (const p of paragraphs) {
                        const text = p.innerText.trim();
                        if (text.length > 100) return text;
                    }
                    return '';
                }
            """)
            if desc_text:
                metadata["description"] = desc_text
                self._sale_description = desc_text
        except Exception:
            pass

        self._sale_metadata = metadata
        return metadata

    async def _extract_photo_urls(self, page: Page) -> list[str]:
        """Extract all photo URLs from the gallery, handling pagination."""
        photo_urls: list[str] = []
        seen: set[str] = set()

        # Extract photos from current page
        async def _get_page_photos() -> list[str]:
            urls = []
            # Try multiple selectors for photo elements
            photos = await page.evaluate("""
                () => {
                    const urls = [];
                    // Direct img tags in gallery
                    const imgs = document.querySelectorAll(
                        'img[alt="Estate sale photo"], .photo-gallery img, .photos img, img[src*="eso-cdn"]'
                    );
                    for (const img of imgs) {
                        const src = img.src || img.getAttribute('data-src') || '';
                        if (src && !src.includes('data:image')) urls.push(src);
                    }
                    // Links to individual photos
                    const links = document.querySelectorAll('a[href*="/photos/"]');
                    for (const a of links) {
                        const img = a.querySelector('img');
                        if (img) {
                            const src = img.src || img.getAttribute('data-src') || '';
                            if (src && !src.includes('data:image')) urls.push(src);
                        }
                    }
                    return urls;
                }
            """)
            return photos or []

        # Scroll to trigger any lazy loading
        await self._scroll_page(page)
        await asyncio.sleep(1)

        page_photos = await _get_page_photos()
        for url in page_photos:
            full_url = self._to_full_size_url(url)
            if full_url not in seen:
                seen.add(full_url)
                photo_urls.append(full_url)

        # Check for pagination — look for "next" or page number links
        page_num = 1
        max_pages = 50  # Safety limit

        while page_num < max_pages:
            # Look for a next page link or numbered pagination
            next_url = await page.evaluate("""
                () => {
                    // Look for "next" link
                    const nextLinks = document.querySelectorAll('a[rel="next"], a.next, a[class*="next"]');
                    for (const a of nextLinks) {
                        if (a.href) return a.href;
                    }
                    // Look for numbered pagination
                    const currentPage = document.querySelector('.active, .current, [aria-current="page"]');
                    if (currentPage) {
                        const next = currentPage.nextElementSibling;
                        if (next && next.tagName === 'A') return next.href;
                    }
                    return null;
                }
            """)

            if not next_url:
                break

            page_num += 1
            console.print(f"[dim]  Gallery page {page_num}...[/dim]")
            await page.goto(next_url, timeout=30000, wait_until="networkidle")
            await self._scroll_page(page)
            await asyncio.sleep(1)

            new_photos = await _get_page_photos()
            new_count = 0
            for url in new_photos:
                full_url = self._to_full_size_url(url)
                if full_url not in seen:
                    seen.add(full_url)
                    photo_urls.append(full_url)
                    new_count += 1

            if new_count == 0:
                break

        return photo_urls

    def _to_full_size_url(self, url: str) -> str:
        """Convert a thumbnail URL to a full-size URL.

        Thumbnail pattern: .../s-{id}-{hash}-t.jpg
        Full-size pattern: .../s-{id}-{hash}.jpg
        """
        # Remove thumbnail suffix (-t before extension)
        url = re.sub(r"-t(\.\w+)$", r"\1", url)
        return url

    async def scrape_listings(self, url: str) -> list[Listing]:
        """Scrape a sale page: extract metadata and all photo URLs as individual listings."""
        browser = await self._ensure_browser()
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        listings: list[Listing] = []

        try:
            console.print(f"[blue]Loading sale page...[/blue]")
            await page.goto(url, timeout=30000, wait_until="networkidle")

            # Extract sale metadata
            metadata = await self._extract_sale_metadata(page)
            sale_title = metadata.get("title", "Estate Sale")
            sale_id = metadata.get("listing_id", "unknown")
            console.print(f"[green]Sale: {sale_title}[/green]")
            if metadata.get("dates"):
                console.print(f"[dim]Dates: {metadata['dates']}[/dim]")
            if metadata.get("company"):
                console.print(f"[dim]Company: {metadata['company']}[/dim]")

            # Extract all photo URLs
            console.print(f"[blue]Extracting photo gallery...[/blue]")
            photo_urls = await self._extract_photo_urls(page)
            console.print(f"[green]Found {len(photo_urls)} photos[/green]")

            # Create one Listing per photo
            for idx, photo_url in enumerate(photo_urls):
                listings.append(Listing(
                    listing_id=f"{sale_id}-photo-{idx + 1:04d}",
                    title=f"{sale_title} - Photo {idx + 1}",
                    description=self._sale_description,
                    url=url,
                    images=[ListingImage(url=photo_url)],
                    is_photo_only=True,
                    seller=metadata.get("company", ""),
                ))

        except Exception as e:
            console.print(f"[red]Error scraping sale page: {e}[/red]")
        finally:
            await page.close()

        return listings

    async def _scroll_page(self, page: Page) -> None:
        """Scroll the page to trigger lazy-loading of images."""
        try:
            await page.evaluate("""
                async () => {
                    const delay = ms => new Promise(r => setTimeout(r, ms));
                    for (let i = 0; i < document.body.scrollHeight; i += 500) {
                        window.scrollTo(0, i);
                        await delay(100);
                    }
                    window.scrollTo(0, 0);
                }
            """)
            await asyncio.sleep(1)
        except Exception:
            pass
