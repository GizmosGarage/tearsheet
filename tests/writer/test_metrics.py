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


class TestBuildFinancialSummary:
    """Derived metrics edge cases — must return None, never raise."""

    def test_revenue_yoy_consecutive_years(self):
        pass

    def test_revenue_yoy_single_year_returns_none(self):
        # - [ ] Only one revenue period → revenue_yoy is None
        pass

    def test_margins_align_on_shared_periods_only(self):
        # - [ ] Gross margin computed only when Revenue and GrossProfit share period_end
        pass

    def test_fcf_sign_convention_ocf_minus_capex(self):
        # - [ ] FCF = OCF - capex (capex reported as positive outflow magnitude)
        pass

    def test_missing_denominator_returns_none(self):
        # - [ ] Zero or missing denominator → metric None, not ZeroDivisionError
        pass

    def test_sentinel_period_excluded(self):
        # - [ ] date(1970, 1, 1) excluded defensively
        pass

    def test_all_metrics_none_on_empty_input(self):
        pass
