"""Crawl configuration shared by the CLI and GUI front ends."""

from dataclasses import dataclass, field


@dataclass
class CrawlConfig:
    start_url: str
    max_pages: int = 200
    max_depth: int = 5
    num_workers: int = 8
    delay_seconds: float = 0.0
    timeout_seconds: float = 15.0
    max_retries: int = 2          # extra attempts on connection errors / 429 / 5xx
    retry_backoff_seconds: float = 0.5  # doubled after each failed attempt
    same_domain_only: bool = True
    include_subdomains: bool = False
    respect_robots: bool = True
    check_orphans: bool = True    # compare sitemap.xml against discovered URLs
    follow_redirects: bool = True
    user_agent: str = "FetchlyBot/0.1 (+https://github.com/fetchly)"
    exclude_patterns: list = field(default_factory=list)  # substrings to skip

    def validate(self) -> None:
        if not self.start_url.startswith(("http://", "https://")):
            raise ValueError("Start URL must begin with http:// or https://")
        if self.max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        if self.num_workers < 1:
            raise ValueError("num_workers must be at least 1")
