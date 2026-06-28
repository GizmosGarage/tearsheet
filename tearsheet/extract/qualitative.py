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


from tearsheet.extract.grounding import verify_quotes
from tearsheet.store.models import Citation

def extract_risk_factors(
    document: Document,
    *,
    llm: LLMClient | None = None,
) -> list[QualitativeFact]:
    """Extract risk factors from Item 1A."""
    if document.id is None:
        raise ValueError("Document must be persisted before extraction.")
    if document.filing is None or document.filing.company_id is None:
        raise ValueError("Document must have a valid filing and company_id.")
    if len(document.text) > 100000:
        raise ValueError("Document text exceeds maximum context window.")
        
    llm = llm or LLMClient()
    system_prompt = _load_prompt("risk_factors.txt")
    
    parsed = llm.complete_structured(
        system_prompt=system_prompt,
        user_prompt=document.text,
        response_model=RiskList,
    )
    
    grounding_result = verify_quotes(document.text, parsed.risks, document_id=document.id)
    
    facts = []
    for span in grounding_result.accepted:
        fact = QualitativeFact(
            company_id=document.filing.company_id,
            category="risk_factor",
            summary=span.summary
        )
        citation = Citation(
            document_id=span.document_id,
            quote=span.quote,
            start_offset=span.start_offset,
            end_offset=span.end_offset
        )
        fact.citations = [citation]
        facts.append(fact)
        
    return facts


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
