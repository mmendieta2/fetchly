# Fetchly — Session handoff

> Living state file. Read `AGENTS.md` first for architecture and rules.
> Whoever works on the project (human or LLM) updates this file at the end
> of each session. Keep it current — it replaces reading the git log and
> the codebase.

**Last updated:** 2026-07-03 (session 2: tests + audit features, by Claude Code)

## Project status

v0.1 complete, tested, and committed (3 commits after the scaffold). The
crawler now has: a 35-test pytest suite (all passing, ~3.5s, runs fully
offline against fixture servers in `tests/conftest.py`), WordPress-audit
CSV columns (meta description, canonical URL, h1/image/word counts,
internal/external link split, images missing alt), broken-link referrer
tracking (`found_on` column — for a 404 row it names the page holding the
broken link), and retry-with-backoff on transient failures (connection
errors, 429/502/503/504; `max_retries`/`retry_backoff_seconds` in config,
`--retries` CLI flag, "Retries" field in the GUI form).

## Current task

**None in progress.** All work is committed and the working tree is clean
(verify with `git status`). Pick up from "Next tasks" below.

## Working files (what was touched last session)

| File | State |
|---|---|
| `tests/` (conftest + test_frontier/parser/engine/fetcher) | new — 35 tests, all passing |
| `src/fetchly/parser.py` | rewritten — `parse_page` now returns a `ParsedPage` dataclass (breaking change from the old `(title, links)` tuple; engine already updated) |
| `src/fetchly/models.py` | extended — 9 new `PageResult` fields + reordered `CSV_FIELDS` |
| `src/fetchly/engine.py` | work items now `(url, depth, found_on)`; new `_apply_parsed()` helper |
| `src/fetchly/frontier.py` | added `same_site()` for internal/external classification |
| `src/fetchly/fetcher.py` | `fetch()` is now a retry loop around `_fetch_once()` |
| `src/fetchly/config.py`, `cli.py`, `gui/app.py` | retry setting plumbed through all three |
| `pyproject.toml` | added `[project.optional-dependencies] dev = ["pytest>=8"]` |
| `README.md`, `AGENTS.md` | updated to match (CSV columns, codebase map, test instructions) |

## Next tasks (in priority order)

1. **Manually test the GUI** — still blocked on Tk not being installed
   (`sudo pacman -S tk`, then `.venv/bin/fetchly-gui`). Verify: start/stop a
   crawl, table fills, progress bar advances, Export CSV works, closing the
   window mid-crawl doesn't hang. Also eyeball the new "Retries" form field
   added blind this session.
2. **Show audit data in the GUI.** The new PageResult fields land in the CSV
   but the GUI table still shows only status/depth/ms/title/url. Options:
   add columns (crowded), or a detail pane showing the selected row's full
   record. Detail pane recommended.
3. **Sitemap.xml seeding** — parse `/sitemap.xml` (and sitemap indexes) and
   seed the frontier so orphaned pages get audited too. Natural home: a new
   `sitemap.py` + a `use_sitemap` CrawlConfig flag; seed in `CrawlEngine.start()`.
4. **Per-host rate limiting** to replace the global per-worker delay
   (only matters once multi-domain crawls are common; low priority).
5. **Packaging**: PyInstaller one-file builds for Windows/mac distribution.

## Warnings & gotchas

- **GUI is still unverified at runtime** (no Tk on this machine —
  `ImportError: libtk8.6.so`; environment issue, don't "fix" in code).
  The Retries field and earlier layout have never been rendered.
- `parse_page()` returns `ParsedPage` now. Any code snippet or doc that
  shows tuple unpacking `(title, links)` is stale.
- **Retry interacts with timing tests**: `fetch()` sleeps between attempts
  (0.5s doubling by default). In tests, pass `retry_backoff_seconds=0.01`
  or `max_retries=0` or suites get slow.
- `elapsed_ms` on a retried fetch is the *last attempt only*, not total time.
- Internal/external link classification (`Frontier.same_site`) counts all
  subdomains as internal regardless of the `include_subdomains` crawl
  setting — intentional, see AGENTS.md map.
- `tests/test_fetcher.py` uses class attributes on `FlakyHandler` for
  hit-counting — tests in that file must not run in parallel (fine under
  plain pytest; would break under pytest-xdist without changes).
- `Fetcher.fetch()` relies on `stream=True` + `response.raw.read(5 MiB)`
  for the body cap; switching to `response.text` loses the cap.
- `engine.stop()` doubles as the page-limit halt (`_claim_page_slot` sets
  the stop flag); `stopped_by_user` logic in `_supervisor()` depends on it.
- Python here is 3.14 but code targets ≥ 3.9 — no 3.10+ syntax.
- Venv at `.venv/`, package installed editable (`pip install -e ".[dev]"`).

## Session changelog

- **2026-07-03 (session 2)** — Initial git commit of scaffold; pytest suite
  (frontier/parser/engine/fetcher, offline fixture servers); audit columns
  (meta_description, canonical_url, h1_count, internal/external_links,
  image_count, images_missing_alt, word_count); `found_on` referrer tracking
  through the work queue; retry-with-backoff in fetcher (config + CLI flag +
  GUI field); docs updated. 35 tests passing; 4 commits total on main.
- **2026-07-03 (session 1)** — Scaffolded entire project: layered architecture
  (config/models/events/frontier/robots/fetcher/parser/engine/report),
  argparse CLI with incremental CSV writing, Tkinter GUI with event-queue
  polling, README, pyproject with entry points. Verified CLI end-to-end
  against a local `http.server` test site. Wrote AGENTS.md + this file.
