from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Prompt

from estate_scraper.ai.client import get_client
from estate_scraper.ai.ranking import rank_listings
from estate_scraper.ai.valuation import valuate_items
from estate_scraper.config import load_config
from estate_scraper.images import download_listing_images
from estate_scraper.models import RankedListing, ScrapeSession
from estate_scraper.reports.terminal import display_rankings, display_summary, display_valuations
from estate_scraper.scrapers.bidmaxpro import BidMaxProScraper
from estate_scraper.utils import extract_store_slug

app = typer.Typer(help="Estate sale scraper with AI-powered valuation")
console = Console()


def _parse_selection(selection: str, max_rank: int) -> list[int]:
    """Parse user selection like '1,3,5-10' into a list of rank numbers."""
    if selection.strip().lower() == "all":
        return list(range(1, min(max_rank + 1, 11)))  # Top 10

    ranks: set[int] = set()
    for part in selection.split(","):
        part = part.strip()
        range_match = re.match(r"(\d+)\s*-\s*(\d+)", part)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            ranks.update(range(start, min(end + 1, max_rank + 1)))
        elif part.isdigit():
            n = int(part)
            if 1 <= n <= max_rank:
                ranks.add(n)
    return sorted(ranks)


def _get_session_dir(sale_slug: str) -> Path:
    """Create a timestamped session directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = Path("data") / f"{sale_slug}_{timestamp}"
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


@app.command()
def scan(
    url: str = typer.Argument(help="URL of the estate sale/auction page"),
    max_pages: int = typer.Option(0, help="Max pages to scrape (0 = all)"),
    skip_details: bool = typer.Option(False, help="Skip fetching detail pages"),
    skip_images: bool = typer.Option(False, help="Skip downloading images"),
    concurrency: int = typer.Option(3, help="Concurrent detail page fetches"),
) -> None:
    """Scrape an estate sale, rank items by value, and deep-dive selected items."""
    asyncio.run(_scan_async(url, max_pages, skip_details, skip_images, concurrency))


async def _scan_async(
    url: str,
    max_pages: int,
    skip_details: bool,
    skip_images: bool,
    concurrency: int,
) -> None:
    config = load_config(url)

    if not config.anthropic_api_key:
        console.print("[red]Error: ANTHROPIC_API_KEY not set. Add it to .env file.[/red]")
        raise typer.Exit(1)

    sale_slug = extract_store_slug(url)
    session_dir = _get_session_dir(sale_slug)
    console.print(f"\n[bold cyan]Estate Sale Scraper[/bold cyan]")
    console.print(f"[dim]URL: {url}[/dim]")
    console.print(f"[dim]Output: {session_dir}[/dim]\n")

    # --- Phase 1: Scrape ---
    scraper = BidMaxProScraper(config.site)
    try:
        listings = await scraper.scrape_listings(url)

        if not listings:
            console.print("[red]No listings found. Check the URL and try again.[/red]")
            raise typer.Exit(1)

        # Fetch detail pages
        if not skip_details:
            listings = await scraper.scrape_all_details(listings, concurrency=concurrency)
    finally:
        await scraper.close()

    # Save raw listings
    session = ScrapeSession(
        sale_url=url,
        sale_slug=sale_slug,
        output_dir=session_dir,
        listings=listings,
    )
    session.save("listings.json")

    # --- Phase 2: Download images ---
    if not skip_images:
        listings = await download_listing_images(listings, session_dir)
        session.listings = listings
        session.save("listings.json")

    total_images = sum(1 for lst in listings for img in lst.images if img.local_path)

    # --- Phase 3: AI Ranking ---
    ai_client = get_client(config.anthropic_api_key)
    rankings = rank_listings(ai_client, listings)
    session.rankings = rankings
    session.save("ranking.json")

    display_rankings(rankings)

    # --- Phase 4: User Selection ---
    if not rankings:
        console.print("[yellow]No items ranked. Exiting.[/yellow]")
        return

    selection = Prompt.ask(
        "[bold]Enter item numbers to deep-dive (e.g. 1,3,5-10) or 'all' for top 10[/bold]",
        default="all",
    )
    selected_ranks = _parse_selection(selection, len(rankings))

    if not selected_ranks:
        console.print("[yellow]No items selected. Exiting.[/yellow]")
        return

    selected = [r for r in rankings if r.rank in selected_ranks]
    console.print(f"\n[blue]Selected {len(selected)} items for deep dive[/blue]")

    # --- Phase 5: Deep Dive ---
    valuations = valuate_items(ai_client, selected)
    session.valuations = valuations
    session.save("valuations.json")

    # --- Phase 6: Display Results ---
    display_valuations(valuations, rankings)
    display_summary(len(listings), total_images, str(session_dir))


@app.command()
def rank(
    session_dir: str = typer.Argument(help="Path to a previous session directory"),
) -> None:
    """Re-rank items from a previous scrape session."""
    session_path = Path(session_dir) / "listings.json"
    if not session_path.exists():
        console.print(f"[red]Session not found: {session_path}[/red]")
        raise typer.Exit(1)

    session = ScrapeSession.load(session_path)
    config = load_config(session.sale_url)

    if not config.anthropic_api_key:
        console.print("[red]Error: ANTHROPIC_API_KEY not set.[/red]")
        raise typer.Exit(1)

    ai_client = get_client(config.anthropic_api_key)
    rankings = rank_listings(ai_client, session.listings)
    session.rankings = rankings
    session.save("ranking.json")
    display_rankings(rankings)


@app.command()
def dive(
    session_dir: str = typer.Argument(help="Path to a previous session directory"),
    items: str = typer.Option("all", help="Item ranks to deep-dive (e.g. 1,3,5-10)"),
) -> None:
    """Deep-dive specific items from a previous session."""
    ranking_path = Path(session_dir) / "ranking.json"
    if not ranking_path.exists():
        console.print(f"[red]Rankings not found: {ranking_path}. Run 'rank' first.[/red]")
        raise typer.Exit(1)

    session = ScrapeSession.load(ranking_path)
    config = load_config(session.sale_url)

    if not config.anthropic_api_key:
        console.print("[red]Error: ANTHROPIC_API_KEY not set.[/red]")
        raise typer.Exit(1)

    selected_ranks = _parse_selection(items, len(session.rankings))
    selected = [r for r in session.rankings if r.rank in selected_ranks]

    if not selected:
        console.print("[yellow]No items selected.[/yellow]")
        return

    ai_client = get_client(config.anthropic_api_key)
    valuations = valuate_items(ai_client, selected)
    session.valuations = valuations
    session.save("valuations.json")
    display_valuations(valuations, session.rankings)


@app.command()
def report(
    session_dir: str = typer.Argument(help="Path to a previous session directory"),
) -> None:
    """Re-display the terminal report from a previous session."""
    valuations_path = Path(session_dir) / "valuations.json"
    if valuations_path.exists():
        session = ScrapeSession.load(valuations_path)
        if session.rankings:
            display_rankings(session.rankings)
        if session.valuations:
            display_valuations(session.valuations, session.rankings)
    else:
        ranking_path = Path(session_dir) / "ranking.json"
        if ranking_path.exists():
            session = ScrapeSession.load(ranking_path)
            display_rankings(session.rankings)
        else:
            console.print(f"[red]No results found in {session_dir}[/red]")
            raise typer.Exit(1)


if __name__ == "__main__":
    app()
