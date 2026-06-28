"""Pure financial metrics — no DB, no I/O, no formatting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

REVENUE_CONCEPTS: list[str] = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
]

NEEDED_CONCEPTS: list[str] = [
    *REVENUE_CONCEPTS,
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
]

SENTINEL_PERIOD_END = date(1970, 1, 1)


@dataclass(frozen=True)
class FinancialSummaryRow:
    """One fiscal year of derived metrics; each field is ``None`` when unavailable."""

    period_end: date
    revenue: float | None
    revenue_yoy: float | None
    gross_margin: float | None
    operating_margin: float | None
    net_margin: float | None
    fcf: float | None
    fcf_margin: float | None
    debt_to_equity: float | None
    roe: float | None


def resolve_series(
    series_by_concept: dict[str, list[tuple[date, float]]],
    concepts: list[str],
) -> list[tuple[date, float]]:
    """Return the first non-empty series matching ``concepts`` in priority order."""
    for concept in concepts:
        if concept in series_by_concept and series_by_concept[concept]:
            return series_by_concept[concept]
    return []


def align_by_period(
    *series: list[tuple[date, float]],
) -> list[tuple[date, tuple[float, ...]]]:
    """Inner-join multiple series on ``period_end``.

    Only dates present in **all** input series survive. Never assume positional
    alignment between two series — this is the correctness keystone for ratios.
    """
    if not series:
        return []
        
    maps = [{d: v for d, v in s} for s in series]
    
    common_dates = set(maps[0].keys())
    for m in maps[1:]:
        common_dates &= set(m.keys())
        
    result = []
    for d in sorted(common_dates):
        result.append((d, tuple(m[d] for m in maps)))
        
    return result


def build_financial_summary(
    series_by_concept: dict[str, list[tuple[date, float]]],
) -> list[FinancialSummaryRow]:
    """Deterministic trajectory table: one row per fiscal year, sorted ASC.

    Revenue concept resolution (priority — first concept with data wins):
        1. ``RevenueFromContractWithCustomerExcludingAssessedTax``
        2. ``Revenues``

    Period alignment:
        Every ratio combines two concepts and **must align on identical
        ``period_end``**. Build a date→value map per concept; only compute a
        metric for periods present in *both* series. Use ``align_by_period``.

    Metrics (``None`` when inputs missing or denominator is zero/``None`` —
    no function may raise on missing data):

        +-------------------+--------------------------------------------------+
        | Metric            | Formula                                          |
        +-------------------+--------------------------------------------------+
        | Revenue YoY       | ``(rev_t - rev_{t-1}) / rev_{t-1}``              |
        | Gross margin      | ``GrossProfit / Revenue``                        |
        | Operating margin  | ``OperatingIncomeLoss / Revenue``                |
        | Net margin        | ``NetIncomeLoss / Revenue``                      |
        | Free cash flow    | ``OCF - Capex`` (see sign note below)            |
        | FCF margin        | ``FCF / Revenue``                                |
        | Debt-to-equity    | ``LongTermDebtNoncurrent / StockholdersEquity``  |
        | ROE               | ``NetIncomeLoss / StockholdersEquity``           |
        +-------------------+--------------------------------------------------+

    FCF sign convention:
        XBRL reports ``PaymentsToAcquirePropertyPlantAndEquipment`` as a positive
        outflow magnitude → ``FCF = NetCashProvidedByUsedInOperatingActivities
        - PaymentsToAcquirePropertyPlantAndEquipment``. A sign error here silently
        corrupts the number.

    Hard rules:
        - Exclude ``1970-01-01`` sentinel and NULL values (re-assert defensively
          even though ``get_financial_series`` filters upstream).
        - Division guards: denominator ``None`` or ``0`` → metric ``None``.
        - No annualization / no quarter mixing — inputs are 10-K annual facts.

    Checklist (Part A2):
        - [ ] ``REVENUE_CONCEPTS`` priority via ``resolve_series``
        - [ ] ``align_by_period`` for all multi-concept metrics
        - [ ] YoY across consecutive revenue periods only
        - [ ] Sentinel exclusion defensive filter
        - [ ] Every edge returns ``None``, never raises
    """
    pass
