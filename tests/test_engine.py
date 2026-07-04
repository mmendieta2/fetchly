import csv
import queue

from fetchly import events
from fetchly.config import CrawlConfig
from fetchly.engine import CrawlEngine
from fetchly.report import write_report


def run_crawl(config, timeout=30):
    """Drive an engine to completion; return (results, skipped, finished, issues)."""
    engine = CrawlEngine(config)
    engine.start()
    results, skipped, issues, finished = [], [], [], None
    while finished is None:
        try:
            event = engine.events.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError("crawl did not finish in time")
        if isinstance(event, events.PageCrawled):
            results.append(event.result)
            issues.extend(event.issues)
        elif isinstance(event, events.UrlSkipped):
            skipped.append(event)
        elif isinstance(event, events.CrawlFinished):
            finished = event
            issues.extend(event.issues)
    return results, skipped, finished, issues


def test_full_crawl(test_site):
    config = CrawlConfig(start_url=test_site, num_workers=4)
    results, skipped, finished, _ = run_crawl(config)

    by_url = {r.url: r for r in results}
    # index, page1, page2, page3, missing — no dupes, no png/mailto, no /private/
    assert len(results) == 5
    assert finished.stats.crawled == 5
    assert finished.stats.errors == 0
    assert not finished.stopped_by_user

    home = by_url[test_site]
    assert home.status_code == 200 and home.title == "Home" and home.depth == 0
    assert by_url[test_site + "page1.html"].depth == 1
    assert by_url[test_site + "page3.html"].depth == 2
    assert by_url[test_site + "missing.html"].status_code == 404


def test_found_on_referrer(test_site):
    """Each crawled page records the page that linked to it."""
    config = CrawlConfig(start_url=test_site, num_workers=1)
    results, _, _, _ = run_crawl(config)
    by_url = {r.url: r for r in results}
    assert by_url[test_site].found_on == ""
    assert by_url[test_site + "missing.html"].found_on == test_site
    assert by_url[test_site + "page3.html"].found_on == test_site + "page1.html"


def test_audit_columns_populated(test_site):
    config = CrawlConfig(start_url=test_site)
    results, _, _, _ = run_crawl(config)
    home = {r.url: r for r in results}[test_site]
    # index links: page1, page2, missing, pic.png (same host) + mailto (no host)
    assert home.links_found == 5
    assert home.internal_links == 4
    assert home.external_links == 1
    assert home.h1_count == 0
    assert home.word_count > 0


def test_page_issues_emitted(test_site):
    config = CrawlConfig(start_url=test_site, check_orphans=False)
    _, _, _, issues = run_crawl(config)
    types = {i.issue_type for i in issues}
    # fixture pages have no meta descriptions or h1s; missing.html is a 404
    assert "broken_link" in types
    assert "missing_meta_description" in types
    broken = next(i for i in issues if i.issue_type == "broken_link")
    assert broken.page_url == test_site + "missing.html"
    assert test_site in broken.detail  # names the linking page


def test_orphan_detection(test_site):
    config = CrawlConfig(start_url=test_site, check_orphans=True)
    _, _, finished, _ = run_crawl(config)
    orphans = [i for i in finished.issues if i.issue_type == "orphan_page"]
    assert [i.page_url for i in orphans] == [test_site + "orphan.html"]


def test_orphan_check_skipped_when_truncated(test_site):
    config = CrawlConfig(start_url=test_site, max_pages=2, check_orphans=True)
    _, _, finished, _ = run_crawl(config)
    assert finished.issues == []


def test_robots_disallow(test_site):
    """A directly-seeded disallowed URL is skipped with reason robots.txt."""
    config = CrawlConfig(start_url=test_site + "private/secret.html")
    results, skipped, _, _ = run_crawl(config)
    assert results == []
    assert len(skipped) == 1 and skipped[0].reason == "robots.txt"


def test_max_pages_limit(test_site):
    config = CrawlConfig(start_url=test_site, max_pages=2, num_workers=2)
    results, _, finished, _ = run_crawl(config)
    assert len(results) <= 2
    assert not finished.stopped_by_user  # hitting the limit isn't a user stop


def test_max_depth_limit(test_site):
    config = CrawlConfig(start_url=test_site, max_depth=1)
    results, _, _, _ = run_crawl(config)
    # page3 is only reachable at depth 2
    assert all(r.depth <= 1 for r in results)
    assert test_site + "page3.html" not in {r.url for r in results}


def test_invalid_start_url():
    try:
        CrawlEngine(CrawlConfig(start_url="notaurl"))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for invalid start URL")


def test_csv_report(test_site, tmp_path):
    config = CrawlConfig(start_url=test_site)
    results, _, _, _ = run_crawl(config)
    out = tmp_path / "report.csv"
    write_report(str(out), results)
    with open(out, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == len(results)
    assert {row["url"] for row in rows} == {r.url for r in results}
    assert all(row["status_code"] for row in rows)
