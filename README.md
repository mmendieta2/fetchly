# Fetchly

A cross-platform website crawler with both a CLI and a GUI, producing CSV reports.
Works on Windows 10/11, macOS, and Linux with plain CPython — the GUI uses Tkinter
(bundled with Python), and the only third-party dependencies are `requests` and
`beautifulsoup4`.

## Architecture

```
                 ┌──────────────────────────────┐
                 │          Front ends          │
                 │  cli.py          gui/app.py  │
                 │ (argparse)     (Tkinter+ttk) │
                 └───────┬──────────────┬───────┘
                         │  CrawlConfig │
                         ▼              ▼
                 ┌──────────────────────────────┐
   events.py ◄── │      engine.CrawlEngine      │  ── thread-safe event
 (queue.Queue)   │  worker thread pool + stop   │     queue back to UIs
                 └──┬───────┬────────┬──────┬───┘
                    ▼       ▼        ▼      ▼
              fetcher.py frontier.py robots.py parser.py
              (requests) (scope +    (robots   (bs4 links
               session)   dedupe)     cache)    + title)
                         │
                         ▼
                     report.py (CSV)
```

Design rules:

- **The engine has zero UI knowledge.** It emits `CrawlStarted`, `PageCrawled`,
  `UrlSkipped`, and `CrawlFinished` events onto a `queue.Queue`. The CLI blocks on
  the queue; the GUI drains it every 100 ms with Tk's `after()`, keeping all widget
  updates on the main thread.
- **Concurrency is a plain thread pool** (`num_workers` threads sharing a work
  queue). Workers exit when the queue is empty and nothing is in flight, or when
  the stop flag is set (Stop button / Ctrl-C / page limit).
- **Scope control lives in `Frontier`**: URL normalization (fragment stripping,
  default ports), dedupe, same-domain/subdomain policy, binary-extension and
  substring exclusions.
- **Politeness**: per-host robots.txt cache (fail-open), optional per-worker
  delay, identifying User-Agent, 5 MiB body cap.

## Install & run

```bash
pip install -e .

fetchly https://example.com -o report.csv -n 100   # CLI
fetchly-gui                                        # GUI
# or without installing entry points:
python -m fetchly.cli https://example.com
python -m fetchly.gui.app
```

### CLI options

| Flag | Meaning | Default |
|---|---|---|
| `-o/--output` | CSV report path | `fetchly_report.csv` |
| `-n/--max-pages` | page limit | 200 |
| `-d/--max-depth` | link depth limit | 5 |
| `-w/--workers` | concurrent workers | 8 |
| `--delay` | per-worker delay (s) | 0 |
| `--retries` | extra attempts on connection errors / 429 / 5xx | 2 |
| `--subdomains` | crawl subdomains too | off |
| `--all-domains` | no domain restriction | off |
| `--no-robots` | ignore robots.txt | off |
| `--exclude STR` | skip URLs containing STR (repeatable) | — |
| `--sitemap FILE` | also generate an XML sitemap of indexable pages | — |
| `--url-list FILE` | audit a fixed URL list (one per line) instead of crawling | — |
| `--no-orphan-check` | skip the sitemap orphan check | off |

`--url-list` is for site migrations: it fetches exactly the listed URLs
(depth 0, any domain) and reports status/redirect/audit data for each. The
GUI has an equivalent **Export Sitemap…** button after a crawl.

## CSV report columns

`url, status_code, ok, depth, found_on, content_type, content_length, title,
meta_description, canonical_url, h1_count, word_count, elapsed_ms,
redirected_to, links_found, internal_links, external_links, image_count,
images_missing_alt, error`

`found_on` is the page where the URL was discovered — for a 404 row it tells
you which page holds the broken link. Internal/external link counts treat the
start domain and all its subdomains as internal.

## Issues report

Alongside the page report, Fetchly writes `<output>_issues.csv`
(columns: `severity, issue_type, page_url, detail`, errors first) and shows
the same list in the GUI's **Issues** tab. Checks:

| Issue | Severity | Meaning |
|---|---|---|
| `broken_link` | error | 4xx/5xx page; detail names the page linking to it |
| `fetch_error` | error | connection failure/timeout after retries |
| `redirect_loop` | error | URL redirects to itself (or exceeds 30 hops) |
| `mixed_content` | error | `http://` scripts/images/styles on an `https://` page |
| `redirect_chain` | warning | 2+ hops to reach the final URL |
| `temporary_redirect` | warning | 302/303/307 where a 301 is usually intended |
| `images_missing_alt` | warning | `<img>` tags without alt text (srcs listed) |
| `missing_title` / `missing_meta_description` | warning | empty or absent tag |
| `title_too_short` / `title_too_long` | warning | outside 30–60 characters |
| `meta_description_too_short` / `_too_long` | warning | outside 70–155 characters |
| `missing_h1` / `multiple_h1` | warning | page has zero or 2+ `<h1>` |
| `thin_content` | warning | fewer than 200 words of visible text |
| `noindex` | warning | excluded from search via meta robots or X-Robots-Tag |
| `canonical_mismatch` | warning | rel=canonical points at a different URL |
| `duplicate_title` / `duplicate_meta_description` | warning | same value on 2+ pages |
| `duplicate_content` | warning | identical visible text (md5) on 2+ pages |
| `orphan_page` | warning | listed in `sitemap.xml` but not linked from any crawled page |

The orphan check fetches `/sitemap.xml` (sitemap indexes supported) after the
crawl finishes; it is skipped when the crawl was truncated by the page limit
or stopped early, since that would report false orphans. Disable it with
`--no-orphan-check`.

## Platform notes

- **Windows 10/11**: python.org installers include Tkinter; the GUI sets
  HiDPI awareness via `SetProcessDpiAwareness`.
- **macOS**: python.org builds bundle Tk 8.6. Homebrew: `brew install python-tk`.
- **Linux**: install the Tk package if missing, e.g. `sudo apt install python3-tk`
  or `sudo pacman -S tk`.

Only crawl sites you own or have permission to crawl, and keep `--delay` and
worker counts considerate on servers you don't control.
