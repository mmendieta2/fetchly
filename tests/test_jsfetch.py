import pytest

from fetchly.config import CrawlConfig
from fetchly.engine import CrawlEngine


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(playwright_available(), reason="playwright installed")
def test_helpful_error_without_playwright():
    with pytest.raises(RuntimeError, match="fetchly\\[js\\]"):
        CrawlEngine(CrawlConfig(start_url="https://example.com/", render_js=True))


@pytest.mark.skipif(not playwright_available(), reason="playwright not installed")
def test_js_rendered_content_visible(test_site):
    """Content injected client-side is visible only through the JS fetcher."""
    from fetchly.fetcher import Fetcher
    from fetchly.jsfetch import JsFetcher

    plain = Fetcher(CrawlConfig(start_url=test_site))
    try:
        _, plain_body = plain.fetch(test_site + "jspage.html", 0)
        assert "RENDERED-BY-JS" not in plain_body
    finally:
        plain.close()

    fetcher = JsFetcher(CrawlConfig(start_url=test_site, render_js=True))
    try:
        result, body = fetcher.fetch(test_site + "jspage.html", 0)
        assert result.status_code == 200
        assert "RENDERED-BY-JS" in body
    finally:
        fetcher.close()


@pytest.mark.skipif(not playwright_available(), reason="playwright not installed")
def test_render_js_through_engine(test_site):
    """Full crawl with render_js: engine workers call the fetcher from other
    threads, which is exactly what broke Playwright's thread-bound sync API."""
    import queue as queue_mod

    from fetchly import events

    config = CrawlConfig(start_url=test_site + "jspage.html", render_js=True,
                         max_depth=0, check_orphans=False, num_workers=2)
    engine = CrawlEngine(config)
    engine.start()
    results, finished = [], None
    while finished is None:
        try:
            event = engine.events.get(timeout=60)
        except queue_mod.Empty:
            raise AssertionError("render crawl did not finish")
        if isinstance(event, events.PageCrawled):
            results.append(event.result)
        elif isinstance(event, events.CrawlFinished):
            finished = event
    assert len(results) == 1
    r = results[0]
    assert r.status_code == 200
    assert r.error == ""
    # word_count comes from the rendered DOM, so the injected text counts
    assert r.word_count >= 1


@pytest.mark.skipif(not playwright_available(), reason="playwright not installed")
def test_js_login_cookie_reaches_browser():
    """Forms auth in JS mode: the login cookie obtained over plain HTTP must
    be carried by Chromium, or the cookie-gated page below returns 403."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from fetchly.jsfetch import JsFetcher

    class GatedHandler(BaseHTTPRequestHandler):
        logins = []

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            type(self).logins.append(self.rfile.read(length).decode())
            self.send_response(200)
            self.send_header("Set-Cookie", "session=abc123")
            self.end_headers()

        def do_GET(self):
            body = b"<html><head><title>in</title></head><body>member area</body></html>"
            code = 200 if "session=abc123" in self.headers.get("Cookie", "") else 403
            self.send_response(code)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), GatedHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    fetcher = None
    try:
        fetcher = JsFetcher(CrawlConfig(
            start_url=base + "/", render_js=True,
            login_url=base + "/login",
            login_data={"user": "u", "password": "p"}))
        assert GatedHandler.logins and "password=p" in GatedHandler.logins[0]
        result, body = fetcher.fetch(base + "/members", 0)
        assert result.status_code == 200
        assert "member area" in body
    finally:
        if fetcher is not None:
            fetcher.close()
        server.shutdown()
