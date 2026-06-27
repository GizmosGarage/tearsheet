"""Filing history (submissions) for a CIK."""

from __future__ import annotations

from typing import Any

from tearsheet import config
from tearsheet.edgar.client import get_client


def get_filing_history(cik: str) -> dict[str, Any]:
    """Return the SEC submissions JSON for a CIK."""
    url = f"{config.SEC_DATA_URL}/submissions/CIK{cik.zfill(10)}.json"
    raise NotImplementedError
