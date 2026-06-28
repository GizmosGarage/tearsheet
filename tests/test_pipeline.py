import pytest
from unittest.mock import patch, MagicMock
from tearsheet.pipeline import ExecutionPipeline
from tearsheet.store.repository import Repository
from tearsheet.extract.schemas import RiskList, RiskFactor
from tearsheet.store.models import Base
from tearsheet.store.db import get_engine, _engine, _SessionLocal
from tearsheet import config
import tearsheet.store.db
from pathlib import Path

@pytest.fixture(autouse=True)
def init_test_db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    # Reset engine singleton
    tearsheet.store.db._engine = None
    tearsheet.store.db._SessionLocal = None
    Base.metadata.create_all(bind=get_engine())
    yield
    Base.metadata.drop_all(bind=get_engine())
    tearsheet.store.db._engine = None
    tearsheet.store.db._SessionLocal = None

@patch("tearsheet.edgar.tickers.get_client")
@patch("tearsheet.edgar.submissions.get_client")
@patch("tearsheet.edgar.filings.get_client")
@patch("tearsheet.extract.qualitative.LLMClient")
def test_pipeline_run_for_ticker(mock_llm_cls, mock_filings_client, mock_submissions_client, mock_tickers_client, tmp_path):
    # Mock tickers client
    mock_tc = MagicMock()
    mock_tc.get_json.return_value = {"0": {"ticker": "AAPL", "cik_str": 320193}}
    mock_tickers_client.return_value = mock_tc
    
    # Mock submissions client
    mock_sc = MagicMock()
    mock_sc.get_json.return_value = {
        "name": "Apple Inc.",
        "cik": "0000320193",
        "filings": {
            "recent": {
                "form": ["10-K"],
                "accessionNumber": ["0000320193-23-000106"],
                "primaryDocument": ["aapl-20230930.htm"]
            }
        }
    }
    mock_submissions_client.return_value = mock_sc
    
    # Mock filings client
    mock_fc = MagicMock()
    mock_response = MagicMock()
    html_content = b"""<html><body>
    <p>Item 1. Business</p><p>We sell phones.</p>
    <p>Item 1A. Risk Factors</p><p>We might run out of chips.</p>
    <p>Item 1B. Unresolved Staff Comments</p><p>None.</p>
    <p>Item 2. Properties</p><p>We have a big ring.</p>
    </body></html>"""
    mock_response.content = html_content
    mock_fc.get.return_value = mock_response
    mock_filings_client.return_value = mock_fc
    
    # Mock LLM Client
    mock_llm = MagicMock()
    mock_llm.complete_structured.return_value = RiskList(risks=[
        RiskFactor(summary="Supply chain risk", exact_quote="We might run out of chips.")
    ])
    mock_llm_cls.return_value = mock_llm
    
    # Patch config directories so we don't pollute global state
    with patch("tearsheet.config.RAW_FILINGS_DIR", tmp_path / "raw"), \
         patch("tearsheet.config.SEC_TICKER_MAP_URL", "http://mock"):
        
        # Run pipeline
        pipeline = ExecutionPipeline()
        facts = pipeline.run_for_ticker("AAPL")
        
        assert len(facts) == 1
        assert facts[0].summary == "Supply chain risk"
        assert facts[0].company.ticker == "AAPL"
        assert len(facts[0].citations) == 1
        assert facts[0].citations[0].quote == "We might run out of chips."
        assert facts[0].citations[0].document.section == "1A"
