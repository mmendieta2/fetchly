"""CSV report writer."""

import csv

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
