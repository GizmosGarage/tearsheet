"""Raw filing -> clean, citable text — deterministic, no LLM."""

from tearsheet.parse.documents import build_documents
from tearsheet.parse.html_clean import html_to_plain_text
from tearsheet.parse.sectioner import split_10k_sections

__all__ = [
    "build_documents",
    "html_to_plain_text",
    "split_10k_sections",
]
