"""Locate and download a specific filing's documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tearsheet import config
from tearsheet.edgar.client import get_client


def locate_filing(
    cik: str,
    form_type: str,
    *,
    accession_number: str | None = None,
) -> dict[str, Any]:
    """Find a filing in submission history and return its metadata."""
    raise NotImplementedError


def download_filing_documents(
    cik: str,
    accession_number: str,
    *,
    cache_dir: Path | None = None,
) -> Path:
    """Download filing documents to the local raw cache (idempotent)."""
    cache_dir = cache_dir or config.RAW_FILINGS_DIR
    raise NotImplementedError
