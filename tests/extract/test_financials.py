"""Tests for XBRL financial fact extraction with ancestry and derivations."""

from __future__ import annotations

import json
import os
import pytest
from datetime import date
from unittest.mock import patch
import tearsheet.store.db as db

@pytest.fixture(autouse=True)
def mock_db_url():
    with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:"}):
        db._engine = None
        db._SessionLocal = None
        db.init_db()
        yield
        db._engine = None
        db._SessionLocal = None

from tearsheet.extract.financials import extract_financial_facts
from tearsheet.store.models import FinancialFact
from tearsheet.store.repository import Repository


def _pt(val, end, accn, fy, fp="FY", form="10-K", filed="2024-02-10"):
    return {"val": val, "end": end, "accn": accn, "fy": fy, "fp": fp, "form": form, "filed": filed}


class TestExtractFinancials:
    """Integration tests for extract_financial_facts."""

    def test_extract_financials_filtering_and_ancestry(self):
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "label": "Revenues Label",
                        "units": {
                            "USD": [
                                # 10-Q (should be filtered out)
                                {"form": "10-Q", "fp": "Q1", "val": 100, "end": "2023-03-31",
                                 "accn": "0001-23-000001", "fy": 2023, "filed": "2023-04-10"},
                                # 10-K missing accession — untraceable, must be skipped
                                {"form": "10-K", "fp": "FY", "fy": 2023, "val": 500,
                                 "end": "2023-12-31", "filed": "2024-02-10"},
                                _pt(400, "2023-12-31", "0001-24-000009", 2023),
                            ],
                        }
                    },
                    "IgnoredConcept": {
                        "label": "Ignored",
                        "units": {"USD": [_pt(999, "2022-12-31", "0001-23-000005", 2022)]}
                    }
                }
            }
        }

        facts = extract_financial_facts(company_id=42, companyfacts=companyfacts)

        # Only the fully-traceable annual Revenues point survives
        assert len(facts) == 1
        rev = facts[0]
        assert rev.concept == "Revenues"
        assert rev.xbrl_concept == "us-gaap:Revenues"
        assert rev.accession_number == "0001-24-000009"
        assert rev.fiscal_year == 2023
        assert rev.fiscal_period == "FY"
        assert rev.unit == "USD"
        assert rev.unit_ref == "USD"
        assert rev.value == 400
        assert rev.as_filed_value == "400"
        assert rev.period_end == date(2023, 12, 31)
        assert rev.label == "Revenues Label"
        assert rev.derivation is None

    def test_derived_margins_carry_resolvable_derivations(self):
        accn = "0001-24-000009"
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "Revenues": {"units": {"USD": [_pt(1000, "2023-12-31", accn, 2023)]}},
                    "GrossProfit": {"units": {"USD": [_pt(600, "2023-12-31", accn, 2023)]}},
                    "OperatingIncomeLoss": {"units": {"USD": [_pt(250, "2023-12-31", accn, 2023)]}},
                    "NetIncomeLoss": {"units": {"USD": [_pt(200, "2023-12-31", accn, 2023)]}},
                }
            }
        }

        facts = extract_financial_facts(company_id=42, companyfacts=companyfacts)

        as_filed = [f for f in facts if f.derivation is None]
        derived = [f for f in facts if f.derivation is not None]
        assert len(as_filed) == 4
        assert {f.concept for f in derived} == {"GrossMargin", "OperatingMargin", "NetMargin"}

        by_identity = {
            (f.xbrl_concept, f.fiscal_year, f.fiscal_period, f.accession_number): f
            for f in as_filed
        }
        gross = next(f for f in derived if f.concept == "GrossMargin")
        assert gross.value == pytest.approx(0.6)
        assert gross.as_filed_value is None
        assert gross.xbrl_concept == "derived:GrossMargin"
        assert gross.fiscal_year == 2023 and gross.accession_number == accn

        # The derivation JSON re-resolves to real input facts and re-executes
        deriv = json.loads(gross.derivation)
        assert deriv["op"] == "div"
        inputs = [
            by_identity[(i["xbrl_concept"], i["fiscal_year"], i["fiscal_period"], i["accession_number"])]
            for i in deriv["inputs"]
        ]
        assert inputs[0].value / inputs[1].value == gross.value

    def test_margin_with_missing_input_not_emitted(self):
        # GrossProfit present, revenue ABSENT -> no margin at all
        # (kills the blank-revenue-with-populated-margin bug class)
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "GrossProfit": {"units": {"USD": [_pt(600, "2023-12-31", "0001-24-000009", 2023)]}},
                    "NetIncomeLoss": {"units": {"USD": [_pt(200, "2023-12-31", "0001-24-000009", 2023)]}},
                }
            }
        }

        facts = extract_financial_facts(company_id=42, companyfacts=companyfacts)
        assert all(f.derivation is None for f in facts)
        assert {f.concept for f in facts} == {"GrossProfit", "NetIncomeLoss"}

    def test_margins_never_mix_accessions(self):
        # Revenue only in accession A, GrossProfit only in accession B:
        # inputs come from different filings' views -> no derived fact.
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "Revenues": {"units": {"USD": [_pt(1000, "2023-12-31", "0001-24-00000A", 2023)]}},
                    "GrossProfit": {"units": {"USD": [_pt(600, "2023-12-31", "0001-24-00000B", 2023)]}},
                }
            }
        }

        facts = extract_financial_facts(company_id=42, companyfacts=companyfacts)
        assert all(f.derivation is None for f in facts)

    def test_revenue_priority_prefers_contract_revenue(self):
        accn = "0001-24-000009"
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "Revenues": {"units": {"USD": [_pt(999, "2023-12-31", accn, 2023)]}},
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {"USD": [_pt(1000, "2023-12-31", accn, 2023)]}},
                    "NetIncomeLoss": {"units": {"USD": [_pt(200, "2023-12-31", accn, 2023)]}},
                }
            }
        }

        facts = extract_financial_facts(company_id=42, companyfacts=companyfacts)
        net_margin = next(f for f in facts if f.concept == "NetMargin")
        assert net_margin.value == pytest.approx(0.2)
        deriv = json.loads(net_margin.derivation)
        assert deriv["inputs"][1]["xbrl_concept"] == (
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
        )


class TestFinancialFactPersistence:

    def test_restatements_coexist_with_lineage(self):
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "NetIncomeLoss": {
                        "label": "Net Income",
                        "units": {
                            "USD": [
                                _pt(200, "2022-12-31", "0001-23-000001", 2022, filed="2023-02-10"),
                                # Restated in the following year's 10-K
                                _pt(150, "2022-12-31", "0001-24-000001", 2022, filed="2024-02-10"),
                            ]
                        }
                    },
                }
            }
        }

        repo = Repository()
        c = repo.upsert_company(ticker="TESTCO", cik="0001")

        facts = extract_financial_facts(company_id=c.id, companyfacts=companyfacts)
        saved = repo.save_financial_facts(facts)

        # Both views survive as separate rows, keyed by accession
        assert len(saved) == 2
        assert {f.accession_number for f in saved} == {"0001-23-000001", "0001-24-000001"}
        assert {f.as_filed_value for f in saved} == {"200", "150"}

        # The read path resolves to the latest accession's view
        series = repo.get_financial_series(c.id, "NetIncomeLoss")
        assert series == [(date(2022, 12, 31), 150.0)]

    def test_rerun_is_idempotent(self):
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "Revenues": {"units": {"USD": [_pt(1000, "2023-12-31", "0001-24-000009", 2023)]}},
                    "NetIncomeLoss": {"units": {"USD": [_pt(200, "2023-12-31", "0001-24-000009", 2023)]}},
                }
            }
        }

        repo = Repository()
        c = repo.upsert_company(ticker="RERUNCO", cik="0002")

        first = repo.save_financial_facts(extract_financial_facts(c.id, companyfacts))
        second = repo.save_financial_facts(extract_financial_facts(c.id, companyfacts))
        assert len(first) == len(second) == 3  # 2 as-filed + NetMargin
        assert {f.id for f in first} == {f.id for f in second}

    def test_huge_value_round_trips_without_precision_loss(self):
        repo = Repository()
        c = repo.upsert_company(ticker="BIGCO", cik="0003")

        big = 2_464_000_000_000
        fact = FinancialFact(
            company_id=c.id, concept="Assets", xbrl_concept="us-gaap:Assets",
            accession_number="0001-24-000001", fiscal_year=2023, fiscal_period="FY",
            unit="USD", value=big, as_filed_value=str(big),
            period_end=date(2023, 12, 31),
        )
        saved = repo.save_financial_facts([fact])[0]
        assert saved.value == big
        assert int(saved.value) == big
        assert saved.as_filed_value == "2464000000000"

        reloaded = repo.get_financial_facts(c.id, concept="Assets")[0]
        assert int(reloaded.value) == big
