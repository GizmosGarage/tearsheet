import pytest
import json
from unittest.mock import patch
from tearsheet.edgar.tickers import load_ticker_map, resolve_ticker_to_cik

@patch("tearsheet.edgar.tickers.get_client")
def test_load_ticker_map_caching(mock_get_client, tmp_path):
    mock_client = mock_get_client.return_value
    mock_data = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"}
    }
    mock_client.get_json.return_value = mock_data
    
    with patch("tearsheet.edgar.tickers.config.RAW_FILINGS_DIR", tmp_path):
        tickers = load_ticker_map()
        
        # The expected returned dictionary is ticker -> CIK mapping
        assert tickers == {"AAPL": 320193, "MSFT": 789019}
        assert mock_client.get_json.call_count == 1
        
        cache_file = tmp_path / "company_tickers.json"
        assert cache_file.exists()
        
        # Call again, should load from cache
        tickers2 = load_ticker_map()
        assert tickers2 == {"AAPL": 320193, "MSFT": 789019}
        assert mock_client.get_json.call_count == 1

@patch("tearsheet.edgar.tickers.load_ticker_map")
def test_resolve_ticker_to_cik(mock_load):
    mock_load.return_value = {"AAPL": 320193, "MSFT": 789019}
    
    cik = resolve_ticker_to_cik("AAPL")
    assert cik == "0000320193"
    
    cik_msft = resolve_ticker_to_cik("MSFT")
    assert cik_msft == "0000789019"
    
    with pytest.raises(ValueError):
        resolve_ticker_to_cik("INVALID")
