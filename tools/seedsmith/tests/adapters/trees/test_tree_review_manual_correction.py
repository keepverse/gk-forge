"""Tests for seedsmith.adapters.trees.review.manual_correction (task J3, spec-tree-review.md §6.1).
"""
from __future__ import annotations

import unittest

from seedsmith.adapters.trees.review.manual_correction import (
    ManualCorrection,
    manual_correction_rate_permille,
)


class ManualCorrectionConstructionTests(unittest.TestCase):
    def test_a_real_correction_with_all_four_fields_constructs_cleanly(self) -> None:
        c = ManualCorrection(node_id="skill.might-off-t1-n0", from_text="old flavor",
                             to_text="new flavor", by="reviewer-1",
                             why="typo fixed, no content change intended")
        self.assertEqual("skill.might-off-t1-n0", c.node_id)
        self.assertEqual("reviewer-1", c.by)

    def test_an_empty_why_is_refused(self) -> None:
        with self.assertRaises(ValueError) as ex:
            ManualCorrection(node_id="n0", from_text="a", to_text="b", by="reviewer-1", why="")
        self.assertIn("empty 'why'", str(ex.exception))

    def test_a_whitespace_only_why_is_also_refused(self) -> None:
        with self.assertRaises(ValueError):
            ManualCorrection(node_id="n0", from_text="a", to_text="b", by="reviewer-1", why="   ")

    def test_from_equal_to_to_is_refused_as_a_no_op_correction(self) -> None:
        with self.assertRaises(ValueError) as ex:
            ManualCorrection(node_id="n0", from_text="same", to_text="same", by="r", why="stated")
        self.assertIn("equals .to", str(ex.exception))


class ManualCorrectionRateTests(unittest.TestCase):
    def _correction(self, node_id: str) -> ManualCorrection:
        return ManualCorrection(node_id=node_id, from_text="a", to_text="b", by="r",
                                why="a real reason")

    def test_zero_corrections_over_a_real_corpus_is_zero_permille(self) -> None:
        self.assertEqual(0, manual_correction_rate_permille([], 1680))

    def test_the_rate_is_against_total_nodes_never_against_the_correction_count_itself(self) -> None:
        corrections = [self._correction(f"n{i}") for i in range(17)]
        # 17/1680 = 10.1‰, integer-truncated -- the same "divide once, last" convention this whole
        # program uses for every other per-mille rate (docs/architecture/numeric-types.md rule 4).
        self.assertEqual(10, manual_correction_rate_permille(corrections, 1680))

    def test_a_zero_total_nodes_denominator_is_refused_never_a_silent_zero(self) -> None:
        with self.assertRaises(ValueError) as ex:
            manual_correction_rate_permille([self._correction("n0")], 0)
        self.assertIn("not measured, not zero", str(ex.exception))

    def test_a_negative_total_nodes_denominator_is_also_refused(self) -> None:
        with self.assertRaises(ValueError):
            manual_correction_rate_permille([], -1)

    def test_every_node_corrected_is_1000_permille(self) -> None:
        corrections = [self._correction(f"n{i}") for i in range(40)]
        self.assertEqual(1000, manual_correction_rate_permille(corrections, 40))
