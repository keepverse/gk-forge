"""seedsmith.numerics — resolves bands to magnitudes (spec-numerics.md). P1's home: a model never
picks a number, and no number is ever stored in a seed file.

Depends on `adapter.channels()`, not on `gk-data/packs/fusion/data/seed/items/` directly (spec-foundation §7.1, B2) —
the locked SHAPE constants below (`MAGNITUDE_RATIO`, band width, `DURATION_RATIO`) are transcribed
once from `bands.v1.json`'s `tierScaling` block, with citation, exactly like
`adapters.items.channels` transcribes `BattleRuleset`; this module never opens that file itself,
which is what lets it resolve against the stub adapter with no `bands.v1.json` on disk at all.
"""
from __future__ import annotations

from .formulas import round_legible
from .model import (
    BAND_CEILING_PERMILLE,
    BAND_FLOOR_PERMILLE,
    DURATION_RATIO_PERMILLE,
    MAGNITUDE_RATIO_PERMILLE,
    REFERENCE_LEVEL,
    TIER_COUNT,
    BattleRulesetProgression,
    NumericsContext,
    OpWeight,
    ProgressionModel,
    ProgressionPoint,
    TierBands,
)
from .resolve import (
    CalibrationLevelError,
    UnsharedChannelError,
    explain,
    resolve,
)
from .rebalance import RebalanceReport, rebalance, solve_base_share
from .apportion import largest_remainder_apportion
from . import tier_bands_io

__all__ = [
    "largest_remainder_apportion", "tier_bands_io",
    "BAND_CEILING_PERMILLE", "BAND_FLOOR_PERMILLE", "DURATION_RATIO_PERMILLE",
    "MAGNITUDE_RATIO_PERMILLE", "REFERENCE_LEVEL", "TIER_COUNT",
    "BattleRulesetProgression", "NumericsContext", "OpWeight", "ProgressionModel",
    "ProgressionPoint", "TierBands",
    "CalibrationLevelError", "UnsharedChannelError", "explain", "resolve",
    "RebalanceReport", "rebalance", "solve_base_share", "round_legible",
]
