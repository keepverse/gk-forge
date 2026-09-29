"""Tests for the `relic` KindSpec (empire-development Task 1.3a, spec-relic-item-kind.md §Design 1).

    python -m pytest gk-forge/tools/seedsmith/tests/test_relic_kinds.py -v

A relic is a rolled, never-equipped item with no equip role and no base type. The KindSpec pins
that shape: required is COMMON_REQUIRED + flavorKey only, and refs is empty -- a relic never
points at a base type or role.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.kinds import (  # noqa: E402
    COMMON_REQUIRED,
    KINDS,
)


def _relic_kind_spec():
    return next(k for k in KINDS if k.kind == "relic")


class RelicKindSpecTests(unittest.TestCase):
    def test_relic_kind_is_registered(self) -> None:
        kinds = {k.kind for k in KINDS}
        self.assertIn("relic", kinds)
        # Closed vocabulary grows by exactly one: 15 -> 16 (relic). `combination`'s own
        # absence here is pre-existing port drift (it exists in KindCatalog.cs but was never
        # ported), not this task's to fix. The count is pinned once, test_items_adapter.py
        # (population-pin SE3.5, 2026-09-20) -- never a second literal for the same KINDS object.

    def test_relic_kind_lives_in_the_relics_directory(self) -> None:
        spec = _relic_kind_spec()
        self.assertEqual("relics", spec.directory)
        self.assertEqual("relics", spec.namespace)

    def test_relic_required_is_common_plus_flavor_key_only(self) -> None:
        spec = _relic_kind_spec()
        self.assertEqual(COMMON_REQUIRED | {"flavorKey"}, spec.required)
        for field in ("frame", "baseType", "role", "counterPressure", "powerAxis"):
            self.assertNotIn(field, spec.required, f"relic.{field} must not be required")

    def test_relic_optional_carries_theme_acquisition_and_fixed_atoms(self) -> None:
        spec = _relic_kind_spec()
        for field in ("theme", "themeKey", "acquisition", "fixedAtoms"):
            self.assertIn(field, spec.optional, f"relic.{field} must be allowed")
        for field in ("frame", "baseType", "role", "counterPressure", "powerAxis"):
            self.assertNotIn(field, spec.optional, f"relic.{field} must not even be allowed")

    def test_fixed_atoms_is_optional_not_required(self) -> None:
        # Spec §Design 1: many relics carry zero atoms and exist purely as Wonder-build cost
        # tokens, so fixedAtoms stays optional, unlike unique's required one.
        spec = _relic_kind_spec()
        self.assertNotIn("fixedAtoms", spec.required)
        self.assertIn("fixedAtoms", spec.optional)

    def test_a_relic_kindspec_has_no_reference_fields(self) -> None:
        # Spec §Testing strategy, verbatim: refs == {} -- a relic never points at a base type
        # or role. unique carries refs={"baseType"}; relic carries nothing.
        spec = _relic_kind_spec()
        self.assertEqual(frozenset(), spec.reference_fields)


if __name__ == "__main__":
    unittest.main()
