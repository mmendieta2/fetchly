"""Audit checks: turn crawl data into a list of actionable issues."""

from dataclasses import dataclass

from .models import PageResult
from .parser import ParsedPage

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

_MAX_DETAIL_ITEMS = 5


@dataclass
class Issue:
    page_url: str
    issue_type: str
    severity: str
    detail: str

    CSV_FIELDS = ("severity", "issue_type", "page_url", "detail")

    def as_row(self) -> dict:
        return {f: getattr(self, f) for f in self.CSV_FIELDS}


def _summarize(items: "list[str]") -> str:
    shown = ", ".join(items[:_MAX_DETAIL_ITEMS])
    extra = len(items) - _MAX_DETAIL_ITEMS
    return shown + (f" (+{extra} more)" if extra > 0 else "")


def audit_page(result: PageResult, parsed: "ParsedPage | None") -> "list[Issue]":
    """Checks that can be decided from a single page."""
    issues = []

    if result.error:
        issues.append(Issue(result.url, "fetch_error", SEVERITY_ERROR, result.error))
        return issues
    if result.status_code >= 400:
        where = f"linked from {result.found_on}" if result.found_on else "start URL"
        issues.append(Issue(result.url, "broken_link", SEVERITY_ERROR,
                            f"HTTP {result.status_code}, {where}"))
        return issues  # error pages aren't judged on content quality

    if parsed is None:
        return issues

    if parsed.mixed_content:
        issues.append(Issue(result.url, "mixed_content", SEVERITY_ERROR,
                            f"{len(parsed.mixed_content)} insecure resource(s): "
                            + _summarize(parsed.mixed_content)))
    if parsed.missing_alt_srcs:
        issues.append(Issue(result.url, "images_missing_alt", SEVERITY_WARNING,
                            f"{len(parsed.missing_alt_srcs)} image(s) without alt text: "
                            + _summarize(parsed.missing_alt_srcs)))
    if not parsed.title:
        issues.append(Issue(result.url, "missing_title", SEVERITY_WARNING, "page has no <title>"))
    if not parsed.meta_description:
        issues.append(Issue(result.url, "missing_meta_description", SEVERITY_WARNING,
                            "page has no meta description"))
    if parsed.h1_count == 0:
        issues.append(Issue(result.url, "missing_h1", SEVERITY_WARNING, "page has no <h1>"))
    elif parsed.h1_count > 1:
        issues.append(Issue(result.url, "multiple_h1", SEVERITY_WARNING,
                            f"page has {parsed.h1_count} <h1> tags"))
    return issues


def find_orphans(sitemap_urls: "list[str]", frontier) -> "list[Issue]":
    """Pages listed in the sitemap that no crawled page links to."""
    issues = []
    for url in sitemap_urls:
        admitted = frontier.admit(url)
        if admitted:  # in scope but never discovered during the crawl
            issues.append(Issue(admitted, "orphan_page", SEVERITY_WARNING,
                                "listed in sitemap.xml but not linked from any crawled page"))
    return issues
