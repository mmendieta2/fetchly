# Fetchly — Session handoff

> Living state file. Read `AGENTS.md` first for architecture and rules.
> Whoever works on the project (human or LLM) updates this file at the end
> of each session. Keep it current — it replaces reading the git log and
> the codebase.

**Last updated:** 2026-07-03 (session 3: audit issues layer, by Claude Code)

## Project status

v0.2-quality: crawler + audit tool. 50 tests passing (~4.5s, fully offline).
Fetchly now produces two CSVs per crawl — the page report and
`<output>_issues.csv` — and the GUI has Pages/Issues tabs. Audit checks:
broken links (with the linking page), fetch errors, mixed content
(http:// resources on https pages), images missing alt text (srcs listed),
missing title / meta description, missing or multiple h1, and orphan pages
(in sitemap.xml but never linked; sitemap indexes supported; check skipped
on truncated crawls to avoid false positives). Tk is now installed on this
machine and the GUI renders; the user has launched it successfully.

## Current task

**None in progress.** All work committed, working tree clean. The user has
not yet run a full crawl through the new Issues tab in the GUI — feedback
may produce small UI tweaks.

## Working files (what was touched last session)

| File | State |
|---|---|
| `src/fetchly/audit.py` | new — Issue model + audit_page()/find_orphans() |
| `src/fetchly/sitemap.py` | new — sitemap.xml fetch/parse incl. index files |
| `src/fetchly/parser.py` | extended — missing_alt_srcs, mixed_content on ParsedPage |
| `src/fetchly/engine.py` | audit_page() per page; orphan check in _supervisor before CrawlFinished |
| `src/fetchly/events.py` | PageCrawled.issues, CrawlFinished.issues |
| `src/fetchly/config.py` | added check_orphans (default True) |
| `src/fetchly/report.py` | write_issues() (errors-first), issues_path_for() |
| `src/fetchly/cli.py` | --no-orphan-check; writes issues CSV; prints issue summary by type |
| `src/fetchly/gui/app.py` | Pages/Issues Notebook tabs; issue counts in tab title + status bar; Export writes both CSVs |
| `tests/` | conftest gains sitemap.xml + orphan.html (`{base}` templating for the ephemeral port); new test_audit.py; run_crawl() in test_engine.py now returns a 4-tuple incl. issues |
| `README.md`, `AGENTS.md` | issues table, new modules in map, rule 6 (audit checks go in audit.py) |

## Next tasks (in priority order)

1. **User feedback pass on the GUI** — Issues tab, tab counter, row colors
   (error red / warning amber) have only been auto-rendered, not human-reviewed.
2. **More audit checks** (easy now — follow AGENTS.md rule 6): redirect
   chains (redirected_to already on PageResult), slow pages (elapsed_ms
   threshold), thin content (word_count threshold), duplicate titles across
   pages (site-level, like orphans), noindex/canonical-mismatch detection.
3. **Sitemap seeding** (distinct from the orphan check): optionally *crawl*
   sitemap URLs too, so orphans get audited rather than just reported.
4. **Per-host rate limiting**; **PyInstaller packaging** (unchanged, lower
   priority).

## Warnings & gotchas

- **Orphan check mutates the frontier**: `find_orphans()` calls
  `frontier.admit()` — fine post-crawl, but don't reuse a Frontier after it.
- Orphan check is deliberately skipped when `stop` was set (user stop OR
  max_pages hit) — a truncated crawl would report false orphans
  (`test_orphan_check_skipped_when_truncated` pins this).
- Mixed content is judged against the page's **final** URL scheme
  (`redirected_to or url` is passed to parse_page as base) and only collected
  for https pages; `link` tags only count rel stylesheet/preload/icon.
- Error pages (4xx/5xx) get only the broken_link issue — content-quality
  checks are skipped for them (see early return in `audit_page`).
- The fixture site now has `sitemap.xml` with a `{base}` placeholder replaced
  at fixture setup (port is ephemeral). If you add fixture pages that you
  link from existing pages, expect `test_full_crawl` counts to change; if you
  add them to the sitemap unlinked, orphan assertions change.
- Retry timing, body-cap, stop-flag, and Python-3.9-syntax gotchas from
  session 2 still apply (see AGENTS.md map + git log if needed):
  `retry_backoff_seconds=0.01` in tests, `stream=True` body cap,
  `engine.stop()` doubles as page-limit halt, no 3.10+ syntax.
- Venv at `.venv/`, editable install; run tests with
  `.venv/bin/python -m pytest tests/ -q`.

## Session changelog

- **2026-07-03 (session 3)** — Audit issues layer: audit.py (8 per-page check
  types), sitemap.py, orphan-page detection, issues CSV (errors-first) from
  CLI + GUI, GUI Pages/Issues tabs with severity colors, issue summary in CLI
  output. Parser collects missing-alt srcs and mixed-content resource URLs.
  50 tests passing. Verified end-to-end: CLI produced correct issues CSV
  (broken link w/ referrer, orphan, h1/meta warnings) against a local site.
- **2026-07-03 (session 2)** — Initial commit; pytest suite; audit CSV columns;
  found_on referrer tracking; retry-with-backoff (config + CLI + GUI).
- **2026-07-03 (session 1)** — Scaffolded project: layered architecture,
  threaded engine + event queue, CLI, Tkinter GUI, README, AGENTS.md, this file.
