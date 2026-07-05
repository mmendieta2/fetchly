"""Crawl engine: a threaded worker pool with no UI dependencies.

Front ends construct a CrawlEngine with a CrawlConfig, call start(), and
drain `engine.events` (a queue.Queue of objects from fetchly.events).
stop() requests a graceful shutdown; workers finish their current page.
"""

import os
import queue
import threading
import time

from . import events
import re as _re

from .audit import (SLOW_PAGE_MS, SLOW_PAGE_MS_JS, Issue, audit_page,
                    find_duplicates, find_hreflang_issues,
                    find_near_duplicates, find_orphans)
from .config import CrawlConfig
from .fetcher import Fetcher
from .frontier import Frontier
from .models import CrawlStats
from .parser import parse_extract_rules, parse_page
from .robots import RobotsCache
from .sitemap import fetch_sitemap_urls


class CrawlEngine:
    def __init__(self, config: CrawlConfig):
        config.validate()
        self.config = config
        self.events: "queue.Queue" = queue.Queue()

        self._work: "queue.Queue" = queue.Queue()   # (url, depth, found_on)
        self._frontier = Frontier(config)

        for flag, name in ((config.mobile_checks, "mobile usability checks"),
                           (config.a11y_checks, "accessibility checks"),
                           (config.js_snippets, "custom JS snippets")):
            if flag and not config.render_js:
                raise ValueError(f"{name} require JS rendering (--render-js)")

        if config.render_js:
            if config.login_url:
                raise ValueError("forms authentication is not yet supported with JS rendering")
            from .jsfetch import JsFetcher  # deferred: optional playwright dependency
            self._fetcher = JsFetcher(config, snippets=self._load_snippets(config),
                                      axe_source=self._load_axe(config))
        else:
            self._fetcher = Fetcher(config)

        self._spell_dictionary = self._load_dictionary(config)

        robots_override = ""
        if config.robots_txt_file:
            try:
                with open(config.robots_txt_file, encoding="utf-8") as fh:
                    robots_override = fh.read()
            except OSError as exc:
                raise ValueError(f"cannot read robots file: {exc}")
        self._robots = (RobotsCache(config.user_agent, override_text=robots_override,
                                    session=self._fetcher.session)
                        if config.respect_robots else None)
        self._extract_rules = parse_extract_rules(config.extract_rules)  # ValueError if malformed
        self._segment_rules = self._parse_segment_rules(config.segment_rules)
        self._stats = CrawlStats()
        self._results = []  # retained for site-level checks (duplicates)
        self._blocked = []  # blocked_by_robots issues (no PageResult to attach to)
        self._stats_lock = threading.Lock()
        self._stop = threading.Event()
        self._pages_claimed = 0
        self._in_flight = 0
        self._state_lock = threading.Lock()
        self._threads: "list[threading.Thread]" = []

    @staticmethod
    def _load_snippets(config) -> dict:
        snippets = {}
        for spec in config.js_snippets:
            name, sep, path = spec.partition("=")
            if not sep or not name.strip() or not path:
                raise ValueError(f"bad JS snippet {spec!r} (expected name=path.js)")
            try:
                with open(path, encoding="utf-8") as fh:
                    snippets[name.strip()] = fh.read()
            except OSError as exc:
                raise ValueError(f"cannot read JS snippet: {exc}")
        return snippets

    @staticmethod
    def _load_axe(config) -> str:
        if not config.a11y_checks:
            return ""
        path = os.path.join(os.path.dirname(__file__), "vendor", "axe.min.js")
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            raise ValueError(f"axe-core not found ({exc}); reinstall fetchly")

    @staticmethod
    def _load_dictionary(config):
        if not config.spellcheck:
            return None
        path = config.dictionary_file or "/usr/share/dict/words"
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                return {line.strip().lower() for line in fh if line.strip()}
        except OSError:
            default = not config.dictionary_file
            raise ValueError(
                f"Spellcheck could not read a word list at '{path}'.\n\n"
                + ("No system dictionary is installed. Install one "
                   "(e.g. `sudo pacman -S words`), or choose a word-list file "
                   "in the Dictionary field / with --dictionary."
                   if default else
                   "Check the Dictionary path (it must be a text file with one "
                   "word per line)."))

    @staticmethod
    def _parse_segment_rules(specs):
        rules = []
        for spec in specs:
            name, sep, pattern = spec.partition("=")
            if not sep or not name.strip() or not pattern:
                raise ValueError(f"bad segment rule {spec!r} (expected name=substring or name=re:pattern)")
            if pattern.startswith("re:"):
                try:
                    matcher = _re.compile(pattern[3:]).search
                except _re.error as exc:
                    raise ValueError(f"bad regex in segment rule {spec!r}: {exc}")
            else:
                matcher = lambda url, _p=pattern: _p in url
            rules.append((name.strip(), matcher))
        return rules

    def _segment_for(self, url: str) -> str:
        for name, matcher in self._segment_rules:
            if matcher(url):
                return name
        return ""

    # -- public API ---------------------------------------------------------

    def start(self) -> None:
        start_url = self._frontier.admit(self.config.start_url)
        if not start_url:
            raise ValueError(f"Start URL is out of scope: {self.config.start_url}")
        self._work.put((start_url, 0, ""))
        for seed in self.config.seed_urls:
            admitted = self._frontier.admit(seed)
            if admitted:
                self._work.put((admitted, 0, ""))
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
                self._blocked.append(Issue(
                    url, "blocked_by_robots", "error",
                    "not read — disallowed by robots.txt"
                    + (f" (linked from {found_on})" if found_on else " (start URL)")))
            self.events.put(events.UrlSkipped(url=url, reason="robots.txt"))
            return

        if self.config.delay_seconds > 0:
            time.sleep(self.config.delay_seconds)

        result, body = self._fetcher.fetch(url, depth)
        result.found_on = found_on
        result.segment = self._segment_for(url)

        parsed = None
        if body:
            base = result.redirected_to or url
            parsed = parse_page(base, body, self._extract_rules,
                                spell_dictionary=self._spell_dictionary)
            self._apply_parsed(result, parsed)
            if depth < self.config.max_depth and not self._stop.is_set():
                for link in parsed.links:
                    admitted = self._frontier.admit(link)
                    if admitted:
                        self._work.put((admitted, depth + 1, url))
                if parsed.amp_url:  # crawl the AMP variant too
                    admitted = self._frontier.admit(parsed.amp_url)
                    if admitted:
                        self._work.put((admitted, depth + 1, url))

        with self._stats_lock:
            self._stats.record(result)
            self._results.append(result)
            self._stats.queued = self._work.qsize()
            snapshot = CrawlStats(**vars(self._stats))
        slow_ms = SLOW_PAGE_MS_JS if self.config.render_js else SLOW_PAGE_MS
        self.events.put(events.PageCrawled(
            result=result, stats=snapshot,
            issues=audit_page(result, parsed, slow_ms=slow_ms)))

    def _apply_parsed(self, result, parsed) -> None:
        result.title = parsed.title
        result.links_found = len(parsed.links)
        result.meta_description = parsed.meta_description
        result.canonical_url = parsed.canonical_url
        result.h1_count = parsed.h1_count
        result.image_count = parsed.image_count
        result.images_missing_alt = parsed.images_missing_alt
        result.word_count = parsed.word_count
        result.meta_robots = parsed.meta_robots
        result.content_hash = parsed.content_hash
        result.simhash = parsed.simhash
        result.hreflang = parsed.hreflang
        result.hreflang_count = len(parsed.hreflang)
        result.schema_types = "|".join(parsed.schema_types)
        result.schema_errors = parsed.schema_errors
        result.amp_url = parsed.amp_url
        result.is_amp = parsed.is_amp
        result.extracted.update(parsed.extracted)
        result.misspellings = ", ".join(parsed.misspellings)
        result.misspell_count = len(parsed.misspellings)
        for link in parsed.links:
            if self._frontier.same_site(link):
                result.internal_links += 1
            else:
                result.external_links += 1

    def _supervisor(self) -> None:
        for t in self._threads:
            t.join()
        stopped_early = self._stop.is_set()

        with self._stats_lock:
            site_issues = find_duplicates(self._results)
            site_issues.extend(find_near_duplicates(self._results))
            site_issues.extend(find_hreflang_issues(self._results))
            site_issues.extend(self._blocked)
            crawled = self._stats.crawled

        # Orphan check: only meaningful when the crawl actually saw the site.
        # Skip it when nothing was crawled (every sitemap URL would look
        # orphaned) or when a truncated crawl would report false orphans.
        if self.config.check_orphans and not stopped_early and crawled > 0:
            sitemap_urls = fetch_sitemap_urls(self._fetcher.session, self.config.start_url,
                                              timeout=self.config.timeout_seconds)
            site_issues.extend(find_orphans(sitemap_urls, self._frontier))

        self._fetcher.close()
        with self._stats_lock:
            snapshot = CrawlStats(**vars(self._stats))
        self.events.put(events.CrawlFinished(
            stats=snapshot,
            stopped_by_user=stopped_early and self._pages_claimed < self.config.max_pages,
            issues=site_issues,
        ))
