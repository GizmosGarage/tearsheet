"""Pydantic shapes the LLM must return — locator-only, never authored text."""

from __future__ import annotations

from pydantic import BaseModel, Field

_QUOTE_RULE = (
    "Exact verbatim substring copied character-for-character from the source text. "
    "You are a locator, not a writer. Any text not present verbatim in the source "
    "will be discarded."
)
_LABEL_RULE = (
    "Optional short verbatim phrase from the source that labels this span, e.g. a "
    "bold lead-in sentence or sub-heading. Copy characters exactly from the source. "
    "You are a locator, not a writer. Any text not present verbatim in the source "
    "will be discarded. Omit if the source has no such label."
)


class LocatedQuote(BaseModel):
    """A span locator: a verbatim quote plus an optional verbatim label."""

    exact_quote: str = Field(description=_QUOTE_RULE, min_length=3)
    label_quote: str | None = Field(default=None, description=_LABEL_RULE)


class RiskFactor(LocatedQuote):
    """A single located risk factor span."""


class RiskList(BaseModel):
    """A list of located risk factor spans."""
    risks: list[RiskFactor]


class GroundedItem(LocatedQuote):
    """A single located span for grouped extraction."""


class BusinessProfile(BaseModel):
    revenue_streams: list[GroundedItem] = Field(
        default_factory=list,
        description="Spans describing core products/services/segments the company earns revenue from.",
    )
    competitors: list[GroundedItem] = Field(
        default_factory=list,
        description="Spans naming or describing competitors and competitive pressures.",
    )
    moats: list[GroundedItem] = Field(
        default_factory=list,
        description="Spans asserting durable competitive advantages: scale, IP, switching costs, brand, network effects.",
    )


class MDAnalysis(BaseModel):
    liquidity: list[GroundedItem] = Field(
        default_factory=list,
        description="Spans on liquidity & capital resources: cash position, debt, credit facilities, capital allocation.",
    )
    kpis: list[GroundedItem] = Field(
        default_factory=list,
        description="Spans stating key performance indicators and operating metrics management emphasizes.",
    )
    forward_sentiment: list[GroundedItem] = Field(
        default_factory=list,
        description="Spans containing management's forward-looking statements, outlook, and guidance.",
    )
