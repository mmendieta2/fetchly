"""Tests for Tier 1 features: save/open, hreflang, near-dup, robots override,
JSON-LD, AMP, segmentation, forms auth."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fetchly.audit import audit_page, find_hreflang_issues, find_near_duplicates
from fetchly.config import CrawlConfig
from fetchly.engine import CrawlEngine
from fetchly.fetcher import Fetcher
from fetchly.models import PageResult
from fetchly.parser import parse_page, simhash64
from fetchly.robots import RobotsCache
from fetchly.session_io import load_crawl, save_crawl
from tests.test_engine import run_crawl


def ok_result(url="https://site.com/p", **kw):
    return PageResult(url=url, status_code=200, ok=True, **kw)


class TestSaveOpen:
    def test_roundtrip(self, tmp_path):
        config = CrawlConfig(start_url="https://s.com/", login_url="https://s.com/login",
                             login_data={"user": "u", "password": "secret"})
        results = [ok_result(extracted={"price": "$5"}, hreflang=[("en", "https://s.com/")])]
        issues = [__import__("fetchly.audit", fromlist=["Issue"]).Issue(
            "https://s.com/", "missing_h1", "warning", "no h1")]
        path = str(tmp_path / "c.fetchly.json.gz")
        save_crawl(path, config, results, issues)
        config2, results2, issues2 = load_crawl(path)
        assert config2.start_url == config.start_url
        assert config2.login_data == {}  # credentials never persisted
        assert results2[0].url == results[0].url
        assert results2[0].extracted == {"price": "$5"}
        assert issues2[0].issue_type == "missing_h1"

    def test_unknown_fields_ignored(self, tmp_path):
        import gzip
        import json
        path = str(tmp_path / "c.fetchly.json.gz")
        data = {"format": 1,
                "config": {"start_url": "https://s.com/", "future_field": 1},
                "results": [{"url": "https://s.com/", "future": 2}], "issues": []}
        with gzip.open(path, "wt") as fh:
            json.dump(data, fh)
        config, results, _ = load_crawl(path)
        assert config.start_url == "https://s.com/"
        assert results[0].url == "https://s.com/"

    def test_bad_format_rejected(self, tmp_path):
        import gzip
        import json
        path = str(tmp_path / "c.fetchly.json.gz")
        with gzip.open(path, "wt") as fh:
            json.dump({"format": 99}, fh)
        with pytest.raises(ValueError):
            load_crawl(path)


class TestHreflang:
    HTML = """<html><head><title>x</title>
      <link rel="alternate" hreflang="en" href="/en/">
      <link rel="alternate" hreflang="de-DE" href="https://s.com/de/">
      <link rel="alternate" hreflang="x-default" href="/">
      <link rel="alternate" hreflang="notalang!" href="/bad/">
    </head><body></body></html>"""

    def test_parser_collects_pairs(self):
        page = parse_page("https://s.com/", self.HTML)
        assert ("en", "https://s.com/en/") in page.hreflang
        assert ("de-DE", "https://s.com/de/") in page.hreflang
        assert len(page.hreflang) == 4

    def test_invalid_code_flagged(self):
        page = parse_page("https://s.com/", self.HTML)
        types = {i.issue_type for i in audit_page(ok_result(), page)}
        assert "invalid_hreflang" in types
        assert "hreflang_missing_x_default" not in types  # x-default present

    def test_missing_x_default(self):
        html = '<link rel="alternate" hreflang="en" href="/en/">'
        page = parse_page("https://s.com/", html)
        types = {i.issue_type for i in audit_page(ok_result(), page)}
        assert "hreflang_missing_x_default" in types

    def test_missing_return_link_and_broken_target(self):
        a = ok_result("https://s.com/en/", hreflang=[("de", "https://s.com/de/")])
        b = ok_result("https://s.com/de/", hreflang=[("fr", "https://s.com/fr/")])
        broken = PageResult(url="https://s.com/fr/", status_code=404,
                            found_on="https://s.com/de/")
        issues = find_hreflang_issues([a, b, broken])
        types = {i.issue_type for i in issues}
        assert "hreflang_missing_return_link" in types  # b doesn't link back to a
        assert "hreflang_broken_target" in types        # b -> fr is a 404


class TestNearDuplicates:
    BASE = ("the quick brown fox jumps over the lazy dog again and again "
            "while the sun sets slowly behind the quiet green hills") * 3

    def test_simhash_close_for_similar_text(self):
        a = simhash64(self.BASE.split())
        b = simhash64((self.BASE + " extra word").split())
        assert bin(a ^ b).count("1") <= 6

    def test_detects_near_duplicates(self):
        a = ok_result("https://s.com/a", simhash=simhash64(self.BASE.split()),
                      content_hash="h1", word_count=60)
        b = ok_result("https://s.com/b",
                      simhash=simhash64((self.BASE + " tweak").split()),
                      content_hash="h2", word_count=61)
        c = ok_result("https://s.com/c",
                      simhash=simhash64(("completely different words about "
                                         "sailing boats and ocean navigation charts " * 8).split()),
                      content_hash="h3", word_count=50)
        issues = find_near_duplicates([a, b, c])
        assert len(issues) == 1
        assert issues[0].issue_type == "near_duplicate_content"
        assert "https://s.com/b" in issues[0].detail

    def test_exact_duplicates_skipped(self):
        a = ok_result("https://s.com/a", simhash=123, content_hash="same", word_count=10)
        b = ok_result("https://s.com/b", simhash=123, content_hash="same", word_count=10)
        assert find_near_duplicates([a, b]) == []


class TestRobotsOverride:
    def test_override_applies_to_all_hosts(self):
        cache = RobotsCache("FetchlyBot", override_text="User-agent: *\nDisallow: /private/\n")
        assert not cache.allowed("https://any-host.com/private/x")
        assert cache.allowed("https://any-host.com/public")

    def test_engine_rejects_missing_file(self, test_site):
        with pytest.raises(ValueError, match="robots file"):
            CrawlEngine(CrawlConfig(start_url=test_site, robots_txt_file="/nonexistent"))


class TestStructuredData:
    def test_types_collected(self):
        html = """<script type="application/ld+json">
          {"@context": "https://schema.org", "@type": "Article",
           "@graph": [{"@type": "Person"}]}
        </script>
        <script type="application/ld+json">[{"@type": ["Product", "Thing"]}]</script>"""
        page = parse_page("https://s.com/", html)
        assert sorted(page.schema_types) == ["Article", "Person", "Product", "Thing"]
        assert page.schema_errors == 0

    def test_invalid_block_flagged(self):
        page = parse_page("https://s.com/", '<script type="application/ld+json">{oops</script>')
        assert page.schema_errors == 1
        types = {i.issue_type for i in audit_page(ok_result(), page)}
        assert "invalid_json_ld" in types


class TestAmp:
    def test_amp_link_and_page_detected(self):
        page = parse_page("https://s.com/post",
                          '<html amp><head><link rel="amphtml" href="/post/amp"></head></html>')
        assert page.is_amp
        assert page.amp_url == "https://s.com/post/amp"

    def test_amp_missing_canonical(self):
        page = parse_page("https://s.com/amp", "<html amp><head></head><body></body></html>")
        types = {i.issue_type for i in audit_page(ok_result(), page)}
        assert "amp_missing_canonical" in types


class TestSegmentation:
    def test_segments_assigned(self, test_site):
        config = CrawlConfig(start_url=test_site, check_orphans=False,
                             segment_rules=["sub=/sub/", "pages=re:page\\d"])
        results, _, _, _ = run_crawl(config)
        by_url = {r.url: r for r in results}
        assert by_url[test_site + "sub/page2.html"].segment == "sub"  # first match wins
        assert by_url[test_site + "page1.html"].segment == "pages"
        assert by_url[test_site].segment == ""

    def test_bad_rule_rejected(self, test_site):
        with pytest.raises(ValueError, match="segment rule"):
            CrawlEngine(CrawlConfig(start_url=test_site, segment_rules=["nosep"]))


class LoginHandler(BaseHTTPRequestHandler):
    logins = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        type(self).logins.append(self.rfile.read(length).decode())
        self.send_response(200)
        self.send_header("Set-Cookie", "session=abc123")
        self.end_headers()

    def do_GET(self):
        body = b"<html><head><title>ok</title></head><body>in</body></html>"
        code = 200 if self.headers.get("Cookie") == "session=abc123" else 403
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class TestFormsAuth:
    @pytest.fixture
    def auth_server(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), LoginHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        LoginHandler.logins = []
        yield f"http://127.0.0.1:{server.server_address[1]}"
        server.shutdown()

    def test_login_posts_and_cookie_persists(self, auth_server):
        config = CrawlConfig(start_url=auth_server + "/",
                             login_url=auth_server + "/login",
                             login_data={"user": "u", "password": "p"})
        fetcher = Fetcher(config)
        try:
            assert LoginHandler.logins and "password=p" in LoginHandler.logins[0]
            result, _ = fetcher.fetch(auth_server + "/page", 0)
            assert result.status_code == 200  # cookie carried over
        finally:
            fetcher.close()

    def test_login_failure_raises(self, auth_server):
        config = CrawlConfig(start_url=auth_server + "/",
                             login_url="http://127.0.0.1:1/login", login_data={})
        with pytest.raises(RuntimeError, match="login"):
            Fetcher(config)

    # JS-mode forms auth is exercised end-to-end in test_jsfetch.py
    # (test_js_login_cookie_reaches_browser); the old rejection is gone.