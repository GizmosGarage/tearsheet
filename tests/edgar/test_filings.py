import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from tearsheet.edgar.filings import locate_filing, download_filing_documents

@patch("tearsheet.edgar.filings.get_filing_history")
def test_locate_filing(mock_get_history):
    mock_get_history.return_value = {
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-23-000106", "0000320193-23-000077"],
                "form": ["10-K", "10-Q"],
                "primaryDocument": ["aapl-20230930.htm", "aapl-20230701.htm"]
            }
        }
    }
    
    metadata = locate_filing("320193", "10-K")
    assert metadata["accessionNumber"] == "0000320193-23-000106"
    assert metadata["primaryDocument"] == "aapl-20230930.htm"
    assert metadata["form"] == "10-K"

@patch("tearsheet.edgar.filings.get_client")
def test_download_filing_documents(mock_get_client, tmp_path):
    mock_client = mock_get_client.return_value
    mock_response = MagicMock()
    mock_response.content = b"<html>10-K content</html>"
    mock_client.get.return_value = mock_response
    
    # We will assume download_filing_documents expects a primaryDocument as kwarg or fetches it.
    # Let's simplify by passing the primary document directly in kwargs, or it will fetch index.json.
    # We'll just patch the internal locate_filing to return our mock metadata if it calls it.
    with patch("tearsheet.edgar.filings.locate_filing") as mock_locate:
        mock_locate.return_value = {
            "accessionNumber": "0000320193-23-000106",
            "primaryDocument": "aapl-20230930.htm"
        }
        
        path = download_filing_documents("320193", "0000320193-23-000106", cache_dir=tmp_path)
        
        assert path.exists()
        assert path.read_text() == "<html>10-K content</html>"
        assert path.name == "aapl-20230930.htm"
