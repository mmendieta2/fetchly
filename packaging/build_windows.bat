@echo off
REM Build standalone Windows executables: packaging\dist\Fetchly.exe (GUI)
REM and fetchly-cli.exe (console). Requires Python 3.9+ from python.org.
cd /d "%~dp0"

py -m venv .buildvenv || exit /b 1
.buildvenv\Scripts\pip install --quiet --upgrade pip || exit /b 1
.buildvenv\Scripts\pip install --quiet .. pyinstaller || exit /b 1
.buildvenv\Scripts\pyinstaller fetchly.spec --distpath dist --workpath build --noconfirm || exit /b 1

echo.
echo Built executables are in packaging\dist\
echo NOTE: binaries are unsigned; on first run SmartScreen may warn -
echo click "More info" then "Run anyway".
