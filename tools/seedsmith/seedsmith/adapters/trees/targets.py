"""seedsmith.adapters.trees.targets — the pure parser over `gk-core/data/tuning/passive-tree-targets.v2.json`
(task A2, spec-tree-plan.md §8, spec-tree-language.md §4.3, spec-tree-review.md §6.3,
spec-species-tree.md §3.2/§5.3).

Foundation module, ahead of B1's `plan.py`/H3's quota stage: `tree-plan` §8's quota algorithm
cannot run without this file existing and loading cleanly, so it ships now rather than being
discovered as a missing dependency mid-B1. `plan.py` and the quota stage import `load()` from here
rather than re-parsing the file.

One class, no defaults, no fallbacks: a missing key raises rather than substituting a plausible
number (T5) — mirrors `adapters.items.setgen.tuning`'s `_require` mould exactly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
TARGETS_PATH = REPO_ROOT / "data" / "tuning" / "passive-tree-targets.v2.json"


class PassiveTreeTargetsError(ValueError):
    """The targets file is structurally unusable. Raised at load, so a defect lands before the
    quota algorithm runs rather than mid-corpus."""


@dataclass(frozen=True)
class SkewRow:
    axis: str
    member: str
    weight_milli: int
    why: str


@dataclass(frozen=True)
class AcceptanceRung:
    rejects_in_60: int
    upper_bound_permille_95: int
    verdict: str


@dataclass(frozen=True)
class PassiveTreeTargets:
    aptitude_weight_scheme: str

    node_class_weights_milli: "tuple[int, ...]"
    node_class_order: "tuple[str, ...]"

    exclusion_form_weights_milli: "tuple[int, ...]"
    exclusion_form_order: "tuple[str, ...]"

    legitimate_skew_rows: "tuple[SkewRow, ...]"

    exclusion_target_share_milli: int
    species_unique_affix_min: int

    tier2_sample_size: int
    tier3_additional_sample_size: int
    acceptance_ladder: "tuple[AcceptanceRung, ...]"

    cell_occupancy_median_max: int
    quota_drift_tolerance_units: int
    mechanism_ramp_deepest_tier_share_milli: int
    exclusion_rate_max_share_permille: int
    near_duplicate_rate_max_share_permille: int
    unresolved_count_max_share_permille: int


#: metric id -> the `PassiveTreeTargets` attribute holding its threshold (spec-tree-language.md §7
#: gates 15-18, 20, 22 — the six gates that are threshold-shaped; the other eighteen are binary/logic
#: gates with no number to carry, per that section, and are deliberately absent from this map).
GATING_METRICS: "dict[str, str]" = {
    "PassiveTree/CellOccupancy": "cell_occupancy_median_max",
    "PassiveTree/QuotaDrift": "quota_drift_tolerance_units",
    "PassiveTree/MechanismRamp": "mechanism_ramp_deepest_tier_share_milli",
    "PassiveTree/ExclusionRate": "exclusion_rate_max_share_permille",
    "PassiveTree/NearDuplicate": "near_duplicate_rate_max_share_permille",
    "PassiveTree/UnresolvedCount": "unresolved_count_max_share_permille",
}


def missing_thresholds(targets: PassiveTreeTargets) -> "list[str]":
    """The gates §7's own "every gate has a threshold" check (gate 5) is asserted against."""
    return [metric for metric, key in GATING_METRICS.items()
            if getattr(targets, key, None) is None]


def _require(doc: dict, *path: str):
    node = doc
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise PassiveTreeTargetsError(
                f"passive-tree-targets is missing {'.'.join(path)!r} — refusing to substitute a "
                f"default; an unreviewed number here reaches every generated tree")
        node = node[key]
    return node


def load(path: "Path | None" = None) -> PassiveTreeTargets:
    doc = json.loads((path or TARGETS_PATH).read_text(encoding="utf-8"))

    skew_rows = tuple(
        SkewRow(
            axis=str(row["axis"]), member=str(row["member"]),
            weight_milli=int(row["weightMilli"]), why=str(_require(row, "_why")))
        for row in _require(doc, "legitimateSkew", "rows")
    )

    acceptance_ladder = tuple(
        AcceptanceRung(
            rejects_in_60=int(row["rejectsIn60"]),
            upper_bound_permille_95=int(row["upperBoundPermille95"]),
            verdict=str(row["verdict"]))
        for row in _require(doc, "sampling", "acceptanceLadder")
    )

    targets = PassiveTreeTargets(
        aptitude_weight_scheme=str(_require(doc, "quotas", "aptitude", "weightScheme")),
        node_class_weights_milli=tuple(int(w) for w in _require(doc, "quotas", "nodeClass", "weightsMilli")),
        node_class_order=tuple(_require(doc, "quotas", "nodeClass", "_order")),
        exclusion_form_weights_milli=tuple(
            int(w) for w in _require(doc, "quotas", "exclusionForm", "weightsMilli")),
        exclusion_form_order=tuple(_require(doc, "quotas", "exclusionForm", "_order")),
        legitimate_skew_rows=skew_rows,
        exclusion_target_share_milli=int(_require(doc, "exclusion", "targetShareMilli")),
        species_unique_affix_min=int(_require(doc, "speciesUniqueAffixMin")),
        tier2_sample_size=int(_require(doc, "sampling", "tier2SampleSize")),
        tier3_additional_sample_size=int(_require(doc, "sampling", "tier3AdditionalSampleSize")),
        acceptance_ladder=acceptance_ladder,
        cell_occupancy_median_max=int(_require(doc, "gates", "cellOccupancy", "medianMax")),
        quota_drift_tolerance_units=int(_require(doc, "gates", "quotaDrift", "toleranceUnits")),
        mechanism_ramp_deepest_tier_share_milli=int(
            _require(doc, "gates", "mechanismRamp", "deepestTierShareMilli")),
        exclusion_rate_max_share_permille=int(
            _require(doc, "gates", "exclusionRate", "maxSharePermille")),
        near_duplicate_rate_max_share_permille=int(
            _require(doc, "gates", "nearDuplicateRate", "maxSharePermille")),
        unresolved_count_max_share_permille=int(
            _require(doc, "gates", "unresolvedCount", "maxSharePermille")),
    )
    _validate(targets)
    return targets


def _validate(t: PassiveTreeTargets) -> None:
    if len(t.node_class_weights_milli) != len(t.node_class_order):
        raise PassiveTreeTargetsError(
            f"quotas.nodeClass.weightsMilli has {len(t.node_class_weights_milli)} entries but "
            f"_order names {len(t.node_class_order)}")
    if sum(t.node_class_weights_milli) != 1000:
        raise PassiveTreeTargetsError(
            f"quotas.nodeClass.weightsMilli sums to {sum(t.node_class_weights_milli)}, not 1000")
    if len(t.exclusion_form_weights_milli) != 3 or len(t.exclusion_form_order) != 3:
        raise PassiveTreeTargetsError(
            "quotas.exclusionForm must carry exactly three forms (reroute, precedence, "
            "nullification — D40, all three reachable)")
    if sum(t.exclusion_form_weights_milli) != 1000:
        raise PassiveTreeTargetsError(
            f"quotas.exclusionForm.weightsMilli sums to {sum(t.exclusion_form_weights_milli)}, not 1000")
    nullification_index = list(t.exclusion_form_order).index("nullification") \
        if "nullification" in t.exclusion_form_order else -1
    if nullification_index < 0:
        raise PassiveTreeTargetsError("quotas.exclusionForm._order must include 'nullification' (D40)")
    if t.exclusion_form_weights_milli[nullification_index] <= 0:
        raise PassiveTreeTargetsError(
            "nullification's weight must be non-zero (D40 — 'nullification: 0' is superseded)")
    for row in t.legitimate_skew_rows:
        if not row.why.strip():
            raise PassiveTreeTargetsError(
                f"legitimateSkew row for {row.axis}/{row.member} has an empty _why — a skew row "
                f"without a stated reason is refused")
    if t.species_unique_affix_min < 0:
        raise PassiveTreeTargetsError("speciesUniqueAffixMin must be >= 0")
    if t.tier2_sample_size < 1:
        raise PassiveTreeTargetsError("sampling.tier2SampleSize must be at least 1")
    missing = missing_thresholds(t)
    if missing:
        raise PassiveTreeTargetsError(
            f"gate(s) with no threshold: {missing} — every gate §7 names as threshold-shaped must "
            f"resolve to a number")
