"""seedsmith.metrics.pipeline_health — the classification RUN's own health (creature-seed module 7,
`seed-to-concrete` T2.12). Distinct from `roster-metrics` (T2.10, which measures the RESULTING
distribution): this measures how the PIPELINES themselves behaved — how often they disagreed with
themselves, how often they needed a repair, whether the echoed `basis` still matches what
`power-parse` actually computed.

**The `threat-audit` disagreement queue (`review_queue.py`, T2.5) is OPEN-loop and is never
registered here as a metric** — it is a review queue by design (Q16: "number wins, and the LLM
audits the result"), and a metric that could gate on it would silently reintroduce exactly the
override the design forbids. `test_threat_audit_queue_never_gates` pins this structurally.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .model import Ctx, Finding, Loop, Metric, Severity

TUNING_DIR = Path(__file__).resolve().parents[4] / "data" / "tuning"


def _load_targets(version: "int | str" = 1) -> dict:
    path = TUNING_DIR / f"creature-pipeline-health-targets.v{int(version)}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _anchors_or_not_measured(metric_id: str, ctx: Ctx) -> "list[Mapping[str, Any]] | Finding":
    anchors = ctx.creature_anchors
    if not anchors:
        return Finding(metric=metric_id, severity=Severity.NOT_MEASURED, subject="(suite)",
                       message="no creature anchors supplied — nothing to measure", evidence={})
    return anchors


class DisagreementRateMetric(Metric):
    """Per field, per side: the share of `option-permutation` votes that were NOT 3-0 — read
    directly from each anchor's own `_provenance.confidence` (spec-anchor-emit.md §3), never
    recomputed. High per spec-option-permutation.md §5: a weak description, the fix is a stronger
    negative clause in `anchor-contract`'s `descriptions.py`."""

    id = "PipelineHealth/DisagreementRate"
    family = "PipelineHealth"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"creature_anchors"})
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        anchors = _anchors_or_not_measured(self.id, ctx)
        if isinstance(anchors, Finding):
            return [anchors]

        max_share_permille = _load_targets()["disagreementRate"]["maxRateSharePermille"]

        totals: "dict[tuple[str, str], int]" = {}
        disagreed: "dict[tuple[str, str], int]" = {}
        for a in anchors:
            side = a.get("side", "")
            confidence = (a.get("_provenance") or {}).get("confidence") or {}
            for field, conf in confidence.items():
                key = (field, side)
                totals[key] = totals.get(key, 0) + 1
                if conf != "high":
                    disagreed[key] = disagreed.get(key, 0) + 1

        findings: "list[Finding]" = []
        for (field, side), total in totals.items():
            share_permille = (disagreed.get((field, side), 0) * 1000) // total
            if share_permille > max_share_permille:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=f"{field}:{side}",
                    message=f"{field} ({side}): {disagreed.get((field, side), 0)}/{total} votes "
                            f"disagreed ({share_permille}‰), above the {max_share_permille}‰ target",
                    evidence={"field": field, "side": side, "total": total,
                             "disagreed": disagreed.get((field, side), 0), "sharePermille": share_permille},
                    remedy="anchor-contract: strengthen this field's negative clause in descriptions.py"))
        return findings


class RepairRateMetric(Metric):
    """Per pipeline: how often it needed at least one repair before persisting (echoed from
    `_provenance.attempts`, `attempts > 1`). A high rate names which validator is fighting the
    model most, not which species are wrong."""

    id = "PipelineHealth/RepairRate"
    family = "PipelineHealth"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"creature_anchors"})
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        anchors = _anchors_or_not_measured(self.id, ctx)
        if isinstance(anchors, Finding):
            return [anchors]

        max_share_permille = _load_targets()["repairRate"]["maxRepairSharePermille"]

        totals: "dict[str, int]" = {}
        repaired: "dict[str, int]" = {}
        for a in anchors:
            attempts = (a.get("_provenance") or {}).get("attempts") or {}
            for pipeline_id, n in attempts.items():
                totals[pipeline_id] = totals.get(pipeline_id, 0) + 1
                if n > 1:
                    repaired[pipeline_id] = repaired.get(pipeline_id, 0) + 1

        if not totals:
            return [Finding(metric=self.id, severity=Severity.NOT_MEASURED, subject="(suite)",
                            message="no anchor carries _provenance.attempts yet", evidence={})]

        findings: "list[Finding]" = []
        for pipeline_id, total in totals.items():
            share_permille = (repaired.get(pipeline_id, 0) * 1000) // total
            if share_permille > max_share_permille:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=pipeline_id,
                    message=f"{pipeline_id}: {repaired.get(pipeline_id, 0)}/{total} species needed "
                            f"a repair ({share_permille}‰), above the {max_share_permille}‰ target",
                    evidence={"pipeline": pipeline_id, "total": total,
                             "repaired": repaired.get(pipeline_id, 0), "sharePermille": share_permille},
                    remedy="check this pipeline's cross-field validator for a systematic conflict"))
        return findings


class BasisMixMetric(Metric):
    """Structural, not a balance number (target is always 0): an anchor's echoed top-level
    `basis` field must match its own `_provenance.basis`. The two are set from the same value at
    emit time (spec-anchor-emit.md §1: `basis` is DERIVED and echoed with a `_derived` marker) —
    the only way they can diverge is a hand-edited file or a real `anchor-emit` bug, never a
    balance choice. (A deeper cross-check against `power-parse`'s live-recomputed basis for the
    same species needs a typeId on the anchor, which isn't in scope for this pass.)
    """

    id = "PipelineHealth/BasisMix"
    family = "PipelineHealth"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"creature_anchors"})
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        anchors = _anchors_or_not_measured(self.id, ctx)
        if isinstance(anchors, Finding):
            return [anchors]

        max_mismatch_permille = _load_targets()["basisMix"]["maxMismatchSharePermille"]

        mismatches = []
        total = 0
        for a in anchors:
            prov = a.get("_provenance") or {}
            recorded_basis = prov.get("basis")
            if recorded_basis is None:
                continue
            total += 1
            if a.get("basis") not in (None, recorded_basis):
                mismatches.append(a.get("speciesId"))

        if total == 0:
            return [Finding(metric=self.id, severity=Severity.NOT_MEASURED, subject="(suite)",
                            message="no anchor carries a comparable basis", evidence={})]

        share_permille = (len(mismatches) * 1000) // total
        if share_permille > max_mismatch_permille:
            return [Finding(
                metric=self.id, severity=Severity.GAP, subject="basis mix",
                message=f"{len(mismatches)}/{total} anchors ({share_permille}‰) have "
                        f"basis != _provenance.basis — a corrupted entry",
                evidence={"mismatchedSpecies": mismatches[:20], "total": total},
                remedy="anchor-emit: this is a bug, not a tuning question — basis and _provenance.basis must always agree")]
        return []


ALL_PIPELINE_HEALTH_METRICS = (DisagreementRateMetric, RepairRateMetric, BasisMixMetric)
