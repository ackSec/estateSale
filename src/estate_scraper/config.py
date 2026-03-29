from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "sites"


class PaginationConfig(BaseModel):
    param: str = "page"
    per_page_param: str = "show"
    max_per_page: int = 80


class SelectorsConfig(BaseModel):
    listing_container: str = "[data-listing-id]"
    listing_id_attr: str = "data-listing-id"
    title: str = "a"
    price: str = ".au-price"
    bid_count: str = ".au-nb-bids"
    status: str = ".au-status"
    countdown: str = ".au-countdown"
    image: str = "img.lazyload"
    image_src_attr: str = "data-src"
    pagination_info: str = ".listing-count"
    detail_description: str = ".listing-description, .description, #description"
    detail_images: str = ".listing-gallery img, .gallery img, .fotorama img"


class SiteConfig(BaseModel):
    name: str
    base_url: str
    browse_path: str = ""
    store_action: str = ""
    ajax_endpoint: str = ""
    detail_path_template: str = ""
    pagination: PaginationConfig = Field(default_factory=PaginationConfig)
    selectors: SelectorsConfig = Field(default_factory=SelectorsConfig)


class AppConfig(BaseModel):
    anthropic_api_key: str = ""
    site: SiteConfig = Field(default_factory=lambda: SiteConfig(name="default", base_url=""))
    output_dir: Path = Path("data")


def load_site_config(site_name: str) -> SiteConfig:
    config_path = CONFIG_DIR / f"{site_name}.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Site config not found: {config_path}")
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return SiteConfig(**data)


def detect_site(url: str) -> str:
    """Detect site name from URL domain."""
    from urllib.parse import urlparse

    domain = urlparse(url).netloc.lower()
    if "bidmaxpro" in domain:
        return "bidmaxpro"
    if "estatesales" in domain:
        return "estatesales"
    raise ValueError(f"Unknown site: {domain}. No scraper config available.")


def load_config(url: str) -> AppConfig:
    load_dotenv()
    site_name = detect_site(url)
    site_config = load_site_config(site_name)
    return AppConfig(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        site=site_config,
    )
