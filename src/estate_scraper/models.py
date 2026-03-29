from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ListingImage(BaseModel):
    url: str
    local_path: Path | None = None
    width: int | None = None
    height: int | None = None


class Listing(BaseModel):
    listing_id: str
    title: str
    description: str = ""
    current_price: Decimal | None = None
    bid_count: int = 0
    status: str = ""
    time_remaining: str = ""
    url: str = ""
    detail_url: str = ""
    images: list[ListingImage] = Field(default_factory=list)
    category: str = ""
    seller: str = ""
    is_photo_only: bool = False


class RankedListing(BaseModel):
    listing: Listing
    rank: int
    estimated_value_low: Decimal | None = None
    estimated_value_high: Decimal | None = None
    value_reasoning: str = ""
    category_tags: list[str] = Field(default_factory=list)


class Valuation(BaseModel):
    listing: Listing
    recommendation: Literal["BUY", "INVESTIGATE FURTHER", "PASS"]
    authenticity_assessment: str = ""
    comparable_sales: list[str] = Field(default_factory=list)
    special_valuations: dict[str, str] = Field(default_factory=dict)
    max_bid_recommendation: Decimal | None = None
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"
    detailed_analysis: str = ""


class ScrapeSession(BaseModel):
    sale_url: str
    sale_slug: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)
    output_dir: Path = Path("data")
    listings: list[Listing] = Field(default_factory=list)
    rankings: list[RankedListing] = Field(default_factory=list)
    valuations: list[Valuation] = Field(default_factory=list)
    sale_metadata: dict[str, str] = Field(default_factory=dict)
    sample_rate: float = 1.0

    def save(self, filename: str) -> Path:
        filepath = self.output_dir / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(self.model_dump_json(indent=2))
        return filepath

    @classmethod
    def load(cls, filepath: Path) -> ScrapeSession:
        return cls.model_validate_json(filepath.read_text())
