"""XBRL companyfacts -> FinancialFact rows (no LLM).

As-filed facts carry full ancestry back to the companyfacts payload
(accession, taxonomy-qualified concept, fiscal period, untouched value
string). Derived facts (margins) carry a machine-readable ``derivation``
referencing their input facts' identities, and are only emitted when every
input is present — a missing input yields no derived fact, never a partial
one.
"""

from __future__ import annotations

import json
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

REVENUE_PRIORITY: tuple[str, ...] = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
)

# (derived concept name, numerator concept)
DERIVED_MARGINS: tuple[tuple[str, str], ...] = (
    ("GrossMargin", "GrossProfit"),
    ("OperatingMargin", "OperatingIncomeLoss"),
    ("NetMargin", "NetIncomeLoss"),
)


def _fact_identity(fact: FinancialFact) -> dict[str, Any]:
    return {
        "xbrl_concept": fact.xbrl_concept,
        "fiscal_year": fact.fiscal_year,
        "fiscal_period": fact.fiscal_period,
        "accession_number": fact.accession_number,
    }


def derive_margin_facts(
    company_id: int,
    facts: list[FinancialFact],
) -> list[FinancialFact]:
    """Emit margin facts derived by visible arithmetic over as-filed facts.

    Inputs must share the same (fiscal_year, fiscal_period, accession_number)
    — one filing's own self-consistent view — and both must exist, otherwise
    no derived fact is emitted for that period.
    """
    usd = [f for f in facts if f.unit == "USD" and f.derivation is None]
    by_key = {
        (f.concept, f.fiscal_year, f.fiscal_period, f.accession_number): f
        for f in usd
    }
    period_keys = sorted({
        (f.fiscal_year, f.fiscal_period, f.accession_number) for f in usd
    }, key=str)

    derived = []
    for (fy, fp, accn) in period_keys:
        revenue = None
        for rev_concept in REVENUE_PRIORITY:
            revenue = by_key.get((rev_concept, fy, fp, accn))
            if revenue is not None:
                break
        if revenue is None or not revenue.value:
            continue

        for derived_name, num_concept in DERIVED_MARGINS:
            numerator = by_key.get((num_concept, fy, fp, accn))
            if numerator is None or numerator.value is None:
                continue

            derivation = json.dumps({
                "op": "div",
                "inputs": [_fact_identity(numerator), _fact_identity(revenue)],
            })
            derived.append(FinancialFact(
                company_id=company_id,
                concept=derived_name,
                xbrl_concept=f"derived:{derived_name}",
                accession_number=accn,
                unit="pure",
                fiscal_year=fy,
                fiscal_period=fp,
                period_end=revenue.period_end,
                value=numerator.value / revenue.value,
                as_filed_value=None,
                derivation=derivation,
            ))

    return derived


def extract_financial_facts(
    company_id: int,
    companyfacts: dict[str, Any],
) -> list[FinancialFact]:
    """Parse SEC companyfacts JSON into FinancialFact rows with full ancestry."""
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
                accession = pt.get("accn")
                fiscal_year = pt.get("fy")
                fiscal_period = pt.get("fp")

                # Identity requires ancestry; a point missing it cannot be
                # traced back to a filing and is not emitted.
                if value is None or not accession or fiscal_year is None or not fiscal_period:
                    continue

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
                    xbrl_concept=f"us-gaap:{concept}",
                    accession_number=str(accession),
                    unit_ref=unit,
                    fiscal_year=int(fiscal_year),
                    fiscal_period=str(fiscal_period),
                    label=label,
                    unit=unit,
                    value=value,
                    as_filed_value=str(value),
                    period_end=period_end,
                    derivation=None,
                )
                facts.append(fact)

    facts.extend(derive_margin_facts(company_id, facts))
    return facts
