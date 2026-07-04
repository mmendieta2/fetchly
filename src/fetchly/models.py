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

    CSV_FIELDS = (
        "url", "status_code", "ok", "depth", "content_type",
        "content_length", "title", "elapsed_ms", "redirected_to",
        "links_found", "error",
    )

    def as_row(self) -> dict:
        return {f: getattr(self, f) for f in self.CSV_FIELDS}


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
