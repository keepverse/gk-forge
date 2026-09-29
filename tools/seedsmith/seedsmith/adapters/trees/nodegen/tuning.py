"""seedsmith.adapters.trees.nodegen.tuning — load `passive-tree-targets.v2.json`; every key
required, no defaults (task H1, spec-tree-language.md §4.3, §7 gate 4).

**Not a second parser.** Task A2 already shipped the pure parser over this exact file at
`adapters.trees.targets` (`PassiveTreeTargets`, `GATING_METRICS`, `missing_thresholds`) — the
`setgen/tuning.py:94-102` mould §7 gate 4 names ("refusing to substitute a default; an unreviewed
number here reaches every generated entry") is already satisfied there. This module re-exports it
under the name `spec-tree-language.md`'s own "Project structure" section gives the file, so every
`nodegen.*` module imports its tuning from one place (`from . import tuning`) without caring which
task originally wrote the parser.
"""
from __future__ import annotations

from ..targets import (
    GATING_METRICS,
    AcceptanceRung,
    PassiveTreeTargets,
    PassiveTreeTargetsError,
    SkewRow,
    load,
    missing_thresholds,
)

__all__ = [
    "PassiveTreeTargets",
    "PassiveTreeTargetsError",
    "SkewRow",
    "AcceptanceRung",
    "GATING_METRICS",
    "load",
    "missing_thresholds",
]
