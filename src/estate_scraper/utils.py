from __future__ import annotations

import re


def slugify(text: str, max_length: int = 60) -> str:
    """Convert text to a URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text[:max_length].rstrip("-")


def extract_store_slug(url: str) -> str:
    """Extract the store_slug from a BidMaxPro URL."""
    match = re.search(r"store_slug=([^&]+)", url)
    if match:
        return match.group(1)
    return slugify(url)


def extract_sale_slug_estatesales(url: str) -> str:
    """Extract a sale slug from an EstateSales.org URL.

    URL pattern: /estate-sales/ca/walnut-creek/94598/sale-name-here-1234567
    """
    match = re.search(r"/estate-sales/[^/]+/[^/]+/\d+/([^/?#]+)", url)
    if match:
        return match.group(1)
    return slugify(url)


def extract_sale_id_estatesales(url: str) -> str:
    """Extract the numeric sale ID from an EstateSales.org URL.

    The ID is the trailing number in the slug: sale-name-here-1234567 → 1234567
    """
    slug = extract_sale_slug_estatesales(url)
    match = re.search(r"-(\d+)$", slug)
    if match:
        return match.group(1)
    # Try to find any ID in the URL
    match = re.search(r"(\d{5,})", url)
    if match:
        return match.group(1)
    return slug
