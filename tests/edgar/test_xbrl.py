import pytest
from unittest.mock import patch
from tearsheet.edgar.xbrl import fetch_companyfacts
from tearsheet import config

@patch("tearsheet.edgar.xbrl.get_client")
def test_fetch_companyfacts(mock_get_client):
    mock_client = mock_get_client.return_value
    mock_data = {"cik": 320193, "entityName": "Apple Inc.", "facts": {}}
    mock_client.get_json.return_value = mock_data
    
    data = fetch_companyfacts("320193")
    
    assert data == mock_data
    expected_url = f"{config.SEC_DATA_URL}/api/xbrl/companyfacts/CIK0000320193.json"
    mock_client.get_json.assert_called_once_with(expected_url)
