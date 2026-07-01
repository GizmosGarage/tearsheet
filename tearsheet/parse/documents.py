"""Orchestrate parsing -> frozen Document rows (one per section)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from tearsheet.parse.html_clean import html_to_plain_text
from tearsheet.parse.sectioner import Section, split_10k_sections
from tearsheet.store.models import Document


def build_documents(
    filing_id: int,
    raw_html_path: Path,
    *,
    source_document_id: int | None = None,
) -> list[Document]:
    """Parse an archived filing into Document rows, one per section.

    Each row is stamped with the SourceDocument it was derived from and the
    sha256 of its exact text, so citation offsets stay verifiable against a
    hash-checked custody chain back to the archived raw bytes.
    """
    with open(raw_html_path, "r", encoding="utf-8", errors="replace") as f:
        html = f.read()

    plain_text = html_to_plain_text(html)
    sections = split_10k_sections(plain_text)

    documents = []
    for sec in sections:
        doc = Document(
            filing_id=filing_id,
            source_document_id=source_document_id,
            section=sec.item,
            title=sec.title,
            text=sec.text,
            text_sha256=hashlib.sha256(sec.text.encode("utf-8")).hexdigest(),
            extraction_method="sectioner",
        )
        documents.append(doc)

    return documents
