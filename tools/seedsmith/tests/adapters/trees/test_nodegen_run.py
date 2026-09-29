"""Tests for seedsmith.adapters.trees.nodegen.run (task H1) — `plan_run` over one tree's committed
plan -> `RunPlan{subjects, held, already_done}`.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _nodegen_fixtures import write_plan  # noqa: E402

from seedsmith.adapters.trees.nodegen import plan_read, run
from seedsmith.adapters.trees.nodegen.emit import NodeSeedRecord


class PlanRunTests(unittest.TestCase):
    def test_one_subject_per_node(self) -> None:
        seed_root = Path(tempfile.mkdtemp())
        write_plan(seed_root, "t1", node_count=4)
        plan = plan_read.load("t1", seed_root)
        result = run.plan_run(plan, ledger={})
        self.assertEqual(len(result.subjects), 4)
        self.assertEqual(result.held, [])
        self.assertEqual(result.already_done, [])
        self.assertTrue(result.complete)

    def test_a_subject_already_in_the_ledger_is_skipped(self) -> None:
        seed_root = Path(tempfile.mkdtemp())
        write_plan(seed_root, "t1", node_count=4)
        plan = plan_read.load("t1", seed_root)
        first_node = plan.nodes[0]
        # A real accepted row: a `record` is what marks a subject done (2026-09-11). A row without
        # one is a prior FAILED attempt, which stays scheduled — see the next test.
        ledger = {f"t1:{first_node.node_id}": {"record": {"id": first_node.node_id}}}
        result = run.plan_run(plan, ledger=ledger)
        self.assertEqual(len(result.subjects), 3)
        self.assertEqual(result.already_done, [f"t1:{first_node.node_id}"])

    def test_a_prior_failed_attempt_is_still_scheduled(self) -> None:
        """An attempt row (`record: null`, written by `record_attempt`) is bookkeeping, never
        "done": the node is still owed a generation, so `plan_run` schedules it again."""
        seed_root = Path(tempfile.mkdtemp())
        write_plan(seed_root, "t1", node_count=4)
        plan = plan_read.load("t1", seed_root)
        first_node = plan.nodes[0]
        ledger = {f"t1:{first_node.node_id}": {
            "record": None, "outcome": "unresolved", "detail": "1-1-1 vote", "attempts": 2}}
        result = run.plan_run(plan, ledger=ledger)
        self.assertEqual(len(result.subjects), 4)
        self.assertEqual(result.already_done, [])
        self.assertIn(f"t1:{first_node.node_id}", [s.subject_id for s in result.subjects])

    def test_subject_carries_no_brief_or_schema_yet(self) -> None:
        """H1's own honest gap: resolving a brief/schema needs a quota cell, which is H3's."""
        seed_root = Path(tempfile.mkdtemp())
        write_plan(seed_root, "t1", node_count=1)
        plan = plan_read.load("t1", seed_root)
        result = run.plan_run(plan, ledger={})
        self.assertIsNone(result.subjects[0].brief)
        self.assertIsNone(result.subjects[0].schema)


class OnlyNodeSelectorTests(unittest.TestCase):
    """ip-censor T16/IC-4.1: `plan_run(only_node_id=...)` restricts the whole run to one node, so a
    CLI `--write --supersede --node <id>` re-rolls exactly that subject and nothing else."""

    def test_only_node_restricts_a_fresh_run_to_that_one_subject(self) -> None:
        seed_root = Path(tempfile.mkdtemp())
        write_plan(seed_root, "t1", node_count=4)
        plan = plan_read.load("t1", seed_root)
        target = plan.nodes[2].node_id
        result = run.plan_run(plan, ledger={}, only_node_id=target)
        self.assertEqual(1, len(result.subjects))
        self.assertEqual(target, result.subjects[0].node_id)

    def test_only_node_restricts_a_supersede_run_to_that_one_stale_row(self) -> None:
        seed_root = Path(tempfile.mkdtemp())
        write_plan(seed_root, "t1", node_count=4)
        plan = plan_read.load("t1", seed_root)
        target = plan.nodes[2].node_id
        # Every row is stale (no promptVersion), so without the selector all four would be re-rolled.
        ledger = {f"t1:{n.node_id}": {"record": {"id": n.node_id}} for n in plan.nodes}
        result = run.plan_run(plan, ledger=ledger, supersede_stale=True,
                              prompt_version="tree-language/4", only_node_id=target)
        self.assertEqual(1, len(result.superseded))
        self.assertEqual(target, result.superseded[0].node_id)
        self.assertEqual([target], [s.node_id for s in result.subjects])
        # ⚠ The OTHER three stay in `already_done`: they are replayed into the emitted document, so
        # trimming them here is what dropped 39 of `command`'s 40 nodes on the first real T16 run.
        self.assertEqual(3, len(result.already_done))
        self.assertNotIn(target, result.already_done)

    def test_only_node_leaves_the_other_rows_replayable_not_generated(self) -> None:
        """The defect the first real T16 run exposed: `--node` must narrow GENERATION, never the set
        of committed rows replayed into the seed document. Each other node stays in `already_done`
        (untouched), so `command.json` is rebuilt complete with only the target re-rolled."""
        seed_root = Path(tempfile.mkdtemp())
        write_plan(seed_root, "t1", node_count=5)
        plan = plan_read.load("t1", seed_root)
        target = plan.nodes[1].node_id
        ledger = {f"t1:{n.node_id}": {"record": {"id": n.node_id}} for n in plan.nodes}
        result = run.plan_run(plan, ledger=ledger, supersede_stale=True,
                              prompt_version="tree-language/4", only_node_id=target)
        # Every non-target node is still an already-done replay; generation is exactly the target.
        self.assertEqual(5, len(result.already_done) + len(result.subjects))
        self.assertEqual([target], [s.node_id for s in result.subjects])
        self.assertEqual(
            {f"t1:{n.node_id}" for n in plan.nodes if n.node_id != target},
            set(result.already_done))

    def test_without_only_node_the_old_behaviour_holds(self) -> None:
        seed_root = Path(tempfile.mkdtemp())
        write_plan(seed_root, "t1", node_count=4)
        plan = plan_read.load("t1", seed_root)
        ledger = {f"t1:{n.node_id}": {"record": {"id": n.node_id}} for n in plan.nodes}
        result = run.plan_run(plan, ledger=ledger, supersede_stale=True,
                              prompt_version="tree-language/4")
        self.assertEqual(4, len(result.superseded))

    def test_an_unknown_node_id_is_refused_by_name(self) -> None:
        seed_root = Path(tempfile.mkdtemp())
        write_plan(seed_root, "t1", node_count=2)
        plan = plan_read.load("t1", seed_root)
        with self.assertRaisesRegex(ValueError, "not a node of tree"):
            run.plan_run(plan, ledger={}, only_node_id="skill.t1-off-t9-n0")


class LedgerRoundTripTests(unittest.TestCase):
    def test_write_then_read_round_trips(self) -> None:
        ledger_path = Path(tempfile.mkdtemp()) / "ledger.json"
        done = {"t1:skill.t1-off-t1-n0": {"acceptedUtc": "2026-09-06T00:00:00Z"}}
        run.write_ledger(done, ledger_path)
        self.assertEqual(run.read_ledger(ledger_path), done)

    def test_reading_a_missing_ledger_returns_empty(self) -> None:
        missing = Path(tempfile.mkdtemp()) / "does-not-exist.json"
        self.assertEqual(run.read_ledger(missing), {})


class AttemptLedgerTests(unittest.TestCase):
    """`record_attempt` (owner request, 2026-09-11): a non-accepted outcome leaves a real ledger row
    so the corpus can name which nodes are still owed and how often each has failed."""

    def test_an_attempt_row_has_no_record_and_counts_attempts(self) -> None:
        done = run.record_attempt({}, "t1:n0", "unresolved", "1-1-1 vote")
        self.assertIsNone(done["t1:n0"]["record"])
        self.assertEqual(done["t1:n0"]["outcome"], "unresolved")
        self.assertEqual(done["t1:n0"]["detail"], "1-1-1 vote")
        self.assertEqual(done["t1:n0"]["attempts"], 1)
        again = run.record_attempt(done, "t1:n0", "unresolved", "still 1-1-1")
        self.assertEqual(again["t1:n0"]["attempts"], 2)

    def test_an_attempt_never_clobbers_an_accepted_record(self) -> None:
        accepted = {"t1:n0": {"record": {"id": "skill.t1-off-t1-n0", "name": "Kept"}}}
        after = run.record_attempt(accepted, "t1:n0", "unresolved", "re-roll failed")
        self.assertEqual(after["t1:n0"], accepted["t1:n0"])

    def test_accepting_over_a_prior_attempt_is_not_a_duplicate(self) -> None:
        attempted = run.record_attempt({}, "t1:n0", "unresolved", "1-1-1 vote")
        record = NodeSeedRecord(
            node_id="skill.t1-off-t1-n0", node_key="n0", branch="offensive", tier=1,
            node_class="mechanism", affix_ids=("atom.a",), affinity=("core",),
            exclusion_form="none", exclusion_property_keys=(), name="Resolved",
            name_key="tree.node.resolved", flavor="line", rationale="")
        done = run.record_accepted(attempted, "t1:n0", record)
        self.assertIsNotNone(done["t1:n0"]["record"])
        self.assertNotIn("outcome", done["t1:n0"])

    def test_accepting_over_an_accepted_record_still_raises(self) -> None:
        accepted = {"t1:n0": {"record": {"id": "x"}}}
        record = NodeSeedRecord(
            node_id="skill.t1-off-t1-n0", node_key="n0", branch="offensive", tier=1,
            node_class="mechanism", affix_ids=("atom.a",), affinity=("core",),
            exclusion_form="none", exclusion_property_keys=(), name="Second",
            name_key="tree.node.second", flavor="line", rationale="")
        with self.assertRaises(ValueError):
            run.record_accepted(accepted, "t1:n0", record)


class RunPlanSummaryTests(unittest.TestCase):
    def test_summary_reports_held_reasons(self) -> None:
        plan = run.RunPlan(subjects=[], held=[("t1:n0", "UnsatisfiableCell"),
                                              ("t1:n1", "UnsatisfiableCell")], already_done=[])
        summary = plan.summary()
        self.assertEqual(summary["held"], 2)
        self.assertEqual(summary["heldByReason"]["UnsatisfiableCell"], 2)
        self.assertFalse(plan.complete)


if __name__ == "__main__":
    unittest.main()
