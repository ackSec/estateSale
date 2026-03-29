from __future__ import annotations

import json
from decimal import Decimal

import anthropic
from rich.console import Console

from estate_scraper.ai.client import call_claude
from estate_scraper.models import Listing, RankedListing

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
