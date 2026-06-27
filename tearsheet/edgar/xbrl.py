"""Fetch XBRL companyfacts JSON (structured financials)."""

from __future__ import annotations

from typing import Any

from tearsheet import config
from tearsheet.edgar.client import get_client


def fetch_companyfacts(cik: str) -> dict[str, Any]:
    """Return the SEC companyfacts JSON for a CIK."""
    url = f"{config.SEC_DATA_URL}/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json"
    raise NotImplementedError
