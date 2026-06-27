"""XBRL companyfacts -> FinancialFact rows (no LLM)."""

from __future__ import annotations

from typing import Any

from tearsheet.store.models import FinancialFact


def extract_financial_facts(
    company_id: int,
    companyfacts: dict[str, Any],
) -> list[FinancialFact]:
    """Parse SEC companyfacts JSON into FinancialFact rows."""
    raise NotImplementedError
