import pytest
from unittest.mock import patch
from tearsheet.edgar.submissions import get_filing_history
from tearsheet import config

@patch("tearsheet.edgar.submissions.get_client")
def test_get_filing_history(mock_get_client):
    mock_client = mock_get_client.return_value
    mock_data = {"cik": "320193", "entityType": "operating", "filings": {"recent": {}}}
    mock_client.get_json.return_value = mock_data
    
    data = get_filing_history("320193")
    
    assert data == mock_data
    expected_url = f"{config.SEC_DATA_URL}/submissions/CIK0000320193.json"
    mock_client.get_json.assert_called_once_with(expected_url)
