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

    # Mock LLM Client (one genuine quote, one hallucination the gate must reject)
    from tearsheet.extract.schemas import RiskList, RiskFactor, BusinessProfile, MDAnalysis, GroundedItem
    def mock_complete(system_prompt, user_prompt, response_model):
        if response_model == RiskList:
            return RiskList(risks=[
                RiskFactor(exact_quote="We might run out of chips."),
                RiskFactor(exact_quote="Entirely hallucinated risk text."),
            ])
        elif response_model == BusinessProfile:
            return BusinessProfile(revenue_streams=[GroundedItem(exact_quote="sell phones.")])
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
        assert result["run_id"] is not None
        assert result["status"] == "completed_with_errors"

        # Typed gaps: Item 7 missing (1), hallucinated span rejected (1),
        # 11 of 12 sought concepts absent (only NetIncomeLoss was extracted).
        assert result["gaps_by_status"] == {"not_found": 12, "rejected_by_gate": 1}
        assert result["gaps_count"] == 13
        assert len(result["errors"]) == 13
        assert any("Item 7" in e and "not_found" in e for e in result["errors"])

        # Gap rows are queryable records, not log lines
        gaps = Repository().get_extraction_gaps(result["run_id"])
        assert len(gaps) == 13
        rejected = [g for g in gaps if g.status == "rejected_by_gate"]
        assert len(rejected) == 1
        assert rejected[0].detail == "Entirely hallucinated risk text."
        assert rejected[0].target == "Item 1A span"
        item7 = next(g for g in gaps if g.target == "Item 7")
        assert item7.status == "not_found"

        assert result["financial_facts_count"] == 1
        assert result["extracted_spans_count"] == 2

        # Every saved artifact carries the run's id
        assert all(f.run_id == result["run_id"] for f in result["financial_facts"])
        assert all(s.run_id == result["run_id"] for s in result["extracted_spans"])

        spans = result["extracted_spans"]
        assert len(spans) == 2

        # Check risk factor span
        risk = next(s for s in spans if s.category == "risk_factor")
        assert risk.company.ticker == "AAPL"
        assert len(risk.citations) == 1
        assert risk.citations[0].quote == "We might run out of chips."
        assert risk.citations[0].document.section == "1A"

        # Custody chain: parsed sections trace to the archived primary document
        risk_doc = risk.citations[0].document
        assert risk_doc.source_document_id is not None
        assert risk_doc.text_sha256 is not None
        assert risk_doc.extraction_method == "sectioner"
        assert risk_doc.run_id == result["run_id"]

        # Check business profile span
        biz = next(s for s in spans if s.category == "revenue_stream")
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
            return RiskList(risks=[RiskFactor(exact_quote="We might run out of chips.")])
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
        
        # Financials failed, Item 1 missing, Item 7 missing -> 3 typed gaps
        assert result["status"] == "completed_with_errors"
        assert result["gaps_by_status"] == {"failed": 1, "not_found": 2}
        assert len(result["errors"]) == 3
        
        assert result["financial_facts_count"] == 0
        assert result["extracted_spans_count"] == 1
        assert len(result["extracted_spans"]) == 1

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
    
    from tearsheet.store.models import ExtractedSpan, Citation
    from tearsheet.extract.qualitative import SectionExtraction
    valid_span = ExtractedSpan(company_id=1, category="risk_factor", label="Valid")
    valid_span.citations = [Citation(document_id=1, quote="valid", start_offset=0, end_offset=5)]

    uncited_span = ExtractedSpan(company_id=1, category="risk_factor", label="Uncited")
    uncited_span.citations = []

    mock_risk.return_value = SectionExtraction(spans=[valid_span, uncited_span])
    mock_business.return_value = SectionExtraction()
    mock_mda.return_value = SectionExtraction()

    with patch("tearsheet.config.RAW_FILINGS_DIR", tmp_path / "raw"), \
         patch("tearsheet.config.SEC_TICKER_MAP_URL", "http://mock"):

        pipeline = ExecutionPipeline()
        result = pipeline.run_for_ticker("AAPL")

        spans = result["extracted_spans"]
        assert len(spans) == 1
        assert spans[0].label == "Valid"
        assert result["extracted_spans_count"] == 1
