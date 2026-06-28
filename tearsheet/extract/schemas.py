"""Pydantic shapes the LLM must return."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RiskFactor(BaseModel):
    """A single extracted risk factor."""
    summary: str = Field(description="A concise summary of the risk factor.")
    exact_quote: str = Field(description="Exact verbatim text from the source document supporting this risk.", min_length=3)

class RiskList(BaseModel):
    """A list of extracted risk factors."""
    risks: list[RiskFactor]


class GroundedItem(BaseModel):
    summary: str = Field(description="A concise plain-English summary of this item.")
    exact_quote: str = Field(
        description="Exact verbatim substring copied from the source text. No paraphrase.",
        min_length=3,
    )


class BusinessProfile(BaseModel):
    revenue_streams: list[GroundedItem] = Field(
        default_factory=list,
        description="Core products/services/segments the company earns revenue from.",
    )
    competitors: list[GroundedItem] = Field(
        default_factory=list,
        description="Named or described competitors and competitive pressures.",
    )
    moats: list[GroundedItem] = Field(
        default_factory=list,
        description="Durable competitive advantages: scale, IP, switching costs, brand, network effects.",
    )


class MDAnalysis(BaseModel):
    liquidity: list[GroundedItem] = Field(
        default_factory=list,
        description="Liquidity & capital resources: cash position, debt, credit facilities, capital allocation.",
    )
    kpis: list[GroundedItem] = Field(
        default_factory=list,
        description="Key performance indicators and operating metrics management emphasizes.",
    )
    forward_sentiment: list[GroundedItem] = Field(
        default_factory=list,
        description="Management's forward-looking statements, outlook, guidance, and tone.",
    )
