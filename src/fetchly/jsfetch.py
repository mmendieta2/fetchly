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

# In-page mobile usability probe: viewport meta, small text, small tap targets.
# Sampling is capped so huge pages stay fast.
_MOBILE_JS = """() => {
  const out = {viewport: !!document.querySelector('meta[name="viewport"]'),
               small_text: 0, small_taps: 0};
  const els = document.querySelectorAll('p,span,li,td,a,button,label');
  let checked = 0;
  for (const el of els) {
    if (checked++ > 300) break;
    const style = getComputedStyle(el);
    if (el.innerText && el.innerText.trim() && parseFloat(style.fontSize) < 12)
      out.small_text++;
  }
  const taps = document.querySelectorAll('a,button,input,select,[onclick]');
  checked = 0;
  for (const el of taps) {
    if (checked++ > 300) break;
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && (r.width < 48 || r.height < 48))
      out.small_taps++;
  }
  return out;
}"""

_A11Y_JS = """() => axe.run(document, {resultTypes: ['violations']})
  .then(r => r.violations.map(v => ({id: v.id, impact: v.impact,
    description: v.description, nodes: v.nodes.length})))"""


class JsFetcher:
    def __init__(self, config: CrawlConfig, snippets=None, axe_source: str = ""):
        """snippets: {name: js_code} run per page into result.extracted;
        axe_source: axe-core JS injected when config.a11y_checks."""
        try:
            import playwright  # noqa: F401
        except ImportError:
            raise RuntimeError(_INSTALL_HINT)
        self.config = config
        self._snippets = snippets or {}
        self._axe_source = axe_source
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
            context_args = {"user_agent": self.config.user_agent}
            if self.config.mobile_checks:
                context_args.update(viewport={"width": 390, "height": 844},
                                    device_scale_factor=3, is_mobile=True,
                                    has_touch=True)
            context = browser.new_context(**context_args)
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
            if is_html and response.ok:
                self._run_page_checks(page, result)
                return result, body
            return result, ""
        except Exception as exc:
            detail = str(exc)
            if type(exc).__name__ == "TimeoutError":  # playwright's, not builtins'
                detail = (f"page did not finish loading within "
                          f"{self.config.timeout_seconds:g} s — the site may be "
                          "slow or overloaded; try raising the Timeout setting "
                          "(--timeout)")
            result.error = f"{type(exc).__name__}: {detail}"
            return result, ""
        finally:
            page.close()
            result.elapsed_ms = round((time.monotonic() - started) * 1000, 1)

    def _run_page_checks(self, page, result: PageResult) -> None:
        """Optional in-browser audits; failures degrade to notes, never crash."""
        for name, code in self._snippets.items():
            try:
                value = page.evaluate(code)
                result.extracted[name] = str(value)[:500] if value is not None else ""
            except Exception as exc:
                result.extracted[name] = f"(snippet error: {exc})"[:200]
        if self.config.mobile_checks:
            try:
                result.browser_checks["mobile"] = page.evaluate(_MOBILE_JS)
            except Exception:
                pass
        if self.config.a11y_checks and self._axe_source:
            try:
                page.add_script_tag(content=self._axe_source)
                result.browser_checks["a11y"] = page.evaluate(_A11Y_JS)
            except Exception:
                pass
