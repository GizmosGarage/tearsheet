"""The gate: verify each quote resolves to a span; reject if not."""

from __future__ import annotations

from dataclasses import dataclass

from tearsheet.extract.schemas import RiskFactor


@dataclass(frozen=True)
class GroundedSpan:
    """A quote verified against source text."""

    quote: str
    summary: str
    start_offset: int
    end_offset: int
    document_id: int


@dataclass(frozen=True)
class GroundingResult:
    """Outcome of grounding verification."""

    accepted: list[GroundedSpan]
    rejected: list[RiskFactor]


def verify_quote_span(
    source_text: str,
    quote: RiskFactor,
    *,
    document_id: int,
) -> GroundedSpan | None:
    """Verify a single quote resolves to an exact span in source_text."""
    if not quote.exact_quote:
        return None
        
    start_offset = source_text.find(quote.exact_quote)
    if start_offset == -1:
        return None
        
    return GroundedSpan(
        quote=quote.exact_quote,
        summary=quote.summary,
        start_offset=start_offset,
        end_offset=start_offset + len(quote.exact_quote),
        document_id=document_id
    )


def verify_quotes(
    source_text: str,
    quotes: list[RiskFactor],
    *,
    document_id: int,
) -> GroundingResult:
    """Verify all quotes; partition into accepted and rejected."""
    accepted = []
    rejected = []
    
    for q in quotes:
        span = verify_quote_span(source_text, q, document_id=document_id)
        if span is not None:
            accepted.append(span)
        else:
            rejected.append(q)
            
    return GroundingResult(accepted=accepted, rejected=rejected)
