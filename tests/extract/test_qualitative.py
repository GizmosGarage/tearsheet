import pytest
from unittest.mock import MagicMock, patch
from tearsheet.store.models import Document, QualitativeFact, Citation, Filing
from tearsheet.extract.schemas import RiskList, RiskFactor
from tearsheet.extract.qualitative import extract_risk_factors

def test_extract_risk_factors():
    # Setup mock document
    filing = Filing(company_id=10)
    doc = Document(id=42, filing=filing, text="We face significant liquidity risks.", section="1A")
    
    # Setup mock LLM Client
    mock_llm = MagicMock()
    
    # Return a RiskList with one valid and one hallucinated quote
    mock_llm.complete_structured.return_value = RiskList(risks=[
        RiskFactor(summary="Liquidity", exact_quote="liquidity risks."),
        RiskFactor(summary="Market", exact_quote="market volatility risks.") # Hallucination
    ])
    
    # Call orchestrator
    with patch("tearsheet.extract.qualitative._load_prompt", return_value="Test prompt"):
        facts = extract_risk_factors(doc, llm=mock_llm)
    
    # Verify only the grounded fact is returned
    assert len(facts) == 1
    fact = facts[0]
    assert fact.category == "risk_factor"
    assert fact.summary == "Liquidity"
    assert fact.company_id == 10
    
    assert len(fact.citations) == 1
    citation = fact.citations[0]
    assert citation.quote == "liquidity risks."
    assert citation.document_id == 42
    assert citation.start_offset == 20
    assert citation.end_offset == 36
