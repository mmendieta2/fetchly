import socket
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


class RedirectHandler(BaseHTTPRequestHandler):
    """/a --302--> /b --301--> /c (200); /loop redirects to itself forever."""

    def do_GET(self):
        routes = {"/a": (302, "/b"), "/b": (301, "/c"), "/loop": (302, "/loop")}
        if self.path in routes:
            code, target = routes[self.path]
            self.send_response(code)
            self.send_header("Location", target)
            self.end_headers()
        else:
            body = b"<html><head><title>Landed</title></head><body>done</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def redirect_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_redirect_chain_recorded(redirect_server):
    result, body = make_fetcher().fetch(redirect_server + "/a", 0)
    assert result.status_code == 200
    assert result.redirect_hops == 2
    assert result.redirect_type == "temporary"  # chain contains a 302
    assert result.redirected_to == redirect_server + "/c"
    assert "Landed" in body


def test_permanent_redirect_type(redirect_server):
    result, _ = make_fetcher().fetch(redirect_server + "/b", 0)
    assert result.redirect_hops == 1
    assert result.redirect_type == "permanent"


def test_redirect_loop_reported(redirect_server):
    result, body = make_fetcher(max_retries=0).fetch(redirect_server + "/loop", 0)
    assert result.status_code == 0
    assert "TooManyRedirects" in result.error
    assert body == ""


class TruncatedBodyHandler(BaseHTTPRequestHandler):
    """Declares a chunked HTML body, then drops the connection mid-chunk."""

    protocol_version = "HTTP/1.1"  # chunked transfer needs 1.1

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        self.wfile.write(b"400\r\n<html><body>partial")  # promises 0x400 bytes
        self.wfile.flush()
        # close() alone leaves the fd open (rfile/wfile still reference it);
        # shutdown() actually sends the FIN mid-chunk.
        self.connection.shutdown(socket.SHUT_RDWR)

    def log_message(self, *args):
        pass


@pytest.fixture
def truncating_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), TruncatedBodyHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


def test_mid_body_disconnect_reported_not_raised(truncating_server):
    # raw.read() raises a bare urllib3 ProtocolError (requests doesn't wrap
    # it); it must land in result.error, not escape and kill the worker.
    result, body = make_fetcher(max_retries=0, timeout_seconds=5).fetch(
        truncating_server, 0)
    assert "ProtocolError" in result.error
    assert "connection dropped" in result.error
    assert body == ""


def test_connection_error_retried_and_reported():
    fetcher = make_fetcher(max_retries=1)
    result, body = fetcher.fetch("http://127.0.0.1:1/", 0)  # nothing listens
    assert result.status_code == 0
    assert result.error
    assert body == ""


class TestFriendlyError:
    def test_timeout_names_the_setting(self):
        from requests.exceptions import ReadTimeout
        from fetchly.fetcher import friendly_error
        msg = friendly_error(ReadTimeout("HTTPSConnectionPool(...)"), 15.0)
        assert "did not respond within 15 s" in msg
        assert "Timeout setting" in msg
        assert "HTTPSConnectionPool" not in msg

    def test_connection_error(self):
        from requests.exceptions import ConnectionError
        from fetchly.fetcher import friendly_error
        msg = friendly_error(ConnectionError("boom"), 15.0)
        assert "could not connect" in msg

    def test_ssl_error_checked_before_connection_error(self):
        from requests.exceptions import SSLError
        from fetchly.fetcher import friendly_error
        assert "SSL/TLS" in friendly_error(SSLError("bad cert"), 15.0)

    def test_urllib3_protocol_error(self):
        from urllib3.exceptions import ProtocolError
        from fetchly.fetcher import friendly_error
        assert "connection dropped" in friendly_error(
            ProtocolError("Connection broken: ConnectionResetError(104)"), 15.0)

    def test_urllib3_read_timeout(self):
        from urllib3.exceptions import ReadTimeoutError
        from fetchly.fetcher import friendly_error
        msg = friendly_error(ReadTimeoutError(None, "http://x/", "read timed out"), 15.0)
        assert "did not respond within 15 s" in msg

    def test_unknown_exception_falls_back(self):
        from requests.exceptions import RequestException
        from fetchly.fetcher import friendly_error
        assert friendly_error(RequestException("odd"), 15.0) == "odd"

    def test_fetch_timeout_produces_friendly_error(self, flaky_server=None):
        # nothing listens on port 1 -> ConnectionError with friendly text
        result, _ = make_fetcher(max_retries=0).fetch("http://127.0.0.1:1/", 0)
        assert result.error.startswith("ConnectionError:")
        assert "could not connect" in result.error
