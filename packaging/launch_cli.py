"""PyInstaller entry point for the CLI build."""

import sys

from fetchly.cli import main

if __name__ == "__main__":
    sys.exit(main())
