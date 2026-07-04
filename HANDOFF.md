# Fetchly — Session handoff

> Living state file. Read `AGENTS.md` first for architecture and rules.
> Whoever works on the project (human or LLM) updates this file at the end
> of each session. Keep it current — it replaces reading the git log and
> the codebase.

**Last updated:** 2026-07-03 (session 4: SEO audit expansion, by Claude Code)

## Project status

Feature parity push against Screaming Frog's free-tier checklist (user asked
for "everything that doesn't require paying or signing up"). Now covered:
broken links w/ source page, redirect auditing (chains, loops, temp-vs-perm),
title/meta length + duplicates, duplicate content (md5 of visible text), thin
content, robots directives (meta robots + X-Robots-Tag, noindex flagging,
canonical mismatch), XML sitemap generation, URL-list audit mode (site
migrations), orphan pages, mixed content, missing alt text. 70 tests passing
(~6s, offline). All committed; CLI verified end-to-end incl. `--sitemap` and
`--url-list`; GUI render-checked.

## Current task

**None in progress.** Remaining free-tier gaps are queued in "Next tasks".

## Working files (what was touched last session)

| File | State |
|---|---|
| `src/fetchly/parser.py` | + meta_robots, content_hash (md5 of normalized visible text) |
| `src/fetchly/fetcher.py` | + redirect_hops/redirect_type from response.history, x_robots_tag header |
| `src/fetchly/models.py` | + 6 PageResult fields, CSV_FIELDS reordered |
| `src/fetchly/audit.py` | + length/thin/canonical/noindex/redirect checks; `find_duplicates()`; threshold constants at top |
| `src/fetchly/engine.py` | retains `_results` for duplicate check (runs even on truncated crawls, unlike orphans); seed_urls queued at depth 0 |
| `src/fetchly/sitemap.py` | + `write_sitemap()` (indexable pages only) |
| `src/fetchly/config.py` | + seed_urls |
| `src/fetchly/cli.py` | + `--sitemap`, `--url-list` (implies all-domains + depth 0; positional URL now optional); retains results list |
| `src/fetchly/gui/app.py` | + Export Sitemap… button |
| `tests/` | 70 tests; new RedirectHandler fixture in test_fetcher.py; TestSeoChecks/TestRedirectChecks/TestDuplicates/TestSitemapGeneration in test_audit.py |
| `README.md`, `AGENTS.md` | full issues table (18 types), new flags, updated map |

## Next tasks (in priority order)

Remaining free-tier Screaming Frog parity items, hardest last:

1. **Custom extraction** (`--extract "name=css:.selector"` and `re:` regex).
   Design decision needed: extracted values are dynamic columns — either
   extend CsvReport with extra_fields or write a third CSV. bs4 `.select()`
   gives CSS support free; XPath would need lxml (allowed, but note rule 7).
2. **Crawl comparison** — `fetchly-compare old.csv new.csv` (or subcommand):
   new/removed URLs, status changes, issue diffs. Pure-CSV post-processing,
   no engine changes.
3. **Site visualization** — self-contained HTML export (inline JS, no CDN)
   drawing the link graph from url+found_on edges; force-directed or tree.
4. **JavaScript rendering** — the big one. Optional extra
   (`pip install fetchly[js]` → playwright); a `render_js` config flag that
   swaps the Fetcher's HTTP get for a headless-Chromium page fetch. Keep it
   an optional dependency so the base install stays light. Free, no signup
   (Playwright downloads Chromium itself).
5. **Scheduling** — document cron/systemd-timer recipes using the CLI
   (`--quiet` + fixed output paths); a built-in scheduler is not worth it.
6. GUI feedback pass (user hasn't reviewed Issues tab / new buttons yet);
   PyInstaller packaging.

## Warnings & gotchas

- **`find_duplicates` runs even on truncated crawls** (duplicates among
  crawled pages are valid regardless); **orphan check does not** (false
  positives). Both feed `CrawlFinished.issues`.
- `find_duplicates` skips redirected pages (`redirected_to` truthy) — both
  redirect source and target being in results would otherwise always flag
  duplicate content. `test_orphan_check_skipped_when_truncated` asserts
  `finished.issues == []` — it will break if fixture pages ever share
  titles/meta/content.
- Redirect hops are counted from `response.history`; `elapsed_ms` covers the
  whole chain (single attempt). Redirect loops surface as
  `TooManyRedirects` in `result.error` → audit maps to `redirect_loop`;
  they ARE retried like transient errors (pass `max_retries=0` in loop tests).
- Audit thresholds (title 30–60, meta 70–155 chars, thin < 200 words) are
  constants at the top of `audit.py` — a likely user-tweak request; if made
  configurable, follow rule 3 (CrawlConfig + CLI + GUI).
- `clean_page()` in test_audit.py must stay inside all thresholds or every
  SEO test gives false positives.
- URL-list mode: CLI maps the file's first URL to `start_url`, rest to
  `seed_urls`; engine seeds all at depth 0. Frontier scope still applies —
  that's why the CLI forces `--all-domains`.
- word_count == 0 pages are NOT flagged thin (empty/non-text pages).
- Older gotchas still apply: retry backoff in tests (`retry_backoff_seconds=0.01`),
  5 MiB body cap needs `stream=True`, `engine.stop()` doubles as page-limit
  halt, Python ≥ 3.9 syntax only, FlakyHandler class-attribute counters
  aren't xdist-safe.
- Venv `.venv/`, editable install; `.venv/bin/python -m pytest tests/ -q`.

## Session changelog

- **2026-07-03 (session 4)** — Free-tier Screaming Frog parity: redirect
  auditing (hops/type/loops), title & meta length checks, duplicate
  title/meta/content detection (md5), thin content, meta robots +
  X-Robots-Tag + noindex + canonical mismatch, XML sitemap generation
  (`--sitemap`, GUI button), URL-list audit mode (`--url-list`). 70 tests.
- **2026-07-03 (session 3)** — Audit issues layer: audit.py, sitemap.py
  (orphans), issues CSV, GUI Pages/Issues tabs, CLI issue summary.
- **2026-07-03 (session 2)** — Initial commit; pytest suite; audit CSV
  columns; found_on referrer tracking; retry-with-backoff.
- **2026-07-03 (session 1)** — Scaffolded project: layered architecture,
  threaded engine + event queue, CLI, Tkinter GUI, README, AGENTS.md.
