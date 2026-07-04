# Fetchly — Session handoff

> Living state file. Read `AGENTS.md` first for architecture and rules.
> Whoever works on the project (human or LLM) updates this file at the end
> of each session. Keep it current — it replaces reading the git log and
> the codebase.

**Last updated:** 2026-07-04 (session 5: free-tier parity complete, by Claude Code)

## Project status

**The free-tier Screaming Frog parity push is complete.** All 11 of the 12
reference features that don't require paid accounts are implemented (the
12th — GA/GSC/PageSpeed integrations — was explicitly excluded by the user).
85 tests passing + 1 conditional skip (~7s). Everything verified end-to-end
via CLI against local fixture servers, including a real headless-Chromium
render. Playwright + Chromium are installed in this machine's `.venv`
(user-level, `~/.cache/ms-playwright`).

Feature set now: crawl + audit (18 issue types), redirects (chains/loops/
temp-perm), duplicates (title/meta/content-md5), robots directives, orphan
pages, mixed content, sitemap read + generation, URL-list migration audits,
custom CSS/regex extraction (dynamic CSV columns), crawl comparison
(`fetchly-compare`), offline HTML link-graph visualization (`--graph`),
optional JavaScript rendering (`--render-js`, `fetchly[js]` extra), cron
recipe documented in README.

## Current task

**None in progress.** Free-tier scope is done. Remaining work is polish.

## Working files (what was touched last session)

| File | State |
|---|---|
| `src/fetchly/parser.py` | + `parse_extract_rules()`, extract_rules param on parse_page, ParsedPage.extracted |
| `src/fetchly/models.py` | + PageResult.extracted (dict; merged into as_row) |
| `src/fetchly/report.py` | CsvReport/write_report take extra_fields for extraction columns |
| `src/fetchly/compare.py` | new — `fetchly-compare` console script (registered in pyproject) |
| `src/fetchly/viz.py` | new — self-contained HTML force-graph export |
| `src/fetchly/jsfetch.py` | new — JsFetcher with dedicated render thread (see gotchas!) |
| `src/fetchly/engine.py` | picks JsFetcher when config.render_js; parses extract rules in __init__ |
| `src/fetchly/config.py` | + extract_rules, render_js |
| `src/fetchly/cli.py` | + --extract, --graph, --render-js; catches RuntimeError from engine init |
| `src/fetchly/gui/app.py` | + Extract entry row, Render JavaScript checkbox, Export Graph button |
| `pyproject.toml` | + fetchly-compare script, `js = ["playwright>=1.40"]` extra |
| `tests/test_extras.py`, `tests/test_jsfetch.py` | new; conftest gains jspage.html (JS-injected marker built by concatenation so it's absent from raw source) |
| `README.md` | "More tools" section, new flags, cron recipe |

## Next tasks (in priority order)

1. **GUI feedback pass** — the user has never human-reviewed: Issues tab,
   Export Sitemap/Graph buttons, Extract row, Render JS checkbox. Form is
   getting crowded; consider grouping advanced options behind a collapsible
   section if the user complains.
2. **PyInstaller packaging** for Windows/mac one-file distribution.
3. Possible refinements if requested: configurable audit thresholds
   (rule 3: CrawlConfig + CLI + GUI), pixel-width title measurement,
   rel=next/prev, image-sitemap generation, issue-CSV diffing in
   fetchly-compare, JS-mode parallelism (multiple browser contexts).
4. GA/GSC/PageSpeed integrations remain intentionally out of scope (require
   Google accounts) — do not build unless the user changes their mind.

## Warnings & gotchas

- **Playwright's sync API is greenlet/thread-bound**: it must be created AND
  used on the same thread. JsFetcher therefore runs a dedicated
  `fetchly-render` thread with a request queue; engine workers block on an
  Event. Do NOT "simplify" this back to a lock — it will break with
  `greenlet.error: Cannot switch to a different thread` (only under threaded
  use; a naive same-thread unit test will pass!). `test_render_js_through_engine`
  pins the threaded path.
- JS mode: no retries, redirect_type is always "permanent" (Playwright
  doesn't expose per-hop status), rendering serialized (slow by design).
  `elapsed_ms` includes full render.
- The JS fixture page builds its marker via `'RENDERED-BY-' + 'JS'` — if
  you inline the literal, the plain-fetcher negative assertion breaks
  (the string would appear in raw source).
- Extraction: rules validated in `CrawlEngine.__init__` (ValueError) —
  CLI/GUI catch it at start. Extracted values are dynamic CSV columns via
  `extra_fields`; `re.error` is NOT a ValueError (converted in
  parse_extract_rules). Extraction runs on raw soup BEFORE script/style
  decompose. Matches capped at 5 per rule, " | "-joined.
- viz.py embeds JSON into an HTML template via `.replace("__DATA__", ...)` —
  don't use str.format/f-strings there (the JS braces collide).
- `fetchly-compare` diffs page CSVs only (not issues CSVs); keys on exact
  URL strings, so crawls of different hosts/ports show as all added/removed.
- Chromium installed via `playwright install chromium` (no sudo;
  `--with-deps` fails without a sudo password on this box).
- All previous gotchas hold (see session-4 entry / AGENTS.md): duplicates
  run on truncated crawls but orphans don't; find_duplicates skips
  redirected pages; retry backoff 0.01 in tests; 3.9 syntax only; etc.
- Venv `.venv/` (editable, `[dev,js]` extras installed);
  `.venv/bin/python -m pytest tests/ -q`.

## Session changelog

- **2026-07-04 (session 5)** — Completed free-tier parity: custom extraction
  (--extract css/regex → dynamic CSV columns), fetchly-compare CSV diff tool,
  offline HTML link-graph (--graph + GUI button), optional JS rendering
  (fetchly[js] + --render-js + GUI checkbox) with dedicated Playwright render
  thread after hitting the greenlet thread-affinity bug, cron docs. 85 tests.
- **2026-07-03 (session 4)** — Redirect auditing, title/meta length +
  duplicates, duplicate/thin content, robots directives, sitemap generation,
  URL-list mode.
- **2026-07-03 (session 3)** — Audit issues layer, orphan pages, issues CSV,
  GUI Issues tab.
- **2026-07-03 (session 2)** — Initial commit; pytest suite; audit columns;
  found_on tracking; retry-with-backoff.
- **2026-07-03 (session 1)** — Scaffold: layered architecture, threaded
  engine + event queue, CLI, Tkinter GUI, README, AGENTS.md.
