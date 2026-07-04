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
