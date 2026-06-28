import pytest
from pydantic import BaseModel
from tearsheet.extract.schemas import RiskFactor, RiskList

def test_risk_factor_schema_has_exact_quote():
    # Verify the schema enforces the exact_quote field
    assert "exact_quote" in RiskFactor.model_fields
    
    # Test instantiation
    rf = RiskFactor(summary="High risk of failure.", exact_quote="We might fail.")
    assert rf.summary == "High risk of failure."
    assert rf.exact_quote == "We might fail."

def test_risk_list_schema_contains_factors():
    # Verify RiskList contains a list of RiskFactors
    assert "risks" in RiskList.model_fields
    
    rf = RiskFactor(summary="A", exact_quote="B")
    rl = RiskList(risks=[rf])
    assert len(rl.risks) == 1
    assert rl.risks[0].exact_quote == "B"
