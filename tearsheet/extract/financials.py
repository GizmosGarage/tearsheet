"""XBRL companyfacts -> FinancialFact rows (no LLM)."""

from __future__ import annotations

from typing import Any
from datetime import date

from tearsheet.store.models import FinancialFact

FINANCIAL_CONCEPTS: tuple[str, ...] = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "GrossProfit",
    "OperatingIncomeLoss",
    "NetIncomeLoss",
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "CashAndCashEquivalentsAtCarryingValue",
    "NetCashProvidedByUsedInOperatingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "LongTermDebtNoncurrent",
)


def extract_financial_facts(
    company_id: int,
    companyfacts: dict[str, Any],
) -> list[FinancialFact]:
    """Parse SEC companyfacts JSON into FinancialFact rows."""
    facts: list[FinancialFact] = []
    
    us_gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    if not us_gaap or not isinstance(us_gaap, dict):
        return facts
        
    for concept in FINANCIAL_CONCEPTS:
        concept_data = us_gaap.get(concept)
        if not concept_data or not isinstance(concept_data, dict):
            continue
            
        label = concept_data.get("label")
        units_data = concept_data.get("units", {})
        if not isinstance(units_data, dict):
            continue
            
        for unit, datapoints in units_data.items():
            if not isinstance(datapoints, list):
                continue
                
            # Filter to annual
            annual_pts = []
            for pt in datapoints:
                if not isinstance(pt, dict):
                    continue
                if pt.get("form") == "10-K" or pt.get("fp") == "FY":
                    annual_pts.append(pt)
                    
            # Sort by filed ascending
            annual_pts.sort(key=lambda x: str(x.get("filed", "")))
            
            for pt in annual_pts:
                value = pt.get("val")
                
                # Parse date
                end_str = pt.get("end")
                period_end = None
                if end_str:
                    try:
                        period_end = date.fromisoformat(str(end_str))
                    except ValueError:
                        pass
                
                fact = FinancialFact(
                    company_id=company_id,
                    concept=concept,
                    label=label,
                    unit=unit,
                    value=value,
                    period_end=period_end
                )
                facts.append(fact)
                
    return facts
