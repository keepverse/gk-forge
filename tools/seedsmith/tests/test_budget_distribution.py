"""Tests for seedsmith.budget and seedsmith.metrics.distribution (tasks/seedsmith-todo.md, S6).

    python -m pytest gk-forge/tools/seedsmith/tests/test_budget_distribution.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items import ItemsAdapter  # noqa: E402
from seedsmith.budget import BudgetRow, Derivation, Provenance, Tolerance, derive_all  # noqa: E402
from seedsmith.corpus import Corpus  # noqa: E402
from seedsmith.metrics import Ctx, MetricRegistry, Severity, run_all  # noqa: E402
from seedsmith.metrics.distribution import CellDeviation, Evenness, Inequality  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
LIVE_ITEMS_ROOT = REPO_ROOT / "data" / "seed" / "items"


class BudgetRowConflictTests(unittest.TestCase):
    def test_row_with_an_authoritative_source_is_not_a_conflict(self) -> None:
        row = BudgetRow(dimension="kind:x", target=5, tolerance=Tolerance(), rationale="r",
                        derivation=Derivation.STATED,
                        provenance=(Provenance(5, "doc", "ok", authoritative=True),))
        self.assertFalse(row.conflict)

    def test_row_with_no_authoritative_source_is_a_conflict(self) -> None:
        row = BudgetRow(dimension="kind:x", target=5, tolerance=Tolerance(), rationale="r",
                        derivation=Derivation.STATED,
                        provenance=(Provenance(20, "a", "old"), Provenance(300, "b", "stale")))
        self.assertTrue(row.conflict)

    def test_row_with_no_provenance_at_all_is_not_treated_as_a_conflict(self) -> None:
        # A structural row with a single self-evidently-authoritative computation may have no
        # separate provenance list to disagree with itself.
        row = BudgetRow(dimension="kind:x", target=5, tolerance=Tolerance(), rationale="r",
                        derivation=Derivation.STRUCTURAL)
        self.assertFalse(row.conflict)


class ToleranceTests(unittest.TestCase):
    def test_zero_tolerance_requires_exact_match(self) -> None:
        t = Tolerance(under=0, over=0)
        self.assertTrue(t.contains(10, 10))
        self.assertFalse(t.contains(9, 10))
        self.assertFalse(t.contains(11, 10))

    def test_asymmetric_tolerance_is_not_symmetric(self) -> None:
        t = Tolerance(under=0, over=5)
        self.assertFalse(t.contains(9, 10))   # short is never OK here
        self.assertTrue(t.contains(15, 10))    # over is fine


@unittest.skipUnless(LIVE_ITEMS_ROOT.is_dir(), "live item corpus not present in this checkout")
class DeriveAllLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = Corpus.load(LIVE_ITEMS_ROOT)
        cls.adapter = ItemsAdapter()
        cls.rows = derive_all(cls.corpus, cls.adapter)

    def test_unique_row_shows_all_three_conflicting_documentary_counts(self) -> None:
        row = next(r for r in self.rows if r.dimension == "kind:unique")
        values = {p.value for p in row.provenance}
        # 154, not 144: D4.29 (2026-09-06) appended 10 real, ItemSeedValidator-clean anchors to
        # the three ordinal-70 partitions (charnel-bloom-70/gilded-porcelain-70/earthen-bastion-70)
        # -- the live-corpus-scan provenance value tracks the real count, the two doc-stated values
        # (20, 300) are unrelated static claims and unaffected by a content addition.
        self.assertEqual(values, {20, 300, 154})
        self.assertEqual(row.derivation, Derivation.STATED)
        self.assertFalse(row.conflict)  # the corpus source IS marked authoritative

    def test_set_row_is_an_unadjudicated_observation_not_a_generation_target(self) -> None:
        """A total reconstructed from the current corpus cannot be an allocation that tells a
        subsequent generator what to add.  In particular, changing the number of themes changes
        the alleged target without an owner decision."""
        row = next(r for r in self.rows if r.dimension == "kind:set")
        self.assertEqual(row.derivation, Derivation.STRUCTURAL)
        self.assertTrue(row.conflict)
        self.assertFalse(any(p.authoritative for p in row.provenance))

    def test_proportional_base_type_role_targets_sum_exactly_to_the_real_total(self) -> None:
        role_rows = [r for r in self.rows if r.dimension.endswith(":base-type")]
        # The count is a growing content population (derived from the live item corpus), never
        # pinned (population-pin SE3.5, 2026-09-20); the real contract is the sum-to-total check
        # below.
        self.assertTrue(len(role_rows) > 0)
        for row in role_rows:
            self.assertEqual(row.derivation, Derivation.PROPORTIONAL)
            self.assertTrue(row.conflict)
        self.assertEqual(sum(r.target for r in role_rows), len(self.corpus.by_kind("base-type")))


class CellDeviationTests(unittest.TestCase):
    def test_conflicted_row_reports_the_conflict_not_a_deviation(self) -> None:
        row = BudgetRow(dimension="kind:widget", target=999, tolerance=Tolerance(),
                        rationale="r", derivation=Derivation.STATED,
                        provenance=(Provenance(1, "a", "x"), Provenance(2, "b", "y")))
        ctx = Ctx(corpus=_fake_corpus({"widget": 5}), adapter=None, budget=[row])
        registry = MetricRegistry()
        registry.register(CellDeviation())
        findings = run_all(registry, ctx)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].evidence["code"], "BudgetConflict")
        self.assertNotIn("target", findings[0].evidence)

    def test_unbudgeted_cell_with_content_is_a_note_not_a_division_error(self) -> None:
        row = BudgetRow(dimension="kind:widget", target=0, tolerance=Tolerance(),
                        rationale="r", derivation=Derivation.STRUCTURAL,
                        provenance=(Provenance(0, "a", "x", authoritative=True),))
        ctx = Ctx(corpus=_fake_corpus({"widget": 5}), adapter=None, budget=[row])
        registry = MetricRegistry()
        registry.register(CellDeviation())
        findings = run_all(registry, ctx)  # must not raise ZeroDivisionError

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].evidence["code"], "UnbudgetedCell")
        self.assertEqual(findings[0].severity, Severity.NOTE)

    def test_zero_target_and_zero_observed_is_silently_fine(self) -> None:
        row = BudgetRow(dimension="kind:widget", target=0, tolerance=Tolerance(),
                        rationale="r", derivation=Derivation.STRUCTURAL,
                        provenance=(Provenance(0, "a", "x", authoritative=True),))
        ctx = Ctx(corpus=_fake_corpus({"widget": 0}), adapter=None, budget=[row])
        registry = MetricRegistry()
        registry.register(CellDeviation())
        self.assertEqual(run_all(registry, ctx), [])

    def test_within_tolerance_is_not_a_finding(self) -> None:
        row = BudgetRow(dimension="kind:widget", target=10, tolerance=Tolerance(under=2, over=2),
                        rationale="r", derivation=Derivation.STRUCTURAL,
                        provenance=(Provenance(10, "a", "x", authoritative=True),))
        ctx = Ctx(corpus=_fake_corpus({"widget": 9}), adapter=None, budget=[row])
        registry = MetricRegistry()
        registry.register(CellDeviation())
        self.assertEqual(run_all(registry, ctx), [])

    def test_outside_tolerance_is_a_gap(self) -> None:
        row = BudgetRow(dimension="kind:widget", target=10, tolerance=Tolerance(under=1, over=1),
                        rationale="r", derivation=Derivation.STRUCTURAL,
                        provenance=(Provenance(10, "a", "x", authoritative=True),))
        ctx = Ctx(corpus=_fake_corpus({"widget": 5}), adapter=None, budget=[row])
        registry = MetricRegistry()
        registry.register(CellDeviation())
        findings = run_all(registry, ctx)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.GAP)


class DiversityDegenerateCaseTests(unittest.TestCase):
    def test_single_cell_family_is_skipped_not_a_finding(self) -> None:
        row = BudgetRow(dimension="kind:onlyone", target=5, tolerance=Tolerance(), rationale="r",
                        derivation=Derivation.STRUCTURAL,
                        provenance=(Provenance(5, "a", "x", authoritative=True),))
        ctx = Ctx(corpus=_fake_corpus({"onlyone": 5}), adapter=None, budget=[row])
        registry = MetricRegistry()
        registry.register(Evenness())
        registry.register(Inequality())
        self.assertEqual(run_all(registry, ctx), [])

    def test_richness_one_across_multiple_cells_reports_pielou_zero_not_a_crash(self) -> None:
        rows = [
            BudgetRow(dimension="role:a:base-type", target=5, tolerance=Tolerance(),
                     rationale="r", derivation=Derivation.PROPORTIONAL,
                     provenance=(Provenance(5, "x", "y", authoritative=True),)),
            BudgetRow(dimension="role:b:base-type", target=5, tolerance=Tolerance(),
                     rationale="r", derivation=Derivation.PROPORTIONAL,
                     provenance=(Provenance(5, "x", "y", authoritative=True),)),
        ]
        corpus = _fake_corpus_by_role({"a": 10, "b": 0})
        ctx = Ctx(corpus=corpus, adapter=None, budget=rows)
        registry = MetricRegistry()
        registry.register(Evenness())
        findings = run_all(registry, ctx)  # must not raise math domain error / ZeroDivisionError

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].evidence["pielou"], 0.0)
        self.assertEqual(findings[0].evidence["richness"], 1)

    def test_perfectly_even_counts_score_pielou_one_and_gini_zero(self) -> None:
        rows = [
            BudgetRow(dimension="role:a:base-type", target=5, tolerance=Tolerance(),
                     rationale="r", derivation=Derivation.PROPORTIONAL,
                     provenance=(Provenance(5, "x", "y", authoritative=True),)),
            BudgetRow(dimension="role:b:base-type", target=5, tolerance=Tolerance(),
                     rationale="r", derivation=Derivation.PROPORTIONAL,
                     provenance=(Provenance(5, "x", "y", authoritative=True),)),
            BudgetRow(dimension="role:c:base-type", target=5, tolerance=Tolerance(),
                     rationale="r", derivation=Derivation.PROPORTIONAL,
                     provenance=(Provenance(5, "x", "y", authoritative=True),)),
        ]
        corpus = _fake_corpus_by_role({"a": 10, "b": 10, "c": 10})
        ctx = Ctx(corpus=corpus, adapter=None, budget=rows)
        registry = MetricRegistry()
        registry.register(Evenness())
        registry.register(Inequality())
        findings = {f.metric: f for f in run_all(registry, ctx)}

        self.assertAlmostEqual(findings["Distribution/Evenness"].evidence["pielou"], 1.0)
        self.assertAlmostEqual(findings["Distribution/Inequality"].evidence["gini"], 0.0)


class _FakeEntry:
    def __init__(self, kind, role=None):
        self.kind = kind
        self._role = role

    def get(self, key, default=None):
        if key == "role":
            return self._role
        return default


class _FakeCorpus:
    def __init__(self, by_kind_map):
        self._by_kind_map = by_kind_map

    def by_kind(self, kind):
        return self._by_kind_map.get(kind, [])


def _fake_corpus(counts: "dict[str, int]"):
    return _FakeCorpus({kind: [_FakeEntry(kind) for _ in range(n)] for kind, n in counts.items()})


def _fake_corpus_by_role(role_counts: "dict[str, int]"):
    entries = [_FakeEntry("base-type", role=role) for role, n in role_counts.items()
              for _ in range(n)]
    return _FakeCorpus({"base-type": entries})


if __name__ == "__main__":
    unittest.main()
