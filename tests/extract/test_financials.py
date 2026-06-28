"""Tests for XBRL financial fact extraction."""

from __future__ import annotations

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


class TestExtractFinancials:
    """Integration tests for extract_financial_facts."""

    def test_extract_financials_filtering_and_parsing(self):
        # Fixture companyfacts dict
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "label": "Revenues Label",
                        "units": {
                            "USD": [
                                # 10-Q (should be filtered out)
                                {"form": "10-Q", "val": 100, "end": "2023-03-31", "filed": "2023-04-10"},
                                # 10-K, missing end
                                {"form": "10-K", "val": 500, "filed": "2024-02-10"}
                            ],
                            "shares": [
                                # Another unit
                                {"fp": "FY", "val": 1000, "end": "2023-12-31", "filed": "2024-02-10"}
                            ]
                        }
                    },
                    "NetIncomeLoss": {
                        "label": "Net Income",
                        "units": {
                            "USD": [
                                # Original filing
                                {"form": "10-K", "val": 200, "end": "2022-12-31", "filed": "2023-02-10"},
                                # Restatement (same concept, same end date, newer filed date)
                                {"form": "10-K", "val": 150, "end": "2022-12-31", "filed": "2023-11-15"}
                            ]
                        }
                    },
                    "IgnoredConcept": {
                        # Not in whitelist
                        "label": "Ignored",
                        "units": {
                            "USD": [
                                {"form": "10-K", "val": 999, "end": "2022-12-31", "filed": "2023-02-10"}
                            ]
                        }
                    }
                }
            }
        }
        
        facts = extract_financial_facts(company_id=42, companyfacts=companyfacts)
        
        # IgnoredConcept should be skipped, 10-Q should be filtered out
        assert len(facts) == 4
        
        # Revenues (USD)
        rev_usd = [f for f in facts if f.concept == "Revenues" and f.unit == "USD"][0]
        assert rev_usd.value == 500
        assert rev_usd.period_end is None
        assert rev_usd.label == "Revenues Label"
        
        # Revenues (shares)
        rev_shares = [f for f in facts if f.concept == "Revenues" and f.unit == "shares"][0]
        assert rev_shares.value == 1000
        assert rev_shares.period_end == date(2023, 12, 31)
        
        # NetIncomeLoss (USD)
        nil = [f for f in facts if f.concept == "NetIncomeLoss"]
        assert len(nil) == 2
        # Ensure ordered by filed date
        assert nil[0].value == 200
        assert nil[1].value == 150

    def test_extract_financials_round_trip_dedupe(self):
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "NetIncomeLoss": {
                        "label": "Net Income",
                        "units": {
                            "USD": [
                                {"form": "10-K", "val": 200, "end": "2022-12-31", "filed": "2023-02-10"},
                                {"form": "10-K", "val": 150, "end": "2022-12-31", "filed": "2023-11-15"}
                            ]
                        }
                    },
                    "Revenues": {
                        "units": {
                            "USD": [
                                {"form": "10-K", "val": 500, "filed": "2024-02-10"} # missing end
                            ]
                        }
                    }
                }
            }
        }
        
        repo = Repository()
        c = repo.upsert_company(ticker="TESTCO", cik="0001")
        
        facts = extract_financial_facts(company_id=c.id, companyfacts=companyfacts)
        saved = repo.save_financial_facts(facts)
        
        # NetIncomeLoss had 2 facts with same end date, should dedupe to 1
        # Revenues had 1 fact with missing end date, should default to 1970-01-01
        assert len(saved) == 2
        
        nil = [f for f in saved if f.concept == "NetIncomeLoss"][0]
        assert nil.value == 150  # Newer filed value wins
        
        rev = [f for f in saved if f.concept == "Revenues"][0]
        assert rev.value == 500
        assert rev.period_end == date(1970, 1, 1)
