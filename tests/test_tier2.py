"""Tier 2: mobile usability, accessibility (axe-core), custom JS, spellcheck."""

import queue as queue_mod

import pytest

from fetchly import events
from fetchly.audit import audit_page
from fetchly.config import CrawlConfig
from fetchly.engine import CrawlEngine
from fetchly.models import PageResult
from fetchly.parser import ParsedPage, find_misspellings, parse_page

DICTIONARY = {"this", "page", "contains", "some", "regular", "words",
              "hello", "world", "example", "content"}


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


class TestSpellcheck:
    def test_unknown_words_found(self):
        words = "this page contains some regullar wrods".split()
        assert find_misspellings(words, DICTIONARY) == ["regullar", "wrods"]

    def test_conservative_skips(self):
        # short, capitalized, digits, non-ascii, non-alpha: never judged
        words = ["ab", "NASA", "Python3", "naïveté", "foo-bar", "Word"]
        assert find_misspellings(words, DICTIONARY) == []

    def test_punctuation_stripped_and_deduped(self):
        words = ["hello,", "(world)", "zorbles!", "zorbles?"]
        assert find_misspellings(words, DICTIONARY) == ["zorbles"]

    def test_parse_page_with_dictionary(self):
        html = "<html><body><p>hello world glorpish content</p></body></html>"
        page = parse_page("https://s.com/", html, spell_dictionary=DICTIONARY)
        assert page.misspellings == ["glorpish"]

    def test_audit_issue_emitted(self):
        page = ParsedPage(title="A perfectly reasonable page title for tests",
                          meta_description="A meta description that is comfortably "
                          "inside the recommended length range for search snippets.",
                          h1_count=1, word_count=500, misspellings=["glorpish"])
        result = PageResult(url="https://s.com/", status_code=200, ok=True)
        types = {i.issue_type for i in audit_page(result, page)}
        assert types == {"possible_misspellings"}

    def test_engine_crawl_with_dictionary_file(self, test_site, tmp_path):
        dict_path = tmp_path / "words"
        dict_path.write_text("\n".join(sorted(DICTIONARY | {"home", "unlinked", "end",
                                                            "one", "two", "three"})))
        from tests.test_engine import run_crawl
        config = CrawlConfig(start_url=test_site, check_orphans=False,
                             spellcheck=True, dictionary_file=str(dict_path))
        results, _, _, _ = run_crawl(config)
        assert all(isinstance(r.misspell_count, int) for r in results)

    def test_missing_dictionary_rejected(self, test_site):
        with pytest.raises(ValueError, match="word list"):
            CrawlEngine(CrawlConfig(start_url=test_site, spellcheck=True,
                                    dictionary_file="/nonexistent/words"))


class TestModeGuards:
    @pytest.mark.parametrize("kw", [{"mobile_checks": True}, {"a11y_checks": True},
                                    {"js_snippets": ["x=/tmp/x.js"]}])
    def test_browser_features_require_render_js(self, test_site, kw):
        with pytest.raises(ValueError, match="render-js"):
            CrawlEngine(CrawlConfig(start_url=test_site, **kw))

    def test_bad_snippet_spec(self, test_site):
        with pytest.raises(ValueError, match="JS snippet"):
            CrawlEngine(CrawlConfig(start_url=test_site, render_js=True,
                                    js_snippets=["nosep"]))


class TestMobileAuditMapping:
    def test_issues_from_browser_checks(self):
        result = PageResult(url="https://s.com/", status_code=200, ok=True,
                            browser_checks={"mobile": {"viewport": False,
                                                       "small_text": 3, "small_taps": 2}})
        page = ParsedPage(title="A perfectly reasonable page title for tests",
                          meta_description="A meta description that is comfortably "
                          "inside the recommended length range for search snippets.",
                          h1_count=1, word_count=500)
        types = {i.issue_type for i in audit_page(result, page)}
        assert types == {"missing_viewport_meta", "small_text_mobile", "small_tap_targets"}

    def test_a11y_severity_mapping(self):
        result = PageResult(url="https://s.com/", status_code=200, ok=True,
                            browser_checks={"a11y": [
                                {"id": "image-alt", "impact": "critical",
                                 "description": "Images must have alt", "nodes": 2},
                                {"id": "region", "impact": "moderate",
                                 "description": "Content in landmarks", "nodes": 1}]})
        page = ParsedPage(title="A perfectly reasonable page title for tests",
                          meta_description="A meta description that is comfortably "
                          "inside the recommended length range for search snippets.",
                          h1_count=1, word_count=500)
        issues = {i.issue_type: i for i in audit_page(result, page)}
        assert issues["a11y_image-alt"].severity == "error"
        assert issues["a11y_region"].severity == "warning"


def drive(config):
    engine = CrawlEngine(config)
    engine.start()
    results, finished = [], None
    while finished is None:
        event = engine.events.get(timeout=90)
        if isinstance(event, events.PageCrawled):
            results.append(event.result)
        elif isinstance(event, events.CrawlFinished):
            finished = event
    return results


@pytest.mark.skipif(not playwright_available(), reason="playwright not installed")
class TestInBrowser:
    def test_mobile_checks_real_page(self, test_site):
        # fixture pages have no viewport meta
        config = CrawlConfig(start_url=test_site + "page3.html", render_js=True,
                             mobile_checks=True, max_depth=0, check_orphans=False)
        results = drive(config)
        mobile = results[0].browser_checks.get("mobile")
        assert mobile is not None
        assert mobile["viewport"] is False

    def test_a11y_real_page(self, test_site):
        # index.html has an image without alt text -> axe image-alt violation
        config = CrawlConfig(start_url=test_site + "a11y.html", render_js=True,
                             a11y_checks=True, max_depth=0, check_orphans=False)
        results = drive(config)
        violations = results[0].browser_checks.get("a11y")
        assert violations is not None
        assert any(v["id"] == "image-alt" for v in violations)

    def test_custom_snippet(self, test_site, tmp_path):
        snippet = tmp_path / "count.js"
        snippet.write_text("() => document.querySelectorAll('a').length")
        config = CrawlConfig(start_url=test_site + "page1.html", render_js=True,
                             js_snippets=[f"links={snippet}"], max_depth=0,
                             check_orphans=False)
        results = drive(config)
        assert results[0].extracted["links"] == "3"