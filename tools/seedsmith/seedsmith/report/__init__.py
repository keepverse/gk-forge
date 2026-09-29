"""seedsmith.report — findings out: human CLI, JSON out, exit codes (spec-foundation §3)."""
from __future__ import annotations

from .cli import EXIT_CANNOT_RUN, EXIT_CLEAN, EXIT_ESCALATED, EXIT_GAP, EXIT_REFUSED, main

__all__ = ["EXIT_CANNOT_RUN", "EXIT_CLEAN", "EXIT_ESCALATED", "EXIT_GAP", "EXIT_REFUSED", "main"]
