import pytest
from tearsheet.extract.schemas import RiskFactor
from tearsheet.extract.grounding import verify_quote_span, verify_quotes

def test_verify_quote_span_genuine():
    text = "This is a genuine quote from the document."
    quote = RiskFactor(summary="A", exact_quote="genuine quote from")
    span = verify_quote_span(text, quote, document_id=1)
    
    assert span is not None
    assert span.quote == "genuine quote from"
    assert span.start_offset == 10
    assert span.end_offset == 28
    assert span.document_id == 1

def test_verify_quote_span_hallucinated():
    text = "This is a genuine quote from the document."
    quote = RiskFactor(summary="A", exact_quote="fake quote")
    span = verify_quote_span(text, quote, document_id=1)
    
    assert span is None

def test_verify_quotes_partition():
    text = "This document discusses major financial risks and some operational risks."
    rf1 = RiskFactor(summary="Financial", exact_quote="major financial risks")
    rf2 = RiskFactor(summary="Market", exact_quote="minor market risks") # Hallucination
    rf3 = RiskFactor(summary="Operational", exact_quote="operational risks.")
    
    result = verify_quotes(text, [rf1, rf2, rf3], document_id=42)
    
    assert len(result.accepted) == 2
    assert result.accepted[0].quote == "major financial risks"
    assert result.accepted[1].quote == "operational risks."
    
    assert len(result.rejected) == 1
    assert result.rejected[0].exact_quote == "minor market risks"
