"""`python -m seedsmith` entry point.

Lives at `seedsmith/__main__.py`, not `seedsmith.py` beside the `seedsmith/` package — the latter
would shadow the package on `sys.path` (spec-foundation §7.5, N3).
"""
from __future__ import annotations

import sys

from .report.cli import main

if __name__ == "__main__":
    sys.exit(main())
