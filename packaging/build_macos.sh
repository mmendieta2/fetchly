#!/usr/bin/env bash
# Build standalone macOS artifacts: packaging/dist/Fetchly.app + fetchly-cli.
# Builds are architecture-specific (Apple Silicon vs Intel) — build on each,
# and on the oldest macOS version you intend to support.
set -euo pipefail
cd "$(dirname "$0")"

python3 -m venv .buildvenv
.buildvenv/bin/pip install --quiet --upgrade pip
.buildvenv/bin/pip install --quiet .. pyinstaller
.buildvenv/bin/pyinstaller fetchly.spec --distpath dist --workpath build --noconfirm

echo
echo "Built: $(ls dist)"
echo "NOTE: the app is unsigned (code signing requires a paid Apple Developer"
echo "account). First launch: right-click Fetchly.app -> Open, or run:"
echo "  xattr -dr com.apple.quarantine dist/Fetchly.app"
