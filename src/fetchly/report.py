"""CSV report writers for pages and issues."""

import csv
import io
import os
import zipfile
from datetime import datetime
from urllib.parse import urlsplit

from .audit import Issue
from .models import PageResult


def export_name(start_url: str, report_type: str, ext: str, when=None) -> str:
    """Export naming convention: domain-reporttype-YYYY-MM-DD-HHhMM.ext"""
    host = urlsplit(start_url).hostname or "site"
    stamp = (when or datetime.now()).strftime("%Y-%m-%d-%Hh%M")
    return f"{host}-{report_type}-{stamp}{ext}"


class CsvReport:
    """Incremental CSV writer so results survive an interrupted crawl.

    extra_fields adds columns for custom-extraction rule names.
    """

    def __init__(self, path: str, extra_fields=()):
        self.path = path
        self._file = open(path, "w", newline="", encoding="utf-8")
        fieldnames = tuple(PageResult.CSV_FIELDS) + tuple(extra_fields)
        self._writer = csv.DictWriter(self._file, fieldnames=fieldnames, restval="")
        self._writer.writeheader()

    def add(self, result: PageResult) -> None:
        self._writer.writerow(result.as_row())

    def close(self) -> None:
        self._file.close()


def write_report(path: str, results: "list[PageResult]", extra_fields=()) -> None:
    report = CsvReport(path, extra_fields)
    try:
        for r in results:
            report.add(r)
    finally:
        report.close()


def issues_path_for(report_path: str) -> str:
    """fetchly_report.csv -> fetchly_report_issues.csv"""
    stem, ext = os.path.splitext(report_path)
    return f"{stem}_issues{ext or '.csv'}"


def write_issues_zip(path: str, issues: "list[Issue]", start_url: str = "",
                     when=None) -> int:
    """Zip archive with one CSV per issue type; returns the CSV count.

    Entry names follow the export naming convention (the issue type is the
    report type), all sharing one timestamp.
    """
    by_type = {}
    for issue in issues:
        by_type.setdefault(issue.issue_type, []).append(issue)
    when = when or datetime.now()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for issue_type in sorted(by_type):
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=Issue.CSV_FIELDS)
            writer.writeheader()
            for issue in sorted(by_type[issue_type], key=lambda i: i.page_url):
                writer.writerow(issue.as_row())
            zf.writestr(export_name(start_url, issue_type, ".csv", when),
                        buf.getvalue())
    return len(by_type)


def write_issues(path: str, issues: "list[Issue]") -> None:
    order = {"error": 0, "warning": 1}
    ranked = sorted(issues, key=lambda i: (order.get(i.severity, 2), i.issue_type, i.page_url))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=Issue.CSV_FIELDS)
        writer.writeheader()
        for issue in ranked:
            writer.writerow(issue.as_row())


def summarize(results, issues, stats) -> dict:
    """Compact crawl digest shared by the CLI printout and the MCP server.

    `issue_types` is ordered most-frequent first. Callers decide how much of it
    to show (the CLI prints all of it; the MCP tool keeps only the top few).
    """
    errors = sum(1 for i in issues if i.severity == "error")
    by_type = {}
    for issue in issues:
        by_type[issue.issue_type] = by_type.get(issue.issue_type, 0) + 1
    by_type = dict(sorted(by_type.items(), key=lambda kv: -kv[1]))
    return {
        "pages_crawled": stats.crawled,
        "fetch_errors": stats.errors,
        "kib_downloaded": round(stats.bytes_downloaded / 1024, 1),
        "issue_counts": {"error": errors, "warning": len(issues) - errors},
        "issue_types": by_type,
    }
