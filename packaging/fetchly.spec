# -*- mode: python ; coding: utf-8 -*-
# Shared PyInstaller spec for all platforms. Build ON the target OS:
#   Windows: build_windows.bat   macOS: build_macos.sh   Linux: build_linux.sh
# Produces two one-file targets: Fetchly (windowed GUI) and fetchly-cli (console).

import sys

# Playwright (optional fetchly[js] extra) is deliberately excluded: it would
# add ~300 MB and still require `playwright install chromium` on the user's
# machine. The engine imports jsfetch lazily, so the build stays clean.
EXCLUDES = ["playwright", "pytest"]
# Bundle vendored assets (axe-core for --a11y) alongside the package.
DATAS = [("../src/fetchly/vendor", "fetchly/vendor")]

gui_a = Analysis(
    ["launch_gui.py"],
    pathex=["../src"],
    datas=DATAS,
    excludes=EXCLUDES,
)
cli_a = Analysis(
    ["launch_cli.py"],
    pathex=["../src"],
    datas=DATAS,
    excludes=EXCLUDES,
)

gui_exe = EXE(
    PYZ(gui_a.pure),
    gui_a.scripts,
    gui_a.binaries,
    gui_a.datas,
    [],
    name="Fetchly",
    console=False,          # windowed: no console behind the GUI
    upx=False,
    # icon="fetchly.ico",   # add when an icon asset exists
)

cli_exe = EXE(
    PYZ(cli_a.pure),
    cli_a.scripts,
    cli_a.binaries,
    cli_a.datas,
    [],
    name="fetchly-cli",
    console=True,
    upx=False,
)

if sys.platform == "darwin":
    app = BUNDLE(
        gui_exe,
        name="Fetchly.app",
        bundle_identifier="com.fetchly.crawler",
    )
