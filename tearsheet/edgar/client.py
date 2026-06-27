"""Rate-limited HTTP client for SEC EDGAR with correct User-Agent and retries."""

from __future__ import annotations

import time
from typing import Any

import httpx

from tearsheet import config


class EdgarClient:
    """Thin wrapper around httpx with SEC-compliant headers and rate limiting."""

    def __init__(
        self,
        *,
        user_agent: str | None = None,
        rate_limit_per_second: float | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self._user_agent = user_agent or config.SEC_USER_AGENT
        self._min_interval = 1.0 / (rate_limit_per_second or config.SEC_RATE_LIMIT_PER_SECOND)
        self._timeout = timeout or config.SEC_REQUEST_TIMEOUT_SECONDS
        self._max_retries = max_retries if max_retries is not None else config.SEC_MAX_RETRIES
        self._last_request_at: float = 0.0
        self._client = httpx.Client(
            headers={"User-Agent": self._user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=self._timeout,
            follow_redirects=True,
        )

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """GET with rate limiting and retries."""
        for attempt in range(self._max_retries):
            self._throttle()
            self._last_request_at = time.monotonic()
            response = self._client.request("GET", url, **kwargs)
            if response.status_code == 429:
                if attempt < self._max_retries - 1:
                    time.sleep(self._min_interval * (2 ** attempt))
                    continue
            response.raise_for_status()
            return response
        raise RuntimeError(f"Max retries exceeded for url: {url}")

    def get_json(self, url: str, **kwargs: Any) -> Any:
        """GET and parse JSON response."""
        return self.get(url, **kwargs).json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> EdgarClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


_default_client: EdgarClient | None = None


def get_client() -> EdgarClient:
    """Return a module-level shared EdgarClient instance."""
    global _default_client
    if _default_client is None:
        _default_client = EdgarClient()
    return _default_client
