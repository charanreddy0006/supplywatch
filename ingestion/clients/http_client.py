import logging
import random
import time
from email.utils import parsedate_to_datetime
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class HttpRequestError(RuntimeError):
    """A request failed after the configured retry policy."""


class HttpClient:
    def __init__(self, connect_timeout: float = 5, read_timeout: float = 45,
                 max_retries: int = 3, headers: dict[str, str] | None = None,
                 session: requests.Session | None = None) -> None:
        self.timeout = (connect_timeout, read_timeout)
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.session.headers.update(headers or {"User-Agent": "SupplyWatch/0.1 (public data ingestion)"})
        retry = Retry(total=0, connect=0, read=0, redirect=0, status=0)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.logger = logging.getLogger(__name__)

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                self.logger.info("HTTP GET %s status=%s attempt=%s", response.url, response.status_code, attempt + 1)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self.max_retries:
                        delay = self._retry_after(response.headers.get("Retry-After"))
                        time.sleep(delay if delay is not None else min(0.5 * 2 ** attempt + random.random() * .1, 8))
                        continue
                response.raise_for_status()
                try:
                    return response.json()
                except ValueError as exc:
                    raise HttpRequestError(f"Invalid JSON from {response.url}: {exc}") from exc
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(min(0.5 * 2 ** attempt + random.random() * .1, 8))
                    continue
                raise HttpRequestError(f"Request to {url} failed after {attempt + 1} attempts: {exc}") from exc
            except requests.HTTPError as exc:
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = exc
                    if attempt < self.max_retries:
                        continue
                raise HttpRequestError(f"HTTP {response.status_code} from {response.url}: {exc}") from exc
        raise HttpRequestError(f"Request to {url} exhausted retries: {last_error}")

    @staticmethod
    def _retry_after(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return max(0.0, min(float(value), 60.0))
        except ValueError:
            try:
                seconds = (parsedate_to_datetime(value) - __import__("datetime").datetime.now(__import__("datetime").timezone.utc)).total_seconds()
                return max(0.0, min(seconds, 60.0))
            except (TypeError, ValueError, OverflowError):
                return None
