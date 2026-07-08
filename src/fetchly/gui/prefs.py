"""Persist GUI preferences between launches.

One JSON file in the platform's config location (overridable via
FETCHLY_PREFS_FILE, which the tests use for isolation). Stores the
settings-form values and the theme choice; login credentials are never
saved. All I/O is best-effort — a missing or corrupt file just means
defaults.
"""

import json
import os
import sys


def _path() -> str:
    override = os.environ.get("FETCHLY_PREFS_FILE")
    if override:
        return override
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Fetchly", "settings.json")
    if sys.platform == "darwin":
        return os.path.expanduser(
            "~/Library/Application Support/Fetchly/settings.json")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "fetchly", "settings.json")


def load() -> dict:
    try:
        with open(_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(values: dict) -> None:
    path = _path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(values, fh, indent=2, sort_keys=True)
    except OSError:
        pass
