"""Command-line front end."""

import argparse
import queue
import sys

from . import events
from .config import CrawlConfig
from .engine import CrawlEngine
from .report import CsvReport, issues_path_for, write_issues


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fetchly", description="Crawl a website and write a CSV report.")
    p.add_argument("url", help="Start URL (http:// or https://)")
    p.add_argument("-o", "--output", default="fetchly_report.csv", help="CSV output path")
    p.add_argument("-n", "--max-pages", type=int, default=200)
    p.add_argument("-d", "--max-depth", type=int, default=5)
    p.add_argument("-w", "--workers", type=int, default=8)
    p.add_argument("--delay", type=float, default=0.0, help="Delay between requests per worker (s)")
    p.add_argument("--timeout", type=float, default=15.0)
    p.add_argument("--retries", type=int, default=2,
                   help="Extra attempts on connection errors and 429/5xx")
    p.add_argument("--subdomains", action="store_true", help="Also crawl subdomains")
    p.add_argument("--all-domains", action="store_true", help="Do not restrict to the start domain")
    p.add_argument("--no-robots", action="store_true", help="Ignore robots.txt")
    p.add_argument("--no-orphan-check", action="store_true",
                   help="Skip the sitemap.xml orphan-page check")
    p.add_argument("--exclude", action="append", default=[], help="Skip URLs containing this substring (repeatable)")
    p.add_argument("-q", "--quiet", action="store_true")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config = CrawlConfig(
        start_url=args.url,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        num_workers=args.workers,
        delay_seconds=args.delay,
        timeout_seconds=args.timeout,
        max_retries=args.retries,
        same_domain_only=not args.all_domains,
        include_subdomains=args.subdomains,
        respect_robots=not args.no_robots,
        check_orphans=not args.no_orphan_check,
        exclude_patterns=args.exclude,
    )

    try:
        engine = CrawlEngine(config)
        engine.start()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report = CsvReport(args.output)
    issues = []
    finished = None
    try:
        while finished is None:
            try:
                event = engine.events.get(timeout=0.5)
            except queue.Empty:
                continue
            if isinstance(event, events.PageCrawled):
                report.add(event.result)
                issues.extend(event.issues)
                if not args.quiet:
                    r = event.result
                    status = r.status_code or "ERR"
                    print(f"[{event.stats.crawled}] {status} {r.url} ({r.elapsed_ms} ms)")
            elif isinstance(event, events.UrlSkipped) and not args.quiet:
                print(f"    skipped ({event.reason}): {event.url}")
            elif isinstance(event, events.CrawlFinished):
                finished = event
                issues.extend(event.issues)
    except KeyboardInterrupt:
        print("\nStopping...", file=sys.stderr)
        engine.stop()
        while finished is None:
            event = engine.events.get()
            if isinstance(event, events.PageCrawled):
                report.add(event.result)
                issues.extend(event.issues)
            elif isinstance(event, events.CrawlFinished):
                finished = event
                issues.extend(event.issues)
    finally:
        report.close()

    issues_path = issues_path_for(args.output)
    write_issues(issues_path, issues)

    s = finished.stats
    errors = sum(1 for i in issues if i.severity == "error")
    warnings = len(issues) - errors
    print(f"\nDone: {s.crawled} pages, {s.errors} fetch errors, "
          f"{s.bytes_downloaded / 1024:.1f} KiB.")
    print(f"Issues: {errors} errors, {warnings} warnings.")
    if not args.quiet:
        by_type = {}
        for issue in issues:
            by_type[issue.issue_type] = by_type.get(issue.issue_type, 0) + 1
        for issue_type, count in sorted(by_type.items(), key=lambda kv: -kv[1]):
            print(f"  {issue_type}: {count}")
    print(f"Reports: {args.output}, {issues_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
