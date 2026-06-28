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
    """Deterministic trajectory table: one row per fiscal year, sorted ASC."""
    rev_series = resolve_series(series_by_concept, REVENUE_CONCEPTS)
    gross_series = series_by_concept.get("GrossProfit", [])
    op_series = series_by_concept.get("OperatingIncomeLoss", [])
    net_series = series_by_concept.get("NetIncomeLoss", [])
    ocf_series = series_by_concept.get("NetCashProvidedByUsedInOperatingActivities", [])
    capex_series = series_by_concept.get("PaymentsToAcquirePropertyPlantAndEquipment", [])
    debt_series = series_by_concept.get("LongTermDebtNoncurrent", [])
    equity_series = series_by_concept.get("StockholdersEquity", [])

    # Filter out SENTINEL_PERIOD_END and None defensively
    def filter_defensive(series):
        return [(d, v) for d, v in series if d != SENTINEL_PERIOD_END and v is not None]

    rev_series = filter_defensive(rev_series)
    gross_series = filter_defensive(gross_series)
    op_series = filter_defensive(op_series)
    net_series = filter_defensive(net_series)
    ocf_series = filter_defensive(ocf_series)
    capex_series = filter_defensive(capex_series)
    debt_series = filter_defensive(debt_series)
    equity_series = filter_defensive(equity_series)

    all_dates = set()
    for s in [rev_series, gross_series, op_series, net_series, ocf_series, capex_series, debt_series, equity_series]:
        all_dates.update(d for d, _ in s)
    
    gross_margin_data = {d: (g/r if r else None) for d, (g, r) in align_by_period(gross_series, rev_series)}
    op_margin_data = {d: (o/r if r else None) for d, (o, r) in align_by_period(op_series, rev_series)}
    net_margin_data = {d: (n/r if r else None) for d, (n, r) in align_by_period(net_series, rev_series)}
    fcf_data = {d: (ocf - capex) for d, (ocf, capex) in align_by_period(ocf_series, capex_series)}
    
    fcf_series = [(d, v) for d, v in fcf_data.items()]
    fcf_margin_data = {d: (fcf/r if r else None) for d, (fcf, r) in align_by_period(fcf_series, rev_series)}
    debt_equity_data = {d: (debt/eq if eq else None) for d, (debt, eq) in align_by_period(debt_series, equity_series)}
    roe_data = {d: (n/eq if eq else None) for d, (n, eq) in align_by_period(net_series, equity_series)}
    
    rev_map = dict(rev_series)
    
    rows = []
    sorted_dates = sorted(list(all_dates))
    for i, d in enumerate(sorted_dates):
        rev = rev_map.get(d)
        
        rev_yoy = None
        if rev is not None and i > 0:
            prev_d = sorted_dates[i-1]
            prev_rev = rev_map.get(prev_d)
            if prev_rev and (d - prev_d).days <= 400:
                rev_yoy = (rev - prev_rev) / prev_rev
                
        rows.append(FinancialSummaryRow(
            period_end=d,
            revenue=rev,
            revenue_yoy=rev_yoy,
            gross_margin=gross_margin_data.get(d),
            operating_margin=op_margin_data.get(d),
            net_margin=net_margin_data.get(d),
            fcf=fcf_data.get(d),
            fcf_margin=fcf_margin_data.get(d),
            debt_to_equity=debt_equity_data.get(d),
            roe=roe_data.get(d),
        ))
        
    return rows
