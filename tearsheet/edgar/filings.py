"""Locate and download a specific filing's documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tearsheet import config
from tearsheet.edgar.client import get_client


from tearsheet.edgar.submissions import get_filing_history

def locate_filing(
    cik: str,
    form_type: str,
    *,
    accession_number: str | None = None,
) -> dict[str, Any]:
    """Find a filing in submission history and return its metadata."""
    history = get_filing_history(cik)
    recent = history.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_documents = recent.get("primaryDocument", [])
    
    for i, f in enumerate(forms):
        if f == form_type:
            acc = accession_numbers[i] if i < len(accession_numbers) else None
            if accession_number and acc != accession_number:
                continue
            primary_doc = primary_documents[i] if i < len(primary_documents) else None
            return {
                "accessionNumber": acc,
                "primaryDocument": primary_doc,
                "form": f
            }
    
    raise ValueError(f"Filing {form_type} not found for CIK {cik}")


def download_filing_documents(
    cik: str,
    accession_number: str,
    *,
    cache_dir: Path | None = None,
) -> Path:
    """Download filing documents to the local raw cache (idempotent)."""
    cache_dir = cache_dir or config.RAW_FILINGS_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    history = get_filing_history(cik)
    recent = history.get("filings", {}).get("recent", {})
    accession_numbers = recent.get("accessionNumber", [])
    primary_documents = recent.get("primaryDocument", [])
    
    primary_doc = None
    for i, acc in enumerate(accession_numbers):
        if acc == accession_number:
            primary_doc = primary_documents[i] if i < len(primary_documents) else None
            break
            
    if not primary_doc:
        raise ValueError(f"Accession number {accession_number} not found for CIK {cik}")
        
    url = f"{config.SEC_BASE_URL}/Archives/edgar/data/{cik.lstrip('0')}/{accession_number.replace('-', '')}/{primary_doc}"
    cache_path = cache_dir / primary_doc
    
    if cache_path.exists():
        return cache_path
        
    client = get_client()
    response = client.get(url)
    
    with open(cache_path, "wb") as f:
        f.write(response.content)
        
    return cache_path
