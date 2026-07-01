"""The gate: verify each quote resolves to a span; reject if not."""

from __future__ import annotations

import re
from dataclasses import dataclass

from tearsheet.extract.schemas import LocatedQuote


@dataclass(frozen=True)
class GroundedSpan:
    """A quote verified against source text. All stored text is a source slice."""

    quote: str
    start_offset: int
    end_offset: int
    document_id: int
    label: str | None = None
    label_start_offset: int | None = None
    label_end_offset: int | None = None


@dataclass(frozen=True)
class GroundingResult:
    """Outcome of grounding verification."""

    accepted: list[GroundedSpan]
    rejected: list[LocatedQuote]


def _resolve_span(source_text: str, quoted: str) -> tuple[int, int] | None:
    """Locate a quote in source text, tolerating whitespace/case drift in the locator."""
    words = quoted.split()
    if not words:
        return None

    pattern_str = r'\s+'.join(re.escape(w) for w in words)
    match = re.search(pattern_str, source_text, re.IGNORECASE)
    if not match:
        return None
    return match.start(), match.end()


def verify_quote_span(
    source_text: str,
    quote: LocatedQuote,
    *,
    document_id: int,
) -> GroundedSpan | None:
    """Verify a single quote resolves to an exact span in source_text.

    The stored quote and label are always slices of ``source_text``, never the
    LLM's strings. A quote that does not resolve rejects the whole item; a
    label that does not resolve is dropped while the span is kept.
    """
    if not quote.exact_quote:
        return None

    span = _resolve_span(source_text, quote.exact_quote)
    if span is None:
        return None
    start, end = span

    label = None
    label_start = None
    label_end = None
    label_quote = getattr(quote, "label_quote", None)
    if label_quote:
        label_span = _resolve_span(source_text, label_quote)
        if label_span is not None:
            label_start, label_end = label_span
            label = source_text[label_start:label_end]

    return GroundedSpan(
        quote=source_text[start:end],
        start_offset=start,
        end_offset=end,
        document_id=document_id,
        label=label,
        label_start_offset=label_start,
        label_end_offset=label_end,
    )


def verify_quotes(
    source_text: str,
    quotes: list[LocatedQuote],
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
