"""Executable entry point when invoked as python -m paperharbor."""

import sys
from paperharbor.cli import run_cli

if __name__ == "__main__":
    sys.exit(run_cli())
