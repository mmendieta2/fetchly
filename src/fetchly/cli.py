"""Command-line front end."""

import argparse
import queue
import sys

from . import events
from .config import CrawlConfig
from .engine import CrawlEngine
from .report import CsvReport


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fetchly", description="Crawl a website and write a CSV report.")
    p.add_argument("url", help="Start URL (http:// or https://)")
    p.add_argument("-o", "--output", default="fetchly_report.csv", help="CSV output path")
    p.add_argument("-n", "--max-pages", type=int, default=200)
    p.add_argument("-d", "--max-depth", type=int, default=5)
    p.add_argument("-w", "--workers", type=int, default=8)
    p.add_argument("--delay", type=float, default=0.0, help="Delay between requests per worker (s)")
    p.add_argument("--timeout", type=float, default=15.0)
    p.add_argument("--subdomains", action="store_true", help="Also crawl subdomains")
    p.add_argument("--all-domains", action="store_true", help="Do not restrict to the start domain")
    p.add_argument("--no-robots", action="store_true", help="Ignore robots.txt")
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
        same_domain_only=not args.all_domains,
        include_subdomains=args.subdomains,
        respect_robots=not args.no_robots,
        exclude_patterns=args.exclude,
    )

    try:
        engine = CrawlEngine(config)
        engine.start()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report = CsvReport(args.output)
    finished = None
    try:
        while finished is None:
            try:
                event = engine.events.get(timeout=0.5)
            except queue.Empty:
                continue
            if isinstance(event, events.PageCrawled):
                report.add(event.result)
                if not args.quiet:
                    r = event.result
                    status = r.status_code or "ERR"
                    print(f"[{event.stats.crawled}] {status} {r.url} ({r.elapsed_ms} ms)")
            elif isinstance(event, events.UrlSkipped) and not args.quiet:
                print(f"    skipped ({event.reason}): {event.url}")
            elif isinstance(event, events.CrawlFinished):
                finished = event
    except KeyboardInterrupt:
        print("\nStopping...", file=sys.stderr)
        engine.stop()
        while finished is None:
            event = engine.events.get()
            if isinstance(event, events.PageCrawled):
                report.add(event.result)
            elif isinstance(event, events.CrawlFinished):
                finished = event
    finally:
        report.close()

    s = finished.stats
    print(f"\nDone: {s.crawled} pages, {s.errors} errors, "
          f"{s.bytes_downloaded / 1024:.1f} KiB. Report: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
