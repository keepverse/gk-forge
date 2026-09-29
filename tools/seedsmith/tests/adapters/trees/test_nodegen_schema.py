"""Tests for seedsmith.adapters.trees.nodegen.schema (task H1) — spec-tree-language.md §7 gates 1
and 8: the response schema refuses a numeric field AT CONSTRUCTION, and the permitted subset IS the
schema enum, so an out-of-quota value is unsampleable rather than merely rejected.

    python -m pytest gk-forge/tools/seedsmith/tests/adapters/trees/test_nodegen_schema.py -v
"""
from __future__ import annotations

import copy
import unittest

from seedsmith.adapters.trees.nodegen import schema
from seedsmith.pipeline.model import Pipeline


class SchemaHasNoNumericFieldTests(unittest.TestCase):
    """§7 gate 1: `audit_schema` passes over the real constant and fails when a numeric field is
    added — proven both as a direct `audit_schema` call and as a `Pipeline` construction-time
    `ValueError` (the actual mechanism `Pipeline.__post_init__` runs the audit through)."""

    def test_audit_schema_passes_over_the_real_shipped_schema(self) -> None:
        self.assertEqual(schema.audit_schema(schema.NODE_RESPONSE_SCHEMA), [])

    def test_audit_schema_fails_when_a_bare_numeric_field_is_added(self) -> None:
        mutated = copy.deepcopy(schema.NODE_RESPONSE_SCHEMA)
        mutated["properties"]["strengthMilli"] = {"type": "integer"}
        mutated["required"] = list(mutated["required"]) + ["strengthMilli"]
        defects = schema.audit_schema(mutated)
        self.assertTrue(defects, "a bare integer field must be caught")

    def test_audit_schema_fails_when_a_deny_listed_name_is_added_even_as_a_closed_enum(self) -> None:
        """§2.1: the name check "fires even when the value is a legal, enum-closed vocabulary, on
        purpose" — a `tier` field with a closed string enum is still refused by NAME."""
        mutated = copy.deepcopy(schema.NODE_RESPONSE_SCHEMA)
        mutated["properties"]["tier"] = {"type": "string", "enum": ["shallow", "mid", "deep"]}
        mutated["required"] = list(mutated["required"]) + ["tier"]
        defects = schema.audit_schema(mutated)
        self.assertTrue(defects)
        self.assertTrue(any("tier" in str(d) for d in defects))

    def test_construction_of_a_pipeline_with_the_real_schema_succeeds(self) -> None:
        pipeline = schema.build_pipeline(schema.schema_for_call(["atom.a", "atom.b"], ["posture"]))
        self.assertIsInstance(pipeline, Pipeline)

    def test_construction_of_a_pipeline_with_a_numeric_field_raises_at_construction(self) -> None:
        """Gate 1's own failure shape: `ValueError` at construction, before any call — never a
        later validation pass."""
        mutated = copy.deepcopy(schema.NODE_RESPONSE_SCHEMA)
        mutated["properties"]["chanceMilli"] = {"type": "integer"}
        with self.assertRaises(ValueError):
            schema.build_pipeline(mutated)

    def test_deny_names_include_the_ones_the_spec_cites_by_line(self) -> None:
        """spec-tree-language.md §2.1 cites `model.py:63-65` for tier/rung/duration/chance/cost/
        weight/damage/hp/atk, plus the *Milli suffix at `:71` — this schema reuses that SHARED
        constant rather than forking a program-local widened copy."""
        for name in ("tier", "rung", "duration", "chance", "cost", "weight", "damage", "hp", "atk"):
            self.assertIn(name, schema.MAGNITUDE_DENY_NAMES)


class EnumIsEmptyInTheConstantTests(unittest.TestCase):
    def test_affix_ids_enum_is_empty_in_the_shipped_constant(self) -> None:
        self.assertEqual(schema.NODE_RESPONSE_SCHEMA["properties"]["affixIds"]["items"]["enum"], [])

    def test_exclusion_property_keys_enum_is_empty_in_the_shipped_constant(self) -> None:
        exclusion_props = schema.NODE_RESPONSE_SCHEMA["properties"]["exclusion"]["properties"]
        self.assertEqual(exclusion_props["propertyKeys"]["items"]["enum"], [])

    def test_only_fill_schema_populates_it(self) -> None:
        filled = schema.schema_for_call(["atom.a"], ["posture"])
        self.assertEqual(filled["properties"]["affixIds"]["items"]["enum"], ["atom.a"])
        # the shared constant is untouched
        self.assertEqual(schema.NODE_RESPONSE_SCHEMA["properties"]["affixIds"]["items"]["enum"], [])


class TwoCallsNeverAliasOneEnumTests(unittest.TestCase):
    def test_two_calls_with_different_cells_never_alias(self) -> None:
        first = schema.schema_for_call(["atom.a", "atom.b"], ["posture"])
        second = schema.schema_for_call(["atom.c"], ["conversionState"])
        self.assertEqual(first["properties"]["affixIds"]["items"]["enum"], ["atom.a", "atom.b"])
        # mutating `second` (or building it) must never have touched `first`'s own enum
        self.assertEqual(first["properties"]["affixIds"]["items"]["enum"], ["atom.a", "atom.b"])
        self.assertNotEqual(
            first["properties"]["affixIds"]["items"]["enum"],
            second["properties"]["affixIds"]["items"]["enum"],
        )


class OutOfQuotaValueIsAbsentFromTheEnumTests(unittest.TestCase):
    """Gate 8, this schema's own load-bearing property: a value outside the permitted subset is
    UNSAMPLEABLE — literally absent from the enum the model is constrained to — not merely
    rejected by a later check."""

    def test_out_of_cell_affix_ids_never_appear_in_the_filled_enum(self) -> None:
        full_corpus = [f"atom.{i}" for i in range(20)]
        permitted_subset = full_corpus[:5]
        filled = schema.schema_for_call(permitted_subset, [])
        enum = filled["properties"]["affixIds"]["items"]["enum"]
        self.assertEqual(set(enum), set(permitted_subset))
        for out_of_quota in full_corpus[5:]:
            self.assertNotIn(out_of_quota, enum)

    def test_out_of_vocabulary_property_keys_never_appear_in_the_filled_enum(self) -> None:
        full_vocab = ["posture", "conversionState", "elementSlot", "somethingElse"]
        permitted_subset = ["posture"]
        filled = schema.schema_for_call([], permitted_subset)
        enum = filled["properties"]["exclusion"]["properties"]["propertyKeys"]["items"]["enum"]
        self.assertEqual(enum, permitted_subset)
        for out_of_quota in full_vocab[1:]:
            self.assertNotIn(out_of_quota, enum)


class RationaleIsOptionalAndNeverGatesTests(unittest.TestCase):
    """The resolved spec ambiguity documented in schema.py's own module docstring: `rationale` is a
    real property, but it is never in `required` and never a verdict field."""

    def test_rationale_is_a_property_but_not_required(self) -> None:
        self.assertIn("rationale", schema.NODE_RESPONSE_SCHEMA["properties"])
        self.assertNotIn("rationale", schema.NODE_RESPONSE_SCHEMA["required"])


if __name__ == "__main__":
    unittest.main()
