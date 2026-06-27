"""Pydantic shapes the LLM must return."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CitedQuote(BaseModel):
    """A verbatim quote with its source location."""

    quote: str = Field(description="Exact verbatim text from the source document")
    document_section: str = Field(description="Section identifier, e.g. Item 1A")
    start_offset: int | None = Field(default=None, description="Character offset in section text")
    end_offset: int | None = Field(default=None, description="Character offset in section text")


class RiskFactorExtraction(BaseModel):
    """Structured risk-factor extraction result."""

    summary: str
    quotes: list[CitedQuote]


class CompetitionExtraction(BaseModel):
    """Structured competition / market-position extraction result."""

    summary: str
    quotes: list[CitedQuote]


class BusinessExtraction(BaseModel):
    """Structured business description extraction result."""

    summary: str
    quotes: list[CitedQuote]


class ManagementDiscussionExtraction(BaseModel):
    """Structured MD&A extraction result."""

    summary: str
    quotes: list[CitedQuote]
