"""seedsmith.adapters.actions.usage_direction.weights --- FC3's own core: real usage counts (FC1)
in, a per-family weight and a legible rendering cue out. Pure and model-free.

**Direction is a bias, not a cage — the one rule that must never break.** An under-used family is
rendered more prominently; it is never made the pool's only option and the pool itself
(`allowedAtomFamilies`) is never touched by anything in this module. There is nothing here that
COULD narrow the pool -- `weight_milli`/`render_cue` only ever produce a number and a label for a
family that is already in the caller's own eligible set, which is exactly what makes
`spec-distribution-planner.md` constraint 4 (the C1 tier-widening gate) structurally unreachable
from this module rather than merely respected by convention.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

__all__ = ["FLOOR_WEIGHT_MILLI", "CEILING_WEIGHT_MILLI", "target_share_milli",
          "weight_milli", "weights_for", "render_cue", "CUE_LABEL",
          "weights_from_usage_report", "latest_usage_report_path"]

#: Every family starts here even at or above its target share -- a weight is never negative and
#: never zero, so a family already well-served still appears (with no special cue), never
#: disappears from consideration.
FLOOR_WEIGHT_MILLI = 1000

#: The strongest boost a zero-usage family can receive -- a real ceiling, not an unbounded blowup,
#: so one badly-neglected family cannot make every other rendering decision moot.
CEILING_WEIGHT_MILLI = 3000

#: Above this weight, a family's rendering carries the legible "underused" cue (spec: "a short
#: 'underused, consider this' marker on families above the median weight"). Set at the floor's own
#: 1.5x -- comfortably above FLOOR_WEIGHT_MILLI so an already-adequate family never gets flagged.
CUE_THRESHOLD_MILLI = 1500

CUE_LABEL = "underused, consider this"


def target_share_milli(population_size: int) -> int:
    """The flat-uniform target -- deliberately the simplest honest target, not a hand-tuned curve
    (spec: "what would overturn it: real evidence a flat target under/over-corrects"). Per-mille,
    integer division, so `98` families gives `1000 // 98 = 10`, never a float."""
    if population_size <= 0:
        raise ValueError("target_share_milli: population_size must be positive")
    return 1000 // population_size


def weight_milli(family: str, usage: Mapping[str, int], *, population_size: int) -> int:
    """A family with zero picks gets the ceiling; a family already at or above the flat-uniform
    target gets the floor; linear in the deficit between them. Per-mille integers throughout --
    widened before multiplying, exactly this repo's own numeric contract for any magnitude a
    balance surface could touch."""
    total = sum(usage.values())
    target_milli = target_share_milli(population_size)
    if total == 0:
        # no usage history at all yet -- every family is equally unproven, ceiling for none of them
        return FLOOR_WEIGHT_MILLI
    observed_milli = (usage.get(family, 0) * 1000) // total
    if observed_milli >= target_milli:
        return FLOOR_WEIGHT_MILLI
    deficit_milli = target_milli - observed_milli
    # deficit_milli is in [1, target_milli]; scale it onto [0, CEILING-FLOOR] linearly.
    span = CEILING_WEIGHT_MILLI - FLOOR_WEIGHT_MILLI
    boost = (deficit_milli * span) // max(1, target_milli)
    return FLOOR_WEIGHT_MILLI + boost


def weights_for(families: "list[str]", usage: Mapping[str, int], *,
                population_size: int) -> "dict[str, int]":
    """Every weight for a given eligible-family list, in one call -- the shape a caller actually
    wants (never one-at-a-time in a hot loop). Sorted output for determinism; the CALLER's own
    ordering of `families` is untouched, since rendering order is `order_for`'s own concern, not
    this module's."""
    return {f: weight_milli(f, usage, population_size=population_size) for f in sorted(set(families))}


def latest_usage_report_path(reports_dir: Path) -> "Path | None":
    """The most recently written FC1 report (`_usage-<date>.json`), sorted lexicographically --
    ISO dates sort correctly as strings, so this needs no date parsing. `None` when none exist yet
    (a caller falls back to `usage_weights=None`, the byte-identical-to-today default)."""
    candidates = sorted(reports_dir.glob("_usage-*.json"))
    return candidates[-1] if candidates else None


def weights_from_usage_report(report: "Mapping[str, Any]") -> "dict[str, int]":
    """The real integration point: FC1's own emitted report (`allTime.counts`, `populationSize`)
    straight into real weights -- no re-tallying, no re-deriving the population, just the pure
    function applied to what FC1 already measured. This is what makes the mechanism's correctness
    checkable against real committed data at zero cost: FC1's report is real, committed, and
    already proven byte-identical across runs (`test_usage_stats.py`)."""
    counts = report["allTime"]["counts"]
    population_size = report["populationSize"]
    # every family in the population needs a weight, not only the ones with a nonzero count --
    # weights_for's own `families` argument is the FULL set to weight, not just the used ones.
    never_used_families = report["allTime"]["neverUsed"]
    all_families = sorted(set(counts) | set(never_used_families))
    return weights_for(all_families, counts, population_size=population_size)


def render_cue(family: str, weights: Mapping[str, int]) -> "str | None":
    """The legible, human-readable cue a rendering function appends -- never a raw number. Returns
    `None` when the family does not clear the threshold, so a caller renders it exactly as before
    (the byte-identical-when-unweighted contract lives one level up, in the caller, but this
    function's own contribution to it is: no weight info at all above the threshold means no cue at
    all, never a cue that leaks the underlying number)."""
    w = weights.get(family)
    if w is None or w < CUE_THRESHOLD_MILLI:
        return None
    return CUE_LABEL
