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


def collapse_series_by_fiscal_year(
    series: list[tuple[date, float]],
) -> dict[int, tuple[date, float]]:
    """One representative (period_end, value) per fiscal year (latest period_end wins)."""
    by_year: dict[int, tuple[date, float]] = {}
    for d, v in series:
        if d.year not in by_year or d > by_year[d.year][0]:
            by_year[d.year] = (d, v)
    return by_year


def align_by_fiscal_year(
    *series: list[tuple[date, float]],
) -> list[tuple[date, tuple[float, ...]]]:
    """Inner-join multiple series on fiscal year. Representative date = max period_end
    among the joined series for that year. Only years present in ALL series survive."""
    if not series:
        return []
    collapsed = [collapse_series_by_fiscal_year(s) for s in series]
    common_years = set(collapsed[0])
    for c in collapsed[1:]:
        common_years &= set(c)
    result = []
    for y in sorted(common_years):
        rep_date = max(c[y][0] for c in collapsed)
        result.append((rep_date, tuple(c[y][1] for c in collapsed)))
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

    all_years = set()
    for s in [rev_series, gross_series, op_series, net_series, ocf_series, capex_series, debt_series, equity_series]:
        all_years.update(d.year for d, _ in s)
    
    gross_margin_data = {d.year: (g/r if r else None) for d, (g, r) in align_by_fiscal_year(gross_series, rev_series)}
    op_margin_data = {d.year: (o/r if r else None) for d, (o, r) in align_by_fiscal_year(op_series, rev_series)}
    net_margin_data = {d.year: (n/r if r else None) for d, (n, r) in align_by_fiscal_year(net_series, rev_series)}
    fcf_data = {d.year: (ocf - capex) for d, (ocf, capex) in align_by_fiscal_year(ocf_series, capex_series)}
    
    fcf_series = [(date(y, 12, 31), v) for y, v in fcf_data.items()]
    fcf_margin_data = {d.year: (fcf/r if r else None) for d, (fcf, r) in align_by_fiscal_year(fcf_series, rev_series)}
    debt_equity_data = {d.year: (debt/eq if eq else None) for d, (debt, eq) in align_by_fiscal_year(debt_series, equity_series)}
    roe_data = {d.year: (n/eq if eq else None) for d, (n, eq) in align_by_fiscal_year(net_series, equity_series)}
    
    rev_by_year = collapse_series_by_fiscal_year(rev_series)
    
    rep_dates = {}
    for y in all_years:
        dates_for_y = []
        for s in [rev_series, gross_series, op_series, net_series, ocf_series, capex_series, debt_series, equity_series]:
            for d, _ in s:
                if d.year == y:
                    dates_for_y.append(d)
        rep_dates[y] = max(dates_for_y)
        
    rows = []
    sorted_years = sorted(list(all_years))
    for i, y in enumerate(sorted_years):
        rep_date = rep_dates[y]
        
        rev_info = rev_by_year.get(y)
        rev = rev_info[1] if rev_info else None
        
        rev_yoy = None
        if rev is not None and i > 0:
            prev_y = sorted_years[i-1]
            if y - prev_y == 1:
                prev_rev_info = rev_by_year.get(prev_y)
                prev_rev = prev_rev_info[1] if prev_rev_info else None
                if prev_rev:
                    rev_yoy = (rev - prev_rev) / prev_rev
                
        rows.append(FinancialSummaryRow(
            period_end=rep_date,
            revenue=rev,
            revenue_yoy=rev_yoy,
            gross_margin=gross_margin_data.get(y),
            operating_margin=op_margin_data.get(y),
            net_margin=net_margin_data.get(y),
            fcf=fcf_data.get(y),
            fcf_margin=fcf_margin_data.get(y),
            debt_to_equity=debt_equity_data.get(y),
            roe=roe_data.get(y),
        ))
        
    return rows
