"""Regression tests for the UA-sensitive robots.txt handling and the clear
'not read' reporting when a page is blocked (the i-creatif.com report)."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fetchly import events
from fetchly.audit import audit_page
from fetchly.config import CrawlConfig
from fetchly.engine import CrawlEngine
from fetchly.models import PageResult
from fetchly.robots import RobotsCache
from tests.test_engine import run_crawl


class UAGatedHandler(BaseHTTPRequestHandler):
    """403s any client whose UA isn't in the allow-list (mimics a WAF).
    robots.txt itself is also gated — exactly the i-creatif.com case."""
    allow_substring = "GoodBot"

    def _blocked(self):
        return self.allow_substring not in self.headers.get("User-Agent", "")

    def do_GET(self):
        if self._blocked():
            self.send_response(403)
            self.end_headers()
            return
        if self.path == "/robots.txt":
            body = b"User-agent: *\nDisallow: /wp-admin/\n"
        else:
            body = b"<html><head><title>Home</title></head><body>hi there world</body></html>"
        self.send_response(200)
        self.send_header("Content-Type",
                         "text/plain" if self.path == "/robots.txt" else "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def ua_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), UAGatedHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_robots_uses_configured_user_agent(ua_server):
    """With a browser-ish UA the site (and its robots.txt) return 200, so the
    home page is allowed — previously the stdlib fetched with urllib's UA,
    got 403, and disallowed everything."""
    import requests
    session = requests.Session()
    session.headers["User-Agent"] = "GoodBot/1.0"
    cache = RobotsCache("GoodBot/1.0", session=session)
    assert cache.allowed(ua_server + "/index.html")
    assert not cache.allowed(ua_server + "/wp-admin/x")  # real rule still parsed


def test_blocked_robots_fails_open():
    """A 403/404 on robots.txt means 'assume no restrictions', not 'disallow
    everything'."""
    import requests
    cache = RobotsCache("Blocked/1.0", session=requests.Session())
    # Nothing listens here → RequestException → fail open.
    assert cache.allowed("http://127.0.0.1:1/anything")


def test_crawl_succeeds_with_browser_ua(ua_server):
    config = CrawlConfig(start_url=ua_server + "/", user_agent="GoodBot/1.0",
                         check_orphans=False)
    results, _, finished, issues = run_crawl(config)
    assert finished.stats.crawled == 1
    assert results[0].status_code == 200
    assert not any(i.issue_type == "blocked_by_robots" for i in issues)


def test_blocked_page_reported_clearly(ua_server):
    """Wrong UA → robots.txt 403 → fail open → page fetched → 403 → a clear
    access_forbidden issue (not a silent 0 pages / 0 issues)."""
    config = CrawlConfig(start_url=ua_server + "/", user_agent="BadBot/9",
                         check_orphans=False)
    results, _, finished, issues = run_crawl(config)
    assert results[0].status_code == 403
    forbidden = [i for i in issues if i.issue_type == "access_forbidden"]
    assert len(forbidden) == 1
    assert "not read" in forbidden[0].detail
    assert "user-agent" in forbidden[0].detail.lower()


def test_start_url_blocked_by_robots_emits_issue(test_site):
    """When robots.txt disallows the start URL, report it plainly instead of
    a bare 0-pages result."""
    config = CrawlConfig(start_url=test_site + "private/secret.html",
                         check_orphans=True)
    results, skipped, finished, issues = run_crawl(config)
    assert results == []
    blocked = [i for i in issues if i.issue_type == "blocked_by_robots"]
    assert len(blocked) == 1
    assert "robots.txt" in blocked[0].detail
    # orphan check must be suppressed when nothing crawled
    assert not any(i.issue_type == "orphan_page" for i in issues)


def test_access_forbidden_message_shape():
    for code in (401, 403):
        r = PageResult(url="https://s.com/x", status_code=code)
        issues = audit_page(r, None)
        assert issues[0].issue_type == "access_forbidden"
        assert str(code) in issues[0].detail
