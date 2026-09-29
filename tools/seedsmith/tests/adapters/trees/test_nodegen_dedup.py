"""Tests for seedsmith.adapters.trees.nodegen.dedup (task H1) — local exact Jaccard over tier
siblings; deliberately NOT the shared MinHash (spec-tree-language.md §7 gate 20).
"""
from __future__ import annotations

import unittest

from seedsmith.adapters.trees.nodegen import dedup


class ExactJaccardTests(unittest.TestCase):
    def test_identical_strings_score_1000(self) -> None:
        self.assertEqual(dedup.exact_jaccard_permille("Frost Bite", "Frost Bite"), 1000)

    def test_unrelated_strings_score_low(self) -> None:
        score = dedup.exact_jaccard_permille("Tier Duration", "Husk of the Murmuration")
        # the measured true value from items/setgen/dedup.py's own table is 0.120 -> 120 permille
        self.assertLess(score, 200)

    def test_empty_strings_score_zero_not_a_division_error(self) -> None:
        self.assertEqual(dedup.exact_jaccard_permille("", ""), 0)


class NearestTests(unittest.TestCase):
    def test_returns_the_k_closest_by_score_descending(self) -> None:
        siblings = {"n1": "Frost Bite", "n2": "Frost Burn", "n3": "Total Nonsense Word Salad"}
        result = dedup.nearest("Frost Byte", siblings, k=2)
        self.assertEqual(len(result), 2)
        self.assertGreaterEqual(result[0].jaccard_permille, result[1].jaccard_permille)
        ids = {m.node_id for m in result}
        self.assertIn("n1", ids)
        self.assertIn("n2", ids)

    def test_k_zero_returns_nothing(self) -> None:
        self.assertEqual(dedup.nearest("Frost Bite", {"n1": "Frost Bite"}, k=0), [])

    def test_negative_k_raises(self) -> None:
        with self.assertRaises(ValueError):
            dedup.nearest("x", {}, k=-1)


class TierReportTests(unittest.TestCase):
    def test_exact_duplicate_names_are_reported(self) -> None:
        names = {"n1": "Frost Bite", "n2": "Frost Bite", "n3": "Something Else"}
        report = dedup.tier_report(names)
        self.assertEqual(len(report.exact_duplicates), 1)

    def test_near_duplicates_meet_the_threshold(self) -> None:
        names = {"n1": "Frost Bite", "n2": "Frost Byte"}
        report = dedup.tier_report(names, threshold_permille=300)
        self.assertEqual(len(report.near_duplicates), 1)

    def test_rate_permille_is_zero_on_an_empty_population(self) -> None:
        report = dedup.tier_report({})
        self.assertEqual(report.rate_permille, 0)


if __name__ == "__main__":
    unittest.main()
