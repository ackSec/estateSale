from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from PIL import Image
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from tenacity import retry, stop_after_attempt, wait_exponential

from estate_scraper.models import Listing, ListingImage

console = Console()

MAX_LONG_EDGE = 1568
JPEG_QUALITY = 85


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=8))
async def _download_one(client: httpx.AsyncClient, url: str, dest: Path) -> Path | None:
    """Download a single image file."""
    try:
        resp = await client.get(url, follow_redirects=True, timeout=30)
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return dest
    except Exception:
        return None


def resize_image(path: Path) -> tuple[int, int]:
    """Resize image so the long edge is at most MAX_LONG_EDGE pixels. Returns (width, height)."""
    try:
        with Image.open(path) as img:
            w, h = img.size
            long_edge = max(w, h)
            if long_edge > MAX_LONG_EDGE:
                scale = MAX_LONG_EDGE / long_edge
                new_w = int(w * scale)
                new_h = int(h * scale)
                img = img.resize((new_w, new_h), Image.LANCZOS)
                img.save(path, "JPEG", quality=JPEG_QUALITY)
                return new_w, new_h
            return w, h
    except Exception:
        return 0, 0


async def download_listing_images(
    listings: list[Listing],
    output_dir: Path,
    concurrency: int = 5,
) -> list[Listing]:
    """Download all images for all listings, organized by listing ID."""
    semaphore = asyncio.Semaphore(concurrency)
    images_dir = output_dir / "images"

    total_images = sum(len(lst.images) for lst in listings)
    console.print(f"[blue]Downloading {total_images} images for {len(listings)} listings...[/blue]")

    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (compatible; EstateScraper/0.1)"},
    ) as client:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Downloading images...", total=total_images)

            for listing in listings:
                listing_dir = images_dir / listing.listing_id
                updated_images: list[ListingImage] = []

                for idx, img in enumerate(listing.images):
                    async with semaphore:
                        ext = _guess_extension(img.url)
                        dest = listing_dir / f"{idx + 1:03d}{ext}"
                        result = await _download_one(client, img.url, dest)

                        if result:
                            w, h = resize_image(result)
                            updated_images.append(ListingImage(
                                url=img.url,
                                local_path=result,
                                width=w,
                                height=h,
                            ))
                        else:
                            updated_images.append(img)

                        progress.advance(task)

                listing.images = updated_images

    downloaded = sum(1 for lst in listings for img in lst.images if img.local_path)
    console.print(f"[green]Downloaded {downloaded}/{total_images} images[/green]")
    return listings


def _guess_extension(url: str) -> str:
    """Guess file extension from URL."""
    lower = url.lower().split("?")[0]
    if lower.endswith(".png"):
        return ".png"
    if lower.endswith(".gif"):
        return ".gif"
    if lower.endswith(".webp"):
        return ".webp"
    return ".jpg"
