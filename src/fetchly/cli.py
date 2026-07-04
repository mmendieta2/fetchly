"""Command-line front end."""

import argparse
import queue
import sys

from . import events
from .config import CrawlConfig
from .engine import CrawlEngine
from .report import CsvReport, issues_path_for, write_issues
from .sitemap import write_sitemap


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fetchly", description="Crawl a website and write a CSV report.")
    p.add_argument("url", nargs="?", help="Start URL (http:// or https://)")
    p.add_argument("--url-list", metavar="FILE",
                   help="Audit a fixed list of URLs (one per line) instead of crawling; "
                        "implies --all-domains and depth 0 unless overridden")
    p.add_argument("-o", "--output", default="fetchly_report.csv", help="CSV output path")
    p.add_argument("-n", "--max-pages", type=int, default=200)
    p.add_argument("-d", "--max-depth", type=int, default=None,
                   help="Link depth limit (default 5; 0 with --url-list)")
    p.add_argument("-w", "--workers", type=int, default=8)
    p.add_argument("--delay", type=float, default=0.0, help="Delay between requests per worker (s)")
    p.add_argument("--timeout", type=float, default=15.0)
    p.add_argument("--retries", type=int, default=2,
                   help="Extra attempts on connection errors and 429/5xx")
    p.add_argument("--subdomains", action="store_true", help="Also crawl subdomains")
    p.add_argument("--all-domains", action="store_true", help="Do not restrict to the start domain")
    p.add_argument("--no-robots", action="store_true", help="Ignore robots.txt")
    p.add_argument("--render-js", action="store_true",
                   help="Render pages with headless Chromium "
                        "(needs: pip install \"fetchly[js]\" && playwright install chromium)")
    p.add_argument("--no-orphan-check", action="store_true",
                   help="Skip the sitemap.xml orphan-page check")
    p.add_argument("--exclude", action="append", default=[], help="Skip URLs containing this substring (repeatable)")
    p.add_argument("--sitemap", metavar="FILE", help="Also generate an XML sitemap of indexable pages")
    p.add_argument("--graph", metavar="FILE",
                   help="Also generate a self-contained HTML link-graph visualization")
    p.add_argument("--extract", action="append", default=[], metavar="RULE",
                   help="Custom extraction: name=css:selector or name=re:pattern "
                        "(repeatable; adds a CSV column per rule)")
    p.add_argument("--segment", action="append", default=[], metavar="RULE",
                   help="Tag pages: name=substring or name=re:pattern (repeatable; "
                        "first match wins, adds a 'segment' CSV column)")
    p.add_argument("--robots-file", metavar="FILE",
                   help="Use a local robots.txt for every host instead of fetching "
                        "(test rule changes before deploying)")
    p.add_argument("--save", metavar="FILE", help="Save the full crawl to a .fetchly.json.gz")
    p.add_argument("--open", dest="open_file", metavar="FILE",
                   help="Reopen a saved crawl and re-export reports (no crawling)")
    p.add_argument("--login-url", metavar="URL",
                   help="Forms auth: POST this login URL once before crawling")
    p.add_argument("--login-field", action="append", default=[], metavar="K=V",
                   help="Forms auth form field (repeatable); use K=? to be prompted "
                        "without echo")
    p.add_argument("-q", "--quiet", action="store_true")
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.open_file:
        return reexport(args)

    login_data = {}
    for field in args.login_field:
        key, sep, value = field.partition("=")
        if not sep or not key:
            print(f"error: bad --login-field {field!r} (expected K=V)", file=sys.stderr)
            return 2
        if value == "?":
            import getpass
            value = getpass.getpass(f"{key}: ")
        login_data[key] = value

    seed_urls = []
    if args.url_list:
        try:
            with open(args.url_list, encoding="utf-8") as fh:
                listed = [line.strip() for line in fh if line.strip() and not line.startswith("#")]
        except OSError as exc:
            print(f"error: cannot read {args.url_list}: {exc}", file=sys.stderr)
            return 2
        if not listed:
            print(f"error: {args.url_list} contains no URLs", file=sys.stderr)
            return 2
        if not args.url:
            args.url = listed[0]
            seed_urls = listed[1:]
        else:
            seed_urls = listed
        args.all_domains = True
        if args.max_depth is None:
            args.max_depth = 0
    elif not args.url:
        parser.error("a start URL is required (or use --url-list FILE)")

    config = CrawlConfig(
        start_url=args.url,
        max_pages=args.max_pages,
        max_depth=args.max_depth if args.max_depth is not None else 5,
        seed_urls=seed_urls,
        num_workers=args.workers,
        delay_seconds=args.delay,
        timeout_seconds=args.timeout,
        max_retries=args.retries,
        same_domain_only=not args.all_domains,
        include_subdomains=args.subdomains,
        respect_robots=not args.no_robots,
        check_orphans=not args.no_orphan_check,
        exclude_patterns=args.exclude,
        extract_rules=args.extract,
        segment_rules=args.segment,
        robots_txt_file=args.robots_file or "",
        login_url=args.login_url or "",
        login_data=login_data,
        render_js=args.render_js,
    )

    try:
        engine = CrawlEngine(config)
        engine.start()
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        login_data.clear()  # drop credentials from memory once the session holds the cookies

    extract_names = [rule.split("=", 1)[0].strip() for rule in args.extract]
    report = CsvReport(args.output, extra_fields=extract_names)
    issues = []
    results = []
    finished = None
    try:
        while finished is None:
            try:
                event = engine.events.get(timeout=0.5)
            except queue.Empty:
                continue
            if isinstance(event, events.PageCrawled):
                report.add(event.result)
                results.append(event.result)
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
                results.append(event.result)
                issues.extend(event.issues)
            elif isinstance(event, events.CrawlFinished):
                finished = event
                issues.extend(event.issues)
    finally:
        report.close()

    issues_path = issues_path_for(args.output)
    write_issues(issues_path, issues)

    if args.save:
        from .session_io import save_crawl
        save_crawl(args.save, config, results, issues)
        print(f"Crawl saved: {args.save}")

    if args.segment:
        by_segment = {}
        for r in results:
            by_segment[r.segment or "(none)"] = by_segment.get(r.segment or "(none)", 0) + 1
        print("Segments: " + ", ".join(f"{k}={v}" for k, v in sorted(by_segment.items())))

    if args.sitemap:
        count = write_sitemap(args.sitemap, results)
        print(f"Sitemap: {args.sitemap} ({count} indexable URLs)")

    if args.graph:
        from .viz import write_graph
        count = write_graph(args.graph, results)
        print(f"Graph: {args.graph} ({count} nodes)")

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


def reexport(args) -> int:
    """--open: rebuild reports from a saved crawl without recrawling."""
    from .session_io import load_crawl
    try:
        config, results, issues = load_crawl(args.open_file)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: cannot open {args.open_file}: {exc}", file=sys.stderr)
        return 2

    extract_names = [rule.split("=", 1)[0].strip() for rule in config.extract_rules]
    from .report import write_report
    write_report(args.output, results, extra_fields=extract_names)
    issues_path = issues_path_for(args.output)
    write_issues(issues_path, issues)
    if args.sitemap:
        print(f"Sitemap: {args.sitemap} ({write_sitemap(args.sitemap, results)} URLs)")
    if args.graph:
        from .viz import write_graph
        print(f"Graph: {args.graph} ({write_graph(args.graph, results)} nodes)")
    print(f"Reopened crawl of {config.start_url}: {len(results)} pages, "
          f"{len(issues)} issues.\nReports: {args.output}, {issues_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
