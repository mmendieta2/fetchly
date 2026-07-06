"""Fetchly GUI: Tkinter front end.

Tkinter ships with CPython on Windows 10/11, macOS, and Linux, so the GUI
needs no extra GUI toolkit installed. The crawl runs on background threads
inside CrawlEngine; this window polls engine.events every 100 ms via
Tk's after() so every widget update happens on the main thread.
"""

import os
import queue
import sys
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from .. import events
from ..config import CrawlConfig, with_scheme
from ..engine import CrawlEngine
from ..report import (export_name, issues_path_for, write_issues,
                      write_issues_zip, write_report)
from ..sitemap import write_sitemap
from ..viz import _status
from .theme import FONTS, PALETTE, SPACING, apply_theme

POLL_MS = 100

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")


def _set_app_icon(root: tk.Tk) -> None:
    """Set the window/taskbar icon from the bundled PNGs; the WM picks the
    best size. Icons are optional — a stripped install just keeps Tk's
    default feather."""
    try:
        icons = [
            tk.PhotoImage(master=root, file=os.path.join(ASSETS_DIR, f"icon_{s}.png"))
            for s in (16, 32, 64, 256)
        ]
        root.iconphoto(True, *icons)
        root._fetchly_icons = icons  # keep refs or Tk garbage-collects them
    except Exception:
        pass


class Tooltip:
    """Hover tooltip for a widget (Tk has no built-in one)."""

    DELAY_MS = 500

    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self._after_id = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._after_id = self.widget.after(self.DELAY_MS, self._show)

    def _show(self) -> None:
        if self._tip:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self._tip, text=self.text, justify="left", wraplength=360,
                 background=PALETTE["text"], foreground="#ffffff",
                 font=(FONTS["family"], 9), relief="flat", borderwidth=0,
                 padx=8, pady=6).pack()

    def _hide(self, _event=None) -> None:
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self._tip:
            self._tip.destroy()
            self._tip = None


class EntryHistory:
    """Undo/redo for a ttk.Entry backed by a StringVar.

    Tk's Entry has no native undo (only the Text widget does), so we snapshot
    the variable on every change and let Ctrl+Z / Ctrl+Shift+Z (and Ctrl+Y)
    walk that history. Runs of typing in the same direction within a short
    window collapse into one undo step, so a burst of characters is undone as
    a unit rather than one keystroke at a time.
    """

    COALESCE_MS = 500

    def __init__(self, entry: ttk.Entry, var: tk.StringVar):
        self.entry = entry
        self.var = var
        self._undo = [var.get()]
        self._redo = []
        self._suspend = False
        self._last_ms = 0.0
        self._grew = True
        self._group_open = False
        var.trace_add("write", self._on_write)
        for seq in ("<Control-z>", "<Command-z>"):
            entry.bind(seq, self._do_undo)
        for seq in ("<Control-y>", "<Control-Shift-Z>", "<Command-Shift-Z>",
                    "<Command-y>"):
            entry.bind(seq, self._do_redo)

    def _on_write(self, *_) -> None:
        if self._suspend:
            return
        value = self.var.get()
        prev = self._undo[-1]
        if value == prev:
            return
        now = time.monotonic() * 1000
        grew = len(value) >= len(prev)
        if (self._group_open and grew == self._grew
                and now - self._last_ms < self.COALESCE_MS):
            self._undo[-1] = value          # extend the current typing group
        else:
            self._undo.append(value)        # start a new undo step
        self._grew = grew
        self._group_open = True
        self._last_ms = now
        self._redo.clear()

    def _apply(self, value: str) -> None:
        self._suspend = True
        self.var.set(value)
        self.entry.icursor("end")
        self.entry.xview_moveto(1.0)         # keep the end (cursor) in view
        self._suspend = False
        self._group_open = False             # next edit begins a fresh group

    def _do_undo(self, _event=None) -> str:
        if len(self._undo) > 1:
            self._redo.append(self._undo.pop())
            self._apply(self._undo[-1])
        return "break"

    def _do_redo(self, _event=None) -> str:
        if self._redo:
            state = self._redo.pop()
            self._undo.append(state)
            self._apply(state)
        return "break"


class FetchlyApp(ttk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root, padding=10)
        self.root = root
        self.engine = None
        self._last_config = None
        self.results = []
        self.issues = []
        root.title("Fetchly — Website Crawler")
        self.pack(fill="both", expand=True)
        self._build_header()
        self._build_form()
        self._build_table()
        self._build_statusbar()
        self._install_context_menus()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Size from the actual laid-out height so the bottom status bar is
        # always visible on open, and forbid shrinking below it.
        self.update_idletasks()
        scale = _ui_scale(root)
        min_h = self.winfo_reqheight()
        min_w = max(round(760 * scale), self.winfo_reqwidth())
        root.minsize(min_w, min_h)
        root.geometry(
            f"{max(round(980 * scale), min_w)}x{max(round(640 * scale), min_h)}")

    # -- layout -------------------------------------------------------------

    def _build_header(self) -> None:
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, SPACING["lg"]))
        # The Crawl Orbit mark (assets/logo.svg); falls back to the old gold ◉
        # if the PNG asset is missing.
        try:
            self._logo_img = tk.PhotoImage(
                master=self.root, file=os.path.join(ASSETS_DIR, "logo_24.png"))
            tk.Label(header, image=self._logo_img, background=PALETTE["bg"],
                     ).pack(side="left", padx=(0, SPACING["sm"]))
        except Exception:
            tk.Label(header, text="◉", foreground=PALETTE["gold"],
                     background=PALETTE["bg"],
                     font=(FONTS["family"], 15)).pack(side="left",
                                                      padx=(0, SPACING["sm"]))
        ttk.Label(header, text="Fetchly", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="Website crawler & auditor",
                  style="Subtitle.TLabel").pack(side="left", padx=(SPACING["md"], 0),
                                                pady=(SPACING["xs"] + 4, 0))

    def _build_form(self) -> None:
        form = ttk.LabelFrame(self, text="Crawl settings", padding=8)
        form.pack(fill="x")

        url_row = ttk.Frame(form)
        url_row.pack(fill="x")
        ttk.Label(url_row, text="Start URL:").pack(side="left")
        self.url_var = tk.StringVar(value="")
        url_entry = ttk.Entry(url_row, textvariable=self.url_var)
        url_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
        url_entry.focus_set()
        EntryHistory(url_entry, self.url_var)

        self.max_pages_var = tk.StringVar(value="200")
        self.max_depth_var = tk.StringVar(value="5")
        self.workers_var = tk.StringVar(value="8")
        self.delay_var = tk.StringVar(value="0")
        self.retries_var = tk.StringVar(value="2")
        self.timeout_var = tk.StringVar(value=f"{CrawlConfig.timeout_seconds:g}")
        self.extract_var = tk.StringVar(value="")
        self.segments_var = tk.StringVar(value="")
        self.robots_file_var = tk.StringVar(value="")
        self.login_url_var = tk.StringVar(value="")
        self.login_fields_var = tk.StringVar(value="")
        self.user_agent_var = tk.StringVar(value=CrawlConfig.user_agent)
        self.dictionary_var = tk.StringVar(value="")
        self.subdomains_var = tk.BooleanVar(value=False)
        self.robots_var = tk.BooleanVar(value=True)
        self.render_js_var = tk.BooleanVar(value=False)
        self.mobile_var = tk.BooleanVar(value=False)
        self.a11y_var = tk.BooleanVar(value=False)
        self.spellcheck_var = tk.BooleanVar(value=False)

        tabs = ttk.Notebook(form)
        tabs.pack(fill="x", pady=(8, 0))
        basics = ttk.Frame(tabs, padding=8)
        advanced = ttk.Frame(tabs, padding=8)
        audits = ttk.Frame(tabs, padding=8)
        tabs.add(basics, text="Basics")
        tabs.add(advanced, text="Advanced")
        tabs.add(audits, text="Audits")
        self.settings_tabs = tabs

        # -- Basics tab
        for col, (label, var, tip) in enumerate((
            ("Max pages:", self.max_pages_var, "Stop after this many pages."),
            ("Max depth:", self.max_depth_var,
             "How many links away from the start URL to follow."),
            ("Workers:", self.workers_var,
             "Pages fetched in parallel. More is faster but harder on the "
             "target server; lower it for fragile sites."),
        )):
            ttk.Label(basics, text=label).grid(row=0, column=col * 2, sticky="w")
            entry = ttk.Entry(basics, textvariable=var, width=7)
            entry.grid(row=0, column=col * 2 + 1, sticky="w", padx=(4, 12))
            Tooltip(entry, tip)

        for col, (label, var, tip) in enumerate((
            ("Delay (s):", self.delay_var,
             "Pause between requests, per worker. Use it to be gentle with "
             "slow or rate-limited servers."),
            ("Timeout (s):", self.timeout_var,
             "How long to wait for each page before giving up. Raise it for "
             "slow sites (timeouts show as fetch_error issues)."),
            ("Retries:", self.retries_var,
             "Extra attempts after connection errors or 429/5xx responses."),
        )):
            ttk.Label(basics, text=label).grid(row=1, column=col * 2, sticky="w", pady=(6, 0))
            entry = ttk.Entry(basics, textvariable=var, width=7)
            entry.grid(row=1, column=col * 2 + 1, sticky="w", padx=(4, 12), pady=(6, 0))
            Tooltip(entry, tip)

        subdomains_check = ttk.Checkbutton(basics, text="Include subdomains",
                                           variable=self.subdomains_var)
        subdomains_check.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        Tooltip(subdomains_check,
                "Also crawl blog.example.com, shop.example.com, … — not just "
                "the start domain.")
        robots_check = ttk.Checkbutton(basics, text="Respect robots.txt",
                                       variable=self.robots_var)
        robots_check.grid(row=2, column=3, columnspan=3, sticky="w", pady=(6, 0))
        Tooltip(robots_check,
                "Skip pages the site's robots.txt disallows for this user "
                "agent. Uncheck only for sites you own.")

        # -- Advanced tab
        ttk.Label(advanced, text="Extract:").grid(row=0, column=0, sticky="w")
        extract_entry = ttk.Entry(advanced, textvariable=self.extract_var)
        extract_entry.grid(row=0, column=1, columnspan=5, sticky="ew", padx=(4, 0))
        Tooltip(extract_entry,
                'Pull custom data from every page into extra CSV columns. '
                '";"-separated rules: name=css:selector or name=re:pattern.')
        ttk.Label(advanced, style="Muted.TLabel",
                  text='Optional, ";"-separated: name=css:selector or name=re:pattern'
                  ).grid(row=1, column=1, columnspan=5, sticky="w", padx=(4, 0))

        ttk.Label(advanced, text="Segments:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        segments_entry = ttk.Entry(advanced, textvariable=self.segments_var)
        segments_entry.grid(row=2, column=1, columnspan=5, sticky="ew", padx=(4, 0), pady=(6, 0))
        Tooltip(segments_entry,
                'Tag pages by URL into a "segment" CSV column. ";"-separated '
                "rules: name=substring or name=re:pattern; first match wins.")

        ttk.Label(advanced, text="Robots file:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        robots_file_entry = ttk.Entry(advanced, textvariable=self.robots_file_var)
        robots_file_entry.grid(row=3, column=1, columnspan=5, sticky="ew",
                               padx=(4, 0), pady=(6, 0))
        Tooltip(robots_file_entry,
                "Path to a local robots.txt applied to every host — test rule "
                "changes before deploying them.")

        ttk.Label(advanced, text="Login URL:").grid(row=4, column=0, sticky="w", pady=(6, 0))
        login_url_entry = ttk.Entry(advanced, textvariable=self.login_url_var)
        login_url_entry.grid(row=4, column=1, columnspan=2, sticky="ew",
                             padx=(4, 12), pady=(6, 0))
        Tooltip(login_url_entry,
                "Forms auth: this URL is POSTed once before crawling; the "
                "session keeps the login cookies. Not available with Render "
                "JavaScript.")
        ttk.Label(advanced, text="Login fields:").grid(row=4, column=3, sticky="w", pady=(6, 0))
        login_fields_entry = ttk.Entry(advanced, textvariable=self.login_fields_var, show="*")
        login_fields_entry.grid(row=4, column=4, columnspan=2, sticky="ew",
                                padx=(4, 0), pady=(6, 0))
        Tooltip(login_fields_entry,
                'Form fields as ";"-separated name=value pairs, e.g. '
                "user=me;pass=secret. Never saved to disk.")

        ttk.Label(advanced, text="User agent:").grid(row=5, column=0, sticky="w", pady=(6, 0))
        ua_entry = ttk.Entry(advanced, textvariable=self.user_agent_var)
        ua_entry.grid(row=5, column=1, columnspan=5, sticky="ew", padx=(4, 0), pady=(6, 0))
        Tooltip(ua_entry,
                "The User-Agent header sent with every request. Paste a "
                "browser UA to get past bot protection.")
        advanced.columnconfigure(5, weight=1)

        # -- Audits tab
        render_js_check = ttk.Checkbutton(
            audits, text="Render JavaScript (needs fetchly[js])",
            variable=self.render_js_var)
        render_js_check.grid(row=0, column=0, columnspan=6, sticky="w")
        Tooltip(render_js_check,
                "Loads every page in a headless browser and waits for its "
                "JavaScript to run. Crawls take considerably longer — expect "
                "several seconds per page instead of milliseconds. Enable it "
                "only for sites that build their content with JavaScript.")

        # The three audit toggles share one left-aligned frame and pack side by
        # side with a small gap, so they read as a group instead of being
        # stretched across the full width.
        checks = ttk.Frame(audits)
        checks.grid(row=1, column=0, columnspan=6, sticky="w", pady=(6, 0))
        mobile_check = ttk.Checkbutton(checks, text="Mobile usability",
                                       variable=self.mobile_var)
        mobile_check.pack(side="left")
        Tooltip(mobile_check,
                "Crawl with a phone viewport and flag missing viewport meta, "
                "tiny text, and small tap targets. Needs Render JavaScript.")
        a11y_check = ttk.Checkbutton(checks, text="Accessibility (axe)",
                                     variable=self.a11y_var)
        a11y_check.pack(side="left", padx=(SPACING["lg"], 0))
        Tooltip(a11y_check,
                "Run the axe-core accessibility checker on every page and "
                "report violations as issues. Needs Render JavaScript.")
        spellcheck_check = ttk.Checkbutton(checks, text="Spellcheck",
                                           variable=self.spellcheck_var)
        spellcheck_check.pack(side="left", padx=(SPACING["lg"], 0))
        Tooltip(spellcheck_check,
                "Flag words in the visible text that aren't in the "
                "dictionary. Conservative: lowercase ASCII words only.")

        # The dictionary controls live in their own row-spanning frame so they
        # line up flush-left and stay adjacent, independent of the equal-width
        # columns used by the checkboxes above.
        dict_row = ttk.Frame(audits)
        dict_row.grid(row=2, column=0, columnspan=6, sticky="ew", pady=(6, 0))
        ttk.Label(dict_row, text="Dictionary:").pack(side="left", padx=(0, 4))
        ttk.Button(dict_row, text="Browse…",
                   command=self._pick_dictionary).pack(side="right")
        dictionary_entry = ttk.Entry(dict_row, textvariable=self.dictionary_var)
        dictionary_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        Tooltip(dictionary_entry,
                "Word list for Spellcheck, one word per line. Defaults to the "
                "system dictionary (/usr/share/dict/words).")
        # Let the full-width rows (render-js, checks, dictionary) stretch.
        audits.columnconfigure(0, weight=1)

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=SPACING["md"])

        def sep():
            ttk.Separator(buttons, orient="vertical").pack(
                side="left", fill="y", padx=SPACING["md"], pady=SPACING["xs"])

        # Primary group: run controls.
        self.start_btn = ttk.Button(buttons, text="▶  Start crawl",
                                    style="Accent.TButton", command=self._start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(buttons, text="■  Stop", command=self._stop,
                                   state="disabled")
        self.stop_btn.pack(side="left", padx=(SPACING["sm"], 0))

        sep()

        # Export group: derived reports from the current crawl.
        self.export_btn = ttk.Button(buttons, text="Export CSV…",
                                     command=self._export, state="disabled")
        self.export_btn.pack(side="left")
        self.zip_btn = ttk.Button(buttons, text="Issues ZIP…",
                                  command=self._export_zip, state="disabled")
        self.zip_btn.pack(side="left", padx=(SPACING["sm"], 0))
        self.sitemap_btn = ttk.Button(buttons, text="Sitemap…",
                                      command=self._export_sitemap, state="disabled")
        self.sitemap_btn.pack(side="left", padx=(SPACING["sm"], 0))
        self.graph_btn = ttk.Button(buttons, text="Graph…",
                                    command=self._export_graph, state="disabled")
        self.graph_btn.pack(side="left", padx=(SPACING["sm"], 0))

        # Session group: save/open a whole crawl. Right-aligned — it's a
        # different kind of action (persistence) from the exports.
        ttk.Button(buttons, text="Open Crawl…", command=self._open_crawl).pack(
            side="right")
        self.save_btn = ttk.Button(buttons, text="Save Crawl…",
                                   command=self._save_crawl, state="disabled")
        # Left pad matches the export group's inter-button gap so that when the
        # window shrinks and the right group meets the left one, the Graph→Save
        # gap is the same as the others (invisible while there's slack).
        self.save_btn.pack(side="right", padx=(SPACING["sm"], SPACING["sm"]))

    def _make_tree(self, parent, headers) -> ttk.Treeview:
        tree = ttk.Treeview(parent, columns=tuple(headers), show="headings")
        for col, (text, width, stretch) in headers.items():
            tree.heading(col, text=text)
            tree.column(col, width=width, stretch=stretch)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        # Striping (background only) and severity/status cues (foreground only)
        # are separate options, so a row can safely carry one of each.
        tree.tag_configure("odd", background=PALETTE["surface"])
        tree.tag_configure("even", background=PALETTE["surface_alt"])
        tree.tag_configure("error", foreground=PALETTE["error"])
        tree.tag_configure("warning", foreground=PALETTE["warning"])
        tree.tag_configure("ok", foreground=PALETTE["status_ok"])
        tree.tag_configure("redirect", foreground=PALETTE["status_redirect"])
        tree.tag_configure("broken", foreground=PALETTE["status_broken"])
        return tree

    @staticmethod
    def _stripe(tree) -> str:
        """Alternating background tag for the next row appended to *tree*."""
        return "even" if len(tree.get_children()) % 2 else "odd"

    def _empty_state(self, parent, text: str):
        """A centered muted placeholder shown over an empty tab.

        Placed with place() so it floats above the treeview; the caller hides
        it with place_forget() once real rows arrive.
        """
        label = tk.Label(parent, text=text, background=PALETTE["surface"],
                         foreground=PALETTE["muted"], justify="center",
                         font=(FONTS["family"], 11))
        label.place(relx=0.5, rely=0.44, anchor="center")
        return label

    def _build_table(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        pages_tab = ttk.Frame(self.notebook)
        self.notebook.add(pages_tab, text="Pages")
        self.tree = self._make_tree(pages_tab, {
            "status": ("Status", 70, False), "depth": ("Depth", 60, False),
            "time": ("ms", 70, False), "segment": ("Segment", 90, False),
            "title": ("Title", 240, True), "url": ("URL", 400, True)})
        self._pages_empty = self._empty_state(
            pages_tab,
            "No pages yet.\nEnter a URL above and press  ▶  Start crawl.")

        issues_tab = ttk.Frame(self.notebook)
        self.notebook.add(issues_tab, text="Issues")
        self.issues_tree = self._make_tree(issues_tab, {
            "severity": ("Severity", 80, False), "type": ("Type", 170, False),
            "page": ("Page", 340, True), "detail": ("Detail", 340, True)})
        self._issues_empty = self._empty_state(
            issues_tab,
            "No issues to show.\nProblems found during a crawl appear here.")
        # The detail column clips long messages; double-click or Enter opens
        # the full text (also on the right-click menu).
        self.issues_tree.bind("<Double-1>", self._show_issue_detail)
        self.issues_tree.bind("<Return>", self._show_issue_detail)

        from .graphview import GraphView
        self.graph_view = GraphView(self.notebook)
        self.notebook.add(self.graph_view, text="Graph")

        self._compare_tab = ttk.Frame(self.notebook)
        self.notebook.add(self._compare_tab, text="Compare")
        compare_bar = ttk.Frame(self._compare_tab)
        compare_bar.pack(fill="x", pady=(0, SPACING["sm"]))
        ttk.Button(compare_bar, text="Compare CSVs…",
                   command=self._compare_crawls).pack(side="left")
        self.compare_tree = self._make_tree(self._compare_tab, {
            "change": ("Change", 90, False), "field": ("Field", 130, False),
            "url": ("URL", 380, True), "before": ("Before", 190, True),
            "after": ("After", 190, True)})
        self._compare_empty = self._empty_state(
            self._compare_tab,
            "No comparison yet.\nPress  Compare CSVs…  above to diff two page reports.")

    def _install_context_menus(self) -> None:
        """Right-click menus: edit actions on entries, copy actions on tables."""
        button = "<Button-2>" if sys.platform == "darwin" else "<Button-3>"

        self._entry_target = None
        self._entry_menu = tk.Menu(self.root, tearoff=0)
        self._entry_menu.add_command(label="Cut", command=lambda: self._entry_event("<<Cut>>"))
        self._entry_menu.add_command(label="Copy", command=lambda: self._entry_event("<<Copy>>"))
        self._entry_menu.add_command(label="Paste", command=lambda: self._entry_event("<<Paste>>"))
        self._entry_menu.add_separator()
        self._entry_menu.add_command(label="Select All", command=self._entry_select_all)
        self.root.bind_class("TEntry", button, self._popup_entry_menu)

        self._tree_target = None
        self._tree_menu = tk.Menu(self.root, tearoff=0)
        self._tree_menu.add_command(label="View Details", command=self._show_issue_detail)
        self._tree_menu.add_command(label="Copy Cell", command=self._copy_cell)
        self._tree_menu.add_command(label="Copy Row", command=self._copy_row)
        self._tree_menu.add_command(label="Copy URL", command=self._copy_url)
        for tree in (self.tree, self.issues_tree, self.compare_tree):
            tree.bind(button, self._popup_tree_menu)

    def _popup_entry_menu(self, event) -> None:
        self._entry_target = event.widget
        event.widget.focus_set()
        try:
            self._entry_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._entry_menu.grab_release()

    def _entry_event(self, virtual_event: str) -> None:
        if self._entry_target is not None:
            self._entry_target.event_generate(virtual_event)

    def _entry_select_all(self) -> None:
        if self._entry_target is not None:
            self._entry_target.select_range(0, "end")
            self._entry_target.icursor("end")

    def _popup_tree_menu(self, event) -> None:
        tree = event.widget
        row = tree.identify_row(event.y)
        if not row:
            return
        tree.selection_set(row)
        tree.focus(row)
        column = tree.identify_column(event.x)
        self._tree_target = (tree, row, column)
        try:
            self._tree_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._tree_menu.grab_release()

    def _copy_to_clipboard(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set(f"Copied: {text[:80]}" + ("…" if len(text) > 80 else ""))

    def _copy_cell(self) -> None:
        if self._tree_target is None:
            return
        tree, row, column = self._tree_target
        values = tree.item(row, "values")
        index = max(0, int(column.lstrip("#") or 1) - 1)
        if index < len(values):
            self._copy_to_clipboard(str(values[index]))

    def _copy_row(self) -> None:
        if self._tree_target is None:
            return
        tree, row, _ = self._tree_target
        self._copy_to_clipboard("\t".join(str(v) for v in tree.item(row, "values")))

    def _copy_url(self) -> None:
        if self._tree_target is None:
            return
        tree, row, _ = self._tree_target
        columns = tree["columns"]
        for name in ("url", "page"):  # pages tab uses "url", issues tab "page"
            if name in columns:
                self._copy_to_clipboard(str(tree.item(row, "values")[columns.index(name)]))
                return

    def _show_issue_detail(self, event=None) -> None:
        """Open a window with the selected row's full, untruncated fields.

        Works from a double-click/Enter on the tree or the right-click menu.
        """
        tree = row = None
        if isinstance(getattr(event, "widget", None), ttk.Treeview):
            tree = event.widget
            row = tree.focus() or (tree.selection()[0] if tree.selection() else None)
        elif self._tree_target is not None:
            tree, row, _ = self._tree_target
        if not tree or not row:
            return

        columns = tree["columns"]
        values = tree.item(row, "values")
        pairs = [(tree.heading(c, "text"), str(v)) for c, v in zip(columns, values)]
        content = "\n\n".join(f"{h}:\n{v}" for h, v in pairs if v)

        win = tk.Toplevel(self.root)
        win.title("Details")
        scale = _ui_scale(self.root)
        win.geometry(f"{round(560 * scale)}x{round(340 * scale)}")
        win.transient(self.root)
        text = tk.Text(win, wrap="word", padx=10, pady=10, height=12,
                       relief="flat", borderwidth=0, background=PALETTE["surface"],
                       foreground=PALETTE["text"], font=(FONTS["family"], 10))
        text.insert("1.0", content)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True)
        bar = ttk.Frame(win)
        bar.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(bar, text="Copy", command=lambda: self._copy_to_clipboard(content)
                   ).pack(side="right", padx=(6, 0))
        ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")
        win.bind("<Escape>", lambda e: win.destroy())
        win.focus_set()

    SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def _build_statusbar(self) -> None:
        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=(8, 0))
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(6, 0))
        self._spinner = ttk.Label(bar, text="", foreground=PALETTE["accent"])
        self._spinner_on = False
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(bar, textvariable=self.status_var, anchor="w",
                  style="Muted.TLabel").pack(side="left", fill="x", expand=True)

    def _spinner_start(self) -> None:
        if not self._spinner_on:
            self._spinner_on = True
            self._spinner.pack(side="left", padx=(0, 8))
            self._spin(0)

    def _spinner_stop(self) -> None:
        self._spinner_on = False
        self._spinner.pack_forget()

    def _spin(self, i: int) -> None:
        if not self._spinner_on:
            return
        self._spinner.configure(
            text=f"{self.SPINNER_FRAMES[i % len(self.SPINNER_FRAMES)]} crawling…")
        self.root.after(100, self._spin, i + 1)

    # -- actions ------------------------------------------------------------

    def _read_config(self) -> CrawlConfig:
        return CrawlConfig(
            start_url=with_scheme(self.url_var.get()),
            max_pages=int(self.max_pages_var.get()),
            max_depth=int(self.max_depth_var.get()),
            num_workers=int(self.workers_var.get()),
            delay_seconds=float(self.delay_var.get() or 0),
            max_retries=int(self.retries_var.get() or 0),
            timeout_seconds=float(self.timeout_var.get() or CrawlConfig.timeout_seconds),
            user_agent=self.user_agent_var.get().strip() or CrawlConfig.user_agent,
            extract_rules=[r.strip() for r in self.extract_var.get().split(";") if r.strip()],
            segment_rules=[r.strip() for r in self.segments_var.get().split(";") if r.strip()],
            robots_txt_file=self.robots_file_var.get().strip(),
            login_url=self.login_url_var.get().strip(),
            login_data=dict(f.split("=", 1) for f in self.login_fields_var.get().split(";")
                            if "=" in f),
            include_subdomains=self.subdomains_var.get(),
            respect_robots=self.robots_var.get(),
            render_js=self.render_js_var.get(),
            mobile_checks=self.mobile_var.get(),
            a11y_checks=self.a11y_var.get(),
            spellcheck=self.spellcheck_var.get(),
            dictionary_file=self.dictionary_var.get().strip(),
        )

    def _pick_dictionary(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose a word list (one word per line)",
            filetypes=[("Word lists", "*"), ("All files", "*.*")])
        if path:
            self.dictionary_var.set(path)

    def _start(self) -> None:
        try:
            config = self._read_config()
            engine = CrawlEngine(config)
            engine.start()
        except (ValueError, TypeError, RuntimeError) as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return
        self.engine = engine
        self._last_config = config
        self.results = []
        self.issues = []
        self.tree.delete(*self.tree.get_children())
        self.issues_tree.delete(*self.issues_tree.get_children())
        self._pages_empty.place(relx=0.5, rely=0.44, anchor="center")
        self._issues_empty.place(relx=0.5, rely=0.44, anchor="center")
        self.graph_view.reset()
        self.notebook.tab(1, text="Issues")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.export_btn.configure(state="disabled")
        self.zip_btn.configure(state="disabled")
        self.sitemap_btn.configure(state="disabled")
        self.graph_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")
        self.status_var.set(f"Crawling {config.start_url}…")
        self._spinner_start()
        self.root.after(POLL_MS, self._poll)

    def _stop(self) -> None:
        if self.engine:
            self.engine.stop()
            self.stop_btn.configure(text="Stopping…", state="disabled")
            self.status_var.set("Stopping — waiting for in-flight requests to finish…")

    def _poll(self) -> None:
        finished = None
        while True:
            try:
                event = self.engine.events.get_nowait()
            except queue.Empty:
                break
            if isinstance(event, events.PageCrawled):
                self._add_row(event)
                self._add_issues(event.issues)
            elif isinstance(event, events.CrawlFinished):
                self._add_issues(event.issues)
                finished = event
        if finished:
            self._on_finished(finished)
        else:
            self.root.after(POLL_MS, self._poll)

    def _add_row(self, event) -> None:
        r = event.result
        self.results.append(r)
        self.tree.insert("", "end", values=(
            r.status_code or "ERR", r.depth, r.elapsed_ms, r.segment, r.title, r.url),
            tags=(self._stripe(self.tree), _status(r)))
        self._pages_empty.place_forget()
        self.graph_view.add_result(r)
        s = event.stats
        self.status_var.set(
            f"Crawled {s.crawled}  |  queued {s.queued}  |  errors {s.errors}  |  "
            f"issues {len(self.issues)}  |  {s.bytes_downloaded / 1024:.0f} KiB")

    def _add_issues(self, issues) -> None:
        for issue in issues:
            self.issues.append(issue)
            self.issues_tree.insert("", "end", values=(
                issue.severity, issue.issue_type, issue.page_url, issue.detail),
                tags=(self._stripe(self.issues_tree), issue.severity))
        if issues:
            self._issues_empty.place_forget()
            self.notebook.tab(1, text=f"Issues ({len(self.issues)})")

    def _on_finished(self, event) -> None:
        self._spinner_stop()
        self.engine = None
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(text="Stop", state="disabled")
        self.export_btn.configure(state="normal" if self.results else "disabled")
        self.zip_btn.configure(state="normal" if self.issues else "disabled")
        self.sitemap_btn.configure(state="normal" if self.results else "disabled")
        self.graph_btn.configure(state="normal" if self.results else "disabled")
        self.save_btn.configure(state="normal" if self.results else "disabled")
        s = event.stats
        suffix = " (stopped)" if event.stopped_by_user else ""
        errors = sum(1 for i in self.issues if i.severity == "error")
        self.status_var.set(
            f"Finished{suffix}: {s.crawled} pages — {errors} error issues, "
            f"{len(self.issues) - errors} warnings.")

    def _export(self) -> None:
        when = datetime.now()
        default = export_name(self._last_config.start_url, "pages", ".csv", when)
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=default)
        if not path:
            return
        extract_names = []
        for r in self.results:
            for name in r.extracted:
                if name not in extract_names:
                    extract_names.append(name)
        write_report(path, self.results, extra_fields=extract_names)
        if os.path.basename(path) == default:
            issues_path = os.path.join(
                os.path.dirname(path),
                export_name(self._last_config.start_url, "issues", ".csv", when))
        else:  # user renamed the report — keep the issues file paired with it
            issues_path = issues_path_for(path)
        write_issues(issues_path, self.issues)
        self.status_var.set(f"Saved {path} and {issues_path}")

    def _export_zip(self) -> None:
        when = datetime.now()
        start_url = self._last_config.start_url
        path = filedialog.asksaveasfilename(
            defaultextension=".zip",
            filetypes=[("ZIP archives", "*.zip"), ("All files", "*.*")],
            initialfile=export_name(start_url, "issues", ".zip", when))
        if not path:
            return
        count = write_issues_zip(path, self.issues, start_url, when)
        self.status_var.set(f"Saved {path} ({count} issue CSVs)")

    def _export_sitemap(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".xml",
            filetypes=[("XML files", "*.xml"), ("All files", "*.*")],
            initialfile=export_name(self._last_config.start_url, "sitemap", ".xml"))
        if not path:
            return
        count = write_sitemap(path, self.results)
        self.status_var.set(f"Sitemap saved to {path} ({count} indexable URLs)")

    def _export_graph(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".html",
            filetypes=[("HTML files", "*.html"), ("All files", "*.*")],
            initialfile=export_name(self._last_config.start_url, "graph", ".html"))
        if not path:
            return
        from ..viz import write_graph
        count = write_graph(path, self.results)
        self.status_var.set(f"Graph saved to {path} ({count} nodes)")

    def _save_crawl(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".fetchly.json.gz",
            filetypes=[("Fetchly crawls", "*.fetchly.json.gz"), ("All files", "*.*")],
            initialfile=export_name(self._last_config.start_url, "crawl",
                                    ".fetchly.json.gz"))
        if not path:
            return
        from ..session_io import save_crawl
        save_crawl(path, self._last_config, self.results, self.issues)
        self.status_var.set(f"Crawl saved to {path}")

    def _open_crawl(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("Fetchly crawls", "*.fetchly.json.gz"), ("All files", "*.*")])
        if not path:
            return
        from ..session_io import load_crawl
        try:
            config, results, issues = load_crawl(path)
        except (OSError, ValueError, KeyError) as exc:
            messagebox.showerror("Cannot open crawl", str(exc))
            return
        self._last_config = config
        self.results = list(results)
        self.issues = []
        self.tree.delete(*self.tree.get_children())
        self.issues_tree.delete(*self.issues_tree.get_children())
        for r in self.results:
            self.tree.insert("", "end", values=(
                r.status_code or "ERR", r.depth, r.elapsed_ms, r.segment, r.title, r.url),
                tags=(self._stripe(self.tree), _status(r)))
        if self.results:
            self._pages_empty.place_forget()
        self._add_issues(issues)
        self.graph_view.load(self.results)
        self.notebook.tab(1, text=f"Issues ({len(self.issues)})" if self.issues else "Issues")
        self.export_btn.configure(state="normal" if self.results else "disabled")
        self.zip_btn.configure(state="normal" if self.issues else "disabled")
        self.sitemap_btn.configure(state="normal" if self.results else "disabled")
        self.graph_btn.configure(state="normal" if self.results else "disabled")
        self.save_btn.configure(state="normal" if self.results else "disabled")
        self.status_var.set(
            f"Opened {path}: {len(self.results)} pages, {len(self.issues)} issues "
            f"(crawl of {config.start_url})")

    def _compare_crawls(self) -> None:
        """Diff two page-report CSVs and show the result in the Compare tab.

        Independent of the current crawl — reads two files chosen from disk,
        mirroring the fetchly-compare CLI.
        """
        old_path = filedialog.askopenfilename(
            title="Old (baseline) page report",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not old_path:
            return
        new_path = filedialog.askopenfilename(
            title="New page report",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not new_path:
            return
        from ..compare import load_report, diff_reports
        try:
            old, new = load_report(old_path), load_report(new_path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Cannot compare", str(exc))
            return
        diff = diff_reports(old, new)

        self.compare_tree.delete(*self.compare_tree.get_children())
        for url in diff["added"]:
            self.compare_tree.insert("", "end", values=("Added", "", url, "", ""),
                                     tags=(self._stripe(self.compare_tree), "ok"))
        for url in diff["removed"]:
            self.compare_tree.insert("", "end", values=("Removed", "", url, "", ""),
                                     tags=(self._stripe(self.compare_tree), "broken"))
        for url, fields in diff["changed"].items():
            for field, (before, after) in fields.items():
                self.compare_tree.insert(
                    "", "end", values=("Changed", field, url, before, after),
                    tags=(self._stripe(self.compare_tree), "warning"))

        n = len(diff["added"]) + len(diff["removed"]) + len(diff["changed"])
        if n:
            self._compare_empty.place_forget()
        else:
            self._compare_empty.place(relx=0.5, rely=0.44, anchor="center")
        compare_index = self.notebook.index(self._compare_tab)
        self.notebook.tab(compare_index, text=f"Compare ({n})" if n else "Compare")
        self.notebook.select(self._compare_tab)
        self.status_var.set(
            f"Compared: {len(old)} → {len(new)} pages · "
            f"+{len(diff['added'])} −{len(diff['removed'])} ~{len(diff['changed'])}")

    def _on_close(self) -> None:
        if self.engine:
            self.engine.stop()
        self.root.destroy()


def _ui_scale(root: tk.Tk) -> float:
    """UI scale factor relative to a 96-DPI display.

    Fonts are sized in points, so Tk scales them itself via ``tk scaling``
    once the process is DPI-aware; this factor is only for values Tk treats
    as raw pixels (table row height, window geometry).
    """
    try:
        return max(1.0, float(root.tk.call("tk", "scaling")) / (96 / 72))
    except Exception:
        return 1.0


def main() -> None:
    # Declare DPI awareness BEFORE tk.Tk(): Tk samples the system DPI once
    # at init, so a late call leaves it laying out for 96 DPI — tiny text
    # on scaled Windows displays. Level 1 (system-aware) rather than
    # per-monitor: Tk 8.6 ignores WM_DPICHANGED, so DWM must handle
    # cross-monitor rescaling.
    if sys.platform == "win32":
        try:
            from ctypes import windll
            try:
                windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                windll.user32.SetProcessDPIAware()  # pre-Win8.1 fallback
        except Exception:
            pass
    root = tk.Tk()
    apply_theme(root, _ui_scale(root))
    _set_app_icon(root)
    FetchlyApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
