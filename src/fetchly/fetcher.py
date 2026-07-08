"""HTTP fetching layer: one shared session, per-request timing and errors."""

import time

import requests
import urllib3

from .config import CrawlConfig
from .models import PageResult

_HTML_TYPES = ("text/html", "application/xhtml+xml")
_MAX_BODY_BYTES = 5 * 1024 * 1024
_RETRY_STATUSES = (429, 502, 503, 504)


def friendly_error(exc: Exception, timeout_seconds: float) -> str:
    """Plain-language description of a fetch failure, with a hint."""
    if isinstance(exc, requests.exceptions.Timeout):
        return (f"server did not respond within {timeout_seconds:g} s — the site "
                "may be slow or overloaded; try raising the Timeout setting "
                "(--timeout)")
    if isinstance(exc, requests.exceptions.SSLError):
        return f"secure connection failed (SSL/TLS problem): {exc}"
    if isinstance(exc, requests.exceptions.TooManyRedirects):
        return "redirect loop — the page keeps redirecting"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return ("could not connect — server refused or dropped the connection "
                "(site down, firewall, or bot protection)")
    if isinstance(exc, urllib3.exceptions.ReadTimeoutError):
        return (f"server did not respond within {timeout_seconds:g} s — the site "
                "may be slow or overloaded; try raising the Timeout setting "
                "(--timeout)")
    if isinstance(exc, urllib3.exceptions.ProtocolError):
        return ("connection dropped while the page body was downloading — the "
                "server or a proxy closed the connection mid-response")
    return str(exc)


class Fetcher:
    def __init__(self, config: CrawlConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.user_agent,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        })
        if config.login_url:
            self._login()

    def _login(self) -> None:
        """Forms auth: POST the login form once; cookies persist in the session."""
        try:
            response = self.session.post(
                self.config.login_url, data=self.config.login_data,
                timeout=self.config.timeout_seconds)
        except requests.RequestException as exc:
            raise RuntimeError(f"login request to {self.config.login_url} failed: {exc}")
        if response.status_code >= 400:
            raise RuntimeError(
                f"login to {self.config.login_url} returned HTTP {response.status_code}")

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
            result.x_robots_tag = response.headers.get("X-Robots-Tag", "").lower()
            if response.url != url:
                result.redirected_to = response.url
            result.redirect_hops = len(response.history)
            if response.history:
                temporary = any(r.status_code in (302, 303, 307) for r in response.history)
                result.redirect_type = "temporary" if temporary else "permanent"

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
        except (requests.RequestException, urllib3.exceptions.HTTPError) as exc:
            # urllib3 errors included: response.raw.read() bypasses requests'
            # error wrapping, so a mid-body failure (e.g. ProtocolError on a
            # connection reset) surfaces raw — uncaught it kills the worker.
            # Class-name prefix kept: audit.py matches on it and the error CSV
            # column stays greppable by exception type.
            result.error = (f"{type(exc).__name__}: "
                            f"{friendly_error(exc, self.config.timeout_seconds)}")
            return result, ""
        finally:
            result.elapsed_ms = round((time.monotonic() - started) * 1000, 1)

    def close(self) -> None:
        self.session.close()
