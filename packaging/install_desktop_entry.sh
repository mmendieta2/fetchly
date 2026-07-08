#!/usr/bin/env bash
# Add Fetchly to the Linux application menu (user-level, no sudo).
#
# Works with any install method that puts fetchly-gui on PATH (pipx, pip in
# a venv, pip --user): it resolves the real executable, pulls the app icon
# out of the installed package, and writes an XDG desktop entry to
# ~/.local/share/applications. Run again after moving the install; remove
# with: rm ~/.local/share/applications/fetchly.desktop
set -euo pipefail

bin=$(command -v fetchly-gui) || {
    echo "error: fetchly-gui not found on PATH — install Fetchly first" >&2
    exit 1
}
bin=$(readlink -f "$bin")

# The icon ships inside the package: <env>/lib/python*/site-packages/fetchly/
env_root=$(dirname "$(dirname "$bin")")
icon_src=$(find "$env_root" -path "*/fetchly/gui/assets/icon_256.png" -print -quit)
[ -n "$icon_src" ] || { echo "error: icon_256.png not found under $env_root" >&2; exit 1; }

apps_dir=${XDG_DATA_HOME:-$HOME/.local/share}/applications
icon_dir=${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps
mkdir -p "$apps_dir" "$icon_dir"
cp "$icon_src" "$icon_dir/fetchly.png"

cat > "$apps_dir/fetchly.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Fetchly
GenericName=Website Crawler
Comment=Crawl and audit websites, producing CSV reports
Exec=$bin
Icon=fetchly
Terminal=false
Categories=Network;WebDevelopment;
Keywords=crawler;SEO;audit;sitemap;broken links;
StartupWMClass=Fetchly
EOF

update-desktop-database "$apps_dir" 2>/dev/null || true
gtk-update-icon-cache "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true

echo "Installed $apps_dir/fetchly.desktop"
echo "  Exec: $bin"
echo "Fetchly should now appear in your application menu (log out/in if not)."
