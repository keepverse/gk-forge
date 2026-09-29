"""Tests for seedsmith.adapters.trees.species.schemas (task J8, spec-species-tree.md §3.1 step 3,
§6, §7.1)."""
from __future__ import annotations

import copy
import unittest

from seedsmith.adapters.trees.species.schemas import (
    CODEX_SUMMARY_RESPONSE_SCHEMA,
    codex_summary_defects,
    favour_fit_schema,
)
from seedsmith.pipeline.model import Pipeline, audit_schema


class CodexSummarySchemaTests(unittest.TestCase):
    def test_the_schema_is_audit_clean(self) -> None:
        self.assertEqual([], audit_schema(CODEX_SUMMARY_RESPONSE_SCHEMA))

    def test_a_pipeline_constructs_without_raising(self) -> None:
        Pipeline(metric="Species/CodexSummary", scope="species-tree",
                 schema=CODEX_SUMMARY_RESPONSE_SCHEMA, gate=lambda r: (),
                 on_persist=lambda s, r: None)

    def test_the_audit_actually_catches_a_numeric_field_added_to_a_copy(self) -> None:
        """The converse proof `nodegen/schema.py`'s own tests already establish for the generic
        node schema — an audit that always returns `[]` regardless of input proves nothing."""
        mutated = copy.deepcopy(CODEX_SUMMARY_RESPONSE_SCHEMA)
        mutated["properties"]["rewardScoreMilli"] = {"type": "integer"}
        mutated["required"] = list(mutated["required"]) + ["rewardScoreMilli"]
        self.assertNotEqual([], audit_schema(mutated))
        with self.assertRaises(ValueError):
            Pipeline(metric="Species/CodexSummary", scope="species-tree", schema=mutated,
                    gate=lambda r: (), on_persist=lambda s, r: None)


class CodexSummaryDefectsTests(unittest.TestCase):
    def test_a_clean_sentence_has_no_defects(self) -> None:
        self.assertEqual([], codex_summary_defects(
            "Building into this bloodline rewards a slow, unbreakable defense."))

    def test_a_sentence_with_a_digit_is_a_defect(self) -> None:
        defects = codex_summary_defects("Grants a 15 percent boost to your defenses.")
        self.assertEqual(1, len(defects))
        self.assertIn("digit", defects[0])

    def test_a_sentence_with_a_channel_id_shaped_token_is_a_defect(self) -> None:
        defects = codex_summary_defects("Rewards investment in combat.power.fire above all else.")
        self.assertEqual(1, len(defects))
        self.assertIn("combat.power.fire", defects[0])

    def test_ordinary_punctuation_is_not_a_false_positive(self) -> None:
        # A single dot at the end of a sentence, or "e.g."-style abbreviations, must never trip
        # the channel-id pattern -- it requires a LOWERCASE WORD on both sides of the dot.
        self.assertEqual([], codex_summary_defects("A steady, disciplined line."))
        self.assertEqual([], codex_summary_defects("Rewards patience, e.g. holding the line."))

    def test_both_defects_can_be_reported_at_once(self) -> None:
        defects = codex_summary_defects("Deals 3 stacks via stat.modify.")
        self.assertEqual(2, len(defects))


class FavourFitSchemaTests(unittest.TestCase):
    def test_the_schema_is_audit_clean(self) -> None:
        schema = favour_fit_schema(["alt-a", "alt-b"])
        self.assertEqual([], audit_schema(schema))

    def test_a_pipeline_constructs_without_raising(self) -> None:
        Pipeline(metric="Species/FavourFit", scope="species-tree",
                 schema=favour_fit_schema(["alt-a"]), gate=lambda r: (),
                 on_persist=lambda s, r: None)

    def test_the_enum_contains_offered_every_alternate_and_none(self) -> None:
        schema = favour_fit_schema(["alt-a", "alt-b"])
        enum = schema["properties"]["choice"]["enum"]
        self.assertEqual(["offered", "alt-a", "alt-b", "none"], enum)

    def test_two_calls_never_alias_one_enum(self) -> None:
        """The same discipline `nodegen.schema.schema_for_call`'s own test proves — a per-call
        schema must not share a mutable list between two calls."""
        first = favour_fit_schema(["alt-a"])
        second = favour_fit_schema(["alt-b"])
        first["properties"]["choice"]["enum"].append("mutated")
        self.assertNotIn("mutated", second["properties"]["choice"]["enum"])

    def test_an_answer_outside_the_offered_options_is_unsampleable(self) -> None:
        schema = favour_fit_schema(["alt-a"])
        self.assertNotIn("some-other-cell", schema["properties"]["choice"]["enum"])


if __name__ == "__main__":
    unittest.main()
