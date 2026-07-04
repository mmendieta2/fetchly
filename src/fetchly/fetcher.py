"""HTTP fetching layer: one shared session, per-request timing and errors."""

import time

import requests

from .config import CrawlConfig
from .models import PageResult

_HTML_TYPES = ("text/html", "application/xhtml+xml")
_MAX_BODY_BYTES = 5 * 1024 * 1024
_RETRY_STATUSES = (429, 502, 503, 504)


class Fetcher:
    def __init__(self, config: CrawlConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.user_agent,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        })

    def fetch(self, url: str, depth: int) -> "tuple[PageResult, str]":
        """Fetch with retries on transient failures; return (result, html_body).

        Retries connection errors/timeouts and 429/502/503/504 up to
        config.max_retries extra attempts with doubling backoff. Returns the
        last attempt's result; body is '' for non-HTML or errors.
        """
        backoff = self.config.retry_backoff_seconds
        for attempt in range(self.config.max_retries + 1):
            result, body = self._fetch_once(url, depth)
            transient = bool(result.error) or result.status_code in _RETRY_STATUSES
            if not transient or attempt == self.config.max_retries:
                return result, body
            time.sleep(backoff)
            backoff *= 2
        return result, body

    def _fetch_once(self, url: str, depth: int) -> "tuple[PageResult, str]":
        result = PageResult(url=url, depth=depth)
        started = time.monotonic()
        try:
            response = self.session.get(
                url,
                timeout=self.config.timeout_seconds,
                allow_redirects=self.config.follow_redirects,
                stream=True,
            )
            result.status_code = response.status_code
            result.ok = response.ok
            result.content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
            if response.url != url:
                result.redirected_to = response.url

            body = ""
            if result.content_type in _HTML_TYPES or not result.content_type:
                raw = response.raw.read(_MAX_BODY_BYTES, decode_content=True)
                result.content_length = len(raw)
                encoding = response.encoding or "utf-8"
                body = raw.decode(encoding, errors="replace")
            else:
                result.content_length = int(response.headers.get("Content-Length") or 0)
            response.close()
            return result, body
        except requests.RequestException as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            return result, ""
        finally:
            result.elapsed_ms = round((time.monotonic() - started) * 1000, 1)

    def close(self) -> None:
        self.session.close()
