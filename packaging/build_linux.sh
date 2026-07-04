#!/usr/bin/env bash
# Build standalone Linux binaries: packaging/dist/Fetchly (GUI) + fetchly-cli.
# Note: the binaries link this machine's glibc — build on the oldest distro
# you intend to support. Tk must be installed (the Tk libs get bundled).
set -euo pipefail
cd "$(dirname "$0")"

python3 -m venv .buildvenv
.buildvenv/bin/pip install --quiet --upgrade pip
.buildvenv/bin/pip install --quiet .. pyinstaller
.buildvenv/bin/pyinstaller fetchly.spec --distpath dist --workpath build --noconfirm

echo
echo "Built: $(ls dist)"
echo "Users just run ./Fetchly (GUI) or ./fetchly-cli <url> — no Python needed."
