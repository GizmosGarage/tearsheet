"""Pure unit tests for tearsheet.writer.metrics — no DB."""

from __future__ import annotations

from datetime import date

import pytest

from tearsheet.writer.metrics import (
    FinancialSummaryRow,
    align_by_period,
    build_financial_summary,
    resolve_series,
)


class TestResolveSeries:
    """Revenue concept priority resolution."""

    def test_first_non_empty_concept_wins(self):
        # - [ ] RevenueFromContractWithCustomerExcludingAssessedTax preferred over Revenues
        series_map = {
            "Revenues": [(date(2020, 1, 1), 100.0)],
            "RevenueFromContractWithCustomerExcludingAssessedTax": [(date(2020, 1, 1), 200.0)],
            "EmptyConcept": []
        }
        concepts = ["EmptyConcept", "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"]
        resolved = resolve_series(series_map, concepts)
        assert resolved == [(date(2020, 1, 1), 200.0)]

    def test_empty_dict_returns_empty_series(self):
        assert resolve_series({}, ["Revenues"]) == []


class TestAlignByPeriod:
    """Period alignment inner-join."""

    def test_only_shared_periods_survive(self):
        # - [ ] Dates present in one series but not the other are dropped
        s1 = [(date(2020, 1, 1), 10.0), (date(2021, 1, 1), 20.0)]
        s2 = [(date(2021, 1, 1), 200.0), (date(2022, 1, 1), 300.0)]
        aligned = align_by_period(s1, s2)
        assert len(aligned) == 1
        assert aligned[0] == (date(2021, 1, 1), (20.0, 200.0))

    def test_no_positional_alignment_assumption(self):
        # - [ ] Misaligned input order still joins on date, not index
        s1 = [(date(2021, 1, 1), 20.0), (date(2020, 1, 1), 10.0)]
        s2 = [(date(2020, 1, 1), 100.0), (date(2021, 1, 1), 200.0)]
        aligned = align_by_period(s1, s2)
        assert len(aligned) == 2
        assert aligned[0] == (date(2020, 1, 1), (10.0, 100.0))
        assert aligned[1] == (date(2021, 1, 1), (20.0, 200.0))

class TestAlignByFiscalYear:
    def test_only_shared_years_survive(self):
        from tearsheet.writer.metrics import align_by_fiscal_year
        s1 = [(date(2020, 1, 20), 10.0), (date(2021, 1, 25), 20.0)]
        s2 = [(date(2021, 1, 31), 200.0), (date(2022, 1, 31), 300.0)]
        aligned = align_by_fiscal_year(s1, s2)
        assert len(aligned) == 1
        # Rep date is the max of the periods in that year -> 2021-01-31
        assert aligned[0] == (date(2021, 1, 31), (20.0, 200.0))
        
    def test_latest_period_end_wins_within_year(self):
        from tearsheet.writer.metrics import align_by_fiscal_year
        s1 = [(date(2021, 1, 10), 10.0), (date(2021, 1, 20), 20.0)] # 20.0 should win
        s2 = [(date(2021, 1, 31), 200.0)]
        aligned = align_by_fiscal_year(s1, s2)
        assert len(aligned) == 1
        assert aligned[0] == (date(2021, 1, 31), (20.0, 200.0))


class TestBuildFinancialSummary:
    """Derived metrics edge cases — must return None, never raise."""

    def test_revenue_yoy_consecutive_years(self):
        series_by_concept = {
            "Revenues": [(date(2020, 12, 31), 100.0), (date(2021, 12, 31), 150.0)]
        }
        summary = build_financial_summary(series_by_concept)
        assert len(summary) == 2
        assert summary[0].revenue_yoy is None
        assert summary[1].revenue_yoy == 0.5

    def test_revenue_yoy_single_year_returns_none(self):
        # - [ ] Only one revenue period → revenue_yoy is None
        series_by_concept = {
            "Revenues": [(date(2020, 12, 31), 100.0)]
        }
        summary = build_financial_summary(series_by_concept)
        assert len(summary) == 1
        assert summary[0].revenue_yoy is None
        
        # Test non-consecutive gap uses year adjacency
        series_gap = {
            "Revenues": [(date(2019, 12, 31), 100.0), (date(2021, 12, 31), 150.0)]
        }
        summary_gap = build_financial_summary(series_gap)
        assert summary_gap[1].revenue_yoy is None

    def test_margins_align_on_shared_periods_only(self):
        series_by_concept = {
            "Revenues": [(date(2021, 12, 31), 100.0)],
            "GrossProfit": [(date(2021, 12, 31), 40.0), (date(2022, 12, 31), 50.0)]
        }
        summary = build_financial_summary(series_by_concept)
        assert len(summary) == 2
        
        # 2021 shared
        assert summary[0].period_end.year == 2021
        assert summary[0].gross_margin == 0.4
        
        # 2022 not shared
        assert summary[1].period_end.year == 2022
        assert summary[1].gross_margin is None
        
    def test_same_fiscal_year_restatements_collapse_to_one_row(self):
        series = {
            "Revenues": [(date(2009, 1, 25), 100.0), (date(2009, 1, 26), 105.0)]
        }
        summary = build_financial_summary(series)
        assert len(summary) == 1
        assert summary[0].period_end == date(2009, 1, 26)
        assert summary[0].revenue == 105.0
        
    def test_cross_concept_floating_fye_still_aligns(self):
        series = {
            "Revenues": [(date(2010, 1, 31), 100.0)],
            "GrossProfit": [(date(2010, 1, 25), 40.0)]
        }
        summary = build_financial_summary(series)
        assert len(summary) == 1
        assert summary[0].period_end == date(2010, 1, 31)
        assert summary[0].gross_margin == 0.4

    def test_fcf_sign_convention_ocf_minus_capex(self):
        # - [ ] FCF = OCF - capex (capex reported as positive outflow magnitude)
        series_by_concept = {
            "NetCashProvidedByUsedInOperatingActivities": [(date(2021, 12, 31), 100.0)],
            "PaymentsToAcquirePropertyPlantAndEquipment": [(date(2021, 12, 31), 30.0)]
        }
        summary = build_financial_summary(series_by_concept)
        assert summary[0].fcf == 70.0 # 100 - 30

    def test_missing_denominator_returns_none(self):
        # - [ ] Zero or missing denominator → metric None, not ZeroDivisionError
        series_by_concept = {
            "Revenues": [(date(2021, 12, 31), 0.0)],
            "GrossProfit": [(date(2021, 12, 31), 40.0)],
            "StockholdersEquity": [(date(2021, 12, 31), 0.0)],
            "LongTermDebtNoncurrent": [(date(2021, 12, 31), 50.0)],
            "NetIncomeLoss": [(date(2021, 12, 31), 10.0)]
        }
        summary = build_financial_summary(series_by_concept)
        assert summary[0].gross_margin is None
        assert summary[0].debt_to_equity is None
        assert summary[0].roe is None

    def test_sentinel_period_excluded(self):
        # - [ ] date(1970, 1, 1) excluded defensively
        series_by_concept = {
            "Revenues": [(date(1970, 1, 1), 100.0), (date(2021, 12, 31), 100.0)]
        }
        summary = build_financial_summary(series_by_concept)
        assert len(summary) == 1
        assert summary[0].period_end == date(2021, 12, 31)

    def test_all_metrics_none_on_empty_input(self):
        assert build_financial_summary({}) == []
