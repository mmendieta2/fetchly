# Fetchly — Instructions for AI assistants

Read this file and `HANDOFF.md` first. Together they should give you enough
context to work without reading the whole codebase. Only open source files
listed as relevant to your current task.

## What this project is

Fetchly is a cross-platform website crawler (Windows 10/11, macOS, Linux) with
two front ends — a CLI and a Tkinter GUI — that produce CSV reports. The owner
uses it for local website auditing (including WordPress sites) with no SaaS
dependency. Python ≥ 3.9. Only third-party deps: `requests`, `beautifulsoup4`.
The GUI deliberately uses Tkinter (bundled with CPython) so nothing extra needs
installing or packaging.

## Codebase map (read only what you need)

All source lives in `src/fetchly/`. Sizes are approximate so you can judge
whether to read a file or trust this summary.

| File | Lines | Responsibility | Key API |
|---|---|---|---|
| `config.py` | ~40 | All crawl settings in one dataclass | `CrawlConfig(start_url, max_pages, max_depth, num_workers, delay_seconds, timeout_seconds, max_retries, retry_backoff_seconds, same_domain_only, include_subdomains, respect_robots, check_orphans, follow_redirects, user_agent, exclude_patterns, seed_urls)`, `.validate()` |
| `models.py` | ~70 | Result/stat dataclasses | `PageResult` (url, status_code, ok, depth, found_on, content_type, content_length, title, meta_description, canonical_url, meta_robots, x_robots_tag, redirect_hops, redirect_type, h1_count, internal_links, external_links, image_count, images_missing_alt, word_count, content_hash, elapsed_ms, redirected_to, links_found, error; `CSV_FIELDS`, `.as_row()`), `CrawlStats` (crawled, queued, errors, skipped, bytes_downloaded, status_counts; `.record(result)`) |
| `events.py` | ~45 | Engine→UI event dataclasses | `CrawlStarted(start_url)`, `PageCrawled(result, stats, issues)`, `UrlSkipped(url, reason)`, `CrawlFinished(stats, stopped_by_user, fatal_error, issues)` — per-page issues ride on PageCrawled; site-level (orphans) on CrawlFinished |
| `frontier.py` | ~85 | URL normalization, dedupe, scope policy | `normalize(url)`, `Frontier(config)`: `.admit(url) -> str` (normalized URL if new+in-scope, else `""`), `.in_scope(url)`, `.same_site(url)` (internal/external classification, subdomains always internal). Skips binary extensions, non-http schemes, excluded substrings |
| `robots.py` | ~35 | Per-host robots.txt cache (stdlib parser), fails open | `RobotsCache(user_agent).allowed(url) -> bool` |
| `fetcher.py` | ~85 | HTTP layer: shared requests.Session, timing, 5 MiB body cap, retry w/ doubling backoff on connection errors and 429/502/503/504 | `Fetcher(config).fetch(url, depth) -> (PageResult, html_body)`; body is `""` for non-HTML or errors |
| `parser.py` | ~90 | BeautifulSoup audit extraction, handles `<base href>` | `parse_page(base_url, html) -> ParsedPage` (title, links, meta_description, canonical_url, meta_robots, h1_count, image_count, images_missing_alt, missing_alt_srcs, mixed_content, word_count, content_hash; word count/hash exclude script/style; mixed_content only populated for https pages) |
| `audit.py` | ~85 | Issue model + audit checks | `Issue(page_url, issue_type, severity, detail)` with `CSV_FIELDS`/`.as_row()`; `audit_page(result, parsed) -> [Issue]` (broken_link, fetch_error, redirect_loop, redirect_chain, temporary_redirect, noindex, mixed_content, images_missing_alt, missing/short/long title & meta_description, missing/multiple h1, thin_content, canonical_mismatch); `find_duplicates(results) -> [Issue]` (duplicate title/meta/content, skips redirected + failed pages); `find_orphans(sitemap_urls, frontier) -> [Issue]`. Thresholds: TITLE 30-60, META 70-155 chars, THIN_CONTENT_WORDS 200 |
| `sitemap.py` | ~75 | sitemap.xml fetch/parse (indexes supported, 20-file cap) and generation | `fetch_sitemap_urls(session, start_url, timeout) -> [url]`; `write_sitemap(path, results) -> int` (200 + html + not noindex + not redirected) |
| `engine.py` | ~150 | **Core.** Threaded worker pool, stop flag, page-limit guard; work items are `(url, depth, found_on)` | `CrawlEngine(config)`: `.start()`, `.stop()`, `.running`, `.events` (a `queue.Queue` of events.py objects) |
| `report.py` | ~60 | CSV output for pages and issues | `CsvReport(path)`: `.add(result)`, `.close()` (incremental); `write_report(path, results)`; `write_issues(path, issues)` (sorted errors-first); `issues_path_for(report_path)` (`x.csv -> x_issues.csv`) |
| `cli.py` | ~130 | argparse front end (`fetchly` entry point) | `main(argv)`. Streams rows to CSV as events arrive; writes `<output>_issues.csv` + prints issue summary; Ctrl-C stops gracefully |
| `gui/app.py` | ~260 | Tkinter front end (`fetchly-gui` entry point) | `FetchlyApp(root)`, `main()`. Settings form, Pages/Issues notebook tabs, progress bar, Stop, Export (writes both CSVs) |

## Architecture rules (do not break these)

1. **The engine must stay UI-agnostic.** `engine.py` and everything below it
   must never import tkinter, print for the user, or know which front end is
   running. All communication with front ends goes through `engine.events`
   (a thread-safe `queue.Queue` of the dataclasses in `events.py`).
2. **All Tkinter calls stay on the main thread.** The GUI polls
   `engine.events` every 100 ms via `root.after()` (`_poll` in `gui/app.py`).
   Never touch a widget from a worker thread.
3. **New crawl settings go through `CrawlConfig`** — add the field there,
   then expose it in both `cli.py` (argparse flag) and `gui/app.py` (form
   widget). Never pass loose kwargs into the engine.
4. **New per-page data goes on `PageResult`** and into `PageResult.CSV_FIELDS`
   so it automatically lands in the CSV report and `as_row()`.
5. **Scope/filtering decisions belong in `Frontier`**, not in the engine or
   fetcher.
6. **New audit checks go in `audit.py`** — per-page checks in `audit_page()`
   (pure function of PageResult + ParsedPage), site-level checks emitted with
   `CrawlFinished`. If a check needs new evidence from the HTML, collect it
   into `ParsedPage` first.
7. Keep dependencies minimal. Do not add a dependency without noting it in
   `HANDOFF.md` and updating `pyproject.toml`.

## How to run and verify

```bash
# one-time setup (venv already exists at .venv/)
.venv/bin/pip install -e .

# CLI smoke test (works offline against a local server):
#   create a couple of HTML files linking to each other in a dir, then:
python3 -m http.server 8642 --bind 127.0.0.1 &   # from that dir
.venv/bin/fetchly http://127.0.0.1:8642/ -o /tmp/report.csv
# expect: pages listed with status codes, CSV written, exit code 0

# GUI (requires system Tk: `sudo pacman -S tk` on this machine)
.venv/bin/fetchly-gui

# quick syntax check when Tk is unavailable:
.venv/bin/python -m py_compile src/fetchly/gui/app.py
```

Test suite: `.venv/bin/python -m pytest tests/ -q` (needs `pip install -e ".[dev]"`).
`tests/conftest.py` serves a small fixture site on an ephemeral localhost port,
so the engine integration tests run offline. Run the suite before finishing
any session; add tests alongside behavior changes.

## Conventions

- Python ≥ 3.9 compatible (no `match`, no `X | Y` type syntax in annotations;
  quoted annotations like `"list[str]"` are used for 3.9 compat).
- Dataclasses for data, plain classes for behavior. No inheritance hierarchies.
- Docstring at the top of each module states its responsibility; comments only
  for non-obvious constraints.
- Thread-shared state in the engine is guarded by `_state_lock` / `_stats_lock`.
- Errors from the network are captured in `PageResult.error`, never raised
  through the engine.

## Session protocol for AI assistants

1. Read `HANDOFF.md` → "Current task" and "Working files".
2. Do the task, touching as few files as possible; respect the rules above.
3. Run the smoke test (or the test suite once it exists).
4. **Update `HANDOFF.md` before finishing**: move the finished work into the
   changelog, set the new "Current task" / "Next tasks", list working files,
   and note anything half-done or surprising in "Warnings & gotchas".
   `HANDOFF.md` is the single source of truth for project state — this file
   (AGENTS.md) only changes when architecture or conventions change.
