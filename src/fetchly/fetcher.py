"""HTTP fetching layer: one shared session, per-request timing and errors."""

import time

import requests

from .config import CrawlConfig
from .models import PageResult

_HTML_TYPES = ("text/html", "application/xhtml+xml")
_MAX_BODY_BYTES = 5 * 1024 * 1024


class Fetcher:
    def __init__(self, config: CrawlConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.user_agent,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        })

    def fetch(self, url: str, depth: int) -> "tuple[PageResult, str]":
        """Fetch a URL; return (result, html_body). Body is '' for non-HTML."""
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
