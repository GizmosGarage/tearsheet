"""LLM extraction: business / risk / management discussion."""

from __future__ import annotations

from pathlib import Path

from tearsheet.extract.llm_client import LLMClient
from tearsheet.extract.schemas import BusinessProfile, MDAnalysis, RiskList
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

import re
import logging

logger = logging.getLogger(__name__)

def _chunk_text(text: str, chunk_size: int = 40000, overlap: int = 4000) -> list[str]:
    """Semantic chunking of text by paragraphs."""
    if not text:
        return []
        
    if len(text) <= chunk_size:
        return [text]
        
    parts = re.split(r'(\n\n+)', text)
    paragraphs = []
    current_para = ""
    for part in parts:
        current_para += part
        if re.match(r'^\n\n+$', part):
            paragraphs.append(current_para)
            current_para = ""
    if current_para:
        paragraphs.append(current_para)
        
    chunks = []
    current_chunk_paras = []
    current_len = 0
    
    i = 0
    while i < len(paragraphs):
        p = paragraphs[i]
        
        if len(p) > chunk_size:
            logger.warning("Paragraph exceeds chunk size, falling back to hard split.")
            if current_chunk_paras:
                chunks.append("".join(current_chunk_paras))
                current_chunk_paras = []
                current_len = 0
            
            start = 0
            while start < len(p):
                end = start + chunk_size
                if end < len(p):
                    last_period = p.rfind('.', start, end)
                    if last_period != -1 and last_period > start:
                        end = last_period + 1
                chunk_str = p[start:end]
                chunks.append(chunk_str)
                start = end
            i += 1
            continue
            
        if current_len + len(p) > chunk_size and current_chunk_paras:
            chunks.append("".join(current_chunk_paras))
            
            overlap_len = 0
            overlap_paras = []
            for rp in reversed(current_chunk_paras):
                if overlap_len + len(rp) > overlap and overlap_paras:
                    break
                overlap_paras.insert(0, rp)
                overlap_len += len(rp)
                
            if len(overlap_paras) == len(current_chunk_paras):
                overlap_len -= len(current_chunk_paras[0])
                overlap_paras = overlap_paras[1:]
                
            current_chunk_paras = overlap_paras
            current_len = sum(len(x) for x in current_chunk_paras)
            
            # QA FIX: Enforce ceiling. If the overlap + new paragraph > chunk_size,
            # we must shrink the overlap from the front until it fits.
            while current_len + len(p) > chunk_size and current_chunk_paras:
                dropped = current_chunk_paras.pop(0)
                current_len -= len(dropped)
            
        current_chunk_paras.append(p)
        current_len += len(p)
        i += 1
        
    if current_chunk_paras:
        chunks.append("".join(current_chunk_paras))
        
    return chunks


def extract_risk_factors(
    document: Document,
    *,
    llm: LLMClient | None = None,
) -> list[QualitativeFact]:
    """Extract risk factors from Item 1A.

    Chunking (_chunk_text):
    - [ ] Split into paragraphs on blank lines, preserving original characters.
    - [ ] Greedily pack whole paragraphs up to `chunk_size`.
    - [ ] Begin each next chunk with trailing paragraphs (~`overlap`) carried over from the previous chunk.
    - [ ] Handle the oversized-single-paragraph edge case with a logged sentence-boundary fallback split.
    - [ ] Guarantee: every chunk ≤ `chunk_size`; short docs yield exactly one chunk (back-compat).

    Looping (extract_risk_factors):
    - [ ] Keep the existing validity checks (`document.id`, `document.filing`, `company_id`).
    - [ ] Chunk `document.text`; loop chunks sequentially calling `llm.complete_structured(..., user_prompt=chunk, response_model=RiskList)`.
    - [ ] Aggregate all `parsed.risks` into one candidate list.
    - [ ] Call `verify_quotes(document.text, candidates, document_id=document.id)` **once, against the full text** (global offsets — do not pass a chunk here).

    Dedupe-by-span before fact creation:
    - [ ] Add `dedupe_by_span(accepted)` keyed on `(start_offset, end_offset)`; one span → one fact (§3.3).
    - [ ] Build `QualitativeFact` + single `Citation` per deduped span (unchanged construction logic).
    """
    if document.id is None:
        raise ValueError("Document must be persisted before extraction.")
    if document.filing is None or document.filing.company_id is None:
        raise ValueError("Document must have a valid filing and company_id.")
        
    llm = llm or LLMClient()
    system_prompt = _load_prompt("risk_factors.txt")
    
    chunks = _chunk_text(document.text, chunk_size=40000, overlap=4000)
    all_risks = []
    
    for chunk in chunks:
        parsed = llm.complete_structured(
            system_prompt=system_prompt,
            user_prompt=chunk,
            response_model=RiskList,
        )
        all_risks.extend(parsed.risks)
    
    grounding_result = verify_quotes(document.text, all_risks, document_id=document.id)
    
    seen_spans = set()
    unique_spans = []
    for span in grounding_result.accepted:
        span_key = (span.start_offset, span.end_offset)
        if span_key not in seen_spans:
            seen_spans.add(span_key)
            unique_spans.append(span)
            
    facts = []
    for span in unique_spans:
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


CATEGORY_RISK_FACTOR = "risk_factor"
CATEGORY_REVENUE_STREAM = "revenue_stream"
CATEGORY_COMPETITOR = "competitor"
CATEGORY_COMPETITIVE_MOAT = "competitive_moat"
CATEGORY_LIQUIDITY = "liquidity"
CATEGORY_KPI = "kpi"
CATEGORY_FORWARD_SENTIMENT = "forward_looking_sentiment"

def _extract_grouped(
    document: Document,
    system_prompt: str,
    response_model: type,
    field_to_category: dict[str, str],
    llm: LLMClient | None = None,
) -> list[QualitativeFact]:
    """Generalized grouped extractor (shared by business and MD&A paths)."""
    if document.id is None:
        raise ValueError("Document must be persisted before extraction.")
    if document.filing is None or document.filing.company_id is None:
        raise ValueError("Document must have a valid filing and company_id.")
        
    llm = llm or LLMClient()
    chunks = _chunk_text(document.text, chunk_size=40000, overlap=4000)
    
    candidates = {cat: [] for cat in field_to_category.values()}
    
    for chunk in chunks:
        parsed = llm.complete_structured(
            system_prompt=system_prompt,
            user_prompt=chunk,
            response_model=response_model,
        )
        for field, category in field_to_category.items():
            candidates[category].extend(getattr(parsed, field))
            
    accepted_by_span = {}
    for category, items in candidates.items():
        result = verify_quotes(document.text, items, document_id=document.id)
        for span in result.accepted:
            key = (span.start_offset, span.end_offset)
            if key not in accepted_by_span:
                accepted_by_span[key] = (category, span)
                
    facts = []
    for (category, span) in accepted_by_span.values():
        fact = QualitativeFact(
            company_id=document.filing.company_id,
            category=category,
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


def extract_business(
    document: Document,
    *,
    llm: LLMClient | None = None,
) -> list[QualitativeFact]:
    """Extract business profile from Item 1."""
    return _extract_grouped(
        document=document,
        system_prompt=_load_prompt("business.txt"),
        response_model=BusinessProfile,
        field_to_category={
            "revenue_streams": CATEGORY_REVENUE_STREAM,
            "competitors": CATEGORY_COMPETITOR,
            "moats": CATEGORY_COMPETITIVE_MOAT,
        },
        llm=llm
    )


def extract_management_discussion(
    document: Document,
    *,
    llm: LLMClient | None = None,
) -> list[QualitativeFact]:
    """Extract MD&A highlights from Item 7."""
    return _extract_grouped(
        document=document,
        system_prompt=_load_prompt("management_discussion.txt"),
        response_model=MDAnalysis,
        field_to_category={
            "liquidity": CATEGORY_LIQUIDITY,
            "kpis": CATEGORY_KPI,
            "forward_sentiment": CATEGORY_FORWARD_SENTIMENT,
        },
        llm=llm
    )
