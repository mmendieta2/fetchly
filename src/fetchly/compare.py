"""Compare two crawl report CSVs: fetchly-compare old.csv new.csv.

Post-processes report files only — no crawling. Useful for tracking issue
progress between audits or comparing staging against production output.
"""

import argparse
import csv
import sys

_TRACKED_FIELDS = ("status_code", "title", "meta_description", "canonical_url",
                   "redirected_to", "word_count")


def load_report(path: str) -> "dict[str, dict]":
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if rows and "url" not in rows[0]:
        raise ValueError(f"{path} is not a fetchly page report (no 'url' column)")
    return {row["url"]: row for row in rows}


def diff_reports(old: "dict[str, dict]", new: "dict[str, dict]") -> dict:
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = {}
    for url in sorted(set(old) & set(new)):
        field_changes = {}
        for field in _TRACKED_FIELDS:
            before, after = old[url].get(field, ""), new[url].get(field, "")
            if before != after:
                field_changes[field] = (before, after)
        if field_changes:
            changed[url] = field_changes
    return {"added": added, "removed": removed, "changed": changed}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="fetchly-compare",
                                description="Diff two fetchly page-report CSVs.")
    p.add_argument("old_csv")
    p.add_argument("new_csv")
    p.add_argument("-q", "--quiet", action="store_true",
                   help="Summary counts only, no per-URL detail")
    args = p.parse_args(argv)

    try:
        old, new = load_report(args.old_csv), load_report(args.new_csv)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    diff = diff_reports(old, new)
    print(f"Old: {len(old)} pages ({args.old_csv})")
    print(f"New: {len(new)} pages ({args.new_csv})")
    print(f"Added: {len(diff['added'])}  Removed: {len(diff['removed'])}  "
          f"Changed: {len(diff['changed'])}")

    if not args.quiet:
        for url in diff["added"]:
            print(f"  + {url}")
        for url in diff["removed"]:
            print(f"  - {url}")
        for url, fields in diff["changed"].items():
            print(f"  ~ {url}")
            for field, (before, after) in fields.items():
                print(f"      {field}: {before!r} -> {after!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
