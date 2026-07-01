import pytest
from pydantic import ValidationError
from tearsheet.extract.schemas import (
    BusinessProfile,
    GroundedItem,
    LocatedQuote,
    MDAnalysis,
    RiskFactor,
    RiskList,
)


def test_locator_shapes_have_no_authored_fields():
    # Invariant 1: the LLM output shape carries only locator fields.
    for model in (LocatedQuote, RiskFactor, GroundedItem):
        assert set(model.model_fields) == {"exact_quote", "label_quote"}
        assert "summary" not in model.model_fields


def test_risk_factor_requires_exact_quote():
    rf = RiskFactor(exact_quote="We might fail because of things.")
    assert rf.exact_quote == "We might fail because of things."
    assert rf.label_quote is None

    with pytest.raises(ValidationError):
        RiskFactor(exact_quote="No")


def test_label_quote_optional():
    rf = RiskFactor(
        exact_quote="We might fail because of things.",
        label_quote="Risks Related to Failure",
    )
    assert rf.label_quote == "Risks Related to Failure"


def test_risk_list_schema_contains_factors():
    assert "risks" in RiskList.model_fields

    rf = RiskFactor(exact_quote="This is a long enough quote.")
    rl = RiskList(risks=[rf])
    assert len(rl.risks) == 1
    assert rl.risks[0].exact_quote == "This is a long enough quote."


def test_grouped_models_are_locator_lists():
    bp = BusinessProfile()
    assert bp.revenue_streams == [] and bp.competitors == [] and bp.moats == []

    md = MDAnalysis()
    assert md.liquidity == [] and md.kpis == [] and md.forward_sentiment == []
