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
