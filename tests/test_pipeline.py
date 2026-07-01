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
@patch("tearsheet.pipeline.fetch_companyfacts")
@patch("tearsheet.pipeline.extract_financial_facts")
def test_pipeline_run_for_ticker(mock_extract_fin, mock_fetch_fin, mock_llm_cls, mock_filings_client, mock_submissions_client, mock_tickers_client, tmp_path):
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
    mock_fc.get_json.return_value = {
        "directory": {"item": [{"name": "aapl-20230930.htm", "type": "text.htm"}]}
    }
    mock_filings_client.return_value = mock_fc

    # Mock LLM Client
    from tearsheet.extract.schemas import RiskList, RiskFactor, BusinessProfile, MDAnalysis, GroundedItem
    def mock_complete(system_prompt, user_prompt, response_model):
        if response_model == RiskList:
            return RiskList(risks=[RiskFactor(summary="Supply chain risk", exact_quote="We might run out of chips.")])
        elif response_model == BusinessProfile:
            return BusinessProfile(revenue_streams=[GroundedItem(summary="Phones", exact_quote="sell phones.")])
        elif response_model == MDAnalysis:
            return MDAnalysis()
            
    mock_llm = MagicMock()
    mock_llm.complete_structured.side_effect = mock_complete
    mock_llm_cls.return_value = mock_llm
    
    # Mock Financials
    mock_fetch_fin.return_value = {"facts": {}}
    from tearsheet.store.models import FinancialFact
    mock_fact = FinancialFact(company_id=1, concept="NetIncomeLoss", value=100)
    mock_extract_fin.return_value = [mock_fact]
    
    # Patch config directories so we don't pollute global state
    with patch("tearsheet.config.RAW_FILINGS_DIR", tmp_path / "raw"), \
         patch("tearsheet.config.SEC_TICKER_MAP_URL", "http://mock"), \
         patch("tearsheet.extract.qualitative._load_prompt", return_value="Test prompt"):
        
        # Run pipeline
        pipeline = ExecutionPipeline()
        result = pipeline.run_for_ticker("AAPL")
        
        assert result["ticker"] == "AAPL"
        assert result["cik"] == "0000320193"
        # Item 7 is missing, so it will log an error and return completed_with_errors
        assert result["status"] == "completed_with_errors"
        assert len(result["errors"]) == 1
        assert "Section 7 not found" in result["errors"][0]
        
        assert result["financial_facts_count"] == 1
        assert result["qualitative_facts_count"] == 2
        
        facts = result["qualitative_facts"]
        assert len(facts) == 2
        
        # Check risk factor
        risk = next(f for f in facts if f.category == "risk_factor")
        assert risk.summary == "Supply chain risk"
        assert risk.company.ticker == "AAPL"
        assert len(risk.citations) == 1
        assert risk.citations[0].quote == "We might run out of chips."
        assert risk.citations[0].document.section == "1A"

        # Check business profile
        biz = next(f for f in facts if f.category == "revenue_stream")
        assert biz.summary == "Phones"
        assert len(biz.citations) == 1
        assert biz.citations[0].quote == "sell phones."
        assert biz.citations[0].document.section == "1"

        fin_facts = result["financial_facts"]
        assert len(fin_facts) == 1
        assert fin_facts[0].concept == "NetIncomeLoss"

@patch("tearsheet.edgar.tickers.get_client")
@patch("tearsheet.edgar.submissions.get_client")
@patch("tearsheet.edgar.filings.get_client")
@patch("tearsheet.extract.qualitative.LLMClient")
@patch("tearsheet.pipeline.fetch_companyfacts")
def test_pipeline_financials_failure_does_not_abort_qualitative(mock_fetch_fin, mock_llm_cls, mock_filings_client, mock_submissions_client, mock_tickers_client, tmp_path):
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
    <p>Item 1A. Risk Factors</p><p>We might run out of chips.</p>
    </body></html>"""
    mock_response.content = html_content
    mock_fc.get.return_value = mock_response
    mock_fc.get_json.return_value = {
        "directory": {"item": [{"name": "aapl-20230930.htm", "type": "text.htm"}]}
    }
    mock_filings_client.return_value = mock_fc

    # Mock LLM Client
    from tearsheet.extract.schemas import RiskList, RiskFactor, BusinessProfile, MDAnalysis
    def mock_complete(system_prompt, user_prompt, response_model):
        if response_model == RiskList:
            return RiskList(risks=[RiskFactor(summary="Supply chain risk", exact_quote="We might run out of chips.")])
        elif response_model == BusinessProfile:
            return BusinessProfile()
        elif response_model == MDAnalysis:
            return MDAnalysis()
            
    mock_llm = MagicMock()
    mock_llm.complete_structured.side_effect = mock_complete
    mock_llm_cls.return_value = mock_llm
    
    # Induce failure in financials
    mock_fetch_fin.side_effect = Exception("Network timeout")
    
    with patch("tearsheet.config.RAW_FILINGS_DIR", tmp_path / "raw"), \
         patch("tearsheet.config.SEC_TICKER_MAP_URL", "http://mock"), \
         patch("tearsheet.extract.qualitative._load_prompt", return_value="Test prompt"):
        
        # Run pipeline
        pipeline = ExecutionPipeline()
        result = pipeline.run_for_ticker("AAPL")
        
        # Financials failed, 1 missing, 7 missing -> 3 errors total
        assert result["status"] == "completed_with_errors"
        assert len(result["errors"]) == 3
        
        assert result["financial_facts_count"] == 0
        assert result["qualitative_facts_count"] == 1
        assert len(result["qualitative_facts"]) == 1

@patch("tearsheet.edgar.tickers.get_client")
@patch("tearsheet.edgar.submissions.get_client")
@patch("tearsheet.edgar.filings.get_client")
@patch("tearsheet.pipeline.fetch_companyfacts")
@patch("tearsheet.pipeline.extract_financial_facts")
@patch("tearsheet.pipeline.extract_risk_factors")
@patch("tearsheet.pipeline.extract_business")
@patch("tearsheet.pipeline.extract_management_discussion")
def test_uncited_fact_discarded_before_save(
    mock_mda, mock_business, mock_risk, mock_extract_fin, mock_fetch_fin,
    mock_filings_client, mock_submissions_client, mock_tickers_client, tmp_path
):
    mock_tc = MagicMock()
    mock_tc.get_json.return_value = {"0": {"ticker": "AAPL", "cik_str": 320193}}
    mock_tickers_client.return_value = mock_tc
    
    mock_sc = MagicMock()
    mock_sc.get_json.return_value = {
        "name": "Apple Inc.", "cik": "0000320193",
        "filings": {"recent": {"form": ["10-K"], "accessionNumber": ["0000320193-23-000106"], "primaryDocument": ["aapl-20230930.htm"]}}
    }
    mock_submissions_client.return_value = mock_sc
    
    mock_fc = MagicMock()
    mock_response = MagicMock()
    mock_response.content = b"<html><body><p>Item 1A. Risk Factors</p></body></html>"
    mock_fc.get.return_value = mock_response
    mock_fc.get_json.return_value = {
        "directory": {"item": [{"name": "aapl-20230930.htm", "type": "text.htm"}]}
    }
    mock_filings_client.return_value = mock_fc
    
    mock_fetch_fin.return_value = {"facts": {}}
    mock_extract_fin.return_value = []
    
    from tearsheet.store.models import QualitativeFact, Citation
    valid_fact = QualitativeFact(company_id=1, category="risk_factor", summary="Valid")
    valid_fact.citations = [Citation(document_id=1, quote="valid", start_offset=0, end_offset=5)]
    
    uncited_fact = QualitativeFact(company_id=1, category="risk_factor", summary="Uncited")
    uncited_fact.citations = []
    
    mock_risk.return_value = [valid_fact, uncited_fact]
    mock_business.return_value = []
    mock_mda.return_value = []
    
    with patch("tearsheet.config.RAW_FILINGS_DIR", tmp_path / "raw"), \
         patch("tearsheet.config.SEC_TICKER_MAP_URL", "http://mock"):
        
        pipeline = ExecutionPipeline()
        result = pipeline.run_for_ticker("AAPL")
        
        facts = result["qualitative_facts"]
        assert len(facts) == 1
        assert facts[0].summary == "Valid"
        assert result["qualitative_facts_count"] == 1
