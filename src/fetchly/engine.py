"""Crawl engine: a threaded worker pool with no UI dependencies.

Front ends construct a CrawlEngine with a CrawlConfig, call start(), and
drain `engine.events` (a queue.Queue of objects from fetchly.events).
stop() requests a graceful shutdown; workers finish their current page.
"""

import queue
import threading
import time

from . import events
from .audit import audit_page, find_orphans
from .config import CrawlConfig
from .fetcher import Fetcher
from .frontier import Frontier
from .models import CrawlStats
from .parser import parse_page
from .robots import RobotsCache
from .sitemap import fetch_sitemap_urls


class CrawlEngine:
    def __init__(self, config: CrawlConfig):
        config.validate()
        self.config = config
        self.events: "queue.Queue" = queue.Queue()

        self._work: "queue.Queue" = queue.Queue()   # (url, depth, found_on)
        self._frontier = Frontier(config)
        self._fetcher = Fetcher(config)
        self._robots = RobotsCache(config.user_agent) if config.respect_robots else None
        self._stats = CrawlStats()
        self._stats_lock = threading.Lock()
        self._stop = threading.Event()
        self._pages_claimed = 0
        self._in_flight = 0
        self._state_lock = threading.Lock()
        self._threads: "list[threading.Thread]" = []

    # -- public API ---------------------------------------------------------

    def start(self) -> None:
        start_url = self._frontier.admit(self.config.start_url)
        if not start_url:
            raise ValueError(f"Start URL is out of scope: {self.config.start_url}")
        self._work.put((start_url, 0, ""))
        self.events.put(events.CrawlStarted(start_url=start_url))
        for i in range(self.config.num_workers):
            t = threading.Thread(target=self._worker, name=f"fetchly-{i}", daemon=True)
            t.start()
            self._threads.append(t)
        threading.Thread(target=self._supervisor, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    # -- internals ----------------------------------------------------------

    def _claim_page_slot(self) -> bool:
        with self._state_lock:
            if self._pages_claimed >= self.config.max_pages:
                return False
            self._pages_claimed += 1
            return True

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                url, depth, found_on = self._work.get(timeout=0.25)
            except queue.Empty:
                with self._state_lock:
                    if self._in_flight == 0 and self._work.empty():
                        return
                continue

            with self._state_lock:
                self._in_flight += 1
            try:
                self._process(url, depth, found_on)
            finally:
                with self._state_lock:
                    self._in_flight -= 1
                self._work.task_done()

    def _process(self, url: str, depth: int, found_on: str) -> None:
        if not self._claim_page_slot():
            self._stop.set()
            return

        if self._robots and not self._robots.allowed(url):
            with self._stats_lock:
                self._stats.skipped += 1
            self.events.put(events.UrlSkipped(url=url, reason="robots.txt"))
            return

        if self.config.delay_seconds > 0:
            time.sleep(self.config.delay_seconds)

        result, body = self._fetcher.fetch(url, depth)
        result.found_on = found_on

        parsed = None
        if body:
            base = result.redirected_to or url
            parsed = parse_page(base, body)
            self._apply_parsed(result, parsed)
            if depth < self.config.max_depth and not self._stop.is_set():
                for link in parsed.links:
                    admitted = self._frontier.admit(link)
                    if admitted:
                        self._work.put((admitted, depth + 1, url))

        with self._stats_lock:
            self._stats.record(result)
            self._stats.queued = self._work.qsize()
            snapshot = CrawlStats(**vars(self._stats))
        self.events.put(events.PageCrawled(
            result=result, stats=snapshot, issues=audit_page(result, parsed)))

    def _apply_parsed(self, result, parsed) -> None:
        result.title = parsed.title
        result.links_found = len(parsed.links)
        result.meta_description = parsed.meta_description
        result.canonical_url = parsed.canonical_url
        result.h1_count = parsed.h1_count
        result.image_count = parsed.image_count
        result.images_missing_alt = parsed.images_missing_alt
        result.word_count = parsed.word_count
        for link in parsed.links:
            if self._frontier.same_site(link):
                result.internal_links += 1
            else:
                result.external_links += 1

    def _supervisor(self) -> None:
        for t in self._threads:
            t.join()
        stopped_early = self._stop.is_set()

        # Orphan check: only meaningful when the crawl saw the whole site;
        # a truncated crawl would report false orphans.
        site_issues = []
        if self.config.check_orphans and not stopped_early:
            sitemap_urls = fetch_sitemap_urls(self._fetcher.session, self.config.start_url,
                                              timeout=self.config.timeout_seconds)
            site_issues = find_orphans(sitemap_urls, self._frontier)

        self._fetcher.close()
        with self._stats_lock:
            snapshot = CrawlStats(**vars(self._stats))
        self.events.put(events.CrawlFinished(
            stats=snapshot,
            stopped_by_user=stopped_early and self._pages_claimed < self.config.max_pages,
            issues=site_issues,
        ))
