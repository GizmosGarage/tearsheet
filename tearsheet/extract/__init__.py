"""Structured facts with citations — financials, qualitative LLM extraction, grounding."""

from tearsheet.extract.financials import extract_financial_facts
from tearsheet.extract.grounding import verify_quote_span
from tearsheet.extract.llm_client import LLMClient
from tearsheet.extract.qualitative import extract_qualitative_facts

__all__ = [
    "LLMClient",
    "extract_financial_facts",
    "extract_qualitative_facts",
    "verify_quote_span",
]
