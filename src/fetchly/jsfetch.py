"""JavaScript-rendering fetcher backed by headless Chromium (Playwright).

Optional: requires `pip install "fetchly[js]"` then `playwright install
chromium`. Presents the same fetch(url, depth) -> (PageResult, body)
interface as fetcher.Fetcher, so the engine can swap it in transparently.

Playwright's sync API is greenlet-bound to the thread that created it, so
all browser work runs on one dedicated render thread; engine workers post
requests to it through a queue and block for their result. Rendering is
therefore serialized — one Chromium saturates most machines anyway.
"""

import queue
import threading
import time

import requests

from .config import CrawlConfig
from .models import PageResult

_INSTALL_HINT = ('JavaScript rendering requires Playwright: '
                 'pip install "fetchly[js]" && playwright install chromium')


class JsFetcher:
    def __init__(self, config: CrawlConfig):
        try:
            import playwright  # noqa: F401
        except ImportError:
            raise RuntimeError(_INSTALL_HINT)
        self.config = config
        # Plain HTTP session for non-rendered fetches (robots.txt, sitemap.xml).
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.user_agent})

        self._requests: "queue.Queue" = queue.Queue()
        self._init_error = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._render_loop,
                                        name="fetchly-render", daemon=True)
        self._thread.start()
        self._ready.wait()
        if self._init_error is not None:
            raise RuntimeError(f"could not launch Chromium ({self._init_error}); {_INSTALL_HINT}")

    def fetch(self, url: str, depth: int) -> "tuple[PageResult, str]":
        box, done = [], threading.Event()
        self._requests.put((url, depth, box, done))
        done.wait()
        return box[0], box[1]

    def close(self) -> None:
        self._requests.put(None)
        self._thread.join(timeout=15)
        self.session.close()

    # -- render thread -------------------------------------------------------

    def _render_loop(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(user_agent=self.config.user_agent)
        except Exception as exc:
            self._init_error = exc
            self._ready.set()
            return
        self._ready.set()
        while True:
            item = self._requests.get()
            if item is None:
                break
            url, depth, box, done = item
            try:
                result, body = self._render(context, url, depth)
            except Exception as exc:  # never leave a worker blocked
                result = PageResult(url=url, depth=depth,
                                    error=f"{type(exc).__name__}: {exc}")
                body = ""
            box.extend((result, body))
            done.set()
        for closer in (context.close, browser.close, pw.stop):
            try:
                closer()
            except Exception:
                pass

    def _render(self, context, url: str, depth: int) -> "tuple[PageResult, str]":
        result = PageResult(url=url, depth=depth)
        started = time.monotonic()
        page = context.new_page()
        try:
            response = page.goto(url, timeout=self.config.timeout_seconds * 1000,
                                 wait_until="load")
            if response is None:
                result.error = "no response (non-HTTP navigation)"
                return result, ""
            result.status_code = response.status
            result.ok = response.ok
            headers = response.headers
            result.content_type = headers.get("content-type", "").split(";")[0].strip()
            result.x_robots_tag = headers.get("x-robots-tag", "").lower()
            if page.url != url:
                result.redirected_to = page.url
            hops, request = 0, response.request
            while request.redirected_from is not None:
                hops += 1
                request = request.redirected_from
            result.redirect_hops = hops
            if hops:
                result.redirect_type = "permanent"  # chain statuses not exposed; best effort
            body = page.content()
            result.content_length = len(body.encode("utf-8", errors="replace"))
            is_html = result.content_type in ("text/html", "application/xhtml+xml", "")
            return result, (body if is_html and response.ok else "")
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            return result, ""
        finally:
            page.close()
            result.elapsed_ms = round((time.monotonic() - started) * 1000, 1)
