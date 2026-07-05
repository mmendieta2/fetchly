"""Fetchly MCP server: expose crawling to LLMs as tool calls.

Two tools:

- ``crawl_site`` runs a crawl and returns a *compact* audit digest (counts +
  small samples), writing the full page report, issues report, and a reopenable
  session file to disk.
- ``crawl_report`` pages through a saved crawl without recrawling, so a model can
  pull just the rows it needs instead of dragging the whole dataset into context.

Compact-by-default keeps results small for small-context / local models. The
crawling itself (HTTP, HTML parsing, robots, dedup) runs in plain Python, so the
model never reads raw page HTML.

Requires the optional ``mcp`` dependency: ``pip install "fetchly[mcp]"``. Importing
this module never pulls in ``mcp``; that happens only when the server is built.
"""

import os
import queue
from datetime import datetime
from typing import Optional

from . import events
from .config import CrawlConfig, with_scheme
from .engine import CrawlEngine
from .report import export_name, summarize, write_issues, write_report
from .session_io import load_crawl, save_crawl

# Hard ceiling on pages per crawl, regardless of what the model asks for, so a
# tool call can't be talked into an unbounded crawl. Override via the env var.
HARD_MAX_PAGES = int(os.environ.get("FETCHLY_MCP_MAX_PAGES", "500"))

TOP_ISSUE_TYPES = 12   # issue types included in a crawl_site digest
BROKEN_LINK_SAMPLE = 10
DETAIL_MAX_ROWS = 200  # ceiling on a single crawl_report page


def _run_crawl(config: CrawlConfig):
    """Run a crawl to completion; return (results, issues, stats).

    Mirrors the event-drain loop the CLI uses (cli.main), but silent.
    """
    engine = CrawlEngine(config)
    engine.start()
    results, issues, finished = [], [], None
    while finished is None:
        try:
            event = engine.events.get(timeout=0.5)
        except queue.Empty:
            continue
        if isinstance(event, events.PageCrawled):
            results.append(event.result)
            issues.extend(event.issues)
        elif isinstance(event, events.CrawlFinished):
            issues.extend(event.issues)
            finished = event
    return results, issues, finished.stats


def _output_dir(output_dir: Optional[str]) -> str:
    path = output_dir or os.environ.get("FETCHLY_MCP_OUTPUT_DIR") or os.getcwd()
    os.makedirs(path, exist_ok=True)
    return path


def build_digest(config: CrawlConfig, results, issues, stats, *,
                 report_csv: str, issues_csv: str, session: str) -> dict:
    """Assemble the compact JSON a crawl_site call returns."""
    summary = summarize(results, issues, stats)
    top = list(summary["issue_types"].items())[:TOP_ISSUE_TYPES]
    broken = [{"url": i.page_url, "detail": i.detail}
              for i in issues if i.issue_type == "broken_link"][:BROKEN_LINK_SAMPLE]
    return {
        "start_url": config.start_url,
        "pages_crawled": summary["pages_crawled"],
        "fetch_errors": summary["fetch_errors"],
        "kib_downloaded": summary["kib_downloaded"],
        "truncated": stats.crawled >= config.max_pages,
        "issues": summary["issue_counts"],
        "top_issue_types": dict(top),
        "broken_links_sample": broken,
        "report_csv": report_csv,
        "issues_csv": issues_csv,
        "session": session,
    }


def report_page(results, issues, *, kind: str = "issues",
                severity: Optional[str] = None, issue_type: Optional[str] = None,
                url_contains: Optional[str] = None, limit: int = 25,
                offset: int = 0) -> dict:
    """Filter + paginate a loaded crawl for crawl_report."""
    limit = max(1, min(limit, DETAIL_MAX_ROWS))
    offset = max(0, offset)
    if kind == "pages":
        rows = [r for r in results if not url_contains or url_contains in r.url]
        window = [{"url": r.url, "status": r.status_code, "depth": r.depth,
                   "title": r.title, "error": r.error}
                  for r in rows[offset:offset + limit]]
    else:
        rows = [i for i in issues
                if (not severity or i.severity == severity)
                and (not issue_type or i.issue_type == issue_type)
                and (not url_contains or url_contains in i.page_url)]
        window = [{"severity": i.severity, "type": i.issue_type,
                   "page": i.page_url, "detail": i.detail}
                  for i in rows[offset:offset + limit]]
    total = len(rows)
    end = offset + len(window)
    return {
        "kind": kind,
        "total": total,
        "returned": len(window),
        "offset": offset,
        "next_offset": end if end < total else None,
        "rows": window,
    }


def _crawl_site(url: str, max_pages: int = 50, max_depth: int = 3,
                include_subdomains: bool = False, respect_robots: bool = True,
                same_domain_only: bool = True, timeout_seconds: float = 15.0,
                workers: int = 4, delay_seconds: float = 0.0,
                user_agent: Optional[str] = None,
                output_dir: Optional[str] = None) -> dict:
    config = CrawlConfig(
        start_url=with_scheme(url),
        max_pages=max(1, min(max_pages, HARD_MAX_PAGES)),
        max_depth=max(0, max_depth),
        num_workers=max(1, workers),
        delay_seconds=max(0.0, delay_seconds),
        timeout_seconds=timeout_seconds,
        same_domain_only=same_domain_only,
        include_subdomains=include_subdomains,
        respect_robots=respect_robots,
        user_agent=user_agent or CrawlConfig.user_agent,
    )
    try:
        config.validate()
    except ValueError as exc:
        return {"error": str(exc)}

    results, issues, stats = _run_crawl(config)

    when = datetime.now()
    out = _output_dir(output_dir)
    report_csv = os.path.join(out, export_name(config.start_url, "pages", ".csv", when))
    issues_csv = os.path.join(out, export_name(config.start_url, "issues", ".csv", when))
    session = os.path.join(out, export_name(config.start_url, "crawl",
                                            ".fetchly.json.gz", when))
    write_report(report_csv, results)
    write_issues(issues_csv, issues)
    save_crawl(session, config, results, issues)
    return build_digest(config, results, issues, stats, report_csv=report_csv,
                        issues_csv=issues_csv, session=session)


def _crawl_report(session: str, kind: str = "issues",
                  severity: Optional[str] = None, issue_type: Optional[str] = None,
                  url_contains: Optional[str] = None, limit: int = 25,
                  offset: int = 0) -> dict:
    try:
        _config, results, issues = load_crawl(session)
    except (OSError, ValueError, KeyError) as exc:
        return {"error": f"cannot open {session}: {exc}"}
    return report_page(results, issues, kind=kind, severity=severity,
                       issue_type=issue_type, url_contains=url_contains,
                       limit=limit, offset=offset)


def build_server():
    """Create the FastMCP server. Imports `mcp` lazily so the module stays
    importable (and testable) without the optional dependency installed."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("fetchly")

    @server.tool()
    def crawl_site(url: str, max_pages: int = 50, max_depth: int = 3,
                   include_subdomains: bool = False, respect_robots: bool = True,
                   same_domain_only: bool = True, timeout_seconds: float = 15.0,
                   workers: int = 4, delay_seconds: float = 0.0,
                   user_agent: Optional[str] = None,
                   output_dir: Optional[str] = None) -> dict:
        """Crawl a website and return a compact audit summary.

        Fetches and analyzes pages server-side (status codes, titles, meta tags,
        links, broken links, SEO issues) and returns counts plus small samples —
        not the full dataset. The complete page report, issues report, and a
        reopenable session file are written to disk; pass the returned `session`
        path to `crawl_report` to page through details without recrawling.

        Args:
            url: Start URL; a bare domain gets https:// added.
            max_pages: Page cap (clamped to the server's hard limit).
            max_depth: Maximum link depth from the start URL.
            include_subdomains: Also crawl subdomains of the start host.
            respect_robots: Obey robots.txt — leave on unless you own the site.
            same_domain_only: Stay on the start domain.
            timeout_seconds: Per-page fetch timeout.
            workers: Number of parallel fetchers.
            delay_seconds: Politeness delay per worker between requests.
            user_agent: Override the User-Agent header (e.g. a browser UA).
            output_dir: Directory for the report files (default: current dir or
                the FETCHLY_MCP_OUTPUT_DIR env var).
        """
        return _crawl_site(url, max_pages=max_pages, max_depth=max_depth,
                           include_subdomains=include_subdomains,
                           respect_robots=respect_robots,
                           same_domain_only=same_domain_only,
                           timeout_seconds=timeout_seconds, workers=workers,
                           delay_seconds=delay_seconds, user_agent=user_agent,
                           output_dir=output_dir)

    @server.tool()
    def crawl_report(session: str, kind: str = "issues",
                     severity: Optional[str] = None,
                     issue_type: Optional[str] = None,
                     url_contains: Optional[str] = None, limit: int = 25,
                     offset: int = 0) -> dict:
        """Page through a saved crawl (from `crawl_site`) without recrawling.

        Returns a bounded window of rows plus `total` and `next_offset` for
        paging. Use this to drill into specifics after a `crawl_site` summary.

        Args:
            session: Path to the .fetchly.json.gz returned by `crawl_site`.
            kind: "issues" or "pages".
            severity: Filter issues by "error" or "warning" (issues only).
            issue_type: Filter issues by type, e.g. "broken_link" (issues only).
            url_contains: Only rows whose URL contains this substring.
            limit: Max rows to return (1-200).
            offset: Number of rows to skip (for paging).
        """
        return _crawl_report(session, kind=kind, severity=severity,
                             issue_type=issue_type, url_contains=url_contains,
                             limit=limit, offset=offset)

    return server


def main() -> None:
    try:
        server = build_server()
    except ImportError:
        raise SystemExit(
            "The Fetchly MCP server needs the 'mcp' package.\n"
            "Install it with:  pip install \"fetchly[mcp]\"")
    server.run()


if __name__ == "__main__":
    main()
