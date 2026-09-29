"""Tests for seedsmith.adapters.trees.review.verdict_queue (task J3, spec-tree-review.md §6.1,
§6.2) — "a review producing no artifact did not happen," and reject reasons becoming the next run's
anti-motifs (§6.2 rung 1).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from seedsmith.adapters.trees.review import sample, verdict_queue
from seedsmith.adapters.trees.review.verdict_queue import VerdictQueueEntry


class VerdictQueueEntryTests(unittest.TestCase):
    def test_a_real_entry_constructs_cleanly(self) -> None:
        e = VerdictQueueEntry(subject_id="skill.might-off-t1-n0", rung=1, reason="generic flavor text")
        self.assertEqual(1, e.rung)

    def test_an_out_of_range_rung_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            VerdictQueueEntry(subject_id="n0", rung=6, reason="a reason")

    def test_an_empty_reason_is_refused(self) -> None:
        with self.assertRaises(ValueError) as ex:
            VerdictQueueEntry(subject_id="n0", rung=1, reason="")
        self.assertIn("empty reason", str(ex.exception))

    def test_round_trips_through_to_dict_from_dict(self) -> None:
        e = VerdictQueueEntry(subject_id="n0", rung=2, reason="brief-level defect")
        self.assertEqual(e, VerdictQueueEntry.from_dict(e.to_dict()))


class WriteAndReadVerdictQueueTests(unittest.TestCase):
    def test_writing_an_empty_lot_still_produces_a_real_committed_artifact(self) -> None:
        # "A review producing no artifact did not happen" -- an empty entries list is still a
        # WRITTEN file, distinct from no file at all (census_review_queue's own "not reviewed yet").
        with tempfile.TemporaryDirectory() as d:
            path = verdict_queue.write_verdict_queue(d, "lot-1", ())
            self.assertTrue(path.exists())
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("lot-1", doc["lot"])
            self.assertEqual([], doc["entries"])

    def test_a_written_queue_reads_back_identically(self) -> None:
        entries = (
            VerdictQueueEntry(subject_id="n0", rung=1, reason="generic flavor text"),
            VerdictQueueEntry(subject_id="t1", rung=2, reason="brief-level defect"),
        )
        with tempfile.TemporaryDirectory() as d:
            verdict_queue.write_verdict_queue(d, "lot-1", entries)
            read_back = verdict_queue.read_verdict_queue(d, "lot-1")
            self.assertEqual(entries, read_back)

    def test_a_lot_that_was_never_written_reads_as_an_honest_empty_tuple(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual((), verdict_queue.read_verdict_queue(d, "never-reviewed"))

    def test_census_review_queue_delegates_to_the_same_reader_not_a_second_one(self) -> None:
        entries = (VerdictQueueEntry(subject_id="n0", rung=1, reason="a reason"),)
        with tempfile.TemporaryDirectory() as d:
            verdict_queue.write_verdict_queue(d, "lot-1", entries)
            via_sample = sample.census_review_queue(Path(d), "lot-1")
            via_verdict_queue = verdict_queue.read_verdict_queue(d, "lot-1")
            self.assertEqual(via_verdict_queue, via_sample)


class AntiMotifsForNodeTests(unittest.TestCase):
    def test_a_rung_1_entry_naming_this_exact_node_becomes_an_anti_motif(self) -> None:
        entries = (VerdictQueueEntry(subject_id="skill.t-off-t1-n0", rung=1,
                                     reason="generic flavor text, too vague"),)
        motifs = verdict_queue.anti_motifs_for_node(entries, "skill.t-off-t1-n0")
        self.assertEqual(("generic flavor text, too vague",), motifs)

    def test_an_entry_naming_a_different_node_is_not_included(self) -> None:
        entries = (VerdictQueueEntry(subject_id="skill.t-off-t1-n1", rung=1, reason="unrelated"),)
        self.assertEqual((), verdict_queue.anti_motifs_for_node(entries, "skill.t-off-t1-n0"))

    def test_a_rung_2_tree_reject_applies_to_every_node_in_that_tree(self) -> None:
        # §6.2 rung 2: "Regenerate the whole tree" -- the tree-level reason must reach EVERY one of
        # its nodes' next briefs, not just a single named node.
        entries = (VerdictQueueEntry(subject_id="t", rung=2, reason="brief-level defect, tree-wide"),)
        self.assertEqual(("brief-level defect, tree-wide",),
                         verdict_queue.anti_motifs_for_node(entries, "skill.t-off-t3-n1", tree_id="t"))

    def test_a_rung_2_entry_for_a_different_tree_does_not_leak_into_this_one(self) -> None:
        entries = (VerdictQueueEntry(subject_id="other-tree", rung=2, reason="unrelated tree"),)
        self.assertEqual((), verdict_queue.anti_motifs_for_node(entries, "skill.t-off-t1-n0", tree_id="t"))

    def test_rung_3_4_5_entries_are_never_folded_into_a_per_node_anti_motif(self) -> None:
        # Cell/batch/owner-escalation reasons route through the PLAN or PROMPT, never a per-node
        # anti-motif line -- folding them in here would silently duplicate a fix quota.py/brief.py
        # already carries.
        entries = (
            VerdictQueueEntry(subject_id="cell-key", rung=3, reason="cell systematically weak"),
            VerdictQueueEntry(subject_id="(corpus)", rung=4, reason="batch reject"),
            VerdictQueueEntry(subject_id="legitimateSkew question", rung=5, reason="owner decision needed"),
        )
        self.assertEqual((), verdict_queue.anti_motifs_for_node(entries, "skill.t-off-t1-n0", tree_id="t"))

    def test_order_is_the_queues_own_commit_order_never_resorted(self) -> None:
        entries = (
            VerdictQueueEntry(subject_id="n0", rung=1, reason="second reason wrote first"),
            VerdictQueueEntry(subject_id="n0", rung=1, reason="first reason wrote second"),
        )
        motifs = verdict_queue.anti_motifs_for_node(entries, "n0")
        self.assertEqual(("second reason wrote first", "first reason wrote second"), motifs)

    def test_the_same_query_twice_is_identical(self) -> None:
        entries = (VerdictQueueEntry(subject_id="n0", rung=1, reason="a reason"),)
        first = verdict_queue.anti_motifs_for_node(entries, "n0")
        second = verdict_queue.anti_motifs_for_node(entries, "n0")
        self.assertEqual(first, second)
