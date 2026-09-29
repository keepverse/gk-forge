"""Tests for the `unique` KindSpec's ownership levels (D4.29, spec-unique-pipeline.md §1).

    python -m pytest gk-forge/tools/seedsmith/tests/test_unique_kinds.py -v

Mirrors `test_dungeon_contract.py`'s own `test_every_field_has_exactly_one_level` -- the exact
acceptance line this task states verbatim ("one ownership level per `unique` field") -- scoped to
the one kind this task amends rather than the dungeon adapter's full seven.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.kinds import (  # noqa: E402
    KINDS,
    UNIQUE_DERIVED_FACTS,
    UNIQUE_OWNERSHIP,
    VALID_OWNERSHIP_LEVELS,
)


def _unique_kind_spec():
    return next(k for k in KINDS if k.kind == "unique")


class UniqueOwnershipTests(unittest.TestCase):
    def test_every_declared_field_has_exactly_one_valid_level(self) -> None:
        spec = _unique_kind_spec()
        all_fields = spec.required | spec.optional
        for field in all_fields:
            self.assertIn(field, UNIQUE_OWNERSHIP, f"unique.{field} has no ownership level")
            self.assertIn(UNIQUE_OWNERSHIP[field], VALID_OWNERSHIP_LEVELS,
                         f"unique.{field} has an invalid level {UNIQUE_OWNERSHIP[field]!r}")

    def test_no_stray_ownership_for_an_undeclared_field(self) -> None:
        spec = _unique_kind_spec()
        all_fields = spec.required | spec.optional
        stray = set(UNIQUE_OWNERSHIP) - all_fields
        self.assertEqual(stray, set(), f"ownership declared for undeclared field(s) {stray}")

    def test_id_and_its_three_minted_keys_are_planned(self) -> None:
        # spec §1: "id, nameKey, iconKey, flavorKey | PLANNED | ... plus three keys minted from
        # the slug; container id DERIVED ... never authored".
        for field in ("id", "nameKey", "iconKey", "flavorKey"):
            self.assertEqual(UNIQUE_OWNERSHIP[field], "PLANNED", f"unique.{field} must be PLANNED")

    def test_the_grid_cell_fields_are_planned(self) -> None:
        # frame/powerAxis/rarity ARE the frame x axis x band grid cell; acquisition is fixed from
        # the band (ssot-uniques.md §4.5) -- none is a free author choice.
        for field in ("frame", "powerAxis", "rarity", "acquisition"):
            self.assertEqual(UNIQUE_OWNERSHIP[field], "PLANNED", f"unique.{field} must be PLANNED")

    def test_only_free_text_fields_are_authored(self) -> None:
        authored = {f for f, lvl in UNIQUE_OWNERSHIP.items() if lvl == "AUTHORED"}
        self.assertEqual(authored, {"name", "flavor", "reason", "notes"})

    def test_validated_fields_are_the_closed_registry_ones(self) -> None:
        validated = {f for f, lvl in UNIQUE_OWNERSHIP.items() if lvl == "VALIDATED"}
        self.assertEqual(validated, {
            "baseType", "fixedAtoms", "varianceSlot", "counterPressure", "actionGrantRef",
            "theme", "themeKey", "tags", "enabled", "overrides", "unlockGate",
        })

    def test_derived_facts_never_appear_as_a_seed_field(self) -> None:
        # spec §1's own table, last row: DERIVED facts are never in the file at all, so they must
        # not double as a declared KindSpec field with their own ownership entry.
        spec = _unique_kind_spec()
        all_fields = spec.required | spec.optional
        self.assertEqual(UNIQUE_DERIVED_FACTS & all_fields, set())
        self.assertEqual(UNIQUE_DERIVED_FACTS & set(UNIQUE_OWNERSHIP), set())


if __name__ == "__main__":
    unittest.main()
