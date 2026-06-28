import pytest
import time
import threading
from unittest.mock import patch, MagicMock
from tearsheet.edgar.client import EdgarClient
import httpx

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
        
        assert duration >= 0.2

def test_edgar_client_concurrency():
    """Verify that multiple threads respect the rate limiter."""
    client = EdgarClient(user_agent="test@example.com")
    
    with patch("httpx.Client.request") as mock_request:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_request.return_value = mock_resp
        
        def worker():
            client.get("https://www.sec.gov/files/company_tickers.json")
            
        threads = [threading.Thread(target=worker) for _ in range(4)]
        start = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
            
        duration = time.time() - start
        assert duration >= 0.3

def test_edgar_client_retries_on_429():
    user_agent = "TestUserAgent test@example.com"
    client = EdgarClient(user_agent=user_agent)
    
    with patch("httpx.Client.request") as mock_request:
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {}
        
        resp_200 = MagicMock()
        resp_200.status_code = 200
        
        mock_request.side_effect = [resp_429, resp_200]
        
        with patch("time.sleep"):
            response = client.get("https://www.sec.gov/files/company_tickers.json")
            
        assert response.status_code == 200
        assert mock_request.call_count == 2

def test_edgar_client_retry_after():
    """Verify that Retry-After header is honored."""
    client = EdgarClient(user_agent="test@example.com")
    
    with patch("httpx.Client.request") as mock_request:
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "5"}
        
        resp_200 = MagicMock()
        resp_200.status_code = 200
        
        mock_request.side_effect = [resp_429, resp_200]
        
        with patch("time.sleep") as mock_sleep:
            response = client.get("https://www.sec.gov/files/company_tickers.json")
            
        assert response.status_code == 200
        assert mock_request.call_count == 2
        mock_sleep.assert_any_call(5.0)

def test_edgar_client_final_429_raises_runtime_error():
    """Verify that exhausting retries raises a RuntimeError, not HTTPStatusError."""
    client = EdgarClient(user_agent="test@example.com", max_retries=2)
    
    with patch("httpx.Client.request") as mock_request:
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {}
        resp_429.raise_for_status.side_effect = httpx.HTTPStatusError("429 Error", request=MagicMock(), response=resp_429)
        
        mock_request.return_value = resp_429
        
        with patch("time.sleep"):
            with pytest.raises(RuntimeError, match="Max retries exceeded"):
                client.get("https://www.sec.gov/files/company_tickers.json")
        
        assert mock_request.call_count == 2
