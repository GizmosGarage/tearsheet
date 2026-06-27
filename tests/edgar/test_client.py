import pytest
import time
from unittest.mock import patch, MagicMock
from tearsheet.edgar.client import EdgarClient

def test_edgar_client_user_agent():
    user_agent = "TestUserAgent test@example.com"
    client = EdgarClient(user_agent=user_agent)
    assert client._client.headers["User-Agent"] == user_agent

def test_edgar_client_rate_limiting():
    user_agent = "TestUserAgent test@example.com"
    client = EdgarClient(user_agent=user_agent)
    
    with patch("httpx.Client.request") as mock_request:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_request.return_value = mock_resp
        
        start = time.time()
        for _ in range(3):
            client.get("https://www.sec.gov/files/company_tickers.json")
        duration = time.time() - start
        
        # 3 requests should take at least 0.2 seconds since the rate limit is 10/sec (0.1s gap)
        assert duration >= 0.2

def test_edgar_client_retries_on_429():
    user_agent = "TestUserAgent test@example.com"
    client = EdgarClient(user_agent=user_agent)
    
    with patch("httpx.Client.request") as mock_request:
        resp_429 = MagicMock()
        resp_429.status_code = 429
        
        resp_200 = MagicMock()
        resp_200.status_code = 200
        
        mock_request.side_effect = [resp_429, resp_200]
        
        # Mock time.sleep to avoid actually waiting during test
        with patch("time.sleep"):
            response = client.get("https://www.sec.gov/files/company_tickers.json")
            
        assert response.status_code == 200
        assert mock_request.call_count == 2
