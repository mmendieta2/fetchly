import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fetchly.config import CrawlConfig
from fetchly.fetcher import Fetcher


class FlakyHandler(BaseHTTPRequestHandler):
    """Returns 503 until `failures_left` runs out, then 200."""
    failures_left = 0
    hits = 0

    def do_GET(self):
        cls = type(self)
        cls.hits += 1
        if cls.failures_left > 0:
            cls.failures_left -= 1
            self.send_response(503)
            self.end_headers()
        else:
            body = b"<html><head><title>OK</title></head><body>fine</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def flaky_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FlakyHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    FlakyHandler.hits = 0
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


def make_fetcher(**overrides):
    defaults = dict(start_url="http://x/", max_retries=2, retry_backoff_seconds=0.01)
    defaults.update(overrides)
    return Fetcher(CrawlConfig(**defaults))


def test_retries_then_succeeds(flaky_server):
    FlakyHandler.failures_left = 2
    result, body = make_fetcher().fetch(flaky_server, 0)
    assert result.status_code == 200
    assert FlakyHandler.hits == 3
    assert "fine" in body


def test_gives_up_after_max_retries(flaky_server):
    FlakyHandler.failures_left = 10
    result, _ = make_fetcher(max_retries=1).fetch(flaky_server, 0)
    assert result.status_code == 503
    assert FlakyHandler.hits == 2


def test_success_does_not_retry(flaky_server):
    FlakyHandler.failures_left = 0
    result, _ = make_fetcher().fetch(flaky_server, 0)
    assert result.status_code == 200
    assert FlakyHandler.hits == 1


def test_connection_error_retried_and_reported():
    fetcher = make_fetcher(max_retries=1)
    result, body = fetcher.fetch("http://127.0.0.1:1/", 0)  # nothing listens
    assert result.status_code == 0
    assert result.error
    assert body == ""
