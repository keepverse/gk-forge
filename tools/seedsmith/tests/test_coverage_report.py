"""Tests for seedsmith.adapters.actions.coverage_report (A-S5, spec-coverage-report.md).

    python -m pytest gk-forge/tools/seedsmith/tests/test_coverage_report.py -v

Spec §5's twelve named cases plus §6's acceptance criteria (1-9, 7b, 7c). Same fixture discipline
every prior module in this session established: the accepted corpus this module measures does not
exist for real (A-S4/A-S3 have never run), so every metric-level test below runs against synthetic,
in-memory `ActionCoverageCtx` fixtures rather than a real `_rounds/round-1/survivors.json` tree. The
one genuinely real thing every test reads directly — never re-typed — is `pairings.json` (for the
"unpaired payoff" case) and the live roster (catalog + family-assignments, for the roster tests),
matching A-S3's own established discipline for exactly this class of test.
"""
from __future__ import annotations

import copy
import json
import random
import socket
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.actions import generate_coverage_report as gen_mod  # noqa: E402
from seedsmith.adapters.actions.characteristic_pool.derive import CATEGORIES  # noqa: E402
from seedsmith.adapters.actions.vocab import SCOPES  # noqa: E402
from seedsmith.adapters.actions.characteristic_pool.catalog import (  # noqa: E402
    derive_live_family_assignments, load_catalog,
)
from seedsmith.adapters.actions.coverage_report import derive as cr  # noqa: E402
from seedsmith.adapters.actions.coverage_report.ctx import (  # noqa: E402
    ActionCoverageCtx, RosterCounts,
)
from seedsmith.adapters.actions.distribution_planner.derive import (  # noqa: E402
    WeightsRow, load_scope_windows,
)
from seedsmith.adapters.actions.load import load_committed  # noqa: E402
from seedsmith.adapters.actions.distribution_planner.tuning import RUN_TUNING_PATH  # noqa: E402
from seedsmith.adapters.actions.vocab import load_family_ids  # noqa: E402
from seedsmith.metrics.action_coverage import (  # noqa: E402
    ALL_ACTION_COVERAGE_CLOSED_METRICS, ALL_ACTION_COVERAGE_OPEN_METRICS,
    EnablerPayoffCoverageMetric, PairingReachMetric, ThinCellMetric,
)
from seedsmith.metrics.model import Ctx, Finding, Loop, Metric, Severity  # noqa: E402
from seedsmith.metrics.registry import MetricRegistry, run_all  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


def _windows():
    """ST3: the windows the entrypoint loads, read from the published rung table -- no test here
    pins a window value, and a retuned file moves every expectation below with it."""
    return load_scope_windows(REPO_ROOT / "data" / "tuning" / "action-rungs.v3.json")


FAMILY_IDS = load_family_ids()                                    # the real 98, read fresh
FAM_A, FAM_B = sorted(FAMILY_IDS)[:2]
PAIRINGS_PATH = REPO_ROOT / "data" / "seed" / "actions" / "pairings.json"
REAL_ACTIONS_ROOT = REPO_ROOT / "data" / "seed" / "actions"
REAL_PLAN_PATH = REAL_ACTIONS_ROOT / "_briefs" / "round-1.json"


# ---------------------------------------------------------------------------------------------
# Fixture builders.
# ---------------------------------------------------------------------------------------------

def _row(id_, scope, scope_key, *, category="attack", rung_band=(1, 10), target_mode="single",
        area_shape=None, relation="enemy", atom_families=(FAM_A,), structure_axes=(),
        pairing_role="none", paired_payoff_family=None, name="Strike"):
    return {
        "id": id_, "scope": scope, "scopeKey": scope_key, "category": category,
        "rungBand": list(rung_band), "targetMode": target_mode, "areaShape": area_shape,
        "relation": relation, "atomFamilies": list(atom_families),
        "structureAxes": list(structure_axes), "pairingRole": pairing_role,
        "pairedPayoffFamily": paired_payoff_family, "name": name,
    }


def _flat_weights() -> WeightsRow:
    return WeightsRow(
        category_milli={"attack": 200, "defense": 200, "support": 200, "movement": 200, "status": 200},
        target_mode_milli={}, area_shape_milli={})


_UNSET = object()   # a caller-passed `pairing_table=None` (missing-input tests) must NOT be
                    # overwritten by the convenience default below — only a genuinely omitted
                    # argument gets one.


def _simple_ctx(accepted_rows, *, quota_by_scope_category=None, subject_category_counts=None,
                roster=None, pairing_table=_UNSET, review_rows=(), mode="smoke", round_no=1):
    """A minimal, hand-built `ActionCoverageCtx` — most tests don't need the real recompute path
    (that path has its own `RecomputeQuotaTests` below), just a fixed quota to test one metric's
    reaction to it."""
    return ActionCoverageCtx(
        accepted_rows=tuple(accepted_rows),
        quota_by_scope_category=quota_by_scope_category or {},
        subject_category_counts=subject_category_counts or {},
        family_ids=FAMILY_IDS,
        pairing_table={} if pairing_table is _UNSET else pairing_table,
        roster=roster or RosterCounts(2, 1, 2),
        scope_windows=_windows(),
        review_rows=tuple(review_rows), round_no=round_no, mode=mode,
    )


def _build_ctx_with_survivors(*, committed, survivors, round_no=1, tmpdir=None):
    """Build a real `ActionCoverageCtx` from an isolated on-disk tree, so the accepted-corpus merge
    (committed + a round's survivors) is exercised exactly as production builds it — never by
    re-implementing the merge in the test. Everything except the two row sets is copied from the
    live tree, so the quota recompute and vocabulary stay real."""
    import shutil
    root = Path(tmpdir) / "actions"
    (root / "_rounds" / f"round-{round_no}").mkdir(parents=True, exist_ok=True)
    real = REAL_ACTIONS_ROOT
    for name in ("type-weights.json", "pairings.json"):
        shutil.copy(real / name, root / name)
    (root / f"committed-round-{round_no}.json").write_text(
        json.dumps({"schemaVersion": 1, "kind": "action-seed",
                    "_meta": {"partition": f"round-{round_no}", "round": round_no},
                    "entries": list(committed)}), encoding="utf-8")
    (root / "_rounds" / f"round-{round_no}" / "survivors.json").write_text(
        json.dumps({"schemaVersion": 1, "kind": "action-seed",
                    "_meta": {"partition": "rounds", "round": round_no},
                    "entries": list(survivors)}), encoding="utf-8")
    return gen_mod._build_ctx(
        actions_root=root, creatures_root=real.parent / "creatures",
        catalog_path=real.parent / "creatures" / "species",
        type_weights_path=root / "type-weights.json", run_tuning_path=RUN_TUNING_PATH,
        family_assignments_path=None, pairings_path=root / "pairings.json", round_no=round_no)


class _TempTreeMixin:
    """A per-test tempdir for the tree-building helpers, torn down automatically."""
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = Path(self._tmp.name)


def _closed_registry() -> MetricRegistry:
    registry = MetricRegistry()
    for metric_cls in ALL_ACTION_COVERAGE_CLOSED_METRICS:
        registry.register(metric_cls())
    return registry


def _open_registry() -> MetricRegistry:
    registry = MetricRegistry()
    for metric_cls in ALL_ACTION_COVERAGE_OPEN_METRICS:
        registry.register(metric_cls())
    return registry


# ---------------------------------------------------------------------------------------------
# Determinism.
# ---------------------------------------------------------------------------------------------

class DeterminismTests(unittest.TestCase):
    def test_two_runs_over_the_same_real_inputs_are_byte_identical_by_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            actions_root = Path(tmp)
            (actions_root / "_reports").mkdir(parents=True)
            first = gen_mod.regenerate(actions_root=actions_root, write=False)
            second = gen_mod.regenerate(actions_root=actions_root, write=False)
        self.assertEqual(first["docHash"], second["docHash"])
        self.assertEqual(first["verdict"], second["verdict"])


# ---------------------------------------------------------------------------------------------
# Planted violation — open metric gates.
# ---------------------------------------------------------------------------------------------

class OpenMetricGatesTests(unittest.TestCase):
    def test_constructing_an_open_metric_with_gates_true_raises_at_registration(self) -> None:
        class _BadOpenMetric(Metric):
            id = "test.bad-open-gates"
            family = "Test"
            loop = Loop.OPEN
            gates = True
            needs = frozenset({"action_coverage"})

            def run(self, ctx: Ctx) -> "list[Finding]":
                return []

        registry = MetricRegistry()
        with self.assertRaises(ValueError) as ctx:
            registry.register(_BadOpenMetric())
        self.assertIn("OPEN-loop metric may never gate", str(ctx.exception))

    def test_both_real_open_metrics_ship_gates_false_and_register_cleanly(self) -> None:
        for metric_cls in ALL_ACTION_COVERAGE_OPEN_METRICS:
            self.assertFalse(metric_cls.gates)
            self.assertIs(metric_cls.loop, Loop.OPEN)
        registry = _open_registry()
        self.assertEqual(len(registry.all()), len(ALL_ACTION_COVERAGE_OPEN_METRICS))

    def test_every_closed_metric_starts_gates_false(self) -> None:
        for metric_cls in ALL_ACTION_COVERAGE_CLOSED_METRICS:
            self.assertFalse(metric_cls.gates)
            self.assertIs(metric_cls.loop, Loop.CLOSED)


# ---------------------------------------------------------------------------------------------
# Planted violation — unevaluated pass (a genuinely missing input -> NOT_MEASURED, never a pass).
# ---------------------------------------------------------------------------------------------

class AcceptedCorpusIsOneRowPerIdTests(_TempTreeMixin, unittest.TestCase):
    """⛔ The 2026-09-12 gate finding (T3.1). The accepted corpus is built as committed rows PLUS a
    round's non-`promoted` survivors. That filter relies on S6 having MARKED every promoted survivor
    in that round's own file — but a survivor file can be stale (the id was promoted by a LATER
    round's S6 run, and this round's file was never reduced to markers). Measured: `round-1/
    survivors.json` held 11 ids already present in `committed-round-2000.json`, with DIFFERENT
    payloads, so the report measured 191 rows for a 179-row corpus and the two reports disagreed
    about the same baseline.

    The invariant the whole pipeline claims is "one id exists in exactly one place". The consumer is
    where a violation does damage, so A-S5 enforces it here: **one row per id, the committed copy
    winning** (it is the promoted, authoritative version; `load_committed` already guarantees committed
    ids are unique). A stale round row is dropped, never merged and never allowed to shadow committed
    content."""

    def test_a_round_row_duplicating_a_committed_id_is_dropped(self) -> None:
        ctx = _build_ctx_with_survivors(
            tmpdir=self.tmpdir,
            committed=[_row("action.x.001", "species", "x")],
            survivors=[_row("action.x.001", "species", "x"), _row("action.x.002", "species", "x")])
        ids = [r["id"] for r in ctx.accepted_rows]
        self.assertEqual(sorted(ids), ["action.x.001", "action.x.002"],
                         "the duplicate id appears once")

    def test_the_committed_copy_wins_a_content_conflict(self) -> None:
        committed_row = dict(_row("action.x.001", "species", "x"), name="committed-wins")
        stale_row = dict(_row("action.x.001", "species", "x"), name="stale-loses")
        ctx = _build_ctx_with_survivors(tmpdir=self.tmpdir, committed=[committed_row],
                                        survivors=[stale_row])
        self.assertEqual(len(ctx.accepted_rows), 1)
        self.assertEqual(ctx.accepted_rows[0]["name"], "committed-wins")

    def test_distinct_round_rows_are_kept(self) -> None:
        ctx = _build_ctx_with_survivors(
            tmpdir=self.tmpdir,
            committed=[_row("action.a.001", "species", "a")],
            survivors=[_row("action.b.001", "species", "b")])
        self.assertEqual(len(ctx.accepted_rows), 2)

    def test_the_real_reports_measure_the_real_committed_corpus(self) -> None:
        """The end-to-end contract on the live tree: a real round's report cannot measure more rows
        than exist once committed plus that round's genuinely-new survivors, and no id repeats."""
        if not REAL_PLAN_PATH.is_file():
            self.skipTest("action corpus not present in this checkout")
        real_root = REAL_ACTIONS_ROOT
        committed = load_committed(real_root).corpus.by_kind("action-seed")
        for round_no in (1, 2000):
            if not (real_root / "_rounds" / f"round-{round_no}" / "survivors.json").is_file():
                continue
            ctx = gen_mod._build_ctx(
                actions_root=real_root, creatures_root=real_root.parent / "creatures",
                catalog_path=real_root.parent / "creatures" / "species",
                type_weights_path=real_root / "type-weights.json",
                run_tuning_path=RUN_TUNING_PATH, family_assignments_path=None,
                pairings_path=real_root / "pairings.json", round_no=round_no)
            ids = [r["id"] for r in ctx.accepted_rows]
            self.assertEqual(len(ids), len(set(ids)),
                             f"round-{round_no} measured a duplicate id")
            self.assertGreaterEqual(len(ids), len(committed))


class VerdictHonoursGatesTests(unittest.TestCase):
    """T1.2 (2026-09-12, spec §3 step 6 + `spec-metrics.md` §4): a metric that has NOT been promoted
    (`gates=False`) reports its GAPs but cannot make the verdict `not-clean`. Promotion is the
    deliberate act that earns the right to gate, and every action-corpus metric ships unpromoted —
    so before this, every GAP blocked the verdict and the full-run gate was unreachable by
    construction. `NOT_MEASURED` stays blocking in every case: an absent check is never a pass."""

    def _verdict(self, findings, *, mode="full", gating=()):
        ids = [m.id for m in ALL_ACTION_COVERAGE_CLOSED_METRICS]
        return cr.compute_verdict(findings, ids, mode, gating_metric_ids=gating)

    def test_a_non_gating_gap_does_not_flip_the_verdict(self) -> None:
        findings = [Finding(metric=ThinCellMetric.id, severity=Severity.GAP, subject="cell.x",
                            message="short")]
        verdict = self._verdict(findings, mode="full", gating=())
        self.assertEqual(verdict.verdict, "pass",
                         "thinCell is not promoted; its GAP is a reading, not a gate")
        self.assertIn(ThinCellMetric.id, verdict.gap_metrics,
                      "the GAP is still reported — it just does not gate")

    def test_a_gating_gap_flips_the_verdict(self) -> None:
        findings = [Finding(metric=ThinCellMetric.id, severity=Severity.GAP, subject="cell.x",
                            message="short")]
        verdict = self._verdict(findings, mode="full", gating=(ThinCellMetric.id,))
        self.assertEqual(verdict.verdict, "not-clean")
        self.assertIn(ThinCellMetric.id, verdict.gap_metrics)

    def test_not_measured_blocks_even_when_not_gating(self) -> None:
        findings = [Finding(metric=PairingReachMetric.id, severity=Severity.NOT_MEASURED,
                            subject="(suite)", message="missing pairings")]
        verdict = self._verdict(findings, mode="full", gating=())
        self.assertNotEqual(verdict.verdict, "pass")
        self.assertNotEqual(verdict.verdict, "smoke-clean")

    def test_the_verdict_reports_which_metrics_are_gating(self) -> None:
        """The report must say WHICH metrics can gate, so a reader can tell a real gate from a
        reading without opening the registry."""
        verdict = self._verdict([], mode="full", gating=(ThinCellMetric.id,))
        self.assertEqual(verdict.gating_metrics, (ThinCellMetric.id,))

    def test_shipped_registry_ships_no_gating_action_metrics(self) -> None:
        """Calibration order (`spec-metrics.md` §4): measure, look, set, gate. Nothing here has been
        promoted, so with real findings the run verdict is not blocked by an unpromoted metric."""
        self.assertTrue(all(not m.gates for m in ALL_ACTION_COVERAGE_CLOSED_METRICS),
                        "no action-corpus metric is promoted yet")


class UnevaluatedPassTests(unittest.TestCase):
    def test_missing_pairings_json_yields_not_measured_and_a_non_pass_verdict(self) -> None:
        cov = _simple_ctx([], pairing_table=None)
        ctx = Ctx(corpus=None, adapter=None, action_coverage=cov)
        findings = run_all(_closed_registry(), ctx)

        pairing_reach = [f for f in findings if f.metric == PairingReachMetric.id]
        enabler_payoff = [f for f in findings if f.metric == EnablerPayoffCoverageMetric.id]
        self.assertTrue(all(f.severity is Severity.NOT_MEASURED for f in pairing_reach))
        self.assertTrue(all(f.severity is Severity.NOT_MEASURED for f in enabler_payoff))
        self.assertTrue(len(pairing_reach) >= 1 and len(enabler_payoff) >= 1)

        closed_ids = [m.id for m in ALL_ACTION_COVERAGE_CLOSED_METRICS]
        verdict = cr.compute_verdict(findings, closed_ids, cov.mode)
        self.assertIn(PairingReachMetric.id, verdict.not_measured_metrics)
        self.assertNotEqual(verdict.verdict, "pass")
        self.assertNotEqual(verdict.verdict, "smoke-clean")


# ---------------------------------------------------------------------------------------------
# Planted violation — thin cell hidden.
# ---------------------------------------------------------------------------------------------

class ThinCellHiddenTests(unittest.TestCase):
    def test_an_empty_planned_cell_produces_a_thin_and_occupancy_finding_naming_the_cell(self) -> None:
        quota = {("species", "attack"): 7}
        cov = _simple_ctx([], quota_by_scope_category=quota)
        ctx = Ctx(corpus=None, adapter=None, action_coverage=cov)
        findings = run_all(_closed_registry(), ctx)

        occ = [f for f in findings if f.metric == "action.corpus.cellOccupancy"]
        thin = [f for f in findings if f.metric == "action.corpus.thinCell"]
        self.assertEqual(len(occ), 1)
        self.assertIn("cell.species.attack.1-10", occ[0].subject)
        self.assertEqual(len(thin), 1)
        self.assertEqual(thin[0].evidence["shortfall"], 7)

        closed_ids = [m.id for m in ALL_ACTION_COVERAGE_CLOSED_METRICS]
        verdict = cr.compute_verdict(findings, closed_ids, cov.mode)
        self.assertNotEqual(verdict.verdict, "pass")
        self.assertNotEqual(verdict.verdict, "smoke-clean")
        self.assertIn("action.corpus.thinCell", verdict.gap_metrics)

    def test_a_partially_filled_cell_is_thin_but_not_missing(self) -> None:
        quota = {("species", "attack"): 7}
        rows = [_row(f"action.species.x.{i:03d}", "species", "x") for i in range(3)]
        cov = _simple_ctx(rows, quota_by_scope_category=quota)
        occ = cr.cell_occupancy_findings("m", cov)
        thin = cr.thin_cell_findings("m", cov)
        self.assertEqual(occ, [])
        self.assertEqual(len(thin), 1)
        self.assertEqual(thin[0].evidence["shortfall"], 4)

    def test_a_zero_quota_cell_is_never_thin_or_missing(self) -> None:
        cov = _simple_ctx([], quota_by_scope_category={})
        self.assertEqual(cr.cell_occupancy_findings("m", cov), [])
        self.assertEqual(cr.thin_cell_findings("m", cov), [])

    def test_every_planned_cell_carries_a_count_and_quota_even_at_zero(self) -> None:
        """Acceptance #4."""
        cov = _simple_ctx([], quota_by_scope_category={})
        groups = cr.build_cell_groups(cov.accepted_rows, cov.quota_by_scope_category,
                                      cov.scope_windows)
        entries = cr.cell_entries(groups, round_no=1)
        # 3 scopes x 5 categories x 3 pairingRoles. Scopes come from the shipped rung table --
        # pin: immutable gk-core/data/tuning/action-rungs.v3.json
        self.assertEqual(len(entries), 45)
        for e in entries:
            self.assertIn("count", e)
            self.assertIn("quota", e)
            self.assertEqual(e["quota"], 0)
            self.assertEqual(e["count"], 0)
            self.assertFalse(e["thin"])


# ---------------------------------------------------------------------------------------------
# Planted violation — unpaired payoff. Reads pairings.json's own first key/enabler at test time.
# ---------------------------------------------------------------------------------------------

class UnpairedPayoffTests(unittest.TestCase):
    def test_a_payoff_family_with_no_enabler_in_the_same_anchor_fails(self) -> None:
        pairing_table = json.loads(PAIRINGS_PATH.read_text(encoding="utf-8"))
        payoff_key = sorted(pairing_table)[0]
        enabler = sorted(pairing_table[payoff_key])[0]

        # payoff present, its enabler absent from the SAME anchor
        rows = [_row("action.species.x.001", "species", "x", atom_families=[payoff_key])]
        cov = _simple_ctx(rows, pairing_table={k: tuple(v) for k, v in pairing_table.items()})
        findings = cr.enabler_payoff_coverage_findings("m", cov)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.GAP)
        self.assertIn(payoff_key, findings[0].message)

        # now with the enabler present in the same anchor -> clean
        rows_ok = rows + [_row("action.species.x.002", "species", "x", atom_families=[enabler])]
        cov_ok = _simple_ctx(rows_ok, pairing_table={k: tuple(v) for k, v in pairing_table.items()})
        self.assertEqual(cr.enabler_payoff_coverage_findings("m", cov_ok), [])

    def test_pairing_reach_is_honestly_nonzero_against_the_real_pairings_file(self) -> None:
        """⛔ CORRECTED 2026-09-06 -- was `..._is_honestly_zero...`, true only while pairings.json
        named ids outside the namespace. `atom.chill-punisher`/`atom.rot-punisher` are now real
        (g-punisher.json) -- pairingReach must say so, never keep reporting the stale zero."""
        pairing_table = json.loads(PAIRINGS_PATH.read_text(encoding="utf-8"))
        cov = _simple_ctx([], pairing_table={k: tuple(v) for k, v in pairing_table.items()})
        findings = cr.pairing_reach_findings("m", cov)
        self.assertEqual(len(findings), 1)
        self.assertIn(f"2/{len(FAMILY_IDS)} authored affix families are reachable payoff keys",
                      findings[0].message)
        self.assertEqual(set(findings[0].evidence["reachablePayoffKeys"]),
                         {"atom.chill-punisher", "atom.rot-punisher"})


# ---------------------------------------------------------------------------------------------
# Planted violation — a family outside the namespace.
# ---------------------------------------------------------------------------------------------

class FamilyOutsideNamespaceTests(unittest.TestCase):
    def test_a_fixture_atom_family_outside_the_98_is_refused(self) -> None:
        rows = [_row("action.general.0001", "general", None,
                     atom_families=["atom.fx-cold-on-hit"])]
        cov = _simple_ctx(rows)
        findings = cr.atom_family_namespace_findings("m", cov)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.GAP)
        self.assertIn("atom.fx-cold-on-hit", findings[0].message)
        self.assertIn("action.general.0001", findings[0].subject)

    def test_a_real_98_family_id_is_not_refused(self) -> None:
        rows = [_row("action.general.0001", "general", None, atom_families=[FAM_A, FAM_B])]
        cov = _simple_ctx(rows)
        self.assertEqual(cr.atom_family_namespace_findings("m", cov), [])


# ---------------------------------------------------------------------------------------------
# Planted violation — a status where a family belongs.
# ---------------------------------------------------------------------------------------------

class StatusWhereFamilyBelongsTests(unittest.TestCase):
    def test_a_bare_status_id_in_paired_payoff_family_is_refused_naming_the_field(self) -> None:
        rows = [_row("action.general.0001", "general", None, pairing_role="enabler",
                     paired_payoff_family="rot")]
        cov = _simple_ctx(rows)
        findings = cr.atom_family_namespace_findings("m", cov)
        self.assertEqual(len(findings), 1)
        self.assertIn("STATUS id", findings[0].message)
        self.assertIn("pairedPayoffFamily", findings[0].subject)


# ---------------------------------------------------------------------------------------------
# Planted violation — reaction accepted.
# ---------------------------------------------------------------------------------------------

class ReactionAcceptedTests(unittest.TestCase):
    def test_a_row_spending_reaction_fails_structure_enforceability(self) -> None:
        rows = [_row("action.general.0001", "general", None, structure_axes=["reaction"])]
        cov = _simple_ctx(rows)
        findings = cr.structure_enforceability_findings("m", cov)
        gaps = [f for f in findings if f.severity is Severity.GAP]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].subject, "reaction")
        self.assertEqual(gaps[0].evidence["count"], 1)

    def test_restriction_is_reported_as_a_note_not_a_gap(self) -> None:
        rows = [_row("action.general.0001", "general", None, structure_axes=["restriction"])]
        cov = _simple_ctx(rows)
        findings = cr.structure_enforceability_findings("m", cov)
        self.assertTrue(all(f.severity is not Severity.GAP for f in findings))
        restriction = [f for f in findings if f.subject == "restriction"][0]
        self.assertEqual(restriction.evidence["count"], 1)

    def test_zero_reaction_is_a_clean_note(self) -> None:
        cov = _simple_ctx([])
        findings = cr.structure_enforceability_findings("m", cov)
        self.assertTrue(all(f.severity is not Severity.GAP for f in findings))


# ---------------------------------------------------------------------------------------------
# Live roster reconciliation.
# ---------------------------------------------------------------------------------------------

class RosterReconciliationTests(unittest.TestCase):
    """The roster reconciliation REPORT is driven by whatever counts it is handed — the test passes
    its own synthetic counts so the arithmetic (band, estimate, message) is what is pinned, not the
    live roster size, which grows per shipped species (validation-ssot.md)."""

    def test_reconciliation_reports_the_arithmetic_it_was_given(self) -> None:
        live_roster = RosterCounts(species_count=900, family_count=220,
                                   family_assigned_count=1200)
        findings = cr.roster_reconciliation_findings("m", live_roster, accepted_corpus_size=0,
                                                     signature_actions_per_species=5)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.NOTE)
        self.assertIn("900 x 5 = 4500", findings[0].message)

    def test_the_live_seed_roster_re_derives_against_the_run_tuning(self) -> None:
        """Acceptance #6 — re-verify the roster numbers directly rather than trusting any prompt.
        Asserted as a RELATIONSHIP (catalog ↔ family map ↔ reconciliation), never a pinned size."""
        catalog = load_catalog()
        family_assignments = derive_live_family_assignments()
        members = gen_mod._family_members(family_assignments)
        roster = RosterCounts(species_count=len(catalog), family_count=len(members),
                              family_assigned_count=sum(len(v) for v in members.values()))
        self.assertEqual(roster.species_count, len({r.species_id for r in catalog}))
        self.assertEqual(roster.family_count, len(members))
        self.assertEqual(roster.family_assigned_count,
                         sum(len(v if isinstance(v, list) else [v])
                             for v in family_assignments.values()))

        findings = cr.roster_reconciliation_findings("m", roster, accepted_corpus_size=0,
                                                     signature_actions_per_species=5)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.NOTE)
        evidence = findings[0].evidence
        self.assertEqual(evidence["signatureTierEstimate"], roster.species_count * 5)
        self.assertEqual(evidence["researchBandRoster"], roster.species_count)
        # the message must show the re-derivation arithmetic, never just repeat "1,500-3,500"
        self.assertIn(f"{roster.species_count} x 5 = {roster.species_count * 5}",
                      findings[0].message)
        self.assertIn("inside/above", findings[0].message)


# ---------------------------------------------------------------------------------------------
# Next-round targets — pure function + shuffle invariance.
# ---------------------------------------------------------------------------------------------

class RetunedWindowReachesTheReportTests(unittest.TestCase):
    """ST3 contract 3, second half: a retuned window must reach this stage's OUTPUT, not merely
    load. The planned cell's own band comes from the loaded windows, so retuning moves it."""

    RUNG_TABLE_PATH = REPO_ROOT / "data" / "tuning" / "action-rungs.v3.json"

    def test_a_retuned_general_ceiling_moves_the_planned_cell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "action-rungs.v3.json"
            doc = json.loads(self.RUNG_TABLE_PATH.read_text(encoding="utf-8"))
            doc["scopeWindows"]["general"]["ceiling"] = 6     # still <= family's own ceiling
            path.write_text(json.dumps(doc), encoding="utf-8")
            windows = load_scope_windows(path)

        self.assertNotEqual(windows["general"], _windows()["general"], "fixture must really retune")

        subject_counts = {("general", "general"): {
            "attack": 1, "defense": 0, "support": 0, "movement": 0, "status": 0}}
        quota = cr.aggregate_scope_category_quota(subject_counts)
        rows = [_row("action.general.general.001", "general", None, rung_band=(1, 6))]

        groups = cr.build_cell_groups(rows, quota, windows)
        general_attack = [g for g in groups if (g.scope, g.category) == ("general", "attack")]

        self.assertEqual([tuple(g.rung_band) for g in general_attack], [(1, 6)],
                         "the planned general cell must sit at the RETUNED band")
        self.assertEqual(sum(g.total_count for g in general_attack), 1,
                         "and the row authored at that band is the planned cell, not an "
                         "off-window group")


class NextRoundTargetsTests(unittest.TestCase):
    def _fixture(self):
        subject_counts = {
            ("species", "alpha"): {"attack": 5, "defense": 0, "support": 0, "movement": 0, "status": 0},
            ("species", "beta"): {"attack": 3, "defense": 0, "support": 0, "movement": 0, "status": 0},
        }
        quota = cr.aggregate_scope_category_quota(subject_counts)
        rows = [_row(f"action.species.alpha.{i:03d}", "species", "alpha") for i in range(2)]
        groups = cr.build_cell_groups(rows, quota, _windows())
        return groups, subject_counts, rows

    def test_same_inputs_produce_the_same_targets(self) -> None:
        groups, subject_counts, rows = self._fixture()
        first = cr.next_round_targets(groups=groups, subject_counts=subject_counts,
                                      accepted_rows=rows, round_no=1, windows=_windows())
        second = cr.next_round_targets(groups=groups, subject_counts=subject_counts,
                                       accepted_rows=rows, round_no=1, windows=_windows())
        self.assertEqual(first, second)
        self.assertTrue(len(first) >= 1)

    def test_shuffling_accepted_row_order_changes_nothing(self) -> None:
        groups, subject_counts, rows = self._fixture()
        baseline = cr.next_round_targets(groups=groups, subject_counts=subject_counts,
                                         accepted_rows=rows, round_no=1, windows=_windows())
        shuffled = list(rows)
        random.Random(42).shuffle(shuffled)
        result = cr.next_round_targets(groups=groups, subject_counts=subject_counts,
                                       accepted_rows=shuffled, round_no=1, windows=_windows())
        self.assertEqual(baseline, result)

    def test_targets_are_ordered_by_shortfall_desc_then_subject_key(self) -> None:
        groups, subject_counts, rows = self._fixture()
        targets = cr.next_round_targets(groups=groups, subject_counts=subject_counts,
                                        accepted_rows=rows, round_no=1, windows=_windows())
        attack_targets = [t for t in targets if t["category"] == "attack"]
        wants = [t["want"] for t in attack_targets]
        self.assertEqual(wants, sorted(wants, reverse=True))
        # beta (shortfall 3) should sort ahead of alpha (shortfall 3) only if wants tie -> then
        # subjectKey ascending; alpha's shortfall is 5-2=3, beta's is 3-0=3 -- a real tie, so
        # alpha (< beta) must come first.
        self.assertEqual([t["scopeKey"] for t in attack_targets], ["alpha", "beta"])

    def test_target_ids_follow_the_action_coverage_id_grammar(self) -> None:
        groups, subject_counts, rows = self._fixture()
        targets = cr.next_round_targets(groups=groups, subject_counts=subject_counts,
                                        accepted_rows=rows, round_no=1, windows=_windows())
        for t in targets:
            self.assertTrue(t["id"].startswith("target.round-2."))
            self.assertEqual(t["kindOfEntry"], "next-target")

    def test_off_window_band_group_emits_no_second_target(self) -> None:
        """Phase-4-found 2026-09-15 (real latent defect, exposed by `act.attack`): an accepted
        row whose own rungBand misses its scope's planned window surfaces as its own group
        (`build_cell_groups`), but the target id carries no band — so emitting from both groups
        duplicates `target.round-2.<scope>.<subject>.<category>` and `Corpus.load` refuses the
        whole report. Only the planned-window group drives top-up; the off-window rows still
        count toward the same subject shortfalls, so nothing is lost."""
        subject_counts = {("general", "general"): {
            "attack": 5, "defense": 0, "support": 0, "movement": 0, "status": 0}}
        quota = cr.aggregate_scope_category_quota(subject_counts)
        planned_band = tuple(_windows()["general"])             # (1, 4) at the shipped values
        off_band = (planned_band[1] + 1, planned_band[1] + 2)   # misses the window
        rows = [_row(f"action.general.general.{i:03d}", "general", None, rung_band=planned_band)
                for i in range(2)]
        rows.append(_row("action.general.general.003", "general", None, rung_band=off_band))
        groups = cr.build_cell_groups(rows, quota, _windows())
        bands = {(g.scope, g.category, tuple(g.rung_band)) for g in groups
                 if (g.scope, g.category) == ("general", "attack")}
        self.assertEqual(len(bands), 2, "fixture must contain the off-window group")
        targets = cr.next_round_targets(groups=groups, subject_counts=subject_counts,
                                        accepted_rows=rows, round_no=1, windows=_windows())
        ids = [t["id"] for t in targets]
        self.assertEqual(len(ids), len(set(ids)), "no duplicate target id")
        attack_targets = [t for t in targets if t["category"] == "attack"]
        self.assertEqual(len(attack_targets), 1)
        # All three rows count toward the one subject shortfall: want == 5 - 3, stated once.
        self.assertEqual(attack_targets[0]["want"], 2)


# ---------------------------------------------------------------------------------------------
# Small batch honesty.
# ---------------------------------------------------------------------------------------------

class SmallBatchHonestyTests(unittest.TestCase):
    def test_twelve_accepted_rows_never_produce_a_corpus_level_pass(self) -> None:
        weights = _flat_weights()
        subject_count = 12
        subject_counts = {}
        for i in range(subject_count):
            subject_counts[("species", f"sp{i}")] = {"attack": 1, "defense": 0, "support": 0,
                                                      "movement": 0, "status": 0}
        quota = cr.aggregate_scope_category_quota(subject_counts)
        rows = [_row(f"action.species.sp{i}.001", "species", f"sp{i}") for i in range(subject_count)]
        cov = _simple_ctx(rows, quota_by_scope_category=quota,
                          subject_category_counts=subject_counts, mode="smoke")
        ctx = Ctx(corpus=None, adapter=None, action_coverage=cov)
        findings = run_all(_closed_registry(), ctx)
        closed_ids = [m.id for m in ALL_ACTION_COVERAGE_CLOSED_METRICS]
        verdict = cr.compute_verdict(findings, closed_ids, cov.mode)

        # Self-referential (population-pin SE3.5, 2026-09-20): this test built subject_count rows
        # itself, so it proves none were lost, not a fact about shipped content.
        self.assertEqual(subject_count, len(cov.accepted_rows))
        self.assertNotEqual(verdict.verdict, "pass")
        self.assertGreater(len(findings), 0)


# ---------------------------------------------------------------------------------------------
# Offline guarantee.
# ---------------------------------------------------------------------------------------------

class OfflineGuaranteeTests(unittest.TestCase):
    def test_no_source_file_references_the_llm_transport(self) -> None:
        forbidden = ("llm_caller", "langchain", "langgraph", "requests", "urllib.request", "httpx")
        paths = list((REPO_ROOT / "tools" / "seedsmith" / "seedsmith" / "adapters" / "actions"
                     / "coverage_report").glob("*.py"))
        paths.append(REPO_ROOT / "tools" / "seedsmith" / "seedsmith" / "adapters" / "actions"
                    / "generate_coverage_report.py")
        paths.append(REPO_ROOT / "tools" / "seedsmith" / "seedsmith" / "metrics"
                    / "action_coverage.py")
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{path.name} references {token!r}")

    def test_regenerate_opens_no_non_loopback_socket(self) -> None:
        real_connect = socket.socket.connect
        attempts: list = []

        def guarded(self, address):
            host = address[0] if isinstance(address, tuple) else str(address)
            if isinstance(host, str) and not (
                host.startswith("127.") or host in ("localhost", "::1", "0.0.0.0")
            ):
                attempts.append(address)
                raise AssertionError(f"non-loopback connection attempted: {address}")
            return real_connect(self, address)

        socket.socket.connect = guarded
        try:
            gen_mod.regenerate(write=False)
        finally:
            socket.socket.connect = real_connect
        self.assertEqual(attempts, [])


# ---------------------------------------------------------------------------------------------
# Quota recomputation (spec §3 step 2) and quotaDrift.
# ---------------------------------------------------------------------------------------------

class RecomputeQuotaTests(unittest.TestCase):
    def test_recompute_uses_the_same_largest_remainder_helper(self) -> None:
        weights = _flat_weights()
        subject_counts = cr.recompute_subject_category_counts(
            species_ids=["alpha", "beta"], family_members={},
            weights_by_key={("species", "alpha"): weights, ("species", "beta"): weights},
            general_count=0, per_family_count=0, per_species_count=5)
        self.assertEqual(sum(subject_counts[("species", "alpha")].values()), 5)
        self.assertEqual(sum(subject_counts[("species", "beta")].values()), 5)

    def test_quota_drift_flags_overshoot_beyond_tolerance(self) -> None:
        quota = {("species", "attack"): 5}
        rows = [_row(f"action.species.x.{i:03d}", "species", "x") for i in range(10)]
        cov = _simple_ctx(rows, quota_by_scope_category=quota)
        findings = cr.quota_drift_findings("m", cov)
        gaps = [f for f in findings if f.severity is Severity.GAP]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].evidence["driftUnits"], 5)

    def test_quota_drift_within_tolerance_is_a_note(self) -> None:
        quota = {("species", "attack"): 5}
        rows = [_row(f"action.species.x.{i:03d}", "species", "x") for i in range(6)]
        cov = _simple_ctx(rows, quota_by_scope_category=quota)
        findings = cr.quota_drift_findings("m", cov)
        self.assertTrue(all(f.severity is Severity.NOTE for f in findings))


# ---------------------------------------------------------------------------------------------
# Species collision.
# ---------------------------------------------------------------------------------------------

class SpeciesCollisionTests(unittest.TestCase):
    def test_two_species_with_identical_signature_sets_collide(self) -> None:
        rows = [
            _row("action.species.a.001", "species", "a", category="attack"),
            _row("action.species.b.001", "species", "b", category="attack"),
        ]
        cov = _simple_ctx(rows)
        findings = cr.species_collision_findings("m", cov)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.GAP)

    def test_two_species_with_different_categories_do_not_collide(self) -> None:
        rows = [
            _row("action.species.a.001", "species", "a", category="attack"),
            _row("action.species.b.001", "species", "b", category="defense"),
        ]
        cov = _simple_ctx(rows)
        self.assertEqual(cr.species_collision_findings("m", cov), [])


# ---------------------------------------------------------------------------------------------
# Singleton share (measure-only).
# ---------------------------------------------------------------------------------------------

class SingletonShareTests(unittest.TestCase):
    def test_all_singleton_cells_report_100_percent_share(self) -> None:
        rows = [
            _row("action.species.a.001", "species", "a", category="attack"),
            _row("action.species.a.002", "species", "a", category="defense"),
        ]
        cov = _simple_ctx(rows)
        findings = cr.singleton_share_findings("m", cov)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].evidence["singletonShare"], 1.0)

    def test_no_accepted_rows_is_not_measured(self) -> None:
        cov = _simple_ctx([])
        findings = cr.singleton_share_findings("m", cov)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.NOT_MEASURED)


# ---------------------------------------------------------------------------------------------
# Open metrics — review queue only, never a defect.
# ---------------------------------------------------------------------------------------------

class OpenMetricsReviewQueueTests(unittest.TestCase):
    def test_flavour_quality_flags_a_generic_name_as_a_note(self) -> None:
        rows = [_row("action.species.a.001", "species", "a", name="Attack")]
        cov = _simple_ctx(rows)
        findings = cr.flavour_quality_findings("m", cov)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.NOTE)

    def test_semantic_neighbour_passes_through_review_rows(self) -> None:
        review_rows = [{"candidateA": "action.species.a.001", "candidateB": "action.species.a.002",
                       "similarityMilli": 900}]
        cov = _simple_ctx([], review_rows=review_rows)
        findings = cr.semantic_neighbour_findings("m", cov)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.NOTE)

    def test_open_metrics_never_appear_in_the_closed_verdict_computation(self) -> None:
        rows = [_row("action.species.a.001", "species", "a", name="Attack")]
        cov = _simple_ctx(rows)
        ctx = Ctx(corpus=None, adapter=None, action_coverage=cov)
        open_findings = run_all(_open_registry(), ctx)
        closed_ids = [m.id for m in ALL_ACTION_COVERAGE_CLOSED_METRICS]
        for f in open_findings:
            self.assertNotIn(f.metric, closed_ids)


# ---------------------------------------------------------------------------------------------
# Real, honest report over round-1.json's plan with zero accepted rows — the module's own
# legitimate "small-batch honesty" case, run for real against the live tree (spec §1).
# ---------------------------------------------------------------------------------------------

class RealNonzeroAcceptedReportTests(unittest.TestCase):
    """Renamed from `RealZeroAcceptedReportTests` (2026-09-04, expanded real smoke batch): this
    checkout's accepted corpus is no longer genuinely empty -- A-S6 (`innate_picker`) has for the
    first time promoted real A-P1/A-P2/A-P3 survivors into `committed-round-1.json` /
    `committed-round-2.json` (24 real accepted rows total), so a real `regenerate()` call now
    measures real, non-empty content rather than degrading to the "small batch honesty" zero case
    this class used to pin. That empty-corpus behavior is still real and still covered --
    `SyntheticContentTests`/`OfflineGuaranteeTests` elsewhere in this file exercise it directly --
    this class only ever asserted it against the REAL checkout, which has permanently moved on."""

    def test_a_real_run_reports_the_real_accepted_corpus_with_gaps_visible_but_not_gating(self) -> None:
        summary = gen_mod.regenerate(write=False)
        # The accepted corpus is a POPULATION (it grows every round and every promotion), so its
        # size is a reading, never a literal (validation-ssot.md). Assert the CONTRACT instead:
        # the report measured SOME real content, and that number reconciles to the committed corpus
        # plus this round's survivors.
        self.assertGreater(summary["acceptedCorpusSize"], 0)
        committed = load_committed(gen_mod.ACTIONS_ROOT)
        committed_rows = committed.corpus.by_kind("action-seed")
        self.assertGreater(len(committed_rows), 0)
        self.assertGreaterEqual(summary["acceptedCorpusSize"], len(committed_rows))
        # ⛔ UPDATED 2026-09-12 (T1.2): the run verdict is `pass` now that `gates` decides it — no
        # action-corpus metric is promoted, so a GAP is a reading and a next-round work order, not a
        # gate (spec-metrics.md §4; spec §3 step 6). The thin corpus is still VISIBLE: `gapMetrics`
        # is non-empty and every gap is named. "Non-pass" was the old (pre-fix) semantics.
        self.assertEqual(summary["verdict"], "pass")
        self.assertNotEqual(summary["gapMetrics"], [],
                            "the thin corpus is still reported, it just does not gate")
        # ⛔ FIXED 2026-09-15 (stale test, not a generator defect): `cellCount` was pinned to
        # the literal 15. `build_cell_groups` emits the planned (scope × category) groups PLUS one
        # group per distinct off-window rungBand found on real accepted rows (derive.py:186-192 —
        # real content is never silently hidden), so the total grows with the corpus and must not
        # be pinned (validation-ssot.md: populations are readings). Assert the CONTRACT instead:
        # the summary reconciles to its own derivation over the same ctx, and the planned floor —
        # 3 scopes × 5 categories, both CLOSED vocabularies pinned by their own registry tests —
        # is always present (acceptance #4).
        cov = gen_mod._build_ctx(
            actions_root=gen_mod.ACTIONS_ROOT, creatures_root=gen_mod.CREATURES_ROOT,
            catalog_path=gen_mod.CATALOG_PATH, type_weights_path=gen_mod.TYPE_WEIGHTS_PATH,
            run_tuning_path=gen_mod.RUN_TUNING_PATH, family_assignments_path=None,
            pairings_path=gen_mod.PAIRINGS_PATH, round_no=1)
        groups = cr.build_cell_groups(cov.accepted_rows, cov.quota_by_scope_category,
                                      cov.scope_windows)
        self.assertEqual(summary["cellCount"], len(groups))
        self.assertGreaterEqual(summary["cellCount"], len(SCOPES) * len(CATEGORIES))
        # pairings.json IS present in this checkout, so both pairing metrics run; with a real,
        # non-empty accepted corpus every metric below now has occupied mechanical cells to
        # measure, so nothing degrades to NOT_MEASURED any more (contrast the old empty-corpus
        # pin: `["action.corpus.singletonShare"]`).
        self.assertEqual(summary["notMeasuredMetrics"], [])
        # The real gaps this thin corpus actually has -- the thin-corpus signature is
        # asserted as a SUBSET (acceptance #3: named explicitly, never silently absorbed into a
        # green verdict), never as an exact set: the gap SET grows with real content (validation-
        # ssot.md). `speciesCoverage` (G3, 2026-09-12) joins them: the corpus names a fraction of
        # the 904-species roster, which the scope-aggregate cells cannot see.
        # ⛔ NOTED 2026-09-15: `atomFamilyNamespace` also reports — subject `act.attack`
        # (hand-authored `authored-basics.json` fallback) carries `atom.fx-overlay-damage`, an id
        # outside the 98 authored affix families. That row is authored content, not generator
        # output, so "fixing" it here would be the exact hand-edit the generated-data rule forbids;
        # whether a hand-authored basic may spend a non-98 atom id is the action program's spec
        # question, not this generator's. The metric reporting it is the metric working.
        self.assertTrue({"action.corpus.enablerPayoffCoverage", "action.corpus.speciesCoverage",
                         "action.corpus.thinCell"}.issubset(set(summary["gapMetrics"])))


class SpeciesCoverageMetricTests(unittest.TestCase):
    """G3 (2026-09-12): the per-SUBJECT coverage gate. A scope-aggregate cell
    (`cell.species.attack.1-10`, quota 976 over 904 species) can pass while hundreds of species hold
    nothing, so this metric asserts every PLANNED species subject has at least one accepted row."""

    @staticmethod
    def _ctx(subject_keys: "list[str]", accepted_scope_keys: "list[str]") -> ActionCoverageCtx:
        subject_counts = {("species", k): {"attack": 1} for k in subject_keys}
        return ActionCoverageCtx(
            accepted_rows=tuple({"scope": "species", "scopeKey": k, "category": "attack",
                                 "targetMode": "self", "relation": "enemy", "pairingRole": "none",
                                 "atomFamilies": ["atom.might"], "rungBand": [1, 10],
                                 "structureAxes": []}
                                for k in accepted_scope_keys),
            quota_by_scope_category={("species", "attack"): len(subject_keys)},
            subject_category_counts=subject_counts,
            family_ids=frozenset({"atom.might"}),
            pairing_table={},
            roster=RosterCounts(species_count=len(subject_keys), family_count=1,
                                family_assigned_count=len(subject_keys)),
            scope_windows=_windows())

    def test_an_uncovered_species_is_a_gap_naming_that_species(self) -> None:
        ctx = self._ctx(["alpha", "beta", "gamma"], ["alpha"])
        findings = cr.species_coverage_findings("m", ctx)
        self.assertEqual(sorted(f.subject for f in findings), ["beta", "gamma"])
        self.assertTrue(all(f.severity == Severity.GAP for f in findings))
        for f in findings:
            self.assertEqual(f.evidence["coveredSpecies"], 1)
            self.assertEqual(f.evidence["requiredSpecies"], 3)

    def test_full_coverage_produces_no_findings(self) -> None:
        ctx = self._ctx(["alpha", "beta"], ["alpha", "beta", "gamma"])
        self.assertEqual(cr.species_coverage_findings("m", ctx), [])

    def test_it_is_scope_aggregate_blind_by_construction(self) -> None:
        """The point of the metric: a fully-satisfied aggregate cell coexists with uncovered
        species. The cell here has count == quota, yet 2 of 3 species are uncovered."""
        ctx = self._ctx(["alpha", "beta", "gamma"], ["alpha"])
        findings = cr.species_coverage_findings("m", ctx)
        self.assertEqual(len(findings), 2, "the aggregate is satisfied; the species are not")

    def test_required_universe_comes_from_the_quota_subjects(self) -> None:
        """It must use exactly the planner's subjects, not a second roster read — a species the
        quota was not recomputed for is not this metric's to require."""
        ctx = self._ctx(["alpha", "beta"], [])
        self.assertEqual({f.subject for f in cr.species_coverage_findings("m", ctx)},
                         {"alpha", "beta"})

    def test_deterministic(self) -> None:
        ctx = self._ctx(["beta", "alpha"], [])
        self.assertEqual(cr.species_coverage_findings("m", ctx),
                         cr.species_coverage_findings("m", ctx))


class SignatureCountIsRequiredNotDefaultedTests(unittest.TestCase):
    """G4 (2026-09-12): `signature_actions_per_species` had a module-constant default of 3 (the
    SEALED ideal's B1 number) while the shipped tuning sets `perSpeciesCount: 5`. The default was
    dead — the one caller always passes the tuning value — but a wrong default that is never reached
    is a second, contradictory source of truth. It is now a REQUIRED parameter."""

    def test_no_module_constant_exists(self) -> None:
        self.assertFalse(hasattr(cr, "SIGNATURE_ACTIONS_PER_SPECIES"),
                         "the contradictory default constant must be gone")

    def test_the_parameter_is_required(self) -> None:
        import inspect
        sig = inspect.signature(cr.roster_reconciliation_findings)
        self.assertIs(inspect.Parameter.empty,
                      sig.parameters["signature_actions_per_species"].default,
                      "a default would let a future caller silently get the wrong count")

    def test_the_metric_passes_the_live_tuning_count(self) -> None:
        """The registered metric must read `cov.per_species_count`, never a literal."""
        from seedsmith.metrics.action_coverage import RosterReconciliationMetric
        import inspect
        src = inspect.getsource(RosterReconciliationMetric.run)
        self.assertIn("per_species_count", src)


if __name__ == "__main__":
    unittest.main()
