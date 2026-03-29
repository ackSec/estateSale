from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from estate_scraper.models import RankedListing, Valuation

console = Console()

RECOMMENDATION_STYLES = {
    "BUY": ("bold green", "[BUY]"),
    "INVESTIGATE FURTHER": ("bold yellow", "[INVESTIGATE]"),
    "PASS": ("bold red", "[PASS]"),
}


def display_rankings(rankings: list[RankedListing]) -> None:
    """Display ranked listings as a Rich table."""
    table = Table(
        title="Estate Sale Items - Ranked by Value Potential",
        show_lines=True,
        title_style="bold cyan",
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Title", style="white", max_width=45)
    table.add_column("Price", style="green", justify="right", width=10)
    table.add_column("Bids", justify="right", width=5)
    table.add_column("Est. Value", style="cyan", justify="right", width=16)
    table.add_column("Tags", style="magenta", max_width=25)
    table.add_column("Reasoning", style="dim", max_width=40)

    for r in rankings:
        price = f"${r.listing.current_price}" if r.listing.current_price else "-"
        est = ""
        if r.estimated_value_low and r.estimated_value_high:
            est = f"${r.estimated_value_low}-${r.estimated_value_high}"
        tags = ", ".join(r.category_tags[:4])
        reasoning = r.value_reasoning[:80] + "..." if len(r.value_reasoning) > 80 else r.value_reasoning

        table.add_row(
            str(r.rank),
            r.listing.title[:45],
            price,
            str(r.listing.bid_count),
            est,
            tags,
            reasoning,
        )

    console.print()
    console.print(table)
    console.print()


def display_valuation(valuation: Valuation, rank: int | None = None) -> None:
    """Display a single valuation as a Rich panel."""
    style, badge = RECOMMENDATION_STYLES.get(
        valuation.recommendation, ("bold white", "[?]")
    )

    # Header
    title_parts = []
    if rank:
        title_parts.append(f"#{rank}")
    title_parts.append(valuation.listing.title)
    header = " - ".join(title_parts)

    # Build content
    lines: list[str] = []

    # Recommendation badge
    lines.append(f"Recommendation: {badge}")
    lines.append(f"Confidence: {valuation.confidence}")
    if valuation.max_bid_recommendation:
        lines.append(f"Max Bid: ${valuation.max_bid_recommendation}")

    price = f"${valuation.listing.current_price}" if valuation.listing.current_price else "N/A"
    lines.append(f"Current Price: {price} ({valuation.listing.bid_count} bids)")
    lines.append("")

    # Authenticity
    if valuation.authenticity_assessment:
        lines.append("[bold]Authenticity Assessment:[/bold]")
        lines.append(valuation.authenticity_assessment)
        lines.append("")

    # Comparable sales
    if valuation.comparable_sales:
        lines.append("[bold]Comparable Sales:[/bold]")
        for comp in valuation.comparable_sales:
            lines.append(f"  • {comp}")
        lines.append("")

    # Special valuations
    if valuation.special_valuations:
        lines.append("[bold]Special Valuations:[/bold]")
        for key, value in valuation.special_valuations.items():
            label = key.replace("_", " ").title()
            lines.append(f"  • {label}: {value}")
        lines.append("")

    # Detailed analysis
    if valuation.detailed_analysis:
        lines.append("[bold]Detailed Analysis:[/bold]")
        lines.append(valuation.detailed_analysis)

    content = "\n".join(lines)
    console.print(Panel(content, title=header, border_style=style, padding=(1, 2)))
    console.print()


def display_valuations(valuations: list[Valuation], rankings: list[RankedListing] | None = None) -> None:
    """Display all valuations."""
    rank_map = {}
    if rankings:
        rank_map = {r.listing.listing_id: r.rank for r in rankings}

    # Sort: BUY first, then INVESTIGATE, then PASS
    order = {"BUY": 0, "INVESTIGATE FURTHER": 1, "PASS": 2}
    sorted_vals = sorted(valuations, key=lambda v: order.get(v.recommendation, 3))

    console.print()
    console.rule("[bold cyan]Deep Dive Valuations[/bold cyan]")
    console.print()

    # Summary counts
    buys = sum(1 for v in valuations if v.recommendation == "BUY")
    investigates = sum(1 for v in valuations if v.recommendation == "INVESTIGATE FURTHER")
    passes = sum(1 for v in valuations if v.recommendation == "PASS")
    console.print(
        f"  [green]{buys} BUY[/green]  |  "
        f"[yellow]{investigates} INVESTIGATE[/yellow]  |  "
        f"[red]{passes} PASS[/red]"
    )
    console.print()

    for val in sorted_vals:
        rank = rank_map.get(val.listing.listing_id)
        display_valuation(val, rank)


def display_summary(total_listings: int, total_images: int, session_dir: str) -> None:
    """Display a session summary."""
    console.print()
    console.rule("[bold cyan]Session Summary[/bold cyan]")
    console.print(f"  Listings scraped: {total_listings}")
    console.print(f"  Images downloaded: {total_images}")
    console.print(f"  Data saved to: {session_dir}")
    console.print()
