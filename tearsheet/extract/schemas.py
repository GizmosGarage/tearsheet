"""Pydantic shapes the LLM must return."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RiskFactor(BaseModel):
    """A single extracted risk factor."""
    summary: str = Field(description="A concise summary of the risk factor.")
    exact_quote: str = Field(description="Exact verbatim text from the source document supporting this risk.")

class RiskList(BaseModel):
    """A list of extracted risk factors."""
    risks: list[RiskFactor]
