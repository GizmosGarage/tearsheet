"""The gate: verify each quote resolves to a span; reject if not."""

from __future__ import annotations

from dataclasses import dataclass

from tearsheet.extract.schemas import CitedQuote


@dataclass(frozen=True)
class GroundedSpan:
    """A quote verified against source text."""

    quote: str
    start_offset: int
    end_offset: int
    document_id: int


@dataclass(frozen=True)
class GroundingResult:
    """Outcome of grounding verification."""

    accepted: list[GroundedSpan]
    rejected: list[CitedQuote]


def verify_quote_span(
    source_text: str,
    quote: CitedQuote,
    *,
    document_id: int,
) -> GroundedSpan | None:
    """Verify a single quote resolves to an exact span in source_text."""
    raise NotImplementedError


def verify_quotes(
    source_text: str,
    quotes: list[CitedQuote],
    *,
    document_id: int,
) -> GroundingResult:
    """Verify all quotes; partition into accepted and rejected."""
    raise NotImplementedError
