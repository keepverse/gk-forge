"""Tests for seedsmith.adapters.items.uniques.audit (D4.29, spec-unique-pipeline.md §1/§7).

    python -m pytest gk-forge/tools/seedsmith/tests/test_unique_audit.py -v

`validate_source_locked_once` is the genuinely new check this session's own research (both here
and independently in the C# `DungeonLootTableGen.ValidateSourceLockedOnce`, same day) confirmed
has no precedent in either language -- covered by the same real-vs-refused matrix as its C#
counterpart, so the two stay provably in agreement on the rule even though neither calls the other.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.uniques.audit import (  # noqa: E402
    SourceLockReference,
    budget_report,
    contract_audit,
    numeric_audit,
    stale_ids,
    validate_source_locked_once,
)
from seedsmith.adapters.items.uniques.briefs import build_unique_schema, role_for_cell  # noqa: E402
from seedsmith.adapters.items.uniques.planner import Cell  # noqa: E402

_CELL = Cell("plant", "offense", "firstseed", "plant-offense-firstseed")
FAKE_SCHEMA_KWARGS = dict(
    base_types_by_frame_and_role={("plant", role_for_cell(_CELL)): frozenset({"item.plant-example-a-001"})},
    atom_families=frozenset({"atom.might"}),
    tag_axes={"mass-class": ("light",), "material-nature": ("organic",)},
)
PLANNED_IDS = {"id": "unique.plant-offense-firstseed-001", "nameKey": "unique.example",
              "iconKey": "icon.unique.example", "flavorKey": "flavor.unique.example"}


class NumericAuditRealSchemaTests(unittest.TestCase):
    def test_the_real_schema_is_clean(self) -> None:
        cell = Cell("plant", "offense", "firstseed", "plant-offense-firstseed")
        schema = build_unique_schema(cell, PLANNED_IDS, **FAKE_SCHEMA_KWARGS)
        self.assertEqual(numeric_audit(schema), [])

    def test_contract_audit_on_the_live_registry_backed_schema_is_clean(self) -> None:
        # No fixture here -- proves the audit passes against the REAL atom/base-type/tag
        # registries this session's own load_atom_families/load_base_types_by_frame_and_role read fresh.
        self.assertEqual(contract_audit(), [])


class NumericAuditSmugglingShapeTests(unittest.TestCase):
    def test_a_bare_integer_field_is_refused(self) -> None:
        schema = {"type": "object", "properties": {"budgetAe": {"type": "integer"}}}
        defects = numeric_audit(schema)
        self.assertTrue(any(d.case == "bare-integer" for d in defects))

    def test_a_number_typed_enum_or_const_field_is_exempt(self) -> None:
        schema = {"type": "object", "properties": {"tier": {"type": "integer", "const": 3}}}
        self.assertEqual(numeric_audit(schema), [])

    def test_a_pattern_admitting_a_bare_digit_string_is_refused(self) -> None:
        schema = {"type": "object", "properties": {"code": {"type": "string", "pattern": r"^\d+$"}}}
        defects = numeric_audit(schema)
        self.assertTrue(any(d.case == "pattern-admits-number" for d in defects))

    def test_an_all_numeric_string_enum_is_refused(self) -> None:
        schema = {"type": "object", "properties": {"band": {"type": "string", "enum": ["10", "20", "30"]}}}
        defects = numeric_audit(schema)
        self.assertTrue(any(d.case == "enum-numeric-strings" for d in defects))

    def test_a_deny_listed_field_name_is_refused_even_if_declared_safely(self) -> None:
        schema = {"type": "object", "properties": {"damage": {"type": "string", "enum": ["low", "high"]}}}
        defects = numeric_audit(schema)
        self.assertTrue(any(d.case == "deny-listed-name" for d in defects))

    def test_a_weight_or_chance_stem_anywhere_in_the_name_is_refused(self) -> None:
        schema = {"type": "object", "properties": {"dropWeightBand": {"type": "string", "enum": ["a", "b"]}}}
        defects = numeric_audit(schema)
        self.assertTrue(any(d.case == "weight-or-chance-stem" for d in defects))


class SetStemAuditTests(unittest.TestCase):
    def test_a_set_prefixed_field_is_refused(self) -> None:
        schema = {"type": "object", "properties": {"setId": {"type": "string", "enum": ["a"]}}}
        defects = numeric_audit(schema)
        self.assertTrue(any(d.case == "set-stem" for d in defects))

    def test_set_bonus_is_refused(self) -> None:
        schema = {"type": "object", "properties": {"setBonus": {"type": "string", "enum": ["a"]}}}
        defects = numeric_audit(schema)
        self.assertTrue(any(d.case == "set-stem" for d in defects))

    def test_members_and_thresholds_are_refused_by_exact_name(self) -> None:
        schema = {"type": "object", "properties": {
            "members": {"type": "array", "items": {"type": "string"}},
            "thresholds": {"type": "array", "items": {"type": "string"}},
        }}
        defects = numeric_audit(schema)
        cases = {d.path: d.case for d in defects}
        self.assertEqual(cases.get("$.members"), "set-stem")
        self.assertEqual(cases.get("$.thresholds"), "set-stem")

    def test_an_unrelated_field_containing_set_as_a_substring_not_a_prefix_is_not_refused(self) -> None:
        # "asset" is not a set-stem match -- the pattern anchors `^set` (prefix), never a bare
        # substring, so an unrelated field is not caught in the net.
        schema = {"type": "object", "properties": {"assetKey": {"type": "string", "enum": ["a"]}}}
        defects = numeric_audit(schema)
        self.assertEqual([d for d in defects if d.case == "set-stem"], [])


class StaleIdsTests(unittest.TestCase):
    def test_an_id_whose_cell_is_no_longer_live_is_stale(self) -> None:
        result = stale_ids(
            ["unique.plant-offense-firstseed-001", "unique.plant-retired-axis-firstseed-001"],
            ["plant-offense-firstseed"])
        self.assertEqual(result, ["unique.plant-retired-axis-firstseed-001"])

    def test_every_id_matching_a_live_cell_is_not_stale(self) -> None:
        result = stale_ids(["unique.plant-offense-firstseed-001"], ["plant-offense-firstseed"])
        self.assertEqual(result, [])


class BudgetReportTests(unittest.TestCase):
    def test_a_cell_hitting_its_declared_target_matches(self) -> None:
        report = budget_report({"plant-offense-firstseed": 1}, {"plant-offense-firstseed": 1})
        self.assertTrue(report["plant-offense-firstseed"]["matches"])

    def test_a_starved_cell_is_named_not_hidden_behind_a_global_total(self) -> None:
        report = budget_report(
            {"plant-offense-firstseed": 1, "plant-control-sunwoven": 1},
            {"plant-offense-firstseed": 2, "plant-control-sunwoven": 0})
        self.assertFalse(report["plant-control-sunwoven"]["matches"])
        self.assertEqual(report["plant-control-sunwoven"]["actual"], 0)
        # The OTHER cell's surplus never masks this one -- each cell reports independently.
        self.assertFalse(report["plant-offense-firstseed"]["matches"])


class ValidateSourceLockedOnceTests(unittest.TestCase):
    def test_a_unique_referenced_by_exactly_one_table_has_no_violation(self) -> None:
        refs = [SourceLockReference("unique.x-001", "dungeon.table-a")]
        self.assertEqual(validate_source_locked_once(refs), [])

    def test_a_unique_referenced_by_two_tables_is_a_violation_naming_both(self) -> None:
        refs = [SourceLockReference("unique.x-001", "dungeon.table-a"),
               SourceLockReference("unique.x-001", "dungeon.table-b")]
        violations = validate_source_locked_once(refs)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].unique_id, "unique.x-001")
        self.assertEqual(violations[0].table_ids, ("dungeon.table-a", "dungeon.table-b"))

    def test_the_same_table_referencing_the_same_unique_twice_is_not_a_violation(self) -> None:
        # The rule is about DISTINCT tables, not row count (e.g. two entries in one table).
        refs = [SourceLockReference("unique.x-001", "dungeon.table-a"),
               SourceLockReference("unique.x-001", "dungeon.table-a")]
        self.assertEqual(validate_source_locked_once(refs), [])

    def test_different_uniques_in_different_tables_never_cross_contaminate(self) -> None:
        refs = [SourceLockReference("unique.x-001", "dungeon.table-a"),
               SourceLockReference("unique.y-001", "dungeon.table-b")]
        self.assertEqual(validate_source_locked_once(refs), [])

    def test_empty_references_is_clean(self) -> None:
        self.assertEqual(validate_source_locked_once([]), [])


if __name__ == "__main__":
    unittest.main()
