"""Tests for the room half of seedsmith.adapters.dungeon.briefs (D1.10's real remaining scope,
2026-09-07).

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_room_briefs.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.dungeon.briefs import (  # noqa: E402
    ENCOUNTER_FORMATION_BY_ROOM_KIND,
    EVENT_KIND_BY_ROOM_KIND,
    ROOM_SYSTEM_PROMPT,
    build_room_brief,
    build_room_schema_for_cell,
)
from seedsmith.adapters.dungeon.planner import Cell  # noqa: E402

HAZARD_BAND = frozenset({"none", "light", "heavy"})
SIGHT_BAND = frozenset({"dim", "lit", "scouting"})
DISPOSITION = frozenset({"eager", "open", "wary", "hostile"})
TAGS = frozenset({"tag1", "tag2"})

ROOM_KIND_ROWS = {
    "fight": {"secretEligible": False}, "elite": {"secretEligible": False},
    "cache": {"secretEligible": True}, "curio": {"secretEligible": False},
    "wild": {"secretEligible": False}, "shrine": {"secretEligible": True},
    "rest": {"secretEligible": False}, "merchant": {"secretEligible": True},
    "trap": {"secretEligible": False}, "unknown": {"secretEligible": False},
    "boss": {"secretEligible": False},
}
ENCOUNTER_IDS = {"pack": frozenset({"encounter.pack-a"}), "party": frozenset({"encounter.party-a"}),
                  "boss": frozenset({"encounter.boss-a"})}
EVENT_IDS = {
    "curio": frozenset({"event.curio-a"}), "shrine": frozenset({"event.shrine-a"}),
    "trap": frozenset({"event.trap-a"}), "bargain": frozenset({"event.bargain-a"}),
    "encounter-event": frozenset({"event.ee-a"}),
}  # deliberately NO "story" -- matches the real, live gap this batch found
EVENT_IDS_WITH_STORY = dict(EVENT_IDS, story=frozenset({"event.story-a"}))


def _schema(kind: str, climate: str = "fire", room_id: str = "room.x-001", *, event_ids=EVENT_IDS) -> dict:
    cell = Cell("dungeon-room", (kind, climate), f"{kind}-{climate}")
    return build_room_schema_for_cell(
        cell, room_id, room_kind_rows=ROOM_KIND_ROWS, hazard_band=HAZARD_BAND, sight_band=SIGHT_BAND,
        disposition=DISPOSITION, tags=TAGS, encounter_ids_by_formation=ENCOUNTER_IDS, event_ids_by_kind=event_ids)


class KindFitMappingTests(unittest.TestCase):
    def test_encounter_formation_mapping_matches_the_spec_exactly(self) -> None:
        self.assertEqual(ENCOUNTER_FORMATION_BY_ROOM_KIND, {
            "fight": "pack", "wild": "pack", "elite": "party", "boss": "boss",
        })

    def test_event_kind_fit_mapping_matches_spec_event_deck_exactly_not_same_name_guessing(self) -> None:
        self.assertEqual(EVENT_KIND_BY_ROOM_KIND, {
            "curio": "curio", "shrine": "shrine", "trap": "trap", "merchant": "bargain",
            "wild": "story", "rest": "encounter-event", "unknown": "any",
        })
        # the three non-obvious ones, named explicitly so a future "simplify to same-name" edit is caught
        self.assertEqual(EVENT_KIND_BY_ROOM_KIND["merchant"], "bargain")
        self.assertEqual(EVENT_KIND_BY_ROOM_KIND["wild"], "story")
        self.assertEqual(EVENT_KIND_BY_ROOM_KIND["rest"], "encounter-event")


class BuildRoomSchemaForCellTests(unittest.TestCase):
    def test_roomId_kind_climate_are_pinned_to_the_real_cell(self) -> None:
        schema = _schema("curio", "ice", "room.curio-ice-004")
        self.assertEqual(schema["properties"]["roomId"]["const"], "room.curio-ice-004")
        self.assertEqual(schema["properties"]["kind"]["const"], "curio")
        self.assertEqual(schema["properties"]["climate"]["const"], "ice")

    def test_secretEligible_is_a_real_choice_only_for_the_three_eligible_kinds(self) -> None:
        for kind in ("cache", "shrine", "merchant"):
            schema = _schema(kind, "fire")
            self.assertEqual(set(schema["properties"]["secretEligible"]["enum"]), {"yes", "no"})
        for kind in ("fight", "elite", "curio", "rest", "trap", "unknown", "boss"):
            schema = _schema(kind, "none")
            self.assertEqual(schema["properties"]["secretEligible"]["const"], "no")
        # wild needs a real story event to build at all today -- covered separately
        wild_schema = _schema("wild", "fire", event_ids=EVENT_IDS_WITH_STORY)
        self.assertEqual(wild_schema["properties"]["secretEligible"]["const"], "no")

    def test_dispositionBase_is_a_real_choice_only_on_wild(self) -> None:
        wild_schema = _schema("wild", "fire", event_ids=EVENT_IDS_WITH_STORY)
        self.assertEqual(set(wild_schema["properties"]["dispositionBase"]["enum"]), DISPOSITION)
        for kind in ("fight", "elite", "cache", "curio", "shrine", "rest", "merchant", "trap", "unknown", "boss"):
            schema = _schema(kind, "none")
            self.assertEqual(schema["properties"]["dispositionBase"]["const"], "none")

    def test_encounterRef_offers_only_the_matching_formations_real_ids(self) -> None:
        fight_schema = _schema("fight", "fire")
        self.assertEqual(set(fight_schema["properties"]["encounterRef"]["enum"]), ENCOUNTER_IDS["pack"])
        elite_schema = _schema("elite", "fire")
        self.assertEqual(set(elite_schema["properties"]["encounterRef"]["enum"]), ENCOUNTER_IDS["party"])

    def test_encounterRef_pins_none_on_a_kind_with_no_formation_mapping(self) -> None:
        schema = _schema("cache", "fire")
        self.assertEqual(schema["properties"]["encounterRef"]["const"], "none")

    def test_eventPool_offers_only_the_kind_fit_real_ids(self) -> None:
        schema = _schema("merchant", "fire")
        self.assertEqual(set(schema["properties"]["eventPool"]["items"]["enum"]), EVENT_IDS["bargain"])

    def test_eventPool_unknown_kind_offers_the_union_of_every_real_event(self) -> None:
        schema = _schema("unknown", "none")
        expected = {eid for ids in EVENT_IDS.values() for eid in ids}
        self.assertEqual(set(schema["properties"]["eventPool"]["items"]["enum"]), expected)

    def test_eventPool_pins_empty_on_a_kind_with_no_pool_at_all(self) -> None:
        schema = _schema("cache", "fire")
        self.assertEqual(schema["properties"]["eventPool"]["minItems"], 0)
        self.assertEqual(schema["properties"]["eventPool"]["maxItems"], 0)

    def test_wild_kind_raises_when_no_real_story_event_exists_yet(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _schema("wild", "fire")
        self.assertIn("story", str(ctx.exception))

    def test_wild_kind_succeeds_once_a_real_story_event_is_supplied(self) -> None:
        event_ids = dict(EVENT_IDS, story=frozenset({"event.story-a"}))
        schema = _schema("wild", "fire", event_ids=event_ids)
        self.assertEqual(set(schema["properties"]["eventPool"]["items"]["enum"]), {"event.story-a"})

    def test_a_formation_kind_with_no_real_encounter_yet_raises(self) -> None:
        with self.assertRaises(ValueError):
            cell = Cell("dungeon-room", ("fight", "fire"), "fight-fire")
            build_room_schema_for_cell(
                cell, "room.fight-fire-001", room_kind_rows=ROOM_KIND_ROWS, hazard_band=HAZARD_BAND,
                sight_band=SIGHT_BAND, disposition=DISPOSITION, tags=TAGS,
                encounter_ids_by_formation={}, event_ids_by_kind=EVENT_IDS)

    def test_required_matches_the_kindspecs_own_thirteen_fields(self) -> None:
        schema = _schema("cache", "fire")
        self.assertEqual(set(schema["required"]), {
            "roomId", "kind", "climate", "name", "flavor", "reason", "hazardBand", "sightBand",
            "dispositionBase", "encounterRef", "eventPool", "secretEligible", "tags",
        })

    def test_additionalProperties_is_false(self) -> None:
        self.assertFalse(_schema("cache", "fire")["additionalProperties"])


class BuildRoomBriefTests(unittest.TestCase):
    def test_every_real_room_kind_produces_a_nonempty_brief_with_no_crash(self) -> None:
        for kind in ROOM_KIND_ROWS:
            cell = Cell("dungeon-room", (kind, "none"), f"{kind}-none")
            self.assertTrue(build_room_brief(cell).strip())

    def test_climate_blind_and_aligned_briefs_differ(self) -> None:
        blind = build_room_brief(Cell("dungeon-room", ("boss", "none"), "boss-none"))
        aligned = build_room_brief(Cell("dungeon-room", ("fight", "fire"), "fight-fire"))
        self.assertIn("climate-blind", blind)
        self.assertIn("fire-aligned", aligned)


class RoomSystemPromptTests(unittest.TestCase):
    def test_prompt_is_nonempty(self) -> None:
        self.assertTrue(ROOM_SYSTEM_PROMPT.strip())


if __name__ == "__main__":
    unittest.main()
