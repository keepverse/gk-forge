"""Tests for seedsmith.sampling and seedsmith.metrics.quality (tasks/seedsmith-todo.md, S8).

    python -m pytest gk-forge/tools/seedsmith/tests/test_sampling_quality.py -v
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items import ItemsAdapter  # noqa: E402
from seedsmith.corpus import Corpus  # noqa: E402
from seedsmith.metrics import Ctx, Loop, MetricRegistry, Severity, run_all  # noqa: E402
from seedsmith.metrics.quality import FlavourGeneric, FlavourMissing  # noqa: E402
from seedsmith.sampling import corpus_revision, stratified_sample  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
LIVE_ITEMS_ROOT = REPO_ROOT / "data" / "seed" / "items"
SEEDSMITH_DIR = Path(__file__).resolve().parent.parent


class StratifiedSampleTests(unittest.TestCase):
    def test_same_seed_produces_the_same_sample_across_calls(self) -> None:
        strata = {"a": list(range(20)), "b": list(range(5)), "c": list(range(100))}
        s1 = stratified_sample(strata, 10, metric_id="Test/X", revision="rev1")
        s2 = stratified_sample(strata, 10, metric_id="Test/X", revision="rev1")
        self.assertEqual(s1, s2)

    def test_different_revision_can_change_the_sample(self) -> None:
        strata = {"a": list(range(50))}
        s1 = stratified_sample(strata, 5, metric_id="Test/X", revision="rev1")
        s2 = stratified_sample(strata, 5, metric_id="Test/X", revision="rev2")
        # Not asserting they MUST differ (a 5-in-50 draw could coincide), only that revision is
        # actually part of the seed key rather than ignored — checked via the seed key itself.
        from seedsmith.sampling import _seeded_shuffle_order
        self.assertNotEqual(
            _seeded_shuffle_order([str(i) for i in range(50)], "Test/X:rev1"),
            _seeded_shuffle_order([str(i) for i in range(50)], "Test/X:rev2"))

    def test_every_non_empty_stratum_gets_at_least_one_sample(self) -> None:
        # A tiny stratum next to a huge one — naive proportional allocation would round the
        # small one to zero and never look at it.
        strata = {"tiny": [1], "huge": list(range(1000))}
        result = stratified_sample(strata, 5, metric_id="Test/X", revision="rev1")
        self.assertIn("tiny", result)
        self.assertGreaterEqual(len(result["tiny"]), 1)
        self.assertIn("huge", result)

    def test_sample_size_never_exceeds_n(self) -> None:
        strata = {"a": list(range(10)), "b": list(range(10)), "c": list(range(10))}
        result = stratified_sample(strata, 7, metric_id="Test/X", revision="rev1")
        self.assertLessEqual(sum(len(v) for v in result.values()), 7)

    def test_empty_strata_dict_returns_empty(self) -> None:
        self.assertEqual(stratified_sample({}, 10, metric_id="Test/X", revision="rev1"), {})

    def test_zero_n_returns_empty(self) -> None:
        self.assertEqual(
            stratified_sample({"a": [1, 2, 3]}, 0, metric_id="Test/X", revision="rev1"), {})


class FlavourMissingTests(unittest.TestCase):
    def test_open_loop_flag_is_correct(self) -> None:
        self.assertEqual(FlavourMissing.loop, Loop.CLOSED)
        self.assertEqual(FlavourGeneric.loop, Loop.OPEN)

    def test_flavour_generic_never_emits_gap_severity(self) -> None:
        # The structural guarantee: an OPEN-loop metric may never report pass/fail, only a
        # review queue — checked here at the finding-severity level, not just the class flag.
        if not LIVE_ITEMS_ROOT.is_dir():
            self.skipTest("live item corpus not present in this checkout")
        corpus = Corpus.load(LIVE_ITEMS_ROOT)
        registry = MetricRegistry()
        registry.register(FlavourGeneric())
        findings = run_all(registry, Ctx(corpus=corpus, adapter=ItemsAdapter()))
        self.assertTrue(findings)  # the corpus does have flavour text to sample
        self.assertTrue(all(f.severity == Severity.NOTE for f in findings))


@unittest.skipUnless(LIVE_ITEMS_ROOT.is_dir(), "live item corpus not present in this checkout")
class LiveFlavourMissingTests(unittest.TestCase):
    def test_reports_a_total_missing_rate_per_kind(self) -> None:
        corpus = Corpus.load(LIVE_ITEMS_ROOT)
        registry = MetricRegistry()
        registry.register(FlavourMissing())
        findings = {f.subject: f for f in run_all(registry, Ctx(corpus=corpus,
                                                                adapter=ItemsAdapter()))}

        # The item corpus is a POPULATION (the owner's setgen/gem/recipe batches grow it), so the
        # row totals are readings, never literals. The invariants that matter are the metric's own
        # contract: every kind reports a non-negative count reconciles to a non-negative total, and
        # `consumable` — which authors no `flavor` field at all — stays at a 100% missing rate.
        for subject in ("consumable", "charm"):
            finding = findings[subject]
            evidence = finding.evidence
            self.assertGreater(evidence["totalCount"], 0, f"{subject} was sampled")
            self.assertGreaterEqual(evidence["missingCount"], 0)
            self.assertLessEqual(evidence["missingCount"], evidence["totalCount"],
                                 f"{subject}: missing cannot exceed total")
        self.assertEqual(findings["consumable"].evidence["missingCount"],
                         findings["consumable"].evidence["totalCount"],
                         "consumable authors no `flavor`, so its missing rate stays 100%")
        print("flavour-missing: "
              + ", ".join(f"{s}={findings[s].evidence['missingCount']}/"
                          f"{findings[s].evidence['totalCount']}"
                          for s in ("consumable", "charm")))


@unittest.skipUnless(LIVE_ITEMS_ROOT.is_dir(), "live item corpus not present in this checkout")
class DeterminismAcrossProcessesTests(unittest.TestCase):
    """The acceptance criterion literally means ACROSS RUNS, i.e. separate processes — a
    same-process test would miss the exact bug this task found and fixed (PYTHONHASHSEED
    randomizing frozenset iteration order between processes, verified live before this test
    existed: two real CLI invocations produced set-equal but list-unequal JSON)."""

    def test_two_separate_processes_produce_byte_identical_json(self) -> None:
        import tempfile
        out_dir = Path(tempfile.mkdtemp())
        cmd_template = [sys.executable, "-m", "seedsmith", "check", "--adapter", "items",
                        "--metric", "Quality/FlavourGeneric", str(LIVE_ITEMS_ROOT)]

        for i in (1, 2):
            out_path = out_dir / f"run{i}.json"
            subprocess.run(cmd_template + ["--json", str(out_path)], cwd=SEEDSMITH_DIR,
                          capture_output=True, check=False)

        import json
        run1 = json.loads((out_dir / "run1.json").read_text(encoding="utf-8"))
        run2 = json.loads((out_dir / "run2.json").read_text(encoding="utf-8"))
        self.assertEqual(run1, run2)
        self.assertTrue(run1)  # not vacuously true on an empty sample


if __name__ == "__main__":
    unittest.main()
