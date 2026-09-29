"""Tests for seedsmith.adapters.dungeon (D1.6/D1.7/D1.8, spec-dungeon-seed-contract.md).

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_contract.py -v

Covers the spec's own Testing-strategy table for the schema/ownership/audit/adapter surface.
Ordering (`derive_kind_order`) has its own file, `test_dungeon_order.py` — it needs the shared
`planner.ordering` module and a live corpus fixture, which belongs apart from these pure-schema
checks.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.base import RegistrySet  # noqa: E402
from seedsmith.adapters.dungeon import DungeonAdapter  # noqa: E402
from seedsmith.adapters.dungeon.audit import (  # noqa: E402
    AuditDefect,
    numeric_audit,
    planned_const_audit,
    run_audit,
)
from seedsmith.adapters.dungeon.kinds import KINDS, MODEL_FREE_KINDS  # noqa: E402
from seedsmith.adapters.dungeon.schema import (  # noqa: E402
    ALLOWLISTED_INTEGER_FIELDS,
    OWNERSHIP_BY_KIND,
    PLANNED_FIELDS_BY_KIND,
    SCHEMA_BUILDERS,
    build_schema,
)
from seedsmith.adapters.dungeon.descriptions import DESCRIPTIONS  # noqa: E402

VALID_LEVELS = frozenset({"AUTHORED", "VALIDATED", "DERIVED", "GENERATED", "PLANNED"})


class KindSpecTests(unittest.TestCase):
    def test_seven_kinds(self) -> None:
        self.assertEqual(len(KINDS), 7)
        self.assertEqual({k.kind for k in KINDS}, {
            "dungeon-domain", "dungeon-room", "dungeon-layout", "dungeon-event",
            "dungeon-quest", "dungeon-encounter", "dungeon-supply-ext",
        })

    def test_layout_is_the_one_model_free_kind(self) -> None:
        self.assertEqual(MODEL_FREE_KINDS, frozenset({"dungeon-layout"}))
        layout = next(k for k in KINDS if k.kind == "dungeon-layout")
        # §1.3: every field on layout is PLANNED.
        levels = {OWNERSHIP_BY_KIND["dungeon-layout"][f] for f in layout.required}
        self.assertEqual(levels, {"PLANNED"})


class OwnershipTests(unittest.TestCase):
    def test_every_field_has_exactly_one_level(self) -> None:
        for kind_spec in KINDS:
            ownership = OWNERSHIP_BY_KIND[kind_spec.kind]
            all_fields = kind_spec.required | kind_spec.optional
            for field in all_fields:
                self.assertIn(field, ownership, f"{kind_spec.kind}.{field} has no ownership level")
                self.assertIn(ownership[field], VALID_LEVELS,
                             f"{kind_spec.kind}.{field} has an invalid level {ownership[field]!r}")
            # No stray ownership entry for a field the KindSpec doesn't actually declare.
            stray = set(ownership) - all_fields
            self.assertEqual(stray, set(), f"{kind_spec.kind} has ownership for undeclared field(s) {stray}")

    def test_ids_are_always_PLANNED(self) -> None:
        # "Every id is PLANNED: the planner mints <kind>.<cell>-<nnn>" (§1 preamble).
        id_fields = {"domainId", "roomId", "layoutId", "eventId", "questId", "encounterId"}
        for kind, ownership in OWNERSHIP_BY_KIND.items():
            for field, level in ownership.items():
                if field in id_fields:
                    self.assertEqual(level, "PLANNED", f"{kind}.{field} must be PLANNED")


class DescriptionTests(unittest.TestCase):
    def test_every_referenced_field_has_a_description(self) -> None:
        for kind_spec in KINDS:
            for field in kind_spec.required | kind_spec.optional:
                self.assertIn(field, DESCRIPTIONS, f"{kind_spec.kind}.{field} has no description")

    def test_every_description_names_what_it_is_not(self) -> None:
        # A negative clause is present -- looked for by the same substring the creatures precedent
        # uses to prove the sentence exists, not to validate its prose quality.
        missing = [f for f, text in DESCRIPTIONS.items() if "NOT" not in text and "not " not in text.lower()]
        self.assertEqual(missing, [], f"fields with no negative clause: {missing}")


class SchemaAuditTests(unittest.TestCase):
    def test_audit_is_green_over_all_seven_live_schemas(self) -> None:
        results = run_audit()
        self.assertEqual(set(results), set(SCHEMA_BUILDERS))
        for kind, defects in results.items():
            self.assertEqual(defects, [], f"{kind} has audit defects: {defects}")

    def test_audit_rejects_a_bare_integer(self) -> None:
        red = {"type": "object", "properties": {"someCount": {"type": "integer"}}}
        defects = numeric_audit(red)
        self.assertTrue(any(d.case == "bare-integer" for d in defects))
        green = {"type": "object", "properties": {"someCount": {"type": "integer", "const": 1}}}
        self.assertEqual(numeric_audit(green), [])

    def test_audit_rejects_a_pattern_admitting_a_bare_number(self) -> None:
        red = {"type": "object", "properties": {"code": {"type": "string", "pattern": r"^\d+$"}}}
        defects = numeric_audit(red)
        self.assertTrue(any(d.case == "pattern-admits-number" for d in defects))

    def test_audit_rejects_a_numeric_string_enum(self) -> None:
        red = {"type": "object", "properties": {"tier": {"type": "string", "enum": ["1", "2", "3"]}}}
        defects = numeric_audit(red)
        self.assertTrue(any(d.case == "enum-numeric-strings" for d in defects))
        green = {"type": "object", "properties": {"tier": {"type": "string", "enum": ["low", "mid", "high"]}}}
        self.assertEqual(numeric_audit(green), [])

    def test_audit_rejects_a_deny_listed_field_name(self) -> None:
        red = {"type": "object", "properties": {"weight": {"type": "string", "enum": ["a", "b"]}}}
        defects = numeric_audit(red)
        self.assertTrue(any(d.case == "deny-listed-name" for d in defects))

    def test_audit_rejects_weight_and_chance_stems(self) -> None:
        red = {"type": "object", "properties": {
            "weightBand": {"type": "string", "enum": ["a"]},
            "spawnChance": {"type": "string", "enum": ["a"]},
        }}
        defects = numeric_audit(red)
        cases = {d.case for d in defects}
        self.assertIn("weight-or-chance-stem", cases)
        self.assertEqual(sum(1 for d in defects if d.case == "weight-or-chance-stem"), 2)

        green = {"type": "object", "properties": {"dropBand": {"type": "string", "enum": ["staple"]}}}
        defects = numeric_audit(green)
        self.assertEqual([d for d in defects if d.case == "weight-or-chance-stem"], [])

    def test_audit_rejects_spelled_number_enums(self) -> None:
        red = {"type": "object", "properties": {"countBand": {"type": "string", "enum": ["one", "two"]}}}
        defects = numeric_audit(red)
        self.assertTrue(any(d.case == "spelled-number-enum" for d in defects))

        green = {"type": "object", "properties": {"countBand": {"type": "string", "enum": ["lone", "pair"]}}}
        # "pair" is not in the SPELLED_NUMBERS list (only zero..ten's cardinal words are banned) --
        # deliberately proving the green fixture from the spec's own row passes clean.
        self.assertEqual([d for d in numeric_audit(green) if d.case == "spelled-number-enum"], [])

    def test_allowlist_is_exactly_manifestCost(self) -> None:
        self.assertEqual(ALLOWLISTED_INTEGER_FIELDS, frozenset({"manifestCost"}))
        # phaseCount / retinuePerParty as bare integer fields must be caught, not silently allowed.
        red = {"type": "object", "properties": {
            "phaseCount": {"type": "integer"},
            "retinuePerParty": {"type": "integer"},
        }}
        defects = numeric_audit(red)
        flagged = {d.path for d in defects if d.case == "bare-integer"}
        self.assertEqual(flagged, {"$.phaseCount", "$.retinuePerParty"})

    def test_planned_fields_are_const_in_every_call_schema(self) -> None:
        for kind in SCHEMA_BUILDERS:
            schema = build_schema(kind)
            defects = planned_const_audit(kind, schema)
            self.assertEqual(defects, [], f"{kind}: {defects}")

    def test_a_planned_field_exposed_as_a_free_enum_fails(self) -> None:
        # Fixture: dungeon-room's PLANNED "kind" field offered as a free enum instead of const.
        schema = build_schema("dungeon-room")
        broken = dict(schema)
        broken["properties"] = dict(schema["properties"])
        broken["properties"]["kind"] = {"type": "string", "enum": ["fight", "elite"]}  # no const
        defects = planned_const_audit("dungeon-room", broken)
        self.assertTrue(any(d.case == "planned-not-const" and "kind" in d.path for d in defects))


class EnumNoneTests(unittest.TestCase):
    def test_every_closed_enum_in_every_schema_admits_none_or_is_const(self) -> None:
        """A free (non-const) string enum must either contain 'none' or be one the spec's own
        table states never admits none (a short, named exception list — every other free enum is
        a contract defect if it silently forgot the option)."""
        NO_NONE_BY_DESIGN = {
            ("dungeon-room", "secretEligible"),  # yes/no, not a none-admitting enum (§1.2)
            ("dungeon-room", "sightBand"),  # required, no default -- omission is unsampleable (§1.2)
            ("dungeon-event", "repeatScope"), ("dungeon-quest", "repeatScope"),  # every event/quest repeats somehow
            ("dungeon-event", "outcomes"),  # ordinal/consequence/dropBand nested -- checked at the leaf, not here
            ("dungeon-domain", "theme"),  # no none: a domain without a theme has no loot binding (§1.1)
            ("dungeon-domain", "entranceHint"),  # no none: decision 14 maps every domain to one (§1.1)
            ("dungeon-quest", "rewardBand"),  # no none: a quest that rewards nothing is not a quest (§1.5's
                                             # "quests reward, never unlock" premise -- a reward is mandatory)
        }
        for kind, schema in ((k, build_schema(k)) for k in SCHEMA_BUILDERS):
            for field, node in schema["properties"].items():
                if "enum" not in node or "const" in node:
                    continue
                if (kind, field) in NO_NONE_BY_DESIGN:
                    continue
                self.assertIn("none", node["enum"],
                             f"{kind}.{field}'s free enum {node['enum']} has no 'none' and no stated exception")


class LegalityTests(unittest.TestCase):
    def test_legality_makes_53_room_cells(self) -> None:
        adapter = DungeonAdapter()
        legal = adapter.legal_combinations()
        dims = {d.id: d for d in adapter.dimensions()}
        room_kinds = dims["roomKind"].values
        climates = dims["climate"].values
        # room_kinds mirrors the same closed vocabulary as RoomKindCatalog/load_room_kinds
        # (pinned there); never a third literal for the same fact (population-pin SE3.5,
        # 2026-09-20). The real point of this test is legal_cells below.
        self.assertTrue(len(room_kinds) > 0)
        self.assertEqual(len(climates), 7)  # six elements + none

        legal_cells = sum(
            1 for kind in room_kinds for climate in climates
            if legal("roomKind", kind, "climate", climate)
        )
        self.assertEqual(legal_cells, 53)

    def test_climate_neutral_kinds_only_legal_at_none(self) -> None:
        adapter = DungeonAdapter()
        legal = adapter.legal_combinations()
        for kind in ("rest", "merchant", "boss", "unknown"):
            self.assertTrue(legal("roomKind", kind, "climate", "none"))
            self.assertFalse(legal("roomKind", kind, "climate", "fire"))

    def test_climate_bearing_kinds_admit_every_element_and_none(self) -> None:
        adapter = DungeonAdapter()
        legal = adapter.legal_combinations()
        for kind in ("fight", "elite", "cache", "curio", "wild", "shrine", "trap"):
            for climate in ("fire", "ice", "air", "earth", "light", "dark", "none"):
                self.assertTrue(legal("roomKind", kind, "climate", climate), f"{kind}/{climate}")


class AdapterRegistrationTests(unittest.TestCase):
    def test_dungeon_is_registered(self) -> None:
        from seedsmith.adapters.registry import known_adapter_names, resolve_adapter

        self.assertIn("dungeon", known_adapter_names())
        adapter = resolve_adapter("dungeon")
        self.assertIsInstance(adapter, DungeonAdapter)

    def test_channels_are_empty_no_dungeon_owned_magnitude(self) -> None:
        self.assertEqual(DungeonAdapter().channels(), [])

    def test_registries_returns_a_real_registry_set(self) -> None:
        # 9 dungeon-native files + 2 cross-program theme files (`creatures.themes`/`creatures.motifs`,
        # D1.10's 2026-09-07 correction: `theme` reads the creature-seed program's own already-shipped
        # registry rather than a dungeon-authored one) = 11.
        registries = DungeonAdapter().registries()
        self.assertIsInstance(registries, RegistrySet)
        # Same tracked-registry-file count as load_versions (pinned there, test_dungeon_registries.py)
        # -- never a second literal (population-pin SE3.5, 2026-09-20).
        self.assertTrue(len(registries.versions) > 0)
        self.assertTrue(registries.is_legal("roomKind", "boss"))
        self.assertFalse(registries.is_legal("roomKind", "not-a-real-kind"))
        self.assertTrue(registries.is_legal("theme", "creature.allpeater"))
        self.assertFalse(registries.is_legal("theme", "not-a-real-theme"))


if __name__ == "__main__":
    unittest.main()


class PlannedClimateTests(unittest.TestCase):
    """NS11 (spec-dungeon-generator-repair.md §5) — `climateAffinity` is PLANNED and pinned `const`."""

    def test_climate_is_planned_const(self) -> None:
        from seedsmith.adapters.dungeon.briefs import build_event_schema_for_cell
        from seedsmith.adapters.dungeon.planner import Cell as PlannerCell

        cell = PlannerCell("dungeon-event", ("curio", "creature.wallnut"), "curio-creature.wallnut")
        schema = build_event_schema_for_cell(
            cell, "event.curio-creature.wallnut-001",
            grantable_atom_families=frozenset({"atom.might"}), power_bands=frozenset({"medium"}),
            override_tags=frozenset({"herbs"}), climate="ice")
        node = schema["properties"]["climateAffinity"]
        self.assertEqual(node["const"], "ice")
        self.assertNotIn("enum", node, "a PLANNED field exposed as a free choice is the defect §1 forbids")

        results = run_audit("dungeon-event")
        self.assertEqual(results, {"dungeon-event": []})

    def test_climate_affinity_is_marked_planned_in_the_ownership_table(self) -> None:
        from seedsmith.adapters.dungeon.schema import EVENT_OWNERSHIP

        self.assertEqual(EVENT_OWNERSHIP["climateAffinity"], "PLANNED")
