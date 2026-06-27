"""Project configuration: paths, model name, SEC user-agent, rate limits."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env from project root (does not override existing shell env vars).
load_dotenv(PROJECT_ROOT / ".env")
DATA_DIR = PROJECT_ROOT / "data"
RAW_FILINGS_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "tearsheet.db"

# ---------------------------------------------------------------------------
# SEC EDGAR
# ---------------------------------------------------------------------------

SEC_BASE_URL = "https://www.sec.gov"
SEC_DATA_URL = "https://data.sec.gov"
SEC_TICKER_MAP_URL = f"{SEC_BASE_URL}/files/company_tickers.json"

# SEC requires a descriptive User-Agent with contact info.
SEC_USER_AGENT: str = os.getenv(
    "SEC_USER_AGENT",
    "Tearsheet/0.1.0 (contact: unset@example.com)",
)

SEC_RATE_LIMIT_PER_SECOND: float = float(os.getenv("SEC_RATE_LIMIT_PER_SECOND", "10"))
SEC_REQUEST_TIMEOUT_SECONDS: float = float(os.getenv("SEC_REQUEST_TIMEOUT_SECONDS", "30"))
SEC_MAX_RETRIES: int = int(os.getenv("SEC_MAX_RETRIES", "3"))

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ensure_data_dirs() -> None:
    """Create local data directories if they do not exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_FILINGS_DIR.mkdir(parents=True, exist_ok=True)


def database_url() -> str:
    """SQLAlchemy connection URL (SQLite now; Postgres later)."""
    override = os.getenv("DATABASE_URL")
    if override:
        return override
    ensure_data_dirs()
    return f"sqlite:///{DB_PATH}"
