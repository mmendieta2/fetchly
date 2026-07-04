from fetchly.audit import audit_page, find_duplicates
from fetchly.models import PageResult
from fetchly.parser import ParsedPage, parse_page
from fetchly.sitemap import _extract, write_sitemap


def ok_result(url="https://site.com/p"):
    return PageResult(url=url, status_code=200, ok=True)


def clean_page():
    return ParsedPage(
        title="A perfectly reasonable page title for tests",           # 30-60 chars
        meta_description="A meta description that is comfortably inside the "
                         "recommended length range for search snippets.",  # 70-155
        h1_count=1,
        word_count=500,
    )


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


class TestSeoChecks:
    def test_title_too_short_and_long(self):
        short = clean_page()
        short.title = "Tiny"
        assert issue_types(audit_page(ok_result(), short)) == {"title_too_short"}
        long = clean_page()
        long.title = "x" * 80
        assert issue_types(audit_page(ok_result(), long)) == {"title_too_long"}

    def test_meta_description_length(self):
        page = clean_page()
        page.meta_description = "too short"
        assert issue_types(audit_page(ok_result(), page)) == {"meta_description_too_short"}
        page.meta_description = "y" * 200
        assert issue_types(audit_page(ok_result(), page)) == {"meta_description_too_long"}

    def test_thin_content(self):
        page = clean_page()
        page.word_count = 50
        assert issue_types(audit_page(ok_result(), page)) == {"thin_content"}

    def test_zero_words_not_flagged_thin(self):
        page = clean_page()
        page.word_count = 0
        assert audit_page(ok_result(), page) == []

    def test_canonical_mismatch(self):
        page = clean_page()
        page.canonical_url = "https://site.com/other"
        assert issue_types(audit_page(ok_result("https://site.com/p"), page)) == {"canonical_mismatch"}

    def test_canonical_match_via_normalization(self):
        page = clean_page()
        page.canonical_url = "https://site.com/p#frag"
        assert audit_page(ok_result("https://site.com/p"), page) == []

    def test_noindex_from_meta_robots(self):
        result = ok_result()
        result.meta_robots = "noindex, nofollow"
        assert issue_types(audit_page(result, clean_page())) == {"noindex"}

    def test_noindex_from_header(self):
        result = ok_result()
        result.x_robots_tag = "noindex"
        assert issue_types(audit_page(result, clean_page())) == {"noindex"}


class TestRedirectChecks:
    def test_redirect_chain(self):
        result = ok_result()
        result.redirect_hops, result.redirect_type = 2, "permanent"
        result.redirected_to = "https://site.com/final"
        assert issue_types(audit_page(result, clean_page())) == {"redirect_chain"}

    def test_temporary_redirect(self):
        result = ok_result()
        result.redirect_hops, result.redirect_type = 1, "temporary"
        assert issue_types(audit_page(result, clean_page())) == {"temporary_redirect"}

    def test_single_permanent_redirect_ok(self):
        result = ok_result()
        result.redirect_hops, result.redirect_type = 1, "permanent"
        assert audit_page(result, clean_page()) == []

    def test_redirect_loop_from_error(self):
        result = PageResult(url="https://site.com/x",
                            error="TooManyRedirects: Exceeded 30 redirects.")
        issues = audit_page(result, None)
        assert issue_types(issues) == {"redirect_loop"}
        assert issues[0].severity == "error"


class TestDuplicates:
    def test_duplicate_titles_and_content(self):
        a = PageResult(url="https://s.com/a", ok=True, title="Same Title", content_hash="h1")
        b = PageResult(url="https://s.com/b", ok=True, title="Same Title", content_hash="h1")
        c = PageResult(url="https://s.com/c", ok=True, title="Other", content_hash="h2")
        issues = find_duplicates([a, b, c])
        assert issue_types(issues) == {"duplicate_title", "duplicate_content"}
        dup = next(i for i in issues if i.issue_type == "duplicate_title")
        assert "2 pages" in dup.detail

    def test_redirected_and_failed_pages_excluded(self):
        a = PageResult(url="https://s.com/a", ok=True, title="T" * 40)
        b = PageResult(url="https://s.com/b", ok=True, title="T" * 40,
                       redirected_to="https://s.com/a")
        c = PageResult(url="https://s.com/c", ok=False, title="T" * 40)
        assert find_duplicates([a, b, c]) == []

    def test_empty_values_not_grouped(self):
        a = PageResult(url="https://s.com/a", ok=True)
        b = PageResult(url="https://s.com/b", ok=True)
        assert find_duplicates([a, b]) == []


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


class TestSitemapGeneration:
    def test_writes_only_indexable_pages(self, tmp_path):
        results = [
            PageResult(url="https://s.com/keep", status_code=200, ok=True,
                       content_type="text/html"),
            PageResult(url="https://s.com/gone", status_code=404, content_type="text/html"),
            PageResult(url="https://s.com/moved", status_code=200, ok=True,
                       content_type="text/html", redirected_to="https://s.com/keep"),
            PageResult(url="https://s.com/hidden", status_code=200, ok=True,
                       content_type="text/html", meta_robots="noindex"),
            PageResult(url="https://s.com/err", error="ConnectionError"),
        ]
        out = tmp_path / "sitemap.xml"
        count = write_sitemap(str(out), results)
        text = out.read_text()
        assert count == 1
        assert "<loc>https://s.com/keep</loc>" in text
        for excluded in ("gone", "moved", "hidden", "err"):
            assert excluded not in text
