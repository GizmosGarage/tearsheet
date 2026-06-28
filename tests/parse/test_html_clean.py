import pytest
from tearsheet.parse.html_clean import html_to_plain_text

def test_html_to_plain_text():
    raw_html = """
    <html>
    <head><style>body { color: red; }</style></head>
    <body>
        <div style="font-weight: bold;">
            <p>This is a <b>test</b>.</p>
            <p>Another paragraph.</p>
        </div>
        <script>alert("test");</script>
    </body>
    </html>
    """
    
    clean_text = html_to_plain_text(raw_html)
    
    assert "This is a test." in clean_text
    assert "Another paragraph." in clean_text
    assert "body { color: red; }" not in clean_text
    assert 'alert("test");' not in clean_text

def test_html_to_plain_text_span_fragments():
    raw_html = """
    <html>
    <body>
        <div>
            <span>I</span><span>T</span><span>E</span><span>M</span> 1A.
        </div>
        <div>
            <span style="font-weight:bold">Risk</span> <span style="font-style:italic">Factors</span>
        </div>
    </body>
    </html>
    """
    clean_text = html_to_plain_text(raw_html)
    
    assert "ITEM 1A." in clean_text
    assert "Risk Factors" in clean_text
