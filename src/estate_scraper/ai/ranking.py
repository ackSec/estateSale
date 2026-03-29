from __future__ import annotations

import base64
import json
import random
import re
from decimal import Decimal
from pathlib import Path

import anthropic
from rich.console import Console

from estate_scraper.ai.client import call_claude
from estate_scraper.models import Listing, ListingImage, RankedListing

console = Console()

SYSTEM_PROMPT = """You are an expert estate sale appraiser and antiques dealer with 30 years of experience. You specialize in identifying undervalued items at estate sales and auctions.

Your task is to rank auction items from most to least valuable based on:
1. Resale potential and profit margin
2. Rarity and collectibility
3. Likelihood of being underpriced at an estate sale
4. Category value (e.g., signed art, jewelry, vintage electronics, designer items)

You must respond ONLY with valid JSON, no markdown formatting."""

USER_PROMPT_TEMPLATE = """I am reviewing items from an estate sale auction. Please rank these items from most to least valuable/profitable based on their resale potential.

For each item, provide:
- listing_id: the original listing ID
- rank: integer (1 = most valuable opportunity)
- estimated_value_low: low end of estimated resale value in USD
- estimated_value_high: high end of estimated resale value in USD
- value_reasoning: brief explanation of why this could be valuable (1-2 sentences)
- category_tags: list of relevant tags (e.g., "jewelry", "gold", "vintage", "art", "signed", "designer")

Items to rank:
{items_text}

Respond with this exact JSON format:
{{"rankings": [{{"listing_id": "123", "rank": 1, "estimated_value_low": 50, "estimated_value_high": 200, "value_reasoning": "...", "category_tags": ["tag1", "tag2"]}}]}}"""


def _format_items(listings: list[Listing]) -> str:
    """Format listings into a text block for the prompt."""
    lines = []
    for lst in listings:
        parts = [f"ID: {lst.listing_id}", f"Title: {lst.title}"]
        if lst.description:
            # Truncate long descriptions
            desc = lst.description[:200] + "..." if len(lst.description) > 200 else lst.description
            parts.append(f"Description: {desc}")
        if lst.current_price is not None:
            parts.append(f"Current Price: ${lst.current_price}")
        if lst.bid_count:
            parts.append(f"Bids: {lst.bid_count}")
        if lst.status:
            parts.append(f"Status: {lst.status}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def rank_listings(
    client: anthropic.Anthropic,
    listings: list[Listing],
    batch_size: int = 50,
) -> list[RankedListing]:
    """Rank listings by value potential using Claude."""
    if not listings:
        return []

    console.print(f"[blue]Ranking {len(listings)} items with AI...[/blue]")

    all_rankings: list[dict] = []

    # Process in batches if needed
    batches = [listings[i:i + batch_size] for i in range(0, len(listings), batch_size)]

    for batch_idx, batch in enumerate(batches):
        if len(batches) > 1:
            console.print(f"[blue]Processing batch {batch_idx + 1}/{len(batches)}...[/blue]")

        items_text = _format_items(batch)
        prompt = USER_PROMPT_TEMPLATE.format(items_text=items_text)

        response = call_claude(
            client=client,
            system=SYSTEM_PROMPT,
            user_content=prompt,
            max_tokens=8192,
        )

        try:
            data = json.loads(response)
            batch_rankings = data.get("rankings", [])
            all_rankings.extend(batch_rankings)
        except json.JSONDecodeError:
            console.print("[red]Failed to parse AI ranking response[/red]")
            console.print(f"[dim]{response[:500]}[/dim]")

    # Re-rank across all batches by estimated value
    all_rankings.sort(key=lambda r: r.get("estimated_value_high", 0), reverse=True)

    # Build RankedListing objects
    listings_by_id = {lst.listing_id: lst for lst in listings}
    ranked: list[RankedListing] = []

    for global_rank, r in enumerate(all_rankings, 1):
        lid = str(r.get("listing_id", ""))
        listing = listings_by_id.get(lid)
        if not listing:
            continue

        ranked.append(RankedListing(
            listing=listing,
            rank=global_rank,
            estimated_value_low=Decimal(str(r.get("estimated_value_low", 0))),
            estimated_value_high=Decimal(str(r.get("estimated_value_high", 0))),
            value_reasoning=r.get("value_reasoning", ""),
            category_tags=r.get("category_tags", []),
        ))

    console.print(f"[green]Ranked {len(ranked)} items[/green]")
    return ranked


# --- Description-Based Item Extraction (for photo-only sites like EstateSales.org) ---

DESCRIPTION_EXTRACT_SYSTEM = """You are an expert estate sale appraiser and antiques dealer with 30 years of experience. You specialize in identifying valuable items from estate sale descriptions.

Your task is to read an estate sale description and extract every specific item or category of items mentioned, then rank them by resale potential and investment opportunity.

You must respond ONLY with valid JSON, no markdown formatting."""

DESCRIPTION_EXTRACT_PROMPT = """Read this estate sale listing description and extract every distinct item or item category mentioned. For each, estimate resale value and rank by investment potential.

Sale Title: {title}
Company: {company}

Description:
{description}

For each item or category you can identify, provide:
- item_id: a sequential number starting at 1
- item_description: what the item is (be specific — include brand, material, era if mentioned)
- estimated_value_low: low end of estimated resale value in USD
- estimated_value_high: high end of estimated resale value in USD
- value_reasoning: why this could be valuable (1-2 sentences)
- category_tags: relevant tags (e.g., "jewelry", "gold", "vintage", "art", "furniture")
- mentioned_details: any specific details from the description (brand names, materials, conditions)

Focus on items with real resale value. Skip generic mentions like "miscellaneous household items" unless they include specifics.

Respond with this JSON format:
{{"items": [{{"item_id": 1, "item_description": "...", "estimated_value_low": 50, "estimated_value_high": 200, "value_reasoning": "...", "category_tags": ["tag1"], "mentioned_details": "..."}}]}}"""


def rank_from_description(
    client: anthropic.Anthropic,
    description: str,
    sale_metadata: dict[str, str] | None = None,
) -> list[RankedListing]:
    """Extract and rank items from a sale description using Claude.

    Used as the first pass for estatesales.org — analyzes the description text
    to identify potentially valuable items before any photo analysis.
    """
    if not description or len(description.strip()) < 20:
        console.print("[yellow]Description too short to extract items from[/yellow]")
        return []

    metadata = sale_metadata or {}
    title = metadata.get("title", "Estate Sale")
    company = metadata.get("company", "Unknown")

    console.print(f"[blue]Analyzing sale description for valuable items...[/blue]")

    prompt = DESCRIPTION_EXTRACT_PROMPT.format(
        title=title,
        company=company,
        description=description[:3000],
    )

    response = call_claude(
        client=client,
        system=DESCRIPTION_EXTRACT_SYSTEM,
        user_content=prompt,
        max_tokens=8192,
    )

    try:
        data = json.loads(response)
        items = data.get("items", [])
    except json.JSONDecodeError:
        console.print("[red]Failed to parse description analysis response[/red]")
        return []

    # Sort by estimated value
    items.sort(key=lambda x: x.get("estimated_value_high", 0), reverse=True)

    ranked: list[RankedListing] = []
    for rank, item in enumerate(items, 1):
        listing = Listing(
            listing_id=f"desc-item-{item.get('item_id', rank)}",
            title=item.get("item_description", "Unknown item"),
            description=item.get("mentioned_details", ""),
            is_photo_only=True,
        )
        ranked.append(RankedListing(
            listing=listing,
            rank=rank,
            estimated_value_low=Decimal(str(item.get("estimated_value_low", 0))),
            estimated_value_high=Decimal(str(item.get("estimated_value_high", 0))),
            value_reasoning=item.get("value_reasoning", ""),
            category_tags=item.get("category_tags", []),
        ))

    console.print(f"[green]Identified {len(ranked)} potentially valuable items from description[/green]")
    return ranked

# Indicators that a description has specific, actionable item info
QUALITY_INDICATORS = [
    r"\b\d+k\s*gold\b",       # "14k gold"
    r"\bsterling\b",           # "sterling silver"
    r"\bsigned\b",             # "signed art"
    r"\bantique\b",
    r"\bvintage\b",
    r"\bmid[- ]century\b",
    r"\bdesigner\b",
    r"\boriginal\b",
    r"\bhandmade\b",
    r"\b\d+\s*ct\b",           # "2 ct diamond"
    r"\b\d+\s*carat\b",
    r"\bmaker['s]*\s*mark\b",
    r"\bhallmark\b",
    r"\blimited\s*edition\b",
    r"\bfirst\s*edition\b",
    r"\bnumbered\b",
    r"\bcertificate\b",
    r"\bprovenance\b",
    r"\bapprais\w+\b",
    r"\b(?:Rolex|Cartier|Tiffany|Hermes|Louis\s*Vuitton|Chanel|Gucci)\b",
    r"\b(?:Eames|Herman\s*Miller|Knoll|Nakashima|Stickley)\b",
]


def assess_description_quality(
    client: anthropic.Anthropic,
    description: str,
) -> str:
    """Assess whether a sale description has specific enough item info for text-based ranking.

    Returns 'good' if description has specific identifiable items, 'poor' if it's
    vague category listings that need photo analysis.
    """
    if not description or len(description.strip()) < 30:
        return "poor"

    # Heuristic: count quality indicators
    text_lower = description.lower()
    word_count = len(description.split())
    indicator_hits = sum(1 for pat in QUALITY_INDICATORS if re.search(pat, text_lower, re.IGNORECASE))

    # Clear cases
    if indicator_hits >= 5 and word_count > 100:
        console.print(f"[dim]Description quality: good ({indicator_hits} specific indicators found)[/dim]")
        return "good"
    if word_count < 50 and indicator_hits < 2:
        console.print(f"[dim]Description quality: poor (too short, {indicator_hits} indicators)[/dim]")
        return "poor"

    # Ambiguous — ask Claude (cheap Haiku call)
    console.print(f"[dim]Evaluating description quality with AI...[/dim]")
    response = call_claude(
        client=client,
        system="You evaluate estate sale descriptions. Respond with exactly 'GOOD' or 'POOR'.",
        user_content=(
            f"Does this estate sale description contain specific, identifiable items "
            f"with enough detail to assess their resale value? Or is it just vague "
            f"category listings like 'furniture, tools, collectibles'?\n\n"
            f"Description:\n{description[:1000]}\n\n"
            f"Respond GOOD if it has specific items, POOR if it's too vague."
        ),
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
    )
    result = "good" if "GOOD" in response.upper() else "poor"
    console.print(f"[dim]Description quality: {result} (AI assessed)[/dim]")
    return result


# --- Photo-Based Ranking ---

PHOTO_RANKING_SYSTEM = """You are an expert estate sale appraiser with 30 years of experience identifying valuable items from photos alone. You specialize in spotting undervalued antiques, jewelry, art, and collectibles at estate sales.

Analyze the provided estate sale photos. For each photo that contains a potentially valuable or interesting item, identify what it is and estimate its resale value. Skip photos that show generic household items, empty rooms, or items with very low resale potential (under $20).

You must respond ONLY with valid JSON, no markdown formatting."""

PHOTO_RANKING_PROMPT = """These are photos from an estate sale. For each photo containing a potentially valuable item, provide:
- photo_index: the 1-based index of the photo in the batch
- item_description: what you see (be specific — material, brand, era, condition)
- estimated_value_low: low end of estimated resale value in USD
- estimated_value_high: high end of estimated resale value in USD
- investment_rating: 1-10 (10 = best investment opportunity)
- category_tags: relevant tags
- value_reasoning: why this item could be valuable (1-2 sentences)

Skip photos showing generic items, empty rooms, or things worth under $20.

Respond with this JSON format:
{{"items": [{{"photo_index": 1, "item_description": "...", "estimated_value_low": 50, "estimated_value_high": 200, "investment_rating": 8, "category_tags": ["tag1"], "value_reasoning": "..."}}]}}"""


def _encode_image_for_ranking(path: Path) -> tuple[str, str] | None:
    """Read and base64-encode an image. Returns (base64_data, media_type) or None."""
    try:
        data = path.read_bytes()
        b64 = base64.standard_b64encode(data).decode("utf-8")
        suffix = path.suffix.lower()
        media_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                       ".gif": "image/gif", ".webp": "image/webp"}
        return b64, media_types.get(suffix, "image/jpeg")
    except Exception:
        return None


def rank_photos(
    client: anthropic.Anthropic,
    listings: list[Listing],
    sample_rate: float = 0.25,
    batch_size: int = 20,
) -> list[RankedListing]:
    """Rank items by sending a random sample of photos to Claude Vision.

    Each listing is assumed to be a single photo (is_photo_only=True).
    A random sample_rate fraction of photos is analyzed to gauge sale quality.
    """
    if not listings:
        return []

    # Random sample
    total = len(listings)
    sample_count = max(1, int(total * sample_rate))
    sampled_indices = sorted(random.sample(range(total), min(sample_count, total)))
    sampled = [listings[i] for i in sampled_indices]

    console.print(f"[blue]Sampling {len(sampled)}/{total} photos ({sample_rate:.0%}) for AI analysis...[/blue]")

    # Filter to listings with downloaded images
    with_images = [(i, lst) for i, lst in zip(sampled_indices, sampled)
                   if lst.images and lst.images[0].local_path and lst.images[0].local_path.exists()]

    if not with_images:
        console.print("[yellow]No downloaded images available for ranking[/yellow]")
        return []

    all_items: list[dict] = []

    # Process in batches
    batches = [with_images[i:i + batch_size] for i in range(0, len(with_images), batch_size)]

    for batch_idx, batch in enumerate(batches):
        if len(batches) > 1:
            console.print(f"[blue]Analyzing photo batch {batch_idx + 1}/{len(batches)}...[/blue]")

        # Build multimodal content: images + text prompt
        content: list[dict] = []
        batch_listing_map: dict[int, tuple[int, Listing]] = {}  # photo_index → (original_index, listing)

        for photo_idx, (orig_idx, lst) in enumerate(batch, 1):
            img_path = lst.images[0].local_path
            encoded = _encode_image_for_ranking(img_path)
            if encoded:
                b64, media_type = encoded
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64},
                })
                batch_listing_map[photo_idx] = (orig_idx, lst)

        content.append({"type": "text", "text": PHOTO_RANKING_PROMPT})

        response = call_claude(
            client=client,
            system=PHOTO_RANKING_SYSTEM,
            user_content=content,
            max_tokens=8192,
        )

        try:
            data = json.loads(response)
            items = data.get("items", [])
            # Map photo_index back to original listing
            for item in items:
                pidx = item.get("photo_index", 0)
                if pidx in batch_listing_map:
                    orig_idx, lst = batch_listing_map[pidx]
                    item["_listing"] = lst
                    item["_orig_index"] = orig_idx
                    all_items.append(item)
        except json.JSONDecodeError:
            console.print(f"[red]Failed to parse photo ranking response for batch {batch_idx + 1}[/red]")

    # Sort by investment rating then by estimated value
    all_items.sort(key=lambda x: (x.get("investment_rating", 0), x.get("estimated_value_high", 0)), reverse=True)

    # Build RankedListing objects
    ranked: list[RankedListing] = []
    for rank, item in enumerate(all_items, 1):
        lst: Listing = item["_listing"]
        # Update the listing title with what Claude identified
        lst.title = item.get("item_description", lst.title)

        ranked.append(RankedListing(
            listing=lst,
            rank=rank,
            estimated_value_low=Decimal(str(item.get("estimated_value_low", 0))),
            estimated_value_high=Decimal(str(item.get("estimated_value_high", 0))),
            value_reasoning=item.get("value_reasoning", ""),
            category_tags=item.get("category_tags", []),
        ))

    console.print(f"[green]Identified {len(ranked)} potentially valuable items from {len(sampled)} photos[/green]")
    return ranked
