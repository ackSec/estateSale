#!/usr/bin/env python3
"""Entry point — run from project root: python run.py scan <URL>"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from estate_scraper.cli import app

app()
