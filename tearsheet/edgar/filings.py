"""Locate and archive a specific filing's documents with content hashes."""

from __future__ import annotations

import hashlib
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_primary_document(cik: str, accession_number: str) -> str:
    history = get_filing_history(cik)
    recent = history.get("filings", {}).get("recent", {})
    accession_numbers = recent.get("accessionNumber", [])
    primary_documents = recent.get("primaryDocument", [])

    for i, acc in enumerate(accession_numbers):
        if acc == accession_number:
            primary_doc = primary_documents[i] if i < len(primary_documents) else None
            if primary_doc:
                return primary_doc
            break

    raise ValueError(f"Accession number {accession_number} not found for CIK {cik}")


def acquire_filing(
    cik: str,
    accession_number: str,
    *,
    cache_dir: Path | None = None,
    known_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Archive every document in an accession locally, keyed by accession, with sha256 hashes.

    Idempotency is by hash, not existence: a file already on disk whose hash
    matches ``known_hashes`` (previously stored SourceDocument hashes keyed by
    filename) is not re-downloaded; a mismatch means the local copy is stale or
    tampered and it is re-fetched.
    """
    cache_dir = cache_dir or config.RAW_FILINGS_DIR
    known_hashes = known_hashes or {}
    accession_dir = cache_dir / cik / accession_number
    accession_dir.mkdir(parents=True, exist_ok=True)

    primary_doc = _find_primary_document(cik, accession_number)

    archive_base = f"{config.SEC_BASE_URL}/Archives/edgar/data/{cik.lstrip('0')}/{accession_number.replace('-', '')}"
    client = get_client()
    index = client.get_json(f"{archive_base}/index.json")
    items = index.get("directory", {}).get("item", [])

    documents = []
    for item in items:
        filename = item.get("name")
        if not filename or item.get("type") == "dir":
            continue

        url = f"{archive_base}/{filename}"
        dest = accession_dir / filename

        needs_download = True
        if dest.exists():
            digest = _sha256_file(dest)
            known = known_hashes.get(filename)
            if known is None or digest == known:
                needs_download = False

        if needs_download:
            response = client.get(url)
            with open(dest, "wb") as f:
                f.write(response.content)
            digest = _sha256_file(dest)

        documents.append({
            "filename": filename,
            "sequence": None,
            "doc_type": item.get("type") or None,
            "sha256": digest,
            "byte_size": dest.stat().st_size,
            "edgar_url": url,
            "path": dest,
        })

    if not any(d["filename"] == primary_doc for d in documents):
        raise ValueError(
            f"Primary document {primary_doc} not present in accession index for {accession_number}"
        )

    return {
        "accession_number": accession_number,
        "primary_document": primary_doc,
        "primary_path": accession_dir / primary_doc,
        "documents": documents,
    }
