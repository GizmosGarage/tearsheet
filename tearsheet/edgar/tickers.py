"""Ticker -> CIK resolution via the SEC company tickers map."""

from __future__ import annotations

from tearsheet import config
from tearsheet.edgar.client import get_client


import json

def load_ticker_map() -> dict[str, int]:
    """Fetch and parse the SEC ticker-to-CIK mapping."""
    cache_path = config.RAW_FILINGS_DIR / "company_tickers.json"
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        client = get_client()
        data = client.get_json(config.SEC_TICKER_MAP_URL)
        config.ensure_data_dirs()
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
            
    return {v["ticker"]: v["cik_str"] for v in data.values()}


def resolve_ticker_to_cik(ticker: str) -> str:
    """Resolve a stock ticker to a zero-padded 10-digit CIK string."""
    ticker_map = load_ticker_map()
    cik_int = ticker_map.get(ticker.upper())
    if cik_int is None:
        raise ValueError(f"Ticker {ticker} not found in SEC map.")
    return f"{cik_int:010d}"
