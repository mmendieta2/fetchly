"""Data models produced by the crawl engine."""

from dataclasses import dataclass, field


@dataclass
class PageResult:
    url: str
    status_code: int = 0
    ok: bool = False
    depth: int = 0
    content_type: str = ""
    content_length: int = 0
    title: str = ""
    elapsed_ms: float = 0.0
    redirected_to: str = ""
    links_found: int = 0
    error: str = ""
    found_on: str = ""  # page where this URL was discovered
    meta_description: str = ""
    canonical_url: str = ""
    meta_robots: str = ""
    x_robots_tag: str = ""
    redirect_hops: int = 0
    redirect_type: str = ""  # "permanent" | "temporary" | ""
    h1_count: int = 0
    internal_links: int = 0
    external_links: int = 0
    image_count: int = 0
    images_missing_alt: int = 0
    word_count: int = 0
    content_hash: str = ""
    simhash: int = 0             # 64-bit near-duplicate fingerprint
    segment: str = ""            # first matching segment rule name
    hreflang_count: int = 0
    hreflang: list = field(default_factory=list)  # (lang, url) pairs; not a CSV column
    schema_types: str = ""       # "|"-joined JSON-LD @type values
    schema_errors: int = 0       # unparseable JSON-LD blocks
    amp_url: str = ""            # <link rel="amphtml"> target
    is_amp: bool = False         # <html amp> / <html ⚡> page
    extracted: dict = field(default_factory=dict)  # custom-extraction values, extra CSV columns

    CSV_FIELDS = (
        "url", "status_code", "ok", "depth", "found_on", "segment",
        "content_type", "content_length", "title", "meta_description",
        "canonical_url", "meta_robots", "x_robots_tag", "h1_count",
        "word_count", "content_hash", "simhash", "hreflang_count",
        "schema_types", "schema_errors", "amp_url", "is_amp", "elapsed_ms",
        "redirected_to", "redirect_hops", "redirect_type", "links_found",
        "internal_links", "external_links", "image_count",
        "images_missing_alt", "error",
    )

    def as_row(self) -> dict:
        row = {f: getattr(self, f) for f in self.CSV_FIELDS}
        row.update(self.extracted)
        return row


@dataclass
class CrawlStats:
    crawled: int = 0
    queued: int = 0
    errors: int = 0
    skipped: int = 0
    bytes_downloaded: int = 0
    status_counts: dict = field(default_factory=dict)

    def record(self, result: PageResult) -> None:
        self.crawled += 1
        self.bytes_downloaded += result.content_length
        if result.error:
            self.errors += 1
        key = str(result.status_code) if result.status_code else "ERR"
        self.status_counts[key] = self.status_counts.get(key, 0) + 1
