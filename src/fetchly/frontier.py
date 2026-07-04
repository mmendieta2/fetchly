"""URL frontier: scope filtering, normalization, and dedupe."""

from urllib.parse import urldefrag, urlparse, urlunparse

from .config import CrawlConfig

_SKIP_SCHEMES = ("mailto:", "javascript:", "tel:", "data:", "ftp:")
_SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".css", ".js", ".mjs", ".woff", ".woff2", ".ttf", ".eot",
    ".pdf", ".zip", ".gz", ".tar", ".rar", ".7z",
    ".mp3", ".mp4", ".avi", ".mov", ".webm", ".wav",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
)


def normalize(url: str) -> str:
    """Strip fragments, lowercase scheme/host, drop default ports."""
    url, _ = urldefrag(url)
    parts = urlparse(url)
    netloc = parts.netloc.lower()
    if netloc.endswith(":80") and parts.scheme == "http":
        netloc = netloc[:-3]
    elif netloc.endswith(":443") and parts.scheme == "https":
        netloc = netloc[:-4]
    path = parts.path or "/"
    return urlunparse((parts.scheme.lower(), netloc, path, parts.params, parts.query, ""))


class Frontier:
    """Decides which discovered URLs are worth crawling."""

    def __init__(self, config: CrawlConfig):
        self.config = config
        self._seen = set()
        start = urlparse(config.start_url)
        self._root_host = start.netloc.lower().split(":")[0]

    def in_scope(self, url: str) -> bool:
        lowered = url.lower()
        if lowered.startswith(_SKIP_SCHEMES):
            return False
        parts = urlparse(url)
        if parts.scheme not in ("http", "https"):
            return False
        path = parts.path.lower()
        if path.endswith(_SKIP_EXTENSIONS):
            return False
        for pattern in self.config.exclude_patterns:
            if pattern and pattern in url:
                return False
        if self.config.same_domain_only:
            host = parts.netloc.lower().split(":")[0]
            if self.config.include_subdomains:
                if host != self._root_host and not host.endswith("." + self._root_host):
                    return False
            elif host != self._root_host:
                return False
        return True

    def admit(self, url: str) -> str:
        """Return the normalized URL if new and in scope, else empty string."""
        norm = normalize(url)
        if norm in self._seen or not self.in_scope(norm):
            return ""
        self._seen.add(norm)
        return norm

    @property
    def seen_count(self) -> int:
        return len(self._seen)
