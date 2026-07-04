"""CSV report writers for pages and issues."""

import csv
import os

from .audit import Issue
from .models import PageResult


class CsvReport:
    """Incremental CSV writer so results survive an interrupted crawl."""

    def __init__(self, path: str):
        self.path = path
        self._file = open(path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=PageResult.CSV_FIELDS)
        self._writer.writeheader()

    def add(self, result: PageResult) -> None:
        self._writer.writerow(result.as_row())

    def close(self) -> None:
        self._file.close()


def write_report(path: str, results: "list[PageResult]") -> None:
    report = CsvReport(path)
    try:
        for r in results:
            report.add(r)
    finally:
        report.close()


def issues_path_for(report_path: str) -> str:
    """fetchly_report.csv -> fetchly_report_issues.csv"""
    stem, ext = os.path.splitext(report_path)
    return f"{stem}_issues{ext or '.csv'}"


def write_issues(path: str, issues: "list[Issue]") -> None:
    order = {"error": 0, "warning": 1}
    ranked = sorted(issues, key=lambda i: (order.get(i.severity, 2), i.issue_type, i.page_url))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=Issue.CSV_FIELDS)
        writer.writeheader()
        for issue in ranked:
            writer.writerow(issue.as_row())
