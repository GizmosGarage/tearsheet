"""Structured facts with citations — financials, LLM-located spans, grounding."""

from tearsheet.extract.financials import extract_financial_facts
from tearsheet.extract.grounding import verify_quote_span
from tearsheet.extract.llm_client import LLMClient
from tearsheet.extract.qualitative import (
    extract_business,
    extract_management_discussion,
    extract_risk_factors,
)

__all__ = [
    "LLMClient",
    "extract_business",
    "extract_financial_facts",
    "extract_management_discussion",
    "extract_risk_factors",
    "verify_quote_span",
]
