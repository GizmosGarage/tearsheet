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
We do business and it is very good.
Part I Item 1A: Risk Factors
We have many many many many risks.
Item 1B Unresolved Staff Comments
None.
ITEM 2. PROPERTIES
Buildings are very very very very big.
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

def test_split_10k_sections_regex_tightness():
    text = """
Item 1A.
This is the first risk sentence.
ITEM 1 RISKS are bad.
Item 1B. Unresolved Staff Comments
None.
    """
    sections = split_10k_sections(text)
    assert len(sections) == 2
    assert sections[0].item == "1A"
    assert "This is the first risk sentence." in sections[0].text
    assert "ITEM 1 RISKS are bad." in sections[0].text
    assert sections[1].item == "1B"

def test_split_10k_sections_toc_heuristics():
    text = """
Table of Contents
Item 1. Business
Item 1A. Risk Factors
Item 1B. Unresolved Staff Comments

Item 1. Business
The real business text which is long enough to not be TOC.
Item 1A. Risk Factors
The real risks which are long enough to not be TOC.
    """
    sections = split_10k_sections(text)
    assert len(sections) == 2
    assert sections[0].item == "1"
    assert "real business text" in sections[0].text

def test_split_10k_sections_verbose_toc():
    """Verify average span heuristic correctly isolates the body sequence against a verbose TOC."""
    text = """
Table of Contents
Item 1. Business
This is a verbose description of the business section that takes up some space in the TOC.
Item 1A. Risk Factors
This is a verbose description of the risk factors section in the TOC.
Item 1B. Unresolved Staff Comments
This is a verbose description of the unresolved staff comments in the TOC.

Item 1. Business
Real business.
Item 1A. Risk Factors
Real risks.
Item 1B. Unresolved Staff Comments
Real comments.
"""
    # Append huge padding to the end of the last body section to increase its average span
    text += "Padding " * 50
    sections = split_10k_sections(text)
    
    assert len(sections) == 3
    assert sections[0].item == "1"
    assert "Real business" in sections[0].text
