# Fetchly — Session handoff

> Living state file. Read `AGENTS.md` first for architecture and rules.
> Whoever works on the project (human or LLM) updates this file at the end
> of each session. Keep it current — it replaces reading the git log and
> the codebase.

**Last updated:** 2026-07-03 (session: initial scaffold, by Claude Code)

## Project status

v0.1 complete and working. The whole crawler (engine + CLI + GUI) was built
from scratch this session and the CLI was verified end-to-end against a local
test site (4 pages, correct depths, 404 flagged, mailto/image/fragment links
filtered, CSV correct). Nothing is committed to git yet — the repo has no
commits; all files are untracked.

## Current task

**None in progress.** The scaffold is finished and verified. Pick up from
"Next tasks" below.

## Working files (what was touched last session)

| File | State |
|---|---|
| `pyproject.toml` | done — deps, `fetchly` + `fetchly-gui` entry points |
| `src/fetchly/*.py` (all modules) | done — see codebase map in AGENTS.md |
| `src/fetchly/gui/app.py` | done, but **only syntax-checked** — Tk is not installed on this machine, so the GUI has never been rendered |
| `README.md` | done — user-facing docs + architecture diagram |
| `.gitignore` | done — `.venv/`, `__pycache__/`, `*.egg-info/`, `*.csv` |

## Next tasks (in priority order)

1. **Initial git commit.** Everything is untracked. Commit the scaffold as
   v0.1 before making further changes.
2. **Manually test the GUI** once Tk is installed (`sudo pacman -S tk`, then
   `.venv/bin/fetchly-gui`). Verify: start/stop a crawl, table fills, progress
   bar advances, Export CSV works, closing the window mid-crawl doesn't hang.
3. **Add a pytest test suite** (`tests/`). Highest-value targets:
   - `frontier.py`: normalize() cases, scope policy (subdomains, excludes,
     binary extensions), admit() dedupe.
   - `parser.py`: link extraction, `<base href>`, missing title.
   - `engine.py`: integration test against `http.server` on localhost
     (mirror the smoke test in AGENTS.md); test stop() and max_pages.
   - Add `pytest` under a `[project.optional-dependencies] dev` extra.
4. **Richer page analysis for the audit use case** (the owner's real goal —
   WordPress site auditing). Candidate columns for `PageResult`:
   meta description, h1 count, canonical URL, internal vs external link
   counts, image count / images missing alt, word count. Follow AGENTS.md
   rule 4 (extend PageResult + CSV_FIELDS) so the CSV picks them up
   automatically.
5. **Broken-link detail**: record *which page linked to* each 404 (a
   `found_on` column). Needs the frontier/work queue to carry the referrer
   URL along with `(url, depth)`.
6. Later / nice-to-have: retry-with-backoff for transient errors in
   `fetcher.py`; sitemap.xml seeding; per-host rate limiting instead of the
   global per-worker delay; packaging a standalone binary (PyInstaller) for
   Windows/mac distribution.

## Warnings & gotchas

- **GUI is unverified at runtime.** It compiles, and the event-queue design
  is the same one the (verified) CLI uses, but no human has seen the window.
  Expect layout tweaks on first run.
- **Tk missing on this machine** (CachyOS/Arch): `ImportError: libtk8.6.so`.
  Fix: `sudo pacman -S tk`. Don't "fix" this in code — it's an environment issue.
- `Fetcher.fetch()` uses `stream=True` + `response.raw.read(5 MiB)` to cap
  body size; if you switch to `response.text` you lose that cap.
- `engine.stop()` is also how the page limit halts the crawl
  (`_claim_page_slot` sets the stop flag). If you add new stop reasons,
  update the `stopped_by_user` logic in `_supervisor()`.
- Python on this machine is 3.14, but the code targets ≥ 3.9 — don't
  introduce 3.10+ syntax.
- The venv is `.venv/` at repo root; the package is installed editable, so
  source edits take effect immediately.

## Session changelog

- **2026-07-03** — Scaffolded entire project: layered architecture
  (config/models/events/frontier/robots/fetcher/parser/engine/report),
  argparse CLI with incremental CSV writing, Tkinter GUI with event-queue
  polling, README, pyproject with entry points. Verified CLI end-to-end
  against a local `http.server` test site. Wrote AGENTS.md + this file.
