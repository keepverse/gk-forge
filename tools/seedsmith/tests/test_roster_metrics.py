"""Tests for seedsmith.metrics.creature_roster (spec-roster-metrics.md, creature-seed module 14,
`seed-to-concrete` T2.10). Fixtures are synthetic rosters with a deliberately injected defect —
the only way to prove a metric would notice (spec's own testing-strategy rule).
"""
from __future__ import annotations

from seedsmith.adapters.creatures.anchor.schema import APTITUDES, ELEMENTS, RARITY, THREAT_BAND
from seedsmith.corpus import Corpus
from seedsmith.metrics.creature_roster import (
    ALL_ELEMENT_PAIRS,
    ALL_CREATURE_ROSTER_METRICS,
    AptitudeDistributionMetric,
    FamilySizeSpreadMetric,
    GridFillMetric,
    PostureBalanceMetric,
    RarityMonotonicityMetric,
    SingleElementShareMetric,
    ThreatBandOccupancyMetric,
    UnresolvedCountMetric,
)
from seedsmith.metrics.model import Ctx, Loop, Severity
from seedsmith.metrics.registry import MetricRegistry, run_all


def anchor(species_id, *, element="fire", element2="none", aptitude="Might",
          rarity="chaff", threat="nuisance", family=("plant",), posture="Force") -> dict:
    return {
        "speciesId": species_id, "elementPrimary": element, "elementSecondary": element2,
        "aptitudePrimary": aptitude, "rarity": rarity, "threatBand": threat,
        "family": list(family), "posture": posture,
    }


def ctx_with(anchors) -> Ctx:
    return Ctx(corpus=Corpus(), adapter=None, creature_anchors=anchors)


# --- grid fill ------------------------------------------------------------------------------


def test_all_element_pairs_is_exactly_21():
    assert len(ALL_ELEMENT_PAIRS) == 21


def test_grid_reports_all_252_cells_including_zeros():
    # A tiny roster occupies almost none of the 252 cells — the metric must report that gap
    # rather than silently averaging it away.
    anchors = [anchor("a", element="fire", aptitude="Might")]
    findings = GridFillMetric().run(ctx_with(anchors))
    assert len(findings) == 1
    assert findings[0].evidence["totalCells"] == 252
    assert findings[0].evidence["occupiedCells"] == 1
    assert len(findings[0].evidence["emptyCells"]) > 0


def test_full_grid_produces_no_finding():
    anchors = []
    for pair_id in ALL_ELEMENT_PAIRS:
        parts = pair_id.split("+")
        e1, e2 = parts[0], (parts[1] if len(parts) > 1 else "none")
        for apt in APTITUDES:
            anchors.append(anchor(f"{pair_id}-{apt}", element=e1, element2=e2, aptitude=apt))
    findings = GridFillMetric().run(ctx_with(anchors))
    assert findings == []


# --- single-element share --------------------------------------------------------------------


def test_skewed_element_distribution_is_a_finding():
    # 60% pure-single-element — well above the 50% target.
    anchors = [anchor(f"pure-{i}", element="fire", element2="none") for i in range(60)]
    anchors += [anchor(f"dual-{i}", element="fire", element2="ice") for i in range(40)]
    findings = SingleElementShareMetric().run(ctx_with(anchors))
    assert len(findings) == 1
    assert findings[0].severity is Severity.GAP
    assert findings[0].evidence["sharePermille"] == 600


def test_healthy_element_split_produces_no_finding():
    anchors = [anchor(f"pure-{i}", element="fire", element2="none") for i in range(30)]
    anchors += [anchor(f"dual-{i}", element="fire", element2="ice") for i in range(70)]
    assert SingleElementShareMetric().run(ctx_with(anchors)) == []


# --- aptitude distribution --------------------------------------------------------------------


def test_starved_aptitude_is_a_finding():
    anchors = [anchor(f"s-{i}", aptitude="Might") for i in range(100)]
    anchors += [anchor("lonely", aptitude="Ferocity")]  # one single species for a whole aptitude
    findings = AptitudeDistributionMetric().run(ctx_with(anchors))
    subjects = {f.subject for f in findings}
    assert "Ferocity" in subjects


# --- threat band occupancy ---------------------------------------------------------------------


def test_empty_threat_rung_is_reported_with_quantiles():
    # Only "nuisance" ever occupied — every other rung is empty.
    anchors = [anchor(f"s-{i}", threat="nuisance") for i in range(50)]
    findings = ThreatBandOccupancyMetric().run(ctx_with(anchors))
    empty_findings = [f for f in findings if f.evidence.get("count") == 0]
    assert len(empty_findings) == 9  # all rungs but nuisance
    # never proposes a table — evidence only ever names counts/shares, no proposed thresholds.
    for f in findings:
        assert "proposedThreshold" not in f.evidence
        assert "newTable" not in f.evidence


def test_over_concentrated_rung_is_a_finding():
    anchors = [anchor(f"s-{i}", threat="warden") for i in range(30)]
    anchors += [anchor(f"o-{r}-{i}", threat=r) for r in THREAT_BAND if r != "warden" for i in range(1)]
    findings = ThreatBandOccupancyMetric().run(ctx_with(anchors))
    over = [f for f in findings if f.subject == "warden" and f.evidence.get("count", 0) > 0]
    assert len(over) == 1


# --- rarity monotonicity ------------------------------------------------------------------------


def test_non_monotone_rarity_is_a_finding():
    counts = {r: 5 for r in RARITY}
    counts[RARITY[6]] = 20  # rung 7 (index 6) commoner than rung 4 (index 3, still 5)
    anchors = []
    for r, n in counts.items():
        anchors += [anchor(f"{r}-{i}", rarity=r) for i in range(n)]
    findings = RarityMonotonicityMetric().run(ctx_with(anchors))
    assert len(findings) >= 1
    assert any(RARITY[6] in f.subject for f in findings)


def test_monotone_rarity_produces_no_finding():
    counts_desc = list(range(400, 400 - 10 * 20, -20))  # strictly decreasing
    anchors = []
    for r, n in zip(RARITY, counts_desc):
        anchors += [anchor(f"{r}-{i}", rarity=r) for i in range(max(n, 1))]
    assert RarityMonotonicityMetric().run(ctx_with(anchors)) == []


# --- family spread + posture balance + unresolved ----------------------------------------------


def test_dominant_family_is_a_finding():
    anchors = [anchor(f"s-{i}", family=("dominant",)) for i in range(50)]
    anchors += [anchor(f"o-{i}", family=(f"family-{i}",)) for i in range(50)]
    findings = FamilySizeSpreadMetric().run(ctx_with(anchors))
    assert any(f.subject == "dominant" for f in findings)


def test_posture_imbalance_is_a_finding():
    # All Force (Might), no Finesse or Bastion at all.
    anchors = [anchor(f"s-{i}", aptitude="Might", posture="Force") for i in range(100)]
    findings = PostureBalanceMetric().run(ctx_with(anchors))
    subjects = {f.subject for f in findings}
    assert "Finesse" in subjects
    assert "Bastion" in subjects


def test_unresolved_field_share_is_reported():
    anchors = [anchor(f"r-{i}") for i in range(90)]
    for a in anchors[:10]:
        a["elementPrimary"] = "unresolved"
    findings = UnresolvedCountMetric().run(ctx_with(anchors))
    assert any(f.subject == "elementPrimary" for f in findings)


def test_a_planted_unresolved_posture_is_visible_to_both_metrics():
    # RB-H1 (2026-09-20, filed from roster-balance's own real run; closed here 2026-09-23): a
    # `posture: "unresolved"` row was invisible to EVERY metric — UnresolvedCount's VOTED_FIELDS
    # omitted `posture` and PostureBalanceMetric skipped rows matching none of its three keys. "posture
    # is balanced" was therefore unfalsifiable, not merely unmeasured: a row no metric can see is a row
    # no gate can ever fail on.
    anchors = [anchor(f"p-{i}", posture="Force") for i in range(20)]
    anchors[0]["posture"] = "unresolved"

    unresolved = UnresolvedCountMetric().run(ctx_with(anchors))
    assert any(f.subject == "posture" for f in unresolved), \
        "UnresolvedCountMetric cannot see an unresolved posture"

    balance = PostureBalanceMetric().run(ctx_with(anchors))
    assert any(f.subject == "unresolved" for f in balance), \
        "PostureBalanceMetric silently dropped the row"


def test_an_all_unresolved_roster_is_named_not_merely_not_measured():
    # The old shape returned ONLY the NOT_MEASURED suite finding ("no species with a resolved posture"),
    # which reads as "nothing to say" — the silent drop rather than a zero. The row count is now named
    # on its own line, so "every posture is unresolved" and "this roster is small" cannot be confused.
    anchors = [anchor(f"u-{i}", posture="unresolved") for i in range(10)]

    findings = PostureBalanceMetric().run(ctx_with(anchors))

    named = [f for f in findings if f.subject == "unresolved"]
    assert len(named) == 1
    assert named[0].evidence["unresolved"] == len(anchors)
    assert named[0].evidence["resolved"] == 0
    assert any(f.severity == Severity.NOT_MEASURED for f in findings)


# --- structural rules (P2, P3) ------------------------------------------------------------------


def test_every_metric_has_a_declared_target_in_tuning():
    # Mechanically: every metric class's own tuning key must exist in the committed file.
    #
    # `data/tuning/**` IS gk-core's, and the nine-repository split moved it out from under the
    # `parents[n]` walk this used to do. `Path(__file__).parents[1] / ".." / ".."` resolved to
    # gk-forge/tools - a repository that has no `data/tuning` at all - so the test reported the
    # committed targets file MISSING while it sat present under gk-core. That is the same
    # docstring-right/code-stale shape `ladders.py` records, and it hid the fact that the module
    # UNDER TEST (`seedsmith.metrics.creature_roster`) carries its own identical defect in
    # `TUNING_DIR`, which is why 13 of this file's 14 failures were never this line.
    #
    # Resolved through the shared resolver's `core_root()` rather than a hand-counted `..` hop:
    # `core_root()` answers "which repository is gk-core" instead of guessing that some fixed
    # number of `..` hops lands there, which is exactly the guess that broke when the split
    # changed the depth. `core_root()` does not raise for an absent pack (unlike `content_root`),
    # so the `read_text` below is the fail-closed half: it names the missing file rather than
    # silently reading somewhere else. The assertion is unchanged - same keys, same subset check.
    import json

    from seedsmith.workspace_roots import core_root

    targets = json.loads(
        (core_root() / "data" / "tuning" / "creature-roster-targets.v1.json")
        .read_text(encoding="utf-8"))
    expected_keys = {"gridFill", "singleElementShare", "aptitudeDistribution", "threatBandOccupancy",
                     "familySizeSpread", "postureBalance", "unresolvedCount"}
    assert expected_keys <= set(targets.keys())


def test_open_loop_metric_never_contributes_to_pass():
    # Every CreatureRoster metric declares CLOSED (spec §4's own table) — this is the mechanical
    # proof the registry itself enforces (Loop.OPEN + gates=True raises at registration).
    #
    # UnresolvedCountMetric was promoted to gates=True 2026-09-03 — a real, deliberate promotion
    # (this program's own registered design: "starts False for every new metric; promotion is a
    # deliberate, later, separate act"), not an accident this test should mask. Found by audit: an
    # unresolved aptitudePrimary silently produced a zero-stat species (SpeciesExpander had no edge
    # to derive a magnitude from) — gating the aggregate rate stops a full run early rather than
    # discovering it species-by-species after the fact. Every other CreatureRoster metric is still
    # measure-only.
    for cls in ALL_CREATURE_ROSTER_METRICS:
        assert cls.loop is Loop.CLOSED
        expected_gates = cls is UnresolvedCountMetric
        assert cls.gates is expected_gates, f"{cls.__name__}.gates should be {expected_gates}"


def test_gate_exits_1_on_a_closed_loop_finding():
    registry = MetricRegistry()
    metric = SingleElementShareMetric()
    # Force it to gate, matching how a promoted metric would be registered later.
    metric.__class__.gates = True
    try:
        registry.register(metric)
        anchors = [anchor(f"pure-{i}", element="fire", element2="none") for i in range(100)]
        findings = run_all(registry, ctx_with(anchors))
        gating_ids = {m.id for m in registry.all() if m.gates}
        relevant = [f for f in findings if f.metric in gating_ids]
        assert any(f.severity is Severity.GAP for f in relevant)
    finally:
        metric.__class__.gates = False  # restore W1 discipline for every other test in this file
