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

## Standalone app (no Python needed)

Prebuilt, dependency-free binaries are published as GitHub Release assets:

| OS | Asset | Run |
|---|---|---|
| Windows 10/11 | `Fetchly-windows-x64.zip` | unzip → double-click `Fetchly.exe` (GUI) or `fetchly-cli.exe <url>` |
| macOS | `Fetchly-macos.dmg` | open dmg → right-click `Fetchly.app` → Open (first launch only) |
| Linux (Arch/CachyOS) | `Fetchly-linux-x86_64.tar.gz` | `tar xzf` → `./Fetchly` or `./fetchly-cli <url>`; or `makepkg -si` with `packaging/arch/PKGBUILD` |
| Linux (older glibc) | `Fetchly-linux-glibc-x86_64.tar.gz` | same, built on Ubuntu for wider compatibility |

Binaries are unsigned (code signing requires paid certificates): Windows
SmartScreen → "More info" → "Run anyway"; macOS Gatekeeper → right-click →
Open or `xattr -dr com.apple.quarantine Fetchly.app`. JavaScript rendering
is not bundled (≈300 MB) — use the pip install below with `fetchly[js]`.

**Building the binaries** (maintainers): PyInstaller cannot cross-compile,
so each OS builds its own — `packaging/build_windows.bat`,
`packaging/build_macos.sh`, `packaging/build_linux.sh` (shared spec:
`packaging/fetchly.spec`). Pushing a `v*` tag runs
`.github/workflows/release.yml`, which builds all three on CI and attaches
the assets to the release. Linux binaries link the build machine's glibc —
build on the oldest distro you target.

## Install & run (from source)

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
| `--user-agent UA` | User-Agent header (set a browser UA to get past bot protection) | FetchlyBot/… |
| `--subdomains` | crawl subdomains too | off |
| `--all-domains` | no domain restriction | off |
| `--no-robots` | ignore robots.txt | off |
| `--exclude STR` | skip URLs containing STR (repeatable) | — |
| `--sitemap FILE` | also generate an XML sitemap of indexable pages | — |
| `--url-list FILE` | audit a fixed URL list (one per line) instead of crawling | — |
| `--no-orphan-check` | skip the sitemap orphan check | off |
| `--graph FILE` | self-contained HTML link-graph visualization | — |
| `--extract RULE` | custom extraction: `name=css:selector` or `name=re:pattern` (repeatable; each rule adds a CSV column) | — |
| `--render-js` | render pages with headless Chromium (see below) | off |
| `--segment RULE` | tag pages: `name=substring` or `name=re:pattern` (repeatable; adds a `segment` column) | — |
| `--robots-file FILE` | use a local robots.txt for every host (test rules pre-deploy) | — |
| `--save FILE` / `--open FILE` | save the crawl to `.fetchly.json.gz` / reopen and re-export without recrawling | — |
| `--mobile` | mobile usability audit: phone viewport, flags missing viewport meta / tiny text / small tap targets (needs `--render-js`) | off |
| `--a11y` | accessibility audit via bundled axe-core (needs `--render-js`) | off |
| `--js-snippet NAME=FILE` | run a JS file in each rendered page; return value becomes a CSV column (repeatable; needs `--render-js`) | — |
| `--spellcheck` + `--dictionary FILE` | flag likely misspellings in visible text (dictionary defaults to /usr/share/dict/words) | off |
| `--login-url URL` + `--login-field K=V` | forms auth: POST once before crawling (use `K=?` to be prompted without echo; not available with `--render-js`; credentials are never saved) | — |

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
| `access_forbidden` | error | 401/403 — page not read (login required or bot protection; try `--user-agent`) |
| `blocked_by_robots` | error | page not read — disallowed by robots.txt |
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
| `near_duplicate_content` | warning | visible text ≥ ~90% similar to another page (SimHash) |
| `invalid_hreflang` / `hreflang_missing_x_default` | warning | bad language code / no x-default alternate |
| `hreflang_broken_target` | error | hreflang points at a 4xx/5xx page |
| `hreflang_missing_return_link` | warning | alternate page doesn't link back |
| `invalid_json_ld` | error | structured-data block fails to parse |
| `amp_missing_canonical` | warning | AMP page without required rel=canonical |
| `missing_viewport_meta` / `small_text_mobile` / `small_tap_targets` | warning | mobile usability (`--mobile`) |
| `a11y_<rule>` | error/warning | axe-core violation (`--a11y`); critical/serious → error |
| `possible_misspellings` | warning | words not in the dictionary (`--spellcheck`) |

The orphan check fetches `/sitemap.xml` (sitemap indexes supported) after the
crawl finishes; it is skipped when the crawl was truncated by the page limit
or stopped early, since that would report false orphans. Disable it with
`--no-orphan-check`.

## More tools

- **`fetchly-compare old.csv new.csv`** — diff two page reports: added/removed
  URLs and per-URL changes to status, title, meta description, canonical,
  redirect target, and word count. Use it to track audit progress or compare
  staging vs production crawls.
- **Link graph** (`--graph out.html` or the GUI's Export Graph button): a
  single offline HTML file with a draggable force-directed view of the crawl;
  blue = ok, amber = redirected, red = broken; click a node to open the URL.
- **JavaScript rendering** for React/Vue/Angular sites:
  ```bash
  pip install "fetchly[js]"
  playwright install chromium     # one-time browser download, no account needed
  fetchly https://spa.example.com --render-js
  ```
  Rendering is serialized through one headless Chromium, so it is much slower
  than the default fetcher — use it only for JS-dependent sites. Retries and
  temporary-vs-permanent redirect detail are not available in this mode.
- **Scheduled audits** — the CLI is cron-friendly. Weekly example:
  ```
  0 6 * * 1 /home/may/code/fetchly/.venv/bin/fetchly https://yoursite.com -q -o /home/may/audits/site-$(date +\%F).csv
  ```

## Platform notes

- **Windows 10/11**: python.org installers include Tkinter; the GUI sets
  HiDPI awareness via `SetProcessDpiAwareness`.
- **macOS**: python.org builds bundle Tk 8.6. Homebrew: `brew install python-tk`.
- **Linux**: install the Tk package if missing, e.g. `sudo apt install python3-tk`
  or `sudo pacman -S tk`.

Only crawl sites you own or have permission to crawl, and keep `--delay` and
worker counts considerate on servers you don't control.
