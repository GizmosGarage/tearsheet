"""Orchestrate parsing -> frozen Document rows (one per section)."""

from __future__ import annotations

from pathlib import Path

from tearsheet.parse.html_clean import html_to_plain_text
from tearsheet.parse.sectioner import Section, split_10k_sections
from tearsheet.store.models import Document


def build_documents(
    filing_id: int,
    raw_html_path: Path,
) -> list[Document]:
    """Parse a cached filing into Document rows, one per section."""
    with open(raw_html_path, "r", encoding="utf-8", errors="replace") as f:
        html = f.read()
        
    plain_text = html_to_plain_text(html)
    sections = split_10k_sections(plain_text)
    
    documents = []
    for sec in sections:
        doc = Document(
            filing_id=filing_id,
            section=sec.item,
            title=sec.title,
            text=sec.text
        )
        documents.append(doc)
        
    return documents
