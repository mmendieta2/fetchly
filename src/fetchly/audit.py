"""Audit checks: turn crawl data into a list of actionable issues."""

from dataclasses import dataclass

from .frontier import normalize
from .models import PageResult
from .parser import ParsedPage

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

_MAX_DETAIL_ITEMS = 5

# SEO thresholds (characters for title/meta, words for thin content).
TITLE_MIN, TITLE_MAX = 30, 60
META_DESC_MIN, META_DESC_MAX = 70, 155
THIN_CONTENT_WORDS = 200


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
        issue_type = "redirect_loop" if "TooManyRedirects" in result.error else "fetch_error"
        issues.append(Issue(result.url, issue_type, SEVERITY_ERROR, result.error))
        return issues
    if result.status_code >= 400:
        where = f"linked from {result.found_on}" if result.found_on else "start URL"
        issues.append(Issue(result.url, "broken_link", SEVERITY_ERROR,
                            f"HTTP {result.status_code}, {where}"))
        return issues  # error pages aren't judged on content quality

    if result.redirect_hops >= 2:
        issues.append(Issue(result.url, "redirect_chain", SEVERITY_WARNING,
                            f"{result.redirect_hops} hops to reach {result.redirected_to}"))
    elif result.redirect_hops == 1 and result.redirect_type == "temporary":
        issues.append(Issue(result.url, "temporary_redirect", SEVERITY_WARNING,
                            f"302/303/307 redirect to {result.redirected_to}"))

    directives = f"{result.meta_robots} {result.x_robots_tag}"
    if "noindex" in directives:
        issues.append(Issue(result.url, "noindex", SEVERITY_WARNING,
                            "page excluded from search indexes "
                            f"(meta robots: {result.meta_robots or '-'}, "
                            f"X-Robots-Tag: {result.x_robots_tag or '-'})"))

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
    elif len(parsed.title) > TITLE_MAX:
        issues.append(Issue(result.url, "title_too_long", SEVERITY_WARNING,
                            f"{len(parsed.title)} chars (recommended <= {TITLE_MAX}): {parsed.title[:80]}"))
    elif len(parsed.title) < TITLE_MIN:
        issues.append(Issue(result.url, "title_too_short", SEVERITY_WARNING,
                            f"{len(parsed.title)} chars (recommended >= {TITLE_MIN}): {parsed.title}"))
    if not parsed.meta_description:
        issues.append(Issue(result.url, "missing_meta_description", SEVERITY_WARNING,
                            "page has no meta description"))
    elif len(parsed.meta_description) > META_DESC_MAX:
        issues.append(Issue(result.url, "meta_description_too_long", SEVERITY_WARNING,
                            f"{len(parsed.meta_description)} chars (recommended <= {META_DESC_MAX})"))
    elif len(parsed.meta_description) < META_DESC_MIN:
        issues.append(Issue(result.url, "meta_description_too_short", SEVERITY_WARNING,
                            f"{len(parsed.meta_description)} chars (recommended >= {META_DESC_MIN})"))
    if parsed.h1_count == 0:
        issues.append(Issue(result.url, "missing_h1", SEVERITY_WARNING, "page has no <h1>"))
    elif parsed.h1_count > 1:
        issues.append(Issue(result.url, "multiple_h1", SEVERITY_WARNING,
                            f"page has {parsed.h1_count} <h1> tags"))
    if 0 < parsed.word_count < THIN_CONTENT_WORDS:
        issues.append(Issue(result.url, "thin_content", SEVERITY_WARNING,
                            f"only {parsed.word_count} words (threshold {THIN_CONTENT_WORDS})"))
    if parsed.canonical_url:
        final_url = result.redirected_to or result.url
        if normalize(parsed.canonical_url) != normalize(final_url):
            issues.append(Issue(result.url, "canonical_mismatch", SEVERITY_WARNING,
                                f"canonical points to {parsed.canonical_url}"))
    return issues


def find_duplicates(results: "list[PageResult]") -> "list[Issue]":
    """Site-level: titles, meta descriptions, and body content shared by 2+ pages."""
    checks = (
        ("duplicate_title", lambda r: r.title, "title"),
        ("duplicate_meta_description", lambda r: r.meta_description, "meta description"),
        ("duplicate_content", lambda r: r.content_hash, "body content (md5 match)"),
    )
    pages = [r for r in results if r.ok and not r.redirected_to]
    issues = []
    for issue_type, key, label in checks:
        groups = {}
        for r in pages:
            value = key(r)
            if value:
                groups.setdefault(value, []).append(r.url)
        for value, urls in groups.items():
            if len(urls) > 1:
                issues.append(Issue(urls[0], issue_type, SEVERITY_WARNING,
                                    f"same {label} on {len(urls)} pages: " + _summarize(urls)))
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
