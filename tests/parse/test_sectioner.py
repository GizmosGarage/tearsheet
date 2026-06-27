import pytest
from tearsheet.parse.sectioner import split_10k_sections, Section

def test_split_10k_sections():
    text = """
Item 1. Business
We are a company that does things.
Item 1A. Risk Factors
There are many risks.
Item 2. Properties
We own buildings.
    """
    
    sections = split_10k_sections(text)
    
    # Depending on implementation it might capture Item 1, 1A, and 2
    assert len(sections) == 3
    
    assert sections[0].item == "1"
    assert "Business" in sections[0].title
    assert "We are a company" in sections[0].text
    
    assert sections[1].item == "1A"
    assert "Risk Factors" in sections[1].title
    assert "many risks" in sections[1].text
    
    assert sections[2].item == "2"
    assert "Properties" in sections[2].title
    assert "buildings" in sections[2].text
