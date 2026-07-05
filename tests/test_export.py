"""Tests for the export naming convention and the per-issue-type ZIP export."""

import csv
import io
import zipfile
from datetime import datetime

from fetchly.audit import Issue
from fetchly.cli import main as cli_main
from fetchly.report import export_name, write_issues_zip

WHEN = datetime(2026, 7, 4, 9, 5)


def test_export_name_convention():
    name = export_name("https://www.example.com/some/path", "pages", ".csv", WHEN)
    assert name == "www.example.com-pages-2026-07-04-09h05.csv"


def test_export_name_falls_back_without_host():
    assert export_name("", "issues", ".zip", WHEN) == "site-issues-2026-07-04-09h05.zip"


def test_issues_zip_one_csv_per_type(tmp_path):
    issues = [
        Issue("http://a/x", "broken_link", "error", "404"),
        Issue("http://a/y", "broken_link", "error", "500"),
        Issue("http://a/x", "missing_title", "warning", "no title"),
    ]
    path = tmp_path / "issues.zip"
    count = write_issues_zip(str(path), issues, "https://example.com/", WHEN)
    assert count == 2

    with zipfile.ZipFile(path) as zf:
        names = sorted(zf.namelist())
        assert names == [
            "example.com-broken_link-2026-07-04-09h05.csv",
            "example.com-missing_title-2026-07-04-09h05.csv",
        ]
        rows = list(csv.DictReader(io.StringIO(zf.read(names[0]).decode("utf-8"))))
        assert len(rows) == 2
        assert {r["issue_type"] for r in rows} == {"broken_link"}
        assert rows[0]["page_url"] == "http://a/x"  # sorted by URL


def test_issues_zip_empty(tmp_path):
    path = tmp_path / "empty.zip"
    assert write_issues_zip(str(path), [], "https://example.com/", WHEN) == 0
    with zipfile.ZipFile(path) as zf:
        assert zf.namelist() == []


def test_cli_issues_zip_flag(test_site, tmp_path, capsys):
    out = tmp_path / "pages.csv"
    zip_path = tmp_path / "issues.zip"
    rc = cli_main([test_site, "-o", str(out), "--issues-zip", str(zip_path),
                   "-q", "--no-orphan-check"])
    assert rc == 0
    assert out.exists()
    with zipfile.ZipFile(zip_path) as zf:
        assert zf.namelist()  # the fixture site has known issues
        for name in zf.namelist():
            assert name.startswith("127.0.0.1-")


def test_with_scheme():
    from fetchly.config import with_scheme
    assert with_scheme("example.com") == "https://example.com"
    assert with_scheme("  example.com/path?q=1 ") == "https://example.com/path?q=1"
    assert with_scheme("http://example.com") == "http://example.com"
    assert with_scheme("https://example.com") == "https://example.com"
    assert with_scheme("") == ""
