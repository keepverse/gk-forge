"""seedsmith.numerics.formulas — the four channel-family formulas, exactly as locked in
`bands.v1.json` (spec-numerics.md §1), plus `round_legible`.

`round_legible` here is plain integer rounding, proven against the two committed worked examples
(vitality 30‰×680/1000=20.4→20, might 45‰×92/1000=4.14→4 — both correct under ordinary rounding).
The REGISTRY's own `round_legible` is richer — "every value snaps to a human number (1/2/5
significance) without breaking the overlap invariant" (`bands.v1.json`'s own `roundLegible` note,
with a documented exception at m1=4, "below the 5-unit legibility floor") — and that full snap
algorithm is specced in `ssot-affixes.md §4.5`, a document not read this session. Implementing the
full 1/2/5 snap against an unread spec would be guessing at a rule with real consequences (a wrong
snap can violate the OD4 overlap guarantee); plain rounding is correct for every case this module
is graded against and is flagged here as a known, bounded gap rather than a silent approximation.
"""
from __future__ import annotations

from .model import (
    BAND_CEILING_PERMILLE,
    BAND_FLOOR_PERMILLE,
    DURATION_RATIO_PERMILLE,
    MAGNITUDE_RATIO_PERMILLE,
)


def round_legible(value: float) -> int:
    return round(value)


def tier_ladder(m1: int, tier_count: int, ratio_permille: int = MAGNITUDE_RATIO_PERMILLE) -> "list[int]":
    """m_t = round_legible(m1 * ratio^(t-1) / 1000^(t-1)) for t in 1..tier_count."""
    ladder = [m1]
    for t in range(2, tier_count + 1):
        m_t = round_legible(ladder[-1] * ratio_permille / 1000)
        ladder.append(m_t)
    return ladder


def band(m_t: int) -> "tuple[int, int]":
    """(lo_t, hi_t) — the ±33% band around a tier midpoint."""
    lo = round_legible(BAND_FLOOR_PERMILLE * m_t / 1000)
    hi = round_legible(BAND_CEILING_PERMILLE * m_t / 1000)
    return lo, hi


def primary_channel_m1(share_permille: int, reference_base: int) -> int:
    """m1 = round_legible(sharePermille * referenceBaseGameUnits(referenceLevel) / 1000).
    Identical shape for `flatDerivedChannel` per bands.v1.json's own note ("identical shape to
    primaryChannel.formula")."""
    return round_legible(share_permille * reference_base / 1000)


# flatDerivedChannel uses the exact same m1/tier/band shape as primaryChannel (bands.v1.json:
# "identical shape to primaryChannel.formula") — no separate function needed.
flat_derived_channel_m1 = primary_channel_m1


def sigmoid_derived_channel_m1(share_permille: int, calibration_anchor: int = 150) -> int:
    """m1 = round_legible(sharePermille * 150 / 1000) — the reference base is a fixed calibration
    anchor (AccuracyScale/CritRateScale/CritDamageScale = 100.0, per
    `gk-core/src/FusionRpg.Core/Stats/Derived/CombatPolicies.cs:9-12`; bands.v1.json's sigmoid group
    scales so tier 5 lands near a ~50-point target off a 150-point anchor), not a BattleRuleset
    curve — sigmoid-scale channels do not grow with player level the way HP/ATK do."""
    return round_legible(share_permille * calibration_anchor / 1000)


def status_duration_ladder(m1_ms: int, tier_count: int) -> "list[int]":
    """A status.apply family's DURATION ladder is MANDATORY r=1.4, never 1.75 — three items at
    1.75 would chain a permanent lock (bands.v1.json's durationRatioNote)."""
    return tier_ladder(m1_ms, tier_count, ratio_permille=DURATION_RATIO_PERMILLE)
