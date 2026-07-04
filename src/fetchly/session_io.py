"""Save and reopen complete crawl sessions (.fetchly.json.gz).

One gzipped JSON file holds the config, every PageResult, and every Issue,
so a crawl can be reopened (GUI) or re-exported (CLI --open) without
recrawling. Credentials (login_data) are never written.
"""

import dataclasses
import gzip
import json

from .audit import Issue
from .config import CrawlConfig
from .models import PageResult

FORMAT_VERSION = 1


def save_crawl(path: str, config: CrawlConfig, results, issues) -> None:
    config_dict = dict(vars(config))
    config_dict["login_data"] = {}  # never persist credentials
    data = {
        "format": FORMAT_VERSION,
        "config": config_dict,
        "results": [vars(r) for r in results],
        "issues": [vars(i) for i in issues],
    }
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(data, fh)


def load_crawl(path: str):
    """Returns (config, results, issues). Unknown fields are ignored so old
    files keep loading after the dataclasses grow new fields."""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("format") != FORMAT_VERSION:
        raise ValueError(f"{path}: unsupported crawl-file format {data.get('format')!r}")

    def build(cls, d):
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})

    config = build(CrawlConfig, data["config"])
    results = [build(PageResult, r) for r in data["results"]]
    issues = [build(Issue, i) for i in data["issues"]]
    return config, results, issues
