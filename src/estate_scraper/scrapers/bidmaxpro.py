from __future__ import annotations

import asyncio
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode, urljoin, urlparse, parse_qs, urlunparse

from playwright.async_api import Browser, Page, async_playwright
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from estate_scraper.config import SiteConfig
from estate_scraper.models import Listing, ListingImage
from estate_scraper.scrapers.base import BaseScraper

console = Console()


class BidMaxProScraper(BaseScraper):
    def __init__(self, site_config: SiteConfig):
        super().__init__(site_config)
        self._playwright = None
        self._browser: Browser | None = None

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

    def _build_page_url(self, base_url: str, page: int) -> str:
        """Add pagination and per-page params to the URL."""
        parsed = urlparse(base_url)
        params = parse_qs(parsed.query)
        params[self.config.pagination.per_page_param] = [str(self.config.pagination.max_per_page)]
        if page > 1:
            params[self.config.pagination.param] = [str(page)]
        elif self.config.pagination.param in params:
            del params[self.config.pagination.param]
        new_query = urlencode(params, doseq=True)
        return urlunparse(parsed._replace(query=new_query))

    async def _extract_listings_from_page(self, page: Page) -> list[Listing]:
        """Extract listing data from a rendered browse page."""
        sel = self.config.selectors
        listings = []

        # Wait for listing containers
        try:
            await page.wait_for_selector(sel.listing_container, timeout=15000)
        except Exception:
            console.print("[yellow]No listings found on page[/yellow]")
            return []

        containers = await page.query_selector_all(sel.listing_container)

        for container in containers:
            try:
                listing_id = await container.get_attribute(sel.listing_id_attr) or ""
                if not listing_id:
                    continue

                # Title and URL
                title = ""
                detail_url = ""
                title_el = await container.query_selector("a[href*='listings']")
                if not title_el:
                    title_el = await container.query_selector("a")
                if title_el:
                    title = (await title_el.inner_text()).strip()
                    href = await title_el.get_attribute("href") or ""
                    if href:
                        detail_url = urljoin(self.config.base_url, href)

                # Price
                price = None
                price_el = await container.query_selector(sel.price)
                if price_el:
                    price_text = (await price_el.inner_text()).strip()
                    price = self._parse_price(price_text)

                # Bid count
                bid_count = 0
                bid_el = await container.query_selector(sel.bid_count)
                if bid_el:
                    bid_text = (await bid_el.inner_text()).strip()
                    nums = re.findall(r"\d+", bid_text)
                    if nums:
                        bid_count = int(nums[0])

                # Status
                status = ""
                status_el = await container.query_selector(sel.status)
                if status_el:
                    status = (await status_el.inner_text()).strip()

                # Countdown
                time_remaining = ""
                countdown_el = await container.query_selector(sel.countdown)
                if countdown_el:
                    time_remaining = (await countdown_el.inner_text()).strip()

                # Thumbnail images
                images = []
                img_els = await container.query_selector_all(sel.image)
                for img_el in img_els:
                    src = await img_el.get_attribute(sel.image_src_attr)
                    if not src:
                        src = await img_el.get_attribute("src")
                    if src and not src.startswith("data:"):
                        full_url = urljoin(self.config.base_url, src)
                        images.append(ListingImage(url=full_url))

                listings.append(Listing(
                    listing_id=listing_id,
                    title=title,
                    current_price=price,
                    bid_count=bid_count,
                    status=status,
                    time_remaining=time_remaining,
                    detail_url=detail_url,
                    images=images,
                ))
            except Exception as e:
                console.print(f"[yellow]Warning: Failed to parse listing: {e}[/yellow]")
                continue

        return listings

    async def _detect_total_pages(self, page: Page) -> int:
        """Detect total number of pages from the browse page."""
        # Look for pagination links - find the highest page number
        try:
            # Try to find pagination elements
            pagination_links = await page.query_selector_all("a[href*='page=']")
            max_page = 1
            for link in pagination_links:
                href = await link.get_attribute("href") or ""
                match = re.search(r"page=(\d+)", href)
                if match:
                    max_page = max(max_page, int(match.group(1)))

            # Also check for "last page" type buttons
            text_content = await page.content()
            page_matches = re.findall(r"page=(\d+)", text_content)
            for p in page_matches:
                max_page = max(max_page, int(p))

            return max_page
        except Exception:
            return 1

    async def scrape_listings(self, url: str) -> list[Listing]:
        """Scrape all listings from a store/sale page with pagination."""
        browser = await self._ensure_browser()
        page = await browser.new_page()
        all_listings: list[Listing] = []

        try:
            # Load first page with max items per page
            first_url = self._build_page_url(url, 1)
            console.print(f"[blue]Loading {first_url}[/blue]")
            await page.goto(first_url, timeout=30000, wait_until="networkidle")

            # Scroll to trigger lazy-load
            await self._scroll_page(page)

            total_pages = await self._detect_total_pages(page)
            console.print(f"[blue]Detected {total_pages} page(s)[/blue]")

            # Scrape first page
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Scraping listings...", total=total_pages)

                page_listings = await self._extract_listings_from_page(page)
                all_listings.extend(page_listings)
                progress.advance(task)

                # Scrape remaining pages
                for page_num in range(2, total_pages + 1):
                    page_url = self._build_page_url(url, page_num)
                    await page.goto(page_url, timeout=30000, wait_until="networkidle")
                    await self._scroll_page(page)
                    page_listings = await self._extract_listings_from_page(page)
                    all_listings.extend(page_listings)
                    progress.advance(task)
                    await asyncio.sleep(1)  # Polite delay

        finally:
            await page.close()

        console.print(f"[green]Found {len(all_listings)} listings[/green]")
        return all_listings

    async def scrape_listing_detail(self, listing: Listing) -> Listing:
        """Visit a listing's detail page to get full description and all images."""
        if not listing.detail_url:
            return listing

        browser = await self._ensure_browser()
        page = await browser.new_page()

        try:
            await page.goto(listing.detail_url, timeout=30000, wait_until="networkidle")
            await self._scroll_page(page)

            # Extract description
            sel = self.config.selectors
            for desc_selector in sel.detail_description.split(","):
                desc_el = await page.query_selector(desc_selector.strip())
                if desc_el:
                    listing.description = (await desc_el.inner_text()).strip()
                    break

            # Extract all gallery images
            detail_images: list[ListingImage] = []
            seen_urls: set[str] = set()

            # Try multiple image selectors
            for img_selector in sel.detail_images.split(","):
                img_els = await page.query_selector_all(img_selector.strip())
                for img_el in img_els:
                    for attr in [sel.image_src_attr, "src", "data-full", "data-img", "href"]:
                        src = await img_el.get_attribute(attr)
                        if src and not src.startswith("data:") and src not in seen_urls:
                            full_url = urljoin(self.config.base_url, src)
                            seen_urls.add(full_url)
                            detail_images.append(ListingImage(url=full_url))
                            break

            # Also check for any large images on the page
            all_imgs = await page.query_selector_all("img[src*='uploads'], img[src*='images/listings']")
            for img_el in all_imgs:
                src = await img_el.get_attribute("src")
                if src and not src.startswith("data:"):
                    full_url = urljoin(self.config.base_url, src)
                    if full_url not in seen_urls:
                        seen_urls.add(full_url)
                        detail_images.append(ListingImage(url=full_url))

            if detail_images:
                listing.images = detail_images

        except Exception as e:
            console.print(f"[yellow]Warning: Failed to get details for {listing.title}: {e}[/yellow]")
        finally:
            await page.close()

        return listing

    async def scrape_all_details(self, listings: list[Listing], concurrency: int = 3) -> list[Listing]:
        """Scrape detail pages for all listings with concurrency limit."""
        semaphore = asyncio.Semaphore(concurrency)

        async def _scrape_one(listing: Listing) -> Listing:
            async with semaphore:
                result = await self.scrape_listing_detail(listing)
                await asyncio.sleep(0.5)  # Polite delay
                return result

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Fetching detail pages...", total=len(listings))
            results = []
            for listing in listings:
                result = await _scrape_one(listing)
                results.append(result)
                progress.advance(task)

        return results

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

    @staticmethod
    def _parse_price(text: str) -> Decimal | None:
        """Parse a price string like '$1,234.56' into a Decimal."""
        cleaned = re.sub(r"[^\d.]", "", text)
        if not cleaned:
            return None
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            return None
