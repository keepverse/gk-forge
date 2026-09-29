"""Tests for seedsmith.adapters.trees.review.diff (task J4, spec-tree-review.md §8) — the exact
three claims J4's own acceptance bullets name: a magnitude retune produces an empty human review
queue; a renamed node id produces a full tree diff; a changed node is judged inside its tree.
"""
from __future__ import annotations

import unittest

from seedsmith.adapters.trees.review import diff


def _node(node_id: str, *, name: str = "Test Node", flavor: str = "A steady line.",
         affix_ids=("atom.a",)) -> dict:
    return {
        "id": node_id, "branch": "offensive", "tier": 1, "nodeKey": "n0", "nodeClass": "magnitude",
        "name": name, "nameKey": "tree.node.test-node", "flavor": flavor,
        "affixIds": list(affix_ids), "affinity": ["core"] * len(affix_ids),
        "exclusion": {"form": "none", "propertyKeys": []}, "rationale": "",
    }


class MagnitudeRetuneTests(unittest.TestCase):
    """Bullet 1: "A magnitude retune produces an empty human review queue" — this is what makes
    F6's D42 republish cheap."""

    def test_diffing_the_bound_catalog_with_only_kMicro_differing_is_a_magnitude_retune(self) -> None:
        # The language seed carries no kMicro at all (confirmed against a real committed file
        # before writing this module) -- a retune is only detectable by diffing the BOUND catalog,
        # with content_fields=() (nothing there is "content" at all, only coefficients).
        old_bound = {"n0": {"nodeId": "n0", "atoms": [{"kindId": "stat.modify", "kMicro": 608}]}}
        new_bound = {"n0": {"nodeId": "n0", "atoms": [{"kindId": "stat.modify", "kMicro": 700}]}}
        result = diff.diff_tree("t", old_bound, new_bound, content_fields=())
        self.assertEqual("magnitude-retune", result.node_diffs[0].kind)

    def test_language_seed_diffing_alone_can_only_ever_report_unchanged_for_a_retune(self) -> None:
        # A real, documented limit, not a silent gap: the language seed is BYTE-IDENTICAL across a
        # pure tuning retune (it never re-runs), so diffing it alone reports "unchanged" -- true,
        # just not the distinct "this was specifically a retune" claim, which needs the bound
        # catalog (proven by the test above).
        old = {"n0": _node("n0")}
        new = {"n0": _node("n0")}
        result = diff.diff_tree("t", old, new)
        self.assertEqual("unchanged", result.node_diffs[0].kind)

    def test_a_magnitude_retune_across_a_whole_tree_produces_an_EMPTY_human_review_queue(self) -> None:
        # The precise bullet-1 proof: a real retune (bound catalog, every kMicro moved, content_fields
        # empty) over a 40-node tree yields zero entries in the human queue -- the exact claim "this
        # is what makes F6's D42 republish cheap" needs.
        node_count = 40
        old_bound = {f"n{i}": {"nodeId": f"n{i}", "atoms": [{"kindId": "stat.modify", "kMicro": 608}]}
                    for i in range(node_count)}
        new_bound = {f"n{i}": {"nodeId": f"n{i}", "atoms": [{"kindId": "stat.modify", "kMicro": 700}]}
                    for i in range(node_count)}
        result = diff.diff_tree("t", old_bound, new_bound, content_fields=())
        # Self-referential (population-pin SE3.5, 2026-09-20): this test built node_count nodes
        # itself, so it proves none were lost, not a fact about shipped content.
        self.assertEqual(node_count, len(result.node_diffs))
        self.assertTrue(all(d.kind == "magnitude-retune" for d in result.node_diffs))
        self.assertEqual((), result.human_review_queue())

    def test_a_byte_identical_tree_is_unchanged_not_a_retune(self) -> None:
        # "unchanged" and "magnitude-retune" are deliberately distinct kinds -- both are equally
        # absent from the human queue, but conflating them would hide the fact that ANYTHING moved.
        old = {"n0": _node("n0")}
        new = {"n0": _node("n0")}
        self.assertEqual("unchanged", diff.diff_tree("t", old, new).node_diffs[0].kind)


class RenamedNodeIdTests(unittest.TestCase):
    """Bullet 2: "A renamed node id produces a full tree diff — the id-stability dependency
    proven, not assumed.\""""

    def test_an_id_present_in_only_one_snapshot_triggers_full_review_for_the_whole_tree(self) -> None:
        old = {"n0": _node("n0"), "n1": _node("n1")}
        # "n1" renamed to "n2" -- structurally indistinguishable from "n1 removed, n2 added",
        # because ids are the only identity a generated corpus has (D14/§5.2 item 3's own rule,
        # extended here to the review pass).
        new = {"n0": _node("n0"), "n2": _node("n1")}
        result = diff.diff_tree("t", old, new)
        self.assertTrue(result.full_review)

    def test_full_review_puts_every_node_in_the_queue_including_ones_that_did_not_change(self) -> None:
        # Once id churn is detected, per-node "kind" cannot be trusted -- n0's own content is
        # identical old vs new, but it still belongs in the queue because the SAFETY VALVE, not the
        # individual node's own comparison, is what's driving this tree's review scope. "n1" (the
        # OLD id, now absent) is included too -- a full review means the whole tree, old side and
        # new side both, never only the new snapshot's own surviving ids.
        old = {"n0": _node("n0"), "n1": _node("n1")}
        new = {"n0": _node("n0"), "n2": _node("n1")}
        result = diff.diff_tree("t", old, new)
        queued_ids = {d.node_id for d in result.human_review_queue()}
        self.assertEqual({"n0", "n1", "n2"}, queued_ids)

    def test_identical_id_sets_never_trigger_full_review(self) -> None:
        old = {"n0": _node("n0"), "n1": _node("n1", name="Old Name")}
        new = {"n0": _node("n0"), "n1": _node("n1", name="New Name")}
        result = diff.diff_tree("t", old, new)
        self.assertFalse(result.full_review)

    def test_a_brand_new_tree_with_no_prior_snapshot_is_a_full_review_over_the_new_lot_only(self) -> None:
        # §8's own table: "New trees... Full protocol over the new lot only." An empty `old_nodes`
        # is the natural representation of "this tree did not exist in the from-revision."
        new = {f"n{i}": _node(f"n{i}") for i in range(5)}
        result = diff.diff_tree("t", {}, new)
        self.assertTrue(result.full_review)
        self.assertEqual(5, len(result.human_review_queue()))


class ChangedNodeJudgedInsideItsTreeTests(unittest.TestCase):
    """Bullet 3: "A changed node is judged inside its tree, never as an isolated line.\""""

    def test_a_content_changed_node_carries_both_its_old_and_new_full_record(self) -> None:
        # "Inside its tree" means the reviewer sees the WHOLE node (every field), not a bare
        # single-line diff of just the one field that happened to change -- both old and new are
        # the complete record, so a renderer can show the full card with the change highlighted.
        old = {"n0": _node("n0", flavor="Old flavor.")}
        new = {"n0": _node("n0", flavor="New flavor.")}
        result = diff.diff_tree("t", old, new)
        changed = result.node_diffs[0]
        self.assertEqual("content-changed", changed.kind)
        self.assertEqual("Old flavor.", changed.old["flavor"])
        self.assertEqual("New flavor.", changed.new["flavor"])
        # The REST of the record travels with it too -- not just the one changed field.
        self.assertEqual("n0", changed.old["id"])
        self.assertEqual("n0", changed.new["id"])

    def test_the_tree_id_is_carried_on_the_diff_result_itself_never_dropped(self) -> None:
        result = diff.diff_tree("fortitude", {"n0": _node("n0")}, {"n0": _node("n0", flavor="New.")})
        self.assertEqual("fortitude", result.tree_id)

    def test_a_multi_node_tree_reports_every_node_never_only_the_changed_one(self) -> None:
        # A reviewer judging "inside the tree" needs the OTHER nodes too, for context -- diff_tree
        # never narrows its own output to only the changed subset (human_review_queue is the
        # narrowing step, kept separate).
        old = {f"n{i}": _node(f"n{i}") for i in range(5)}
        new = dict(old)
        new["n2"] = _node("n2", flavor="Changed.")
        result = diff.diff_tree("t", old, new)
        self.assertEqual(5, len(result.node_diffs))
        kinds = {d.node_id: d.kind for d in result.node_diffs}
        self.assertEqual("content-changed", kinds["n2"])
        for other in ("n0", "n1", "n3", "n4"):
            self.assertEqual("unchanged", kinds[other])


class RemovedNodeTests(unittest.TestCase):
    def test_a_node_retired_from_the_new_snapshot_is_removed_and_queued(self) -> None:
        old = {"n0": _node("n0"), "n1": _node("n1")}
        new = {"n0": _node("n0")}
        result = diff.diff_tree("t", old, new)
        removed = [d for d in result.node_diffs if d.kind == "removed"]
        self.assertEqual(1, len(removed))
        self.assertEqual("n1", removed[0].node_id)
        self.assertIn(removed[0], result.human_review_queue())
