"""seedsmith.metrics.creature_roster — roster-shape metrics (creature-seed module 14,
spec-roster-metrics.md; `seed-to-concrete` T2.10). Measures the GENERATED anchors, not concrete
rows — deliberately placed before `species-generator`: if the distribution is wrong, it is wrong
in the anchors, and expanding skewed anchors into concrete rows just moves the problem somewhere
more expensive to fix (spec §6).

**Every target here is declared in tuning (P2)** — `gk-core/data/tuning/creature-roster-targets.v1.json`.
**Every metric here is CLOSED-loop (P3)** — each is machine-verifiable (a grid cell fills, a
distribution flattens); the genuinely open-loop questions this program has ("is this species'
element actually right?", the `threat-audit` review queue) live elsewhere (`review_queue.py`,
T2.5) and are not re-implemented here as a metric that would silently claim to gate them.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..adapters.creatures.anchor.schema import APTITUDES, ELEMENTS, RARITY, THREAT_BAND
from .model import Ctx, Finding, Loop, Metric, Severity

TUNING_DIR = Path(__file__).resolve().parents[4] / "data" / "tuning"


def _load_targets(version: "int | str" = 1) -> dict:
    path = TUNING_DIR / f"creature-roster-targets.v{int(version)}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _element_pair_id(primary: str, secondary: "str | None") -> str:
    if not secondary or secondary == "none":
        return primary
    return "+".join(sorted((primary, secondary)))


#: The 21 canonical element-pair/single ids: 6 singles + C(6,2)=15 pairs (spec §2).
ALL_ELEMENT_PAIRS: "tuple[str, ...]" = tuple(
    sorted(ELEMENTS) + ["+".join(sorted(p)) for p in itertools.combinations(sorted(ELEMENTS), 2)]
)
assert len(ALL_ELEMENT_PAIRS) == 21


def _anchors_or_not_measured(metric_id: str, ctx: Ctx) -> "list[Mapping[str, Any]] | Finding":
    anchors = ctx.creature_anchors
    if not anchors:
        return Finding(metric=metric_id, severity=Severity.NOT_MEASURED, subject="(suite)",
                       message="no creature anchors supplied — nothing to measure", evidence={})
    return anchors


class GridFillMetric(Metric):
    """21 element-pairs × 12 aptitudes = 252 cells (spec §2, ideal §6.3's Genshin/FGO safe band).
    Reports every cell, zeros included — an empty cell hidden behind an average is exactly the
    failure this module exists to prevent."""

    id = "CreatureRoster/GridFill"
    family = "CreatureRoster"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"creature_anchors"})
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        anchors = _anchors_or_not_measured(self.id, ctx)
        if isinstance(anchors, Finding):
            return [anchors]

        targets = _load_targets()["gridFill"]
        min_occupied_permille = targets["minCellsOccupiedPermille"]

        grid: "dict[str, int]" = {f"{pair}|{apt}": 0 for pair in ALL_ELEMENT_PAIRS for apt in APTITUDES}
        for a in anchors:
            primary = a.get("elementPrimary")
            secondary = a.get("elementSecondary")
            aptitude = a.get("aptitudePrimary")
            if not primary or not aptitude or primary == "unresolved" or aptitude == "unresolved":
                continue
            pair_id = _element_pair_id(primary, secondary)
            key = f"{pair_id}|{aptitude}"
            if key in grid:
                grid[key] += 1

        occupied = sum(1 for v in grid.values() if v > 0)
        total_cells = len(grid)
        occupied_permille = (occupied * 1000) // total_cells

        findings: "list[Finding]" = []
        if occupied_permille < min_occupied_permille:
            empty_cells = sorted(k for k, v in grid.items() if v == 0)
            findings.append(Finding(
                metric=self.id, severity=Severity.GAP, subject="grid occupancy",
                message=f"{occupied}/{total_cells} cells occupied ({occupied_permille}‰), "
                        f"below the {min_occupied_permille}‰ target",
                evidence={"occupiedCells": occupied, "totalCells": total_cells,
                         "emptyCells": empty_cells[:20], "emptyCellCount": len(empty_cells)},
                remedy="classify-pipelines: check for a position/label bias in element or aptitude classification"))
        return findings


class SingleElementShareMetric(Metric):
    """A single (pure) element must not be the majority (spec §2's own literal rule; FEH's
    failure zone per ideal §6.2 ①)."""

    id = "CreatureRoster/SingleElementShare"
    family = "CreatureRoster"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"creature_anchors"})
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        anchors = _anchors_or_not_measured(self.id, ctx)
        if isinstance(anchors, Finding):
            return [anchors]

        targets = _load_targets()["singleElementShare"]
        max_permille = targets["maxSingleElementSharePermille"]

        total = sum(1 for a in anchors if a.get("elementPrimary") not in (None, "unresolved"))
        pure = sum(1 for a in anchors
                  if a.get("elementPrimary") not in (None, "unresolved")
                  and a.get("elementSecondary") in (None, "none"))
        if total == 0:
            return [Finding(metric=self.id, severity=Severity.NOT_MEASURED, subject="(suite)",
                            message="no species with a resolved elementPrimary", evidence={})]

        share_permille = (pure * 1000) // total
        if share_permille > max_permille:
            return [Finding(
                metric=self.id, severity=Severity.GAP, subject="single-element share",
                message=f"{pure}/{total} species ({share_permille}‰) are single-element, "
                        f"above the {max_permille}‰ target",
                evidence={"pure": pure, "total": total, "sharePermille": share_permille},
                remedy="check element-secondary pipeline for a bias toward 'none'")]
        return []


class AptitudeDistributionMetric(Metric):
    """No aptitude below half the mean (spec §2) — there are 12 by construction; a starved one
    is dead content for the class system's own allocation scopes."""

    id = "CreatureRoster/AptitudeDistribution"
    family = "CreatureRoster"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"creature_anchors"})
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        anchors = _anchors_or_not_measured(self.id, ctx)
        if isinstance(anchors, Finding):
            return [anchors]

        targets = _load_targets()["aptitudeDistribution"]
        min_share_of_mean_permille = targets["minShareOfMeanPermille"]

        counts = {apt: 0 for apt in APTITUDES}
        for a in anchors:
            apt = a.get("aptitudePrimary")
            if apt in counts:
                counts[apt] += 1

        total = sum(counts.values())
        if total == 0:
            return [Finding(metric=self.id, severity=Severity.NOT_MEASURED, subject="(suite)",
                            message="no species with a resolved aptitudePrimary", evidence={})]
        mean = total / len(counts)

        findings: "list[Finding]" = []
        for apt, count in sorted(counts.items()):
            share_of_mean_permille = int((count / mean) * 1000) if mean else 0
            if share_of_mean_permille < min_share_of_mean_permille:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=apt,
                    message=f"{apt}: {count} species ({share_of_mean_permille}‰ of the mean "
                            f"{mean:.1f}), below the {min_share_of_mean_permille}‰ target",
                    evidence={"count": count, "mean": mean, "shareOfMeanPermille": share_of_mean_permille},
                    remedy="check aptitude-primary pipeline for a position/label bias against this aptitude"))
        return findings


class ThreatBandOccupancyMetric(Metric):
    """No empty rung, no rung above ~25% (spec §2-3). Reports occupancy per rung; never proposes
    a retuned table — that is a human call over the reported quantiles (spec's own boundary)."""

    id = "CreatureRoster/ThreatBandOccupancy"
    family = "CreatureRoster"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"creature_anchors"})
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        anchors = _anchors_or_not_measured(self.id, ctx)
        if isinstance(anchors, Finding):
            return [anchors]

        targets = _load_targets()["threatBandOccupancy"]
        max_share_permille = targets["maxRungSharePermille"]

        counts = {rung: 0 for rung in THREAT_BAND}
        for a in anchors:
            rung = a.get("threatBand")
            if rung in counts:
                counts[rung] += 1
        total = sum(counts.values())
        if total == 0:
            return [Finding(metric=self.id, severity=Severity.NOT_MEASURED, subject="(suite)",
                            message="no species with a resolved threatBand", evidence={})]

        findings: "list[Finding]" = []
        for rung, count in counts.items():
            if count == 0:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=rung,
                    message=f"threat rung {rung!r} has zero occupants",
                    evidence={"count": 0, "total": total},
                    remedy="creature-threat.v1.json retune — this module reports occupancy, never proposes a table"))
                continue
            share_permille = (count * 1000) // total
            if share_permille > max_share_permille:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=rung,
                    message=f"threat rung {rung!r}: {count}/{total} ({share_permille}‰), "
                            f"above the {max_share_permille}‰ target",
                    evidence={"count": count, "total": total, "sharePermille": share_permille},
                    remedy="creature-threat.v1.json retune — this module reports occupancy, never proposes a table"))
        return findings


class RarityMonotonicityMetric(Metric):
    """The ten rarity rungs must be monotone NON-increasing in count as ordinal rises — a ladder
    where rung 7 is commoner than rung 4 is not a ladder (spec §2)."""

    id = "CreatureRoster/RarityMonotonicity"
    family = "CreatureRoster"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"creature_anchors"})
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        anchors = _anchors_or_not_measured(self.id, ctx)
        if isinstance(anchors, Finding):
            return [anchors]

        counts = {r: 0 for r in RARITY}
        for a in anchors:
            r = a.get("rarity")
            if r in counts:
                counts[r] += 1
        ordered = [counts[r] for r in RARITY]  # RARITY is already ordinal chaff..almanac

        findings: "list[Finding]" = []
        for i in range(1, len(ordered)):
            if ordered[i] > ordered[i - 1]:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP,
                    subject=f"{RARITY[i-1]}->{RARITY[i]}",
                    message=f"{RARITY[i]!r} ({ordered[i]} species) is commoner than "
                            f"{RARITY[i-1]!r} ({ordered[i-1]} species) — not monotone",
                    evidence={"counts": dict(zip(RARITY, ordered))},
                    remedy="identity pipeline: check for a bias toward higher rarity, or the rarity ladder itself needs review"))
        return findings


class FamilySizeSpreadMetric(Metric):
    """No family holds more than ~10% of the roster (spec §2)."""

    id = "CreatureRoster/FamilySizeSpread"
    family = "CreatureRoster"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"creature_anchors"})
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        anchors = _anchors_or_not_measured(self.id, ctx)
        if isinstance(anchors, Finding):
            return [anchors]

        targets = _load_targets()["familySizeSpread"]
        max_share_permille = targets["maxFamilySharePermille"]

        counts: "dict[str, int]" = {}
        total = 0
        for a in anchors:
            for fam in a.get("family") or []:
                counts[fam] = counts.get(fam, 0) + 1
            if a.get("family"):
                total += 1
        if total == 0:
            return [Finding(metric=self.id, severity=Severity.NOT_MEASURED, subject="(suite)",
                            message="no species with a resolved family", evidence={})]

        findings: "list[Finding]" = []
        for fam, count in sorted(counts.items()):
            share_permille = (count * 1000) // total
            if share_permille > max_share_permille:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=fam,
                    message=f"family {fam!r}: {count}/{total} ({share_permille}‰), "
                            f"above the {max_share_permille}‰ target",
                    evidence={"count": count, "total": total, "sharePermille": share_permille},
                    remedy="identity pipeline: check for a bias toward this family label"))
        return findings


class PostureBalanceMetric(Metric):
    """Force/Finesse/Bastion within a stated band — derived from aptitudePrimary, so a skew here
    IS an aptitude skew, reported from the other angle (spec §2)."""

    id = "CreatureRoster/PostureBalance"
    family = "CreatureRoster"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"creature_anchors"})
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        anchors = _anchors_or_not_measured(self.id, ctx)
        if isinstance(anchors, Finding):
            return [anchors]

        targets = _load_targets()["postureBalance"]
        min_permille = targets["minPostureSharePermille"]
        max_permille = targets["maxPostureSharePermille"]

        counts = {"Force": 0, "Finesse": 0, "Bastion": 0}
        unresolved = 0
        for a in anchors:
            posture = a.get("posture")
            if posture in counts:
                counts[posture] += 1
            else:
                # RB-H1 (2026-09-23): COUNTED, never skipped. This loop used to drop every row whose
                # posture matched none of the three keys, so a roster with unresolved postures
                # reported a band share over a silent subset — "posture is balanced" was
                # unfalsifiable, not merely unmeasured.
                unresolved += 1
        total = sum(counts.values())

        findings: "list[Finding]" = []
        if unresolved > 0:
            findings.append(Finding(
                metric=self.id, severity=Severity.GAP, subject="unresolved",
                message=f"{unresolved}/{len(anchors)} species carry no resolved posture "
                        f"(neither Force, Finesse nor Bastion) — reported, never silently dropped; "
                        f"the band below is measured over the {total} resolved row(s) only",
                evidence={"unresolved": unresolved, "total": len(anchors), "resolved": total},
                remedy="aptitude-primary pipeline: an unresolved primary posture is unresolvable "
                       "downstream; strengthen that pipeline's description, or the anchor is wrong"))
        if total == 0:
            return findings + [Finding(metric=self.id, severity=Severity.NOT_MEASURED, subject="(suite)",
                                       message="no species with a resolved posture", evidence={})]

        for posture, count in counts.items():
            share_permille = (count * 1000) // total
            if share_permille < min_permille or share_permille > max_permille:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=posture,
                    message=f"{posture}: {count}/{total} ({share_permille}‰), outside the "
                            f"[{min_permille}, {max_permille}]‰ band",
                    evidence={"count": count, "total": total, "sharePermille": share_permille},
                    remedy="aptitude-primary pipeline: this posture's four aptitudes are over/under-represented"))
        return findings


class UnresolvedCountMetric(Metric):
    """Per voted field, the unresolved (1-1-1) share is reported, and a high rate is a finding —
    it means a weak description, not a species-level defect (spec §2, option-permutation.md §5).

    Promoted to `gates=True` 2026-09-03 (a deliberate, later act, per this program's own registered
    design — `model.py`'s "starts False for every new metric; promotion is a deliberate, later,
    separate act"). Found by audit: an unresolved `aptitudePrimary` is not merely a description-
    quality signal — `SpeciesExpander.Expand` has no edge to derive a magnitude from, so every
    species with an unresolved aptitude was silently generated with ZERO stats
    (SnorkleZombie/ThreePeater in the real 28-species tree, both fixed the same day by making
    `SpeciesExpander` refuse to expand one at all). Gating the RATE here stops a full run early —
    before spending thousands of model calls — if the aptitude-primary description is systematically
    too ambiguous to converge, rather than discovering it species-by-species after the fact."""

    id = "CreatureRoster/UnresolvedCount"
    family = "CreatureRoster"
    loop = Loop.CLOSED
    gates = True
    needs = frozenset({"creature_anchors"})
    covers: "tuple[str, ...]" = ()

    VOTED_FIELDS = ("elementPrimary", "aptitudePrimary", "rarity", "threatBand", "deployMode",
                    # RB-H1 (2026-09-23): `posture` is DERIVED, not voted — and that is exactly why it
                    # was invisible here. It is the one derived field that can carry the same sentinel
                    # (`derive_posture` propagates "unresolved" from an unresolved primary), so leaving
                    # it out of this tuple made an unresolved posture a row NO metric could see and no
                    # gate could fail on. Reported now, for the same reason the five above are.
                    "posture")

    def run(self, ctx: Ctx) -> "list[Finding]":
        anchors = _anchors_or_not_measured(self.id, ctx)
        if isinstance(anchors, Finding):
            return [anchors]

        targets = _load_targets()["unresolvedCount"]
        max_share_permille = targets["maxUnresolvedSharePermille"]
        total = len(anchors)
        if total == 0:
            return [Finding(metric=self.id, severity=Severity.NOT_MEASURED, subject="(suite)",
                            message="no anchors", evidence={})]

        findings: "list[Finding]" = []
        for field in self.VOTED_FIELDS:
            unresolved = sum(1 for a in anchors if a.get(field) == "unresolved")
            share_permille = (unresolved * 1000) // total
            if share_permille > max_share_permille:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=field,
                    message=f"{field}: {unresolved}/{total} unresolved ({share_permille}‰), "
                            f"above the {max_share_permille}‰ target — likely a weak description",
                    evidence={"unresolved": unresolved, "total": total, "sharePermille": share_permille},
                    remedy="anchor-contract: strengthen this field's description with a clearer negative clause"))
            elif unresolved > 0:
                # RB-H1 (2026-09-23): MEASURED and reported, never counted-but-invisible. Below the
                # gate's own band this is a NOTE, deliberately not a GAP — so adding a field to
                # VOTED_FIELDS makes it visible without silently tightening a gating metric.
                findings.append(Finding(
                    metric=self.id, severity=Severity.NOTE, subject=field,
                    message=f"{field}: {unresolved}/{total} unresolved ({share_permille}‰), at or below "
                            f"the {max_share_permille}‰ target",
                    evidence={"unresolved": unresolved, "total": total, "sharePermille": share_permille}))
        return findings


ALL_CREATURE_ROSTER_METRICS = (
    GridFillMetric, SingleElementShareMetric, AptitudeDistributionMetric,
    ThreatBandOccupancyMetric, RarityMonotonicityMetric, FamilySizeSpreadMetric,
    PostureBalanceMetric, UnresolvedCountMetric,
)
