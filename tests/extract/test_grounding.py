import pytest
from tearsheet.extract.schemas import RiskFactor
from tearsheet.extract.grounding import verify_quote_span, verify_quotes

def test_verify_quote_span_genuine():
    text = "This is a genuine quote from the document."
    quote = RiskFactor(exact_quote="genuine quote from")
    span = verify_quote_span(text, quote, document_id=1)

    assert span is not None
    assert span.quote == "genuine quote from"
    assert span.start_offset == 10
    assert span.end_offset == 28
    assert span.document_id == 1
    assert span.label is None

def test_verify_quote_span_hallucinated():
    text = "This is a genuine quote from the document."
    quote = RiskFactor(exact_quote="fake quote from")
    span = verify_quote_span(text, quote, document_id=1)

    assert span is None

def test_verify_quote_span_flexible():
    text = "This is\n a   geNUiNE \n quote FROM the document."
    quote = RiskFactor(exact_quote="a genuine quote from")
    span = verify_quote_span(text, quote, document_id=1)

    assert span is not None
    assert span.start_offset == 9
    assert span.end_offset == 33
    assert span.quote == "a   geNUiNE \n quote FROM"

def test_verify_label_resolves_to_source_slice():
    text = "Supply Chain Risk. We depend on a limited number of suppliers."
    quote = RiskFactor(
        exact_quote="We depend on a limited number of suppliers.",
        label_quote="supply chain risk.",  # case drift: stored label must be the SOURCE slice
    )
    span = verify_quote_span(text, quote, document_id=1)

    assert span is not None
    assert span.label == "Supply Chain Risk."
    assert text[span.label_start_offset:span.label_end_offset] == span.label
    assert text[span.start_offset:span.end_offset] == span.quote

def test_bad_label_dropped_span_kept():
    text = "We depend on a limited number of suppliers."
    quote = RiskFactor(
        exact_quote="limited number of suppliers.",
        label_quote="Concentration Risk",  # not in source
    )
    span = verify_quote_span(text, quote, document_id=1)

    assert span is not None
    assert span.quote == "limited number of suppliers."
    assert span.label is None
    assert span.label_start_offset is None
    assert span.label_end_offset is None

def test_bad_quote_rejected_even_with_good_label():
    text = "Supply Chain Risk. We depend on suppliers."
    quote = RiskFactor(
        exact_quote="We rely on wholly imaginary text.",
        label_quote="Supply Chain Risk.",
    )
    span = verify_quote_span(text, quote, document_id=1)

    assert span is None

def test_verify_quotes_partition():
    text = "This document discusses major financial risks and some operational risks."
    rf1 = RiskFactor(exact_quote="major financial risks")
    rf2 = RiskFactor(exact_quote="minor market risks") # Hallucination
    rf3 = RiskFactor(exact_quote="operational risks.")

    result = verify_quotes(text, [rf1, rf2, rf3], document_id=42)

    assert len(result.accepted) == 2
    assert result.accepted[0].quote == "major financial risks"
    assert result.accepted[1].quote == "operational risks."

    assert len(result.rejected) == 1
    assert result.rejected[0].exact_quote == "minor market risks"
