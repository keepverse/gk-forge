"""Task 4 (seedsmith-content-standard) — the generalized backfill loop, proven against a REAL
passive-tree ledger fixture (plan's own Checkpoint 0 requirement): missing-only automatic
regeneration, staleness reported but never auto-acted on, and a manual `--force` escape hatch.

    python -m pytest gk-forge/tools/seedsmith/tests/pipeline/test_backfill_loop.py -q
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from seedsmith.adapters.trees.nodegen.brief import PROMPT_VERSION
from seedsmith.corpus import Corpus, Entry
from seedsmith.metrics import Ctx, MetricRegistry, run_all
from seedsmith.metrics.content_completeness import (
    CompletenessSpec, ContentFieldStale, clear_registry, register_completeness,
)
from seedsmith.pipeline.backfill import force_regenerate, plan_missing
from seedsmith.pipeline.run_ledger import RunLedger
from seedsmith.pipeline.staleness import staleness_key

REPO_ROOT = Path(__file__).resolve().parents[4]
FEROCITY_SEED = REPO_ROOT / "data/seed/passive-tree/nodes/ferocity.json"


def _real_ferocity_node_ids() -> "list[str]":
    doc = json.loads(FEROCITY_SEED.read_text(encoding="utf-8"))
    return [n["id"] for n in doc["nodes"]]


class MissingOnlyAutomaticTests(unittest.TestCase):
    """A real, mostly-complete ledger: every real ferocity node id marked done except one, which
    stands in for "never generated" — the only thing an automatic resumed run may touch."""

    def setUp(self) -> None:
        self.node_ids = _real_ferocity_node_ids()
        self.assertGreater(len(self.node_ids), 5, "sanity: the real fixture has real nodes")
        self.missing_id = self.node_ids[0]
        self.tmp_dir = tempfile.mkdtemp()
        self.ledger = RunLedger(Path(self.tmp_dir) / "backfill-test.ledger.json")

        # Mark every node EXCEPT the first as done, one of them deliberately STALE (an old
        # promptVersion) to prove staleness alone never triggers automatic regeneration.
        for i, node_id in enumerate(self.node_ids[1:], start=1):
            prompt_version = "tree-language/1" if i == 1 else PROMPT_VERSION
            self.ledger.mark_done(node_id, {"promptVersion": prompt_version})

    def test_plan_missing_returns_exactly_the_one_never_generated_node(self) -> None:
        plan = plan_missing(self.ledger, self.node_ids)
        self.assertEqual(plan, [self.missing_id])

    def test_a_stale_but_existing_node_is_not_in_the_automatic_plan(self) -> None:
        stale_id = self.node_ids[1]  # marked done above with the OLD prompt version
        plan = plan_missing(self.ledger, self.node_ids)
        self.assertNotIn(stale_id, plan, "an existing entry must be a no-op even when stale")

    def test_running_plan_missing_makes_zero_model_calls_worth_of_work_for_existing_entries(self) -> None:
        # No model is called in this test (that's the whole point — proving the PLAN is right is
        # cheaper and sufficient); the plan itself must be small: 1 of N, not N.
        plan = plan_missing(self.ledger, self.node_ids)
        self.assertEqual(len(plan), 1)
        self.assertEqual(len(self.node_ids) - len(plan), len(self.node_ids) - 1)


class ManualForceEscapeHatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.node_ids = _real_ferocity_node_ids()
        self.tmp_dir = tempfile.mkdtemp()
        self.ledger = RunLedger(Path(self.tmp_dir) / "backfill-test.ledger.json")
        for node_id in self.node_ids:
            self.ledger.mark_done(node_id, {"promptVersion": PROMPT_VERSION})

    def test_force_all_regenerates_every_targeted_record_even_though_none_are_missing(self) -> None:
        # Every subject already has a ledger entry — plan_missing would return nothing.
        self.assertEqual(plan_missing(self.ledger, self.node_ids), [])

        forced = force_regenerate(self.ledger, self.node_ids, scope="all")
        self.assertEqual(sorted(forced), sorted(self.node_ids))

    def test_force_rejects_an_unscoped_call_rather_than_silently_defaulting(self) -> None:
        with self.assertRaises(ValueError):
            force_regenerate(self.ledger, self.node_ids, scope="everything")


class StalenessIsReportedNeverAutoTriggeredTests(unittest.TestCase):
    """Connects Task 2 (staleness_key) + Task 3 (Content/FieldStale) + Task 4 (backfill loop) on
    the same real data, proving the resolved contract end to end: the real, already-stale
    ferocity.json record is reported stale by the metric, while the backfill loop's own automatic
    plan never mentions it (it already exists)."""

    def setUp(self) -> None:
        clear_registry()

    def tearDown(self) -> None:
        clear_registry()

    def test_a_real_stale_node_is_reported_by_the_metric_but_never_auto_planned(self) -> None:
        doc = json.loads(FEROCITY_SEED.read_text(encoding="utf-8"))
        prov = doc["_provenance"]
        recorded_prompt_version = prov["promptVersion"]

        # ⛔ CORRECTED 2026-09-11: `build_seed_document` now derives the document stamp from the
        # records and emits `"mixed"` (with a per-node `promptVersionByNode` split) when a tree holds
        # more than one vintage. The test's real claim is that the committed record is NOT current;
        # it no longer has to be a specific older literal.
        if recorded_prompt_version == "mixed":
            self.assertTrue(any(v != PROMPT_VERSION
                                for v in prov.get("promptVersionByNode", {}).values()))
        else:
            self.assertNotEqual(recorded_prompt_version, PROMPT_VERSION)

        current_key = staleness_key(brief_hash="x", prompt_version=PROMPT_VERSION,
                                    schema_version="1", model_id=prov["model"])
        recorded_key = staleness_key(brief_hash="x", prompt_version=recorded_prompt_version,
                                     schema_version="1", model_id=prov["model"])

        corpus = Corpus()
        corpus.add(Entry(id="ferocity", kind="tree", partition="passive-tree",
                         path="nodes/ferocity.json",
                         data={"flavor": "already has content",
                              "_provenance": {"stalenessKey": recorded_key},
                              "_stalenessCurrentKey": current_key}))
        register_completeness(CompletenessSpec(domain="passive-tree", kinds=frozenset({"tree"}),
                                               field="flavor"))
        registry = MetricRegistry()
        registry.register(ContentFieldStale())
        findings = run_all(registry, Ctx(corpus=corpus, adapter=None))

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].evidence["staleCount"], 1)

        # The automatic path never sees this at all — it operates on a RunLedger's done-map, not
        # on the staleness metric, and "ferocity" already has an entry either way.
        tmp_dir = tempfile.mkdtemp()
        ledger = RunLedger(Path(tmp_dir) / "x.ledger.json")
        ledger.mark_done("ferocity", {"promptVersion": recorded_prompt_version})
        self.assertEqual(plan_missing(ledger, ["ferocity"]), [])


if __name__ == "__main__":
    unittest.main()
