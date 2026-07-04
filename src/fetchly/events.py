"""Events emitted by the crawl engine.

The engine pushes these onto a thread-safe queue; front ends (CLI, GUI)
drain the queue on their own schedule. This keeps the engine free of any
UI dependency and keeps Tkinter calls on the main thread.
"""

from dataclasses import dataclass, field

from .models import CrawlStats, PageResult


@dataclass
class CrawlStarted:
    start_url: str


@dataclass
class PageCrawled:
    result: PageResult
    stats: CrawlStats
    issues: list = field(default_factory=list)  # audit.Issue for this page


@dataclass
class UrlSkipped:
    url: str
    reason: str


@dataclass
class CrawlFinished:
    stats: CrawlStats
    stopped_by_user: bool = False
    fatal_error: str = ""
    issues: list = field(default_factory=list)  # site-level issues (orphan pages)
