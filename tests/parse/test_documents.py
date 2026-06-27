import pytest
from pathlib import Path
from tearsheet.parse.documents import build_documents
from tearsheet.store.models import Document

def test_build_documents(tmp_path):
    html_file = tmp_path / "filing.html"
    # Create HTML with a format that our html_to_plain_text and split_10k_sections will handle correctly
    html = """<html><body>
    <p>Item 1. Business</p>
    <p>We do business.</p>
    <p>Item 2. Properties</p>
    <p>We own properties.</p>
    </body></html>"""
    html_file.write_text(html, encoding="utf-8")
    
    documents = build_documents(1, html_file)
    
    assert len(documents) == 2
    
    assert isinstance(documents[0], Document)
    assert documents[0].filing_id == 1
    assert documents[0].section == "1"
    assert "Business" in documents[0].title
    assert "We do business." in documents[0].text
    
    assert documents[1].filing_id == 1
    assert documents[1].section == "2"
    assert "Properties" in documents[1].title
    assert "We own properties." in documents[1].text
