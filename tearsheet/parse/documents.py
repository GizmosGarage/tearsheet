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
    raise NotImplementedError
