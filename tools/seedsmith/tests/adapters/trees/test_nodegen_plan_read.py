"""Tests for seedsmith.adapters.trees.nodegen.plan_read (task H1) — reads tree-plan's committed
plan; refuses an unfilled hole rather than defaulting (spec-tree-language.md §2, §7 gate 3).
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _nodegen_fixtures import minimal_plan, write_plan  # noqa: E402

from seedsmith.adapters.trees.nodegen import plan_read


class LoadTests(unittest.TestCase):
    def test_loads_a_well_formed_fixture_plan(self) -> None:
        seed_root = Path(tempfile.mkdtemp())
        write_plan(seed_root, "t1", node_count=4)
        plan = plan_read.load("t1", seed_root)
        self.assertEqual(plan.tree_id, "t1")
        self.assertEqual(len(plan.nodes), 4)
        self.assertIn("posture", plan.property_vocabulary)

    def test_nodes_for_filters_by_branch_and_tier(self) -> None:
        seed_root = Path(tempfile.mkdtemp())
        write_plan(seed_root, "t1", node_count=4)
        plan = plan_read.load("t1", seed_root)
        offensive = plan.nodes_for("offensive")
        self.assertTrue(all(n.branch == "offensive" for n in offensive))
        tier_1 = plan.nodes_for("offensive", tier=1)
        self.assertTrue(all(n.tier == 1 for n in tier_1))

    def test_quota_cell_and_permitted_ids_are_none_on_a_b1_shaped_plan(self) -> None:
        """H3's own not-yet-wired fields: a plan B1 actually emits today carries neither
        `quotaCell` nor `permittedIds` on its nodes."""
        seed_root = Path(tempfile.mkdtemp())
        write_plan(seed_root, "t1", node_count=2)
        plan = plan_read.load("t1", seed_root)
        for node in plan.nodes:
            self.assertIsNone(node.quota_cell)
            self.assertIsNone(node.permitted_ids)


class LoadFromDictTests(unittest.TestCase):
    """Task J8: the identical parse `load()` performs, for a caller (species-tree orchestration)
    that already has the plan document in memory rather than a committed file at the generic
    `plan/<treeId>.v1.json` path -- proves the two entrypoints share one parser, not two."""

    def test_loads_an_in_memory_plan_with_no_file_at_all(self) -> None:
        plan_doc = minimal_plan("SomeSpecies", node_count=4)
        plan = plan_read.load_from_dict(plan_doc)
        self.assertEqual(plan.tree_id, "SomeSpecies")
        self.assertEqual(4, len(plan.nodes))

    def test_refuses_an_empty_nodes_array_the_same_as_load_does(self) -> None:
        plan_doc = minimal_plan("empty-species", node_count=0)
        with self.assertRaises(plan_read.TreePlanReadError):
            plan_read.load_from_dict(plan_doc)

    def test_refuses_a_missing_property_vocabulary_the_same_as_load_does(self) -> None:
        plan_doc = minimal_plan("no-vocab-species", node_count=2)
        del plan_doc["propertyVocabulary"]
        with self.assertRaises(plan_read.TreePlanReadError):
            plan_read.load_from_dict(plan_doc)

    def test_raw_round_trips_the_real_document(self) -> None:
        plan_doc = minimal_plan("SomeSpecies", node_count=2)
        plan_doc["favouredAptitude"] = "Might"
        plan = plan_read.load_from_dict(plan_doc)
        self.assertEqual("Might", plan.raw["favouredAptitude"])


class RefusalTests(unittest.TestCase):
    def test_refuses_a_missing_plan_file(self) -> None:
        seed_root = Path(tempfile.mkdtemp())
        with self.assertRaises(plan_read.TreePlanReadError):
            plan_read.load("does-not-exist", seed_root)

    def test_refuses_an_empty_nodes_array(self) -> None:
        seed_root = Path(tempfile.mkdtemp())
        plan = minimal_plan("empty-tree", node_count=0)
        path = seed_root / "passive-tree" / "plan" / "empty-tree.v1.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaises(plan_read.TreePlanReadError):
            plan_read.load("empty-tree", seed_root)

    def test_refuses_a_plan_with_no_property_vocabulary(self) -> None:
        """§5.1/R8: "the stage refuses to run against a plan carrying no propertyVocabulary — it
        never synthesises one"."""
        seed_root = Path(tempfile.mkdtemp())
        plan = minimal_plan("no-vocab-tree", node_count=2)
        del plan["propertyVocabulary"]
        path = seed_root / "passive-tree" / "plan" / "no-vocab-tree.v1.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaises(plan_read.TreePlanReadError):
            plan_read.load("no-vocab-tree", seed_root)

    def test_refuses_a_plan_missing_a_required_top_level_key(self) -> None:
        seed_root = Path(tempfile.mkdtemp())
        plan = minimal_plan("no-archetype-tree", node_count=2)
        del plan["archetype"]
        path = seed_root / "passive-tree" / "plan" / "no-archetype-tree.v1.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaises(plan_read.TreePlanReadError):
            plan_read.load("no-archetype-tree", seed_root)


if __name__ == "__main__":
    unittest.main()
