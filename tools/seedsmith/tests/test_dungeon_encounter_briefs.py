"""Tests for the encounter half of seedsmith.adapters.dungeon.briefs (D1.10's real remaining scope,
2026-09-07).

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_encounter_briefs.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.dungeon.briefs import (  # noqa: E402
    ENCOUNTER_SYSTEM_PROMPT,
    SLOT_COUNT_BY_FORMATION,
    build_encounter_brief,
    build_encounter_schema_for_cell,
)
from seedsmith.adapters.dungeon.planner import Cell  # noqa: E402
from seedsmith.ladders import THREAT_BAND  # declaring read (tier-propagation-contract T-2)
ZOMBOSS_IDS = frozenset({"force-pure", "finesse-pure", "bastion-pure"})


def _schema(formation: str, element_spread: str = "mono", encounter_id: str = "encounter.x-001") -> dict:
    cell = Cell("dungeon-encounter", (formation, element_spread), f"{formation}-{element_spread}")
    return build_encounter_schema_for_cell(cell, encounter_id, threat_band=THREAT_BAND, zomboss_pattern_ids=ZOMBOSS_IDS)


class SlotCountByFormationTests(unittest.TestCase):
    def test_pack_two_party_three_boss_one(self) -> None:
        self.assertEqual(SLOT_COUNT_BY_FORMATION, {"pack": 2, "party": 3, "boss": 1})


class BuildEncounterSchemaForCellTests(unittest.TestCase):
    def test_encounterId_formation_elementSpread_are_pinned_to_the_real_cell(self) -> None:
        schema = _schema("party", "dual", "encounter.party-dual-007")
        self.assertEqual(schema["properties"]["encounterId"]["const"], "encounter.party-dual-007")
        self.assertEqual(schema["properties"]["formation"]["const"], "party")
        self.assertEqual(schema["properties"]["elementSpread"]["const"], "dual")

    def test_slots_and_rankOrder_length_matches_the_formations_own_slot_count(self) -> None:
        for formation, expected_n in SLOT_COUNT_BY_FORMATION.items():
            schema = _schema(formation)
            self.assertEqual(schema["properties"]["slots"]["minItems"], expected_n)
            self.assertEqual(schema["properties"]["slots"]["maxItems"], expected_n)
            self.assertEqual(schema["properties"]["rankOrder"]["minItems"], expected_n)
            self.assertEqual(schema["properties"]["rankOrder"]["items"]["maximum"], expected_n - 1)

    def test_boss_field_present_only_for_boss_formation(self) -> None:
        self.assertNotIn("boss", _schema("pack")["properties"])
        self.assertNotIn("boss", _schema("party")["properties"])
        boss_schema = _schema("boss")
        self.assertIn("boss", boss_schema["properties"])
        self.assertIn("boss", boss_schema["required"])

    def test_boss_retinue_is_pinned_to_the_only_legal_index_zero(self) -> None:
        schema = _schema("boss")
        self.assertEqual(schema["properties"]["boss"]["properties"]["retinue"]["const"], 0)

    def test_boss_build_offers_exactly_the_supplied_zomboss_ids(self) -> None:
        schema = _schema("boss")
        self.assertEqual(set(schema["properties"]["boss"]["properties"]["build"]["enum"]), ZOMBOSS_IDS)

    def test_synergyHint_and_affixRoll_are_pinned_none(self) -> None:
        schema = _schema("pack")
        self.assertEqual(schema["properties"]["synergyHint"]["const"], "none")
        self.assertEqual(schema["properties"]["affixRoll"]["const"], "none")

    def test_threatWindow_offers_the_real_ten_threat_nouns(self) -> None:
        schema = _schema("pack")
        self.assertEqual(set(schema["properties"]["threatWindow"]["properties"]["floorRung"]["enum"]), set(THREAT_BAND))
        self.assertEqual(set(schema["properties"]["threatWindow"]["properties"]["ceilRung"]["enum"]), set(THREAT_BAND))

    def test_rankOrder_requires_unique_items(self) -> None:
        schema = _schema("party")
        self.assertTrue(schema["properties"]["rankOrder"]["uniqueItems"])

    def test_required_matches_the_kindspecs_own_fields_for_a_non_boss_formation(self) -> None:
        schema = _schema("pack")
        self.assertEqual(set(schema["required"]), {
            "encounterId", "formation", "elementSpread", "name", "reason", "slots",
            "threatWindow", "rankOrder", "tempo", "synergyHint", "affixRoll",
        })

    def test_additionalProperties_is_false_at_every_level(self) -> None:
        schema = _schema("boss")
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(schema["properties"]["slots"]["items"]["additionalProperties"])
        self.assertFalse(schema["properties"]["threatWindow"]["additionalProperties"])
        self.assertFalse(schema["properties"]["boss"]["additionalProperties"])

    def test_posture_is_not_part_of_the_slot_item_schema_at_all(self) -> None:
        # The real, measured fix: posture is assigned by the pipeline after the model responds
        # (planner.posture_multisets_for), never offered as a model choice -- a live batch showed
        # asking for it and retrying on collision resolves only 12/40, then 1/4 even with
        # per-attempt enum permutation and a strengthened retry message.
        schema = _schema("party")
        slot_props = schema["properties"]["slots"]["items"]["properties"]
        self.assertNotIn("posture", slot_props)
        self.assertNotIn("posture", schema["properties"]["slots"]["items"]["required"])
        self.assertEqual(set(slot_props), {"reach", "targetPreference", "countBand"})


class BuildEncounterBriefTests(unittest.TestCase):
    def test_every_formation_produces_a_nonempty_brief_with_no_crash(self) -> None:
        for formation in SLOT_COUNT_BY_FORMATION:
            n_slots = SLOT_COUNT_BY_FORMATION[formation]
            cell = Cell("dungeon-encounter", (formation, "mono"), f"{formation}-mono")
            postures = ("Bastion",) * n_slots
            brief = build_encounter_brief(cell, postures)
            self.assertTrue(brief.strip())
            self.assertIn(f"slot {n_slots - 1} is", brief)  # every slot index up to the last is named

    def test_only_boss_formation_mentions_boss_in_the_brief(self) -> None:
        pack_brief = build_encounter_brief(Cell("dungeon-encounter", ("pack", "mono"), "pack-mono"), ("Bastion", "Finesse"))
        boss_brief = build_encounter_brief(Cell("dungeon-encounter", ("boss", "mono"), "boss-mono"), ("Bastion",))
        self.assertNotIn("BOSS encounter", pack_brief)
        self.assertIn("BOSS encounter", boss_brief)

    def test_brief_names_each_slots_own_pre_assigned_posture_in_order(self) -> None:
        cell = Cell("dungeon-encounter", ("party", "mono"), "party-mono")
        brief = build_encounter_brief(cell, ("Bastion", "Finesse", "Force"))
        self.assertIn("slot 0 is Bastion", brief)
        self.assertIn("slot 1 is Finesse", brief)
        self.assertIn("slot 2 is Force", brief)


class EncounterSystemPromptTests(unittest.TestCase):
    def test_prompt_is_nonempty_and_warns_against_naming_species(self) -> None:
        self.assertTrue(ENCOUNTER_SYSTEM_PROMPT.strip())
        self.assertIn("species", ENCOUNTER_SYSTEM_PROMPT.lower())


if __name__ == "__main__":
    unittest.main()
