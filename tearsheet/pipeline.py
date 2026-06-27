"""One company end-to-end: ticker -> grounded fact store."""

from __future__ import annotations

from tearsheet.edgar import (
    download_filing_documents,
    fetch_companyfacts,
    get_filing_history,
    resolve_ticker_to_cik,
)
from tearsheet.extract import extract_financial_facts, extract_qualitative_facts
from tearsheet.parse import build_documents
from tearsheet.store.repository import Repository

# Re-export stage entry points for pipeline wiring (not yet connected):
__all__ = [
    "build_documents",
    "download_filing_documents",
    "extract_financial_facts",
    "extract_qualitative_facts",
    "fetch_companyfacts",
    "get_filing_history",
    "resolve_ticker_to_cik",
    "run_company_pipeline",
]


def run_company_pipeline(ticker: str) -> None:
    """Orchestrate gather -> parse -> extract -> store for a single company."""
    repo = Repository()

    cik = resolve_ticker_to_cik(ticker)
    repo.upsert_company(ticker=ticker, cik=cik)

    submissions = get_filing_history(cik)
    # TODO: select target 10-K filing from submissions
    _ = submissions

    # TODO: wire filing selection, download, parse, extract, persist
    # raw_path = download_filing_documents(cik, accession_number)
    # documents = build_documents(filing_id, raw_path)
    # companyfacts = fetch_companyfacts(cik)
    # financial_facts = extract_financial_facts(company_id, companyfacts)
    # qualitative_facts = extract_qualitative_facts(company_id, documents)

    raise NotImplementedError("Pipeline wiring not yet implemented")
