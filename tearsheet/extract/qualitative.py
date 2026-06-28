"""LLM extraction: business / risk / competition / management discussion."""

from __future__ import annotations

from pathlib import Path

from tearsheet.extract.llm_client import LLMClient
from tearsheet.extract.schemas import RiskList
from tearsheet.store.models import Document, QualitativeFact

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def extract_qualitative_facts(
    company_id: int,
    documents: list[Document],
    *,
    llm: LLMClient | None = None,
) -> list[QualitativeFact]:
    """Run LLM extraction tasks over parsed document sections."""
    raise NotImplementedError


def extract_risk_factors(
    document: Document,
    *,
    llm: LLMClient | None = None,
) -> RiskList:
    """Extract risk factors from Item 1A."""
    raise NotImplementedError


def extract_competition(
    document: Document,
    *,
    llm: LLMClient | None = None,
) -> RiskList:
    """Extract competitive landscape from relevant sections."""
    raise NotImplementedError


def extract_business(
    document: Document,
    *,
    llm: LLMClient | None = None,
) -> RiskList:
    """Extract business description from Item 1."""
    raise NotImplementedError


def extract_management_discussion(
    document: Document,
    *,
    llm: LLMClient | None = None,
) -> RiskList:
    """Extract MD&A highlights from Item 7."""
    raise NotImplementedError
