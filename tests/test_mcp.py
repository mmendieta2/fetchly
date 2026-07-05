"""Tests for the MCP server's pure helpers.

These exercise the digest/summary/pagination logic without needing the optional
`mcp` package or the network — the tool wrappers in mcp_server just call these.
"""

from fetchly.audit import Issue
from fetchly.config import CrawlConfig
from fetchly.mcp_server import build_digest, report_page
from fetchly.models import CrawlStats, PageResult
from fetchly.report import summarize
from fetchly.session_io import load_crawl, save_crawl


def _sample():
    results = [
        PageResult(url="https://x.com/", status_code=200, content_length=2048),
        PageResult(url="https://x.com/a", status_code=200, content_length=1024),
        PageResult(url="https://x.com/dead", status_code=404, error="404"),
    ]
    issues = [
        Issue("https://x.com/dead", "broken_link", "error", "linked from /"),
        Issue("https://x.com/a", "broken_link", "error", "linked from /"),
        Issue("https://x.com/", "missing_title", "warning", "no title"),
        Issue("https://x.com/a", "missing_title", "warning", "no title"),
        Issue("https://x.com/a", "thin_content", "warning", "40 words"),
    ]
    stats = CrawlStats()
    for r in results:
        stats.record(r)
    return results, issues, stats


def test_summarize_counts():
    results, issues, stats = _sample()
    s = summarize(results, issues, stats)
    assert s["pages_crawled"] == 3
    assert s["fetch_errors"] == 1
    assert s["kib_downloaded"] == 3.0          # (2048 + 1024) / 1024
    assert s["issue_counts"] == {"error": 2, "warning": 3}
    # most-frequent first
    assert list(s["issue_types"]) == ["broken_link", "missing_title", "thin_content"]


def test_build_digest_shape():
    results, issues, stats = _sample()
    config = CrawlConfig(start_url="https://x.com/", max_pages=50)
    digest = build_digest(config, results, issues, stats,
                          report_csv="/tmp/p.csv", issues_csv="/tmp/i.csv",
                          session="/tmp/s.fetchly.json.gz")
    assert digest["start_url"] == "https://x.com/"
    assert digest["pages_crawled"] == 3
    assert digest["truncated"] is False        # 3 < max_pages 50
    assert digest["issues"] == {"error": 2, "warning": 3}
    assert digest["top_issue_types"]["broken_link"] == 2
    assert len(digest["broken_links_sample"]) == 2
    assert digest["broken_links_sample"][0]["url"].startswith("https://x.com/")
    assert digest["session"].endswith(".fetchly.json.gz")


def test_build_digest_truncated_when_cap_hit():
    results, issues, stats = _sample()
    config = CrawlConfig(start_url="https://x.com/", max_pages=3)
    digest = build_digest(config, results, issues, stats, report_csv="p",
                          issues_csv="i", session="s")
    assert digest["truncated"] is True         # crawled 3 == cap 3


def test_report_page_filters_and_paginates():
    results, issues, _ = _sample()
    # errors only
    errs = report_page(results, issues, kind="issues", severity="error")
    assert errs["total"] == 2
    assert all(r["severity"] == "error" for r in errs["rows"])
    # by type
    byt = report_page(results, issues, kind="issues", issue_type="missing_title")
    assert byt["total"] == 2
    # pagination
    first = report_page(results, issues, kind="issues", limit=2, offset=0)
    assert first["returned"] == 2 and first["next_offset"] == 2
    second = report_page(results, issues, kind="issues", limit=2, offset=2)
    assert second["returned"] == 2 and second["next_offset"] == 4
    last = report_page(results, issues, kind="issues", limit=2, offset=4)
    assert last["returned"] == 1 and last["next_offset"] is None  # 5 issues total
    # pages kind + url filter
    pages = report_page(results, issues, kind="pages", url_contains="/a")
    assert pages["total"] == 1 and pages["rows"][0]["url"] == "https://x.com/a"


def test_report_page_round_trip_through_saved_session(tmp_path):
    results, issues, _ = _sample()
    config = CrawlConfig(start_url="https://x.com/")
    path = tmp_path / "x.fetchly.json.gz"
    save_crawl(str(path), config, results, issues)
    _cfg, loaded_results, loaded_issues = load_crawl(str(path))
    page = report_page(loaded_results, loaded_issues, kind="issues",
                       issue_type="broken_link")
    assert page["total"] == 2
    assert {r["page"] for r in page["rows"]} == {"https://x.com/dead", "https://x.com/a"}
