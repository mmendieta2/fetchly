"""Fetchly GUI: Tkinter front end.

Tkinter ships with CPython on Windows 10/11, macOS, and Linux, so the GUI
needs no extra GUI toolkit installed. The crawl runs on background threads
inside CrawlEngine; this window polls engine.events every 100 ms via
Tk's after() so every widget update happens on the main thread.
"""

import queue
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import events
from ..config import CrawlConfig
from ..engine import CrawlEngine
from ..report import issues_path_for, write_issues, write_report
from ..sitemap import write_sitemap

POLL_MS = 100


class FetchlyApp(ttk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root, padding=10)
        self.root = root
        self.engine = None
        self._last_config = None
        self.results = []
        self.issues = []
        root.title("Fetchly — Website Crawler")
        root.geometry("980x640")
        root.minsize(760, 480)
        self.pack(fill="both", expand=True)
        self._build_form()
        self._build_table()
        self._build_statusbar()
        self._install_context_menus()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- layout -------------------------------------------------------------

    def _build_form(self) -> None:
        form = ttk.LabelFrame(self, text="Crawl settings", padding=8)
        form.pack(fill="x")

        ttk.Label(form, text="Start URL:").grid(row=0, column=0, sticky="w")
        self.url_var = tk.StringVar(value="https://")
        url_entry = ttk.Entry(form, textvariable=self.url_var)
        url_entry.grid(row=0, column=1, columnspan=5, sticky="ew", padx=(4, 0))
        url_entry.focus_set()

        self.max_pages_var = tk.StringVar(value="200")
        self.max_depth_var = tk.StringVar(value="5")
        self.workers_var = tk.StringVar(value="8")
        self.delay_var = tk.StringVar(value="0")
        for col, (label, var) in enumerate((
            ("Max pages:", self.max_pages_var),
            ("Max depth:", self.max_depth_var),
            ("Workers:", self.workers_var),
        )):
            ttk.Label(form, text=label).grid(row=1, column=col * 2, sticky="w", pady=(6, 0))
            ttk.Entry(form, textvariable=var, width=7).grid(
                row=1, column=col * 2 + 1, sticky="w", padx=(4, 12), pady=(6, 0))

        ttk.Label(form, text="Delay (s):").grid(row=2, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.delay_var, width=7).grid(row=2, column=1, sticky="w", padx=(4, 12))

        self.retries_var = tk.StringVar(value="2")
        ttk.Label(form, text="Retries:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.retries_var, width=7).grid(
            row=3, column=1, sticky="w", padx=(4, 12), pady=(6, 0))

        self.extract_var = tk.StringVar(value="")
        ttk.Label(form, text="Extract:").grid(row=4, column=0, sticky="w", pady=(6, 0))
        extract_entry = ttk.Entry(form, textvariable=self.extract_var)
        extract_entry.grid(row=4, column=1, columnspan=5, sticky="ew", padx=(4, 0), pady=(6, 0))
        extract_entry.insert(0, "")
        ttk.Label(form, foreground="#777",
                  text='Optional, ";"-separated: name=css:selector or name=re:pattern'
                  ).grid(row=5, column=1, columnspan=5, sticky="w", padx=(4, 0))

        self.segments_var = tk.StringVar(value="")
        ttk.Label(form, text="Segments:").grid(row=6, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.segments_var).grid(
            row=6, column=1, columnspan=5, sticky="ew", padx=(4, 0), pady=(6, 0))

        self.robots_file_var = tk.StringVar(value="")
        ttk.Label(form, text="Robots file:").grid(row=7, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.robots_file_var).grid(
            row=7, column=1, columnspan=3, sticky="ew", padx=(4, 0), pady=(6, 0))

        self.login_url_var = tk.StringVar(value="")
        self.login_fields_var = tk.StringVar(value="")
        ttk.Label(form, text="Login URL:").grid(row=8, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.login_url_var).grid(
            row=8, column=1, columnspan=2, sticky="ew", padx=(4, 12), pady=(6, 0))
        ttk.Label(form, text="Login fields:").grid(row=8, column=3, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.login_fields_var, show="*").grid(
            row=8, column=4, columnspan=2, sticky="ew", padx=(4, 0), pady=(6, 0))

        self.user_agent_var = tk.StringVar(value=CrawlConfig.user_agent)
        ttk.Label(form, text="User agent:").grid(row=9, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.user_agent_var).grid(
            row=9, column=1, columnspan=5, sticky="ew", padx=(4, 0), pady=(6, 0))

        self.subdomains_var = tk.BooleanVar(value=False)
        self.robots_var = tk.BooleanVar(value=True)
        self.render_js_var = tk.BooleanVar(value=False)
        self.mobile_var = tk.BooleanVar(value=False)
        self.a11y_var = tk.BooleanVar(value=False)
        self.spellcheck_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="Mobile usability", variable=self.mobile_var).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(form, text="Accessibility (axe)", variable=self.a11y_var).grid(
            row=10, column=2, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(form, text="Spellcheck", variable=self.spellcheck_var).grid(
            row=10, column=4, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(form, text="Include subdomains", variable=self.subdomains_var).grid(
            row=2, column=2, columnspan=2, sticky="w")
        ttk.Checkbutton(form, text="Respect robots.txt", variable=self.robots_var).grid(
            row=2, column=4, columnspan=2, sticky="w")
        ttk.Checkbutton(form, text="Render JavaScript (needs fetchly[js])",
                        variable=self.render_js_var).grid(
            row=3, column=2, columnspan=4, sticky="w")

        form.columnconfigure(5, weight=1)

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=8)
        self.start_btn = ttk.Button(buttons, text="Start crawl", command=self._start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(buttons, text="Stop", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        self.export_btn = ttk.Button(buttons, text="Export CSV…", command=self._export, state="disabled")
        self.export_btn.pack(side="left")
        self.sitemap_btn = ttk.Button(buttons, text="Export Sitemap…",
                                      command=self._export_sitemap, state="disabled")
        self.sitemap_btn.pack(side="left", padx=6)
        self.graph_btn = ttk.Button(buttons, text="Export Graph…",
                                    command=self._export_graph, state="disabled")
        self.graph_btn.pack(side="left")
        self.save_btn = ttk.Button(buttons, text="Save Crawl…",
                                   command=self._save_crawl, state="disabled")
        self.save_btn.pack(side="left", padx=6)
        ttk.Button(buttons, text="Open Crawl…", command=self._open_crawl).pack(side="left")

    def _make_tree(self, parent, headers) -> ttk.Treeview:
        tree = ttk.Treeview(parent, columns=tuple(headers), show="headings")
        for col, (text, width, stretch) in headers.items():
            tree.heading(col, text=text)
            tree.column(col, width=width, stretch=stretch)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        tree.tag_configure("error", foreground="#c0392b")
        tree.tag_configure("warning", foreground="#b9770e")
        return tree

    def _build_table(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        pages_tab = ttk.Frame(self.notebook)
        self.notebook.add(pages_tab, text="Pages")
        self.tree = self._make_tree(pages_tab, {
            "status": ("Status", 70, False), "depth": ("Depth", 60, False),
            "time": ("ms", 70, False), "segment": ("Segment", 90, False),
            "title": ("Title", 240, True), "url": ("URL", 400, True)})

        issues_tab = ttk.Frame(self.notebook)
        self.notebook.add(issues_tab, text="Issues")
        self.issues_tree = self._make_tree(issues_tab, {
            "severity": ("Severity", 80, False), "type": ("Type", 170, False),
            "page": ("Page", 340, True), "detail": ("Detail", 340, True)})
        # The detail column clips long messages; double-click or Enter opens
        # the full text (also on the right-click menu).
        self.issues_tree.bind("<Double-1>", self._show_issue_detail)
        self.issues_tree.bind("<Return>", self._show_issue_detail)

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
        for tree in (self.tree, self.issues_tree):
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
        win.geometry("560x340")
        win.transient(self.root)
        text = tk.Text(win, wrap="word", padx=10, pady=10, height=12,
                       relief="flat", background=self.root.cget("background"))
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

    def _build_statusbar(self) -> None:
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status_var, anchor="w").pack(fill="x", pady=(6, 0))

    # -- actions ------------------------------------------------------------

    def _read_config(self) -> CrawlConfig:
        return CrawlConfig(
            start_url=self.url_var.get().strip(),
            max_pages=int(self.max_pages_var.get()),
            max_depth=int(self.max_depth_var.get()),
            num_workers=int(self.workers_var.get()),
            delay_seconds=float(self.delay_var.get() or 0),
            max_retries=int(self.retries_var.get() or 0),
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
        )

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
        self.notebook.tab(1, text="Issues")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.export_btn.configure(state="disabled")
        self.sitemap_btn.configure(state="disabled")
        self.graph_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")
        self.status_var.set(f"Crawling {config.start_url}…")
        self.root.after(POLL_MS, self._poll)

    def _stop(self) -> None:
        if self.engine:
            self.engine.stop()
            self.status_var.set("Stopping…")

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
        tags = ("error",) if (r.error or r.status_code >= 400) else ()
        self.tree.insert("", "end", values=(
            r.status_code or "ERR", r.depth, r.elapsed_ms, r.segment, r.title, r.url),
            tags=tags)
        s = event.stats
        self.status_var.set(
            f"Crawled {s.crawled}  |  queued {s.queued}  |  errors {s.errors}  |  "
            f"issues {len(self.issues)}  |  {s.bytes_downloaded / 1024:.0f} KiB")

    def _add_issues(self, issues) -> None:
        for issue in issues:
            self.issues.append(issue)
            self.issues_tree.insert("", "end", values=(
                issue.severity, issue.issue_type, issue.page_url, issue.detail),
                tags=(issue.severity,))
        if issues:
            self.notebook.tab(1, text=f"Issues ({len(self.issues)})")

    def _on_finished(self, event) -> None:
        self.engine = None
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.export_btn.configure(state="normal" if self.results else "disabled")
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
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile="fetchly_report.csv")
        if not path:
            return
        extract_names = []
        for r in self.results:
            for name in r.extracted:
                if name not in extract_names:
                    extract_names.append(name)
        write_report(path, self.results, extra_fields=extract_names)
        issues_path = issues_path_for(path)
        write_issues(issues_path, self.issues)
        self.status_var.set(f"Saved {path} and {issues_path}")

    def _export_sitemap(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".xml",
            filetypes=[("XML files", "*.xml"), ("All files", "*.*")],
            initialfile="sitemap.xml")
        if not path:
            return
        count = write_sitemap(path, self.results)
        self.status_var.set(f"Sitemap saved to {path} ({count} indexable URLs)")

    def _export_graph(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".html",
            filetypes=[("HTML files", "*.html"), ("All files", "*.*")],
            initialfile="crawl_graph.html")
        if not path:
            return
        from ..viz import write_graph
        count = write_graph(path, self.results)
        self.status_var.set(f"Graph saved to {path} ({count} nodes)")

    def _save_crawl(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".fetchly.json.gz",
            filetypes=[("Fetchly crawls", "*.fetchly.json.gz"), ("All files", "*.*")],
            initialfile="crawl.fetchly.json.gz")
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
            tags = ("error",) if (r.error or r.status_code >= 400) else ()
            self.tree.insert("", "end", values=(
                r.status_code or "ERR", r.depth, r.elapsed_ms, r.segment, r.title, r.url),
                tags=tags)
        self._add_issues(issues)
        self.notebook.tab(1, text=f"Issues ({len(self.issues)})" if self.issues else "Issues")
        self.export_btn.configure(state="normal" if self.results else "disabled")
        self.sitemap_btn.configure(state="normal" if self.results else "disabled")
        self.graph_btn.configure(state="normal" if self.results else "disabled")
        self.save_btn.configure(state="normal" if self.results else "disabled")
        self.status_var.set(
            f"Opened {path}: {len(self.results)} pages, {len(self.issues)} issues "
            f"(crawl of {config.start_url})")

    def _on_close(self) -> None:
        if self.engine:
            self.engine.stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:  # Better scaling on Windows HiDPI displays.
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    FetchlyApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
