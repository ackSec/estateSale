from __future__ import annotations

import base64
import json
from decimal import Decimal
from pathlib import Path

import anthropic
from rich.console import Console

from estate_scraper.ai.client import call_claude
from estate_scraper.models import Listing, RankedListing, Valuation

console = Console()

SYSTEM_PROMPT = """You are a certified appraiser specializing in estate sales, antiques, jewelry, art, and collectibles. You have 30 years of experience authenticating items and providing accurate market valuations.

When analyzing images, look carefully for:
- Maker's marks, signatures, hallmarks, stamps
- Material quality indicators (weight, patina, wear patterns)
- Signs of age vs reproduction
- Condition issues that affect value
- Style/period indicators

You must respond ONLY with valid JSON, no markdown formatting."""

USER_PROMPT_TEMPLATE = """Analyze this estate sale item and provide a comprehensive valuation.

Title: {title}
Description: {description}
Current Auction Price: {price}
Number of Bids: {bids}

Please provide your analysis in this exact JSON format:
{{
    "recommendation": "BUY" or "INVESTIGATE FURTHER" or "PASS",
    "authenticity_assessment": "Detailed assessment of whether this item appears genuine...",
    "comparable_sales": ["Similar item sold for $X at Y auction house", "Comparable piece listed for $X on Z platform"],
    "special_valuations": {{"key": "value"}},
    "max_bid_recommendation": 100.00,
    "confidence": "HIGH" or "MEDIUM" or "LOW",
    "detailed_analysis": "2-3 paragraph detailed analysis..."
}}

For special_valuations, include relevant calculations like:
- For gold/silver jewelry: melt value based on approximate weight and purity
- For art: artist market, recent auction results
- For collectibles: condition grade, edition rarity
- For designer items: retail vs resale pricing

Be specific about comparable sales with realistic price ranges. If you can identify the maker, artist, or brand from the images, include that information."""


def _encode_image(path: Path) -> tuple[str, str]:
    """Read and base64-encode an image file. Returns (base64_data, media_type)."""
    data = path.read_bytes()
    b64 = base64.standard_b64encode(data).decode("utf-8")
    suffix = path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_types.get(suffix, "image/jpeg")
    return b64, media_type


def _build_vision_content(listing: Listing, max_images: int = 5) -> list[dict]:
    """Build the multimodal content array with text and images."""
    content: list[dict] = []

    # Add images first
    images_added = 0
    for img in listing.images:
        if img.local_path and img.local_path.exists() and images_added < max_images:
            try:
                b64, media_type = _encode_image(img.local_path)
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64,
                    },
                })
                images_added += 1
            except Exception as e:
                console.print(f"[yellow]Warning: Could not encode image {img.local_path}: {e}[/yellow]")

    # Add the text prompt
    price_str = f"${listing.current_price}" if listing.current_price else "Not listed"
    prompt = USER_PROMPT_TEMPLATE.format(
        title=listing.title,
        description=listing.description or "No description available",
        price=price_str,
        bids=listing.bid_count,
    )
    content.append({"type": "text", "text": prompt})

    return content


def valuate_item(
    client: anthropic.Anthropic,
    ranked_listing: RankedListing,
) -> Valuation:
    """Perform a deep-dive valuation on a single item using vision analysis."""
    listing = ranked_listing.listing
    console.print(f"[blue]  Analyzing: {listing.title}[/blue]")

    content = _build_vision_content(listing)

    # Check if we have any images
    has_images = any(c["type"] == "image" for c in content)
    if not has_images:
        console.print(f"[yellow]  No images available for {listing.title}, text-only analysis[/yellow]")

    response = call_claude(
        client=client,
        system=SYSTEM_PROMPT,
        user_content=content,
        max_tokens=4096,
    )

    try:
        data = json.loads(response)
        return Valuation(
            listing=listing,
            recommendation=data.get("recommendation", "INVESTIGATE FURTHER"),
            authenticity_assessment=data.get("authenticity_assessment", ""),
            comparable_sales=data.get("comparable_sales", []),
            special_valuations=data.get("special_valuations", {}),
            max_bid_recommendation=Decimal(str(data["max_bid_recommendation"])) if data.get("max_bid_recommendation") else None,
            confidence=data.get("confidence", "MEDIUM"),
            detailed_analysis=data.get("detailed_analysis", ""),
        )
    except (json.JSONDecodeError, KeyError) as e:
        console.print(f"[red]  Failed to parse valuation for {listing.title}: {e}[/red]")
        return Valuation(
            listing=listing,
            recommendation="INVESTIGATE FURTHER",
            detailed_analysis=f"AI analysis returned unparseable response. Raw: {response[:500]}",
        )


def valuate_items(
    client: anthropic.Anthropic,
    ranked_listings: list[RankedListing],
) -> list[Valuation]:
    """Perform deep-dive valuations on multiple items."""
    console.print(f"\n[blue]Deep-diving into {len(ranked_listings)} items...[/blue]\n")
    valuations = []
    for ranked in ranked_listings:
        val = valuate_item(client, ranked)
        valuations.append(val)
    return valuations
