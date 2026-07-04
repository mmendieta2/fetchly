"""Fetchly GUI: Tkinter front end.

Tkinter ships with CPython on Windows 10/11, macOS, and Linux, so the GUI
needs no extra GUI toolkit installed. The crawl runs on background threads
inside CrawlEngine; this window polls engine.events every 100 ms via
Tk's after() so every widget update happens on the main thread.
"""

import queue
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
        self.results = []
        self.issues = []
        root.title("Fetchly — Website Crawler")
        root.geometry("980x640")
        root.minsize(760, 480)
        self.pack(fill="both", expand=True)
        self._build_form()
        self._build_table()
        self._build_statusbar()
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

        self.subdomains_var = tk.BooleanVar(value=False)
        self.robots_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text="Include subdomains", variable=self.subdomains_var).grid(
            row=2, column=2, columnspan=2, sticky="w")
        ttk.Checkbutton(form, text="Respect robots.txt", variable=self.robots_var).grid(
            row=2, column=4, columnspan=2, sticky="w")

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
        self.progress = ttk.Progressbar(buttons, mode="determinate", length=220)
        self.progress.pack(side="right")

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
            "time": ("ms", 70, False), "title": ("Title", 260, True),
            "url": ("URL", 420, True)})

        issues_tab = ttk.Frame(self.notebook)
        self.notebook.add(issues_tab, text="Issues")
        self.issues_tree = self._make_tree(issues_tab, {
            "severity": ("Severity", 80, False), "type": ("Type", 170, False),
            "page": ("Page", 340, True), "detail": ("Detail", 340, True)})

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
            include_subdomains=self.subdomains_var.get(),
            respect_robots=self.robots_var.get(),
        )

    def _start(self) -> None:
        try:
            config = self._read_config()
            engine = CrawlEngine(config)
            engine.start()
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return
        self.engine = engine
        self.results = []
        self.issues = []
        self.tree.delete(*self.tree.get_children())
        self.issues_tree.delete(*self.issues_tree.get_children())
        self.notebook.tab(1, text="Issues")
        self.progress.configure(maximum=config.max_pages, value=0)
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.export_btn.configure(state="disabled")
        self.sitemap_btn.configure(state="disabled")
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
            r.status_code or "ERR", r.depth, r.elapsed_ms, r.title, r.url), tags=tags)
        s = event.stats
        self.progress.configure(value=s.crawled)
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
        write_report(path, self.results)
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
