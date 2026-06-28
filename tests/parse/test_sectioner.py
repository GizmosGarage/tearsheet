import pytest
from tearsheet.parse.sectioner import split_10k_sections, Section

def test_split_10k_sections_basic():
    text = """
Item 1. Business
We are a company that does things.
Item 1A. Risk Factors
There are many risks.
Item 2. Properties
We own buildings.
    """
    
    sections = split_10k_sections(text)
    assert len(sections) == 3
    assert sections[0].item == "1"
    assert sections[1].item == "1A"
    assert sections[2].item == "2"

def test_split_10k_sections_adversarial_headings():
    """Verify regex handles stylizations (missing dots, colons, PART prefixes, etc)."""
    text = """
PART I
ITEM 1 BUSINESS
We do business.
Part I Item 1A: Risk Factors
We have risks.
Item 1B Unresolved Staff Comments
None.
ITEM 2. PROPERTIES
Buildings.
    """
    sections = split_10k_sections(text)
    assert len(sections) == 4
    assert sections[0].item == "1"
    assert sections[1].item == "1A"
    assert sections[2].item == "1B"
    assert sections[3].item == "2"

def test_split_10k_sections_ignores_toc():
    """Verify TOC matches are ignored."""
    text = """
Table of Contents
Item 1. Business ........................................ 3
Item 1A. Risk Factors 12
Item 1B. Unresolved Staff Comments 14

Item 1. Business
This is the real business section.
Item 1A. Risk Factors
These are the real risks.
    """
    sections = split_10k_sections(text)
    # The TOC entries should be ignored. Only the real ones should be captured.
    assert len(sections) == 2
    assert sections[0].item == "1"
    assert "real business" in sections[0].text
    assert sections[1].item == "1A"
    assert "real risks" in sections[1].text
