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
| `--subdomains` | crawl subdomains too | off |
| `--all-domains` | no domain restriction | off |
| `--no-robots` | ignore robots.txt | off |
| `--exclude STR` | skip URLs containing STR (repeatable) | — |

## CSV report columns

`url, status_code, ok, depth, found_on, content_type, content_length, title,
meta_description, canonical_url, h1_count, word_count, elapsed_ms,
redirected_to, links_found, internal_links, external_links, image_count,
images_missing_alt, error`

`found_on` is the page where the URL was discovered — for a 404 row it tells
you which page holds the broken link. Internal/external link counts treat the
start domain and all its subdomains as internal.

## Platform notes

- **Windows 10/11**: python.org installers include Tkinter; the GUI sets
  HiDPI awareness via `SetProcessDpiAwareness`.
- **macOS**: python.org builds bundle Tk 8.6. Homebrew: `brew install python-tk`.
- **Linux**: install the Tk package if missing, e.g. `sudo apt install python3-tk`
  or `sudo pacman -S tk`.

Only crawl sites you own or have permission to crawl, and keep `--delay` and
worker counts considerate on servers you don't control.
