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

@pytest.mark.parametrize("retry_after, expected_sleep", [
    ("5", 5.0),
    (" 5.5 ", 5.5),
    ("999999999", 60.0), # Capped
    ("Wed, 21 Oct 2015 07:28:00 GMT", 0.0), # Past date, defaults or 0
])
def test_edgar_client_retry_after(retry_after, expected_sleep):
    """Verify that Retry-After header is honored with various formats."""
    client = EdgarClient(user_agent="test@example.com")
    
    with patch("httpx.Client.request") as mock_request:
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": retry_after}
        
        resp_200 = MagicMock()
        resp_200.status_code = 200
        
        mock_request.side_effect = [resp_429, resp_200]
        
        with patch("time.sleep") as mock_sleep:
            # We mock email.utils.parsedate_to_datetime to return a future date for the date test
            if "GMT" in retry_after:
                import email.utils
                from datetime import datetime, timezone, timedelta
                future_date = datetime.now(timezone.utc) + timedelta(seconds=10.5)
                with patch("email.utils.parsedate_to_datetime", return_value=future_date):
                    response = client.get("https://www.sec.gov/files/company_tickers.json")
                    mock_sleep.assert_any_call(10.5)
            else:
                response = client.get("https://www.sec.gov/files/company_tickers.json")
                mock_sleep.assert_any_call(expected_sleep)
            
        assert response.status_code == 200
        assert mock_request.call_count == 2

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

def test_singleton_thread_safety():
    from tearsheet.edgar.client import get_client, _default_client
    import tearsheet.edgar.client as client_module
    
    # reset singleton
    client_module._default_client = None
    
    clients = []
    
    def worker():
        clients.append(get_client())
        
    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
        
    assert len(clients) == 10
    assert all(c is clients[0] for c in clients)

