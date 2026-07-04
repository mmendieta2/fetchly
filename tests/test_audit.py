from fetchly.audit import audit_page
from fetchly.models import PageResult
from fetchly.parser import ParsedPage, parse_page
from fetchly.sitemap import _extract


def ok_result(url="https://site.com/p"):
    return PageResult(url=url, status_code=200, ok=True)


def clean_page():
    return ParsedPage(title="T", meta_description="d", h1_count=1)


def issue_types(issues):
    return {i.issue_type for i in issues}


class TestAuditPage:
    def test_clean_page_has_no_issues(self):
        assert audit_page(ok_result(), clean_page()) == []

    def test_broken_link_includes_referrer(self):
        result = PageResult(url="https://site.com/gone", status_code=404,
                            found_on="https://site.com/")
        issues = audit_page(result, None)
        assert issue_types(issues) == {"broken_link"}
        assert "linked from https://site.com/" in issues[0].detail
        assert issues[0].severity == "error"

    def test_fetch_error(self):
        result = PageResult(url="https://site.com/x", error="ConnectionError: boom")
        assert issue_types(audit_page(result, None)) == {"fetch_error"}

    def test_content_warnings(self):
        page = ParsedPage(title="", meta_description="", h1_count=3,
                          missing_alt_srcs=["a.png", "b.png"])
        issues = audit_page(ok_result(), page)
        assert issue_types(issues) == {
            "images_missing_alt", "missing_title", "missing_meta_description", "multiple_h1"}
        alt = next(i for i in issues if i.issue_type == "images_missing_alt")
        assert "2 image(s)" in alt.detail and "a.png" in alt.detail

    def test_missing_h1(self):
        page = clean_page()
        page.h1_count = 0
        assert issue_types(audit_page(ok_result(), page)) == {"missing_h1"}

    def test_mixed_content_is_error(self):
        page = clean_page()
        page.mixed_content = ["http://cdn.old.com/app.js"]
        issues = audit_page(ok_result(), page)
        assert issue_types(issues) == {"mixed_content"}
        assert issues[0].severity == "error"
        assert "http://cdn.old.com/app.js" in issues[0].detail


class TestMixedContentParsing:
    def test_detected_on_https_page(self):
        html = """<html><body>
          <img src="http://insecure.com/a.png">
          <script src="http://insecure.com/x.js"></script>
          <img src="https://ok.com/b.png" alt="fine">
          <link rel="stylesheet" href="http://insecure.com/s.css">
        </body></html>"""
        page = parse_page("https://site.com/", html)
        assert sorted(page.mixed_content) == [
            "http://insecure.com/a.png", "http://insecure.com/s.css",
            "http://insecure.com/x.js"]

    def test_not_flagged_on_http_page(self):
        html = '<img src="http://anything.com/a.png">'
        page = parse_page("http://site.com/", html)
        assert page.mixed_content == []

    def test_missing_alt_srcs_collected(self):
        html = '<img src="a.png"><img src="b.png" alt="ok"><img>'
        page = parse_page("https://site.com/", html)
        assert page.missing_alt_srcs == ["a.png", "(no src)"]


class TestSitemapExtract:
    def test_urlset(self):
        xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://s.com/a</loc></url>
          <url><loc>https://s.com/b</loc></url>
        </urlset>"""
        pages, children = _extract(xml)
        assert pages == ["https://s.com/a", "https://s.com/b"]
        assert children == []

    def test_sitemap_index(self):
        xml = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>https://s.com/sitemap-1.xml</loc></sitemap>
        </sitemapindex>"""
        pages, children = _extract(xml)
        assert pages == []
        assert children == ["https://s.com/sitemap-1.xml"]

    def test_garbage_xml(self):
        assert _extract("not xml at all") == ([], [])
