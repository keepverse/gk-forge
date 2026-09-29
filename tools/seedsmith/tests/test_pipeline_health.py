"""Tests for seedsmith.metrics.pipeline_health (spec-option-permutation.md §5,
spec-classify-pipelines.md; `seed-to-concrete` T2.12)."""
from __future__ import annotations

from seedsmith.corpus import Corpus
from seedsmith.metrics.pipeline_health import (
    ALL_PIPELINE_HEALTH_METRICS,
    BasisMixMetric,
    DisagreementRateMetric,
    RepairRateMetric,
)
from seedsmith.metrics.model import Ctx, Loop, Severity


def anchor_with_confidence(species_id, side, confidence, *, basis="observed") -> dict:
    return {"speciesId": species_id, "side": side, "basis": basis,
            "_provenance": {"basis": basis, "confidence": confidence}}


def anchor_with_attempts(species_id, attempts) -> dict:
    return {"speciesId": species_id, "side": "plant", "basis": "observed",
            "_provenance": {"basis": "observed", "attempts": attempts}}


def ctx_with(anchors, *, creature_dump=None) -> Ctx:
    return Ctx(corpus=Corpus(), adapter=None, creature_anchors=anchors, creature_dump=creature_dump)


# --- disagreement rate -----------------------------------------------------------------------


def test_high_disagreement_rate_is_a_finding():
    anchors = [
        anchor_with_confidence("a", "plant", {"elementPrimary": "split"}),
        anchor_with_confidence("b", "plant", {"elementPrimary": "unresolved"}),
        anchor_with_confidence("c", "plant", {"elementPrimary": "split"}),
        anchor_with_confidence("d", "plant", {"elementPrimary": "high"}),
    ]  # 3/4 = 750‰, above the 300‰ target
    findings = DisagreementRateMetric().run(ctx_with(anchors))
    assert len(findings) == 1
    assert findings[0].evidence["sharePermille"] == 750


def test_low_disagreement_rate_produces_no_finding():
    anchors = [anchor_with_confidence(f"s{i}", "plant", {"elementPrimary": "high"}) for i in range(10)]
    anchors.append(anchor_with_confidence("split1", "plant", {"elementPrimary": "split"}))
    findings = DisagreementRateMetric().run(ctx_with(anchors))
    assert findings == []


def test_rate_reported_separately_per_side():
    anchors = [
        anchor_with_confidence("z1", "zombie", {"elementPrimary": "unresolved"}),
        anchor_with_confidence("p1", "plant", {"elementPrimary": "high"}),
        anchor_with_confidence("p2", "plant", {"elementPrimary": "high"}),
    ]
    findings = DisagreementRateMetric().run(ctx_with(anchors))
    subjects = {f.subject for f in findings}
    assert "elementPrimary:zombie" in subjects
    assert "elementPrimary:plant" not in subjects


# --- repair rate ------------------------------------------------------------------------------


def test_high_repair_rate_is_a_finding():
    anchors = [anchor_with_attempts(f"s{i}", {"kit-shape": 3}) for i in range(5)]
    anchors += [anchor_with_attempts(f"h{i}", {"kit-shape": 1}) for i in range(5)]
    # 5/10 = 500‰, above the 200‰ target
    findings = RepairRateMetric().run(ctx_with(anchors))
    assert len(findings) == 1
    assert findings[0].subject == "kit-shape"


def test_no_attempts_data_is_not_measured():
    anchors = [anchor_with_confidence("a", "plant", {})]
    findings = RepairRateMetric().run(ctx_with(anchors))
    assert len(findings) == 1
    assert findings[0].severity is Severity.NOT_MEASURED


# --- basis mix ----------------------------------------------------------------------------------


def test_basis_mismatch_is_a_finding():
    anchor = {"speciesId": "a", "side": "plant", "basis": "observed",
             "_provenance": {"basis": "stated"}}  # deliberately contradicts the top-level basis
    findings = BasisMixMetric().run(ctx_with([anchor]))
    assert len(findings) == 1
    assert "a" in findings[0].evidence["mismatchedSpecies"]


def test_consistent_basis_produces_no_finding():
    anchors = [anchor_with_confidence(f"s{i}", "plant", {}, basis="observed") for i in range(5)]
    findings = BasisMixMetric().run(ctx_with(anchors))
    assert findings == []


# --- structural rules -----------------------------------------------------------------------


def test_every_pipeline_health_metric_is_closed_loop_and_measure_only():
    for cls in ALL_PIPELINE_HEALTH_METRICS:
        assert cls.loop is Loop.CLOSED
        assert cls.gates is False


def test_threat_audit_queue_never_gates():
    # The review queue (review_queue.py) is a plain data structure with no `loop`/`gates`
    # attributes at all — it cannot be registered into MetricRegistry, so it structurally
    # cannot appear in any --gate pass/fail decision. This test pins that by construction.
    from seedsmith.adapters.creatures.anchor.review_queue import ThreatAuditReviewEntry
    assert not hasattr(ThreatAuditReviewEntry, "loop")
    assert not hasattr(ThreatAuditReviewEntry, "gates")
    pipeline_health_ids = {m.id for m in ALL_PIPELINE_HEALTH_METRICS}
    assert not any("threat" in mid.lower() and "audit" in mid.lower() for mid in pipeline_health_ids)
