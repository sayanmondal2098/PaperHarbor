#!/usr/bin/env python3
"""PaperHarbor entrypoint."""

import sys
from paperharbor.cli import run_cli

if __name__ == "__main__":
    sys.exit(run_cli())
