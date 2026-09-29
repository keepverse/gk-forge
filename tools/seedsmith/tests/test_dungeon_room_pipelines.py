"""Tests for the room half of seedsmith.adapters.dungeon.pipelines (D1.10's real remaining scope,
2026-09-07).

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_room_pipelines.py -v

`FakeCall` proves the one-call-per-slot / name-collision retry logic without any network
dependency, matching `test_dungeon_event_pipelines.py`'s own established shape.
"""
from __future__ import annotations

import collections
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.dungeon.pipelines import (  # noqa: E402
    MAX_QUALITY_RETRY,
    run_room_draws,
)
from seedsmith.adapters.dungeon.planner import Cell  # noqa: E402

ROOM_KIND_ROWS = {"cache": {"secretEligible": True}, "curio": {"secretEligible": False}, "wild": {"secretEligible": False}}
HAZARD_BAND = frozenset({"none", "light", "heavy"})
SIGHT_BAND = frozenset({"dim", "lit", "scouting"})
DISPOSITION = frozenset({"eager", "open", "wary", "hostile"})
TAGS = frozenset({"tag1"})
ENCOUNTER_IDS = {"pack": frozenset({"encounter.pack-a"})}
EVENT_IDS = {"curio": frozenset({"event.curio-a"})}


def _room(room_id: str, kind: str, climate: str, *, name: str = "Title") -> dict:
    return {
        "roomId": room_id, "kind": kind, "climate": climate, "name": name, "flavor": "a scene",
        "reason": "because", "hazardBand": "light", "sightBand": "dim", "dispositionBase": "none",
        "encounterRef": "none", "eventPool": ["event.curio-a"] if kind == "curio" else [],
        "secretEligible": "no", "tags": [],
    }


class FakeCall:
    def __init__(self, responses: "list[dict]") -> None:
        self._responses = collections.deque(responses)
        self.calls: "list[tuple[str, str]]" = []

    def __call__(self, system: str, user: str, *, config=None, schema=None) -> str:
        self.calls.append((system, user))
        if not self._responses:
            raise AssertionError("FakeCall exhausted -- more calls made than responses supplied")
        return json.dumps(self._responses.popleft())


def _kwargs():
    return dict(room_kind_rows=ROOM_KIND_ROWS, hazard_band=HAZARD_BAND, sight_band=SIGHT_BAND,
                disposition=DISPOSITION, tags=TAGS, encounter_ids_by_formation=ENCOUNTER_IDS,
                event_ids_by_kind=EVENT_IDS)


class RunRoomDrawsTests(unittest.TestCase):
    def test_one_call_per_slot_no_vote(self) -> None:
        cell = Cell("dungeon-room", ("curio", "fire"), "curio-fire")
        fake = FakeCall([_room("room.curio-fire-001", "curio", "fire")])
        results = run_room_draws([cell], {"curio-fire": ["room.curio-fire-001"]}, call=fake, **_kwargs())
        self.assertEqual(len(fake.calls), 1)
        self.assertIsNotNone(results[0].entry)

    def test_a_cell_with_two_slots_makes_two_calls_each_with_the_slots_own_roomId(self) -> None:
        cell = Cell("dungeon-room", ("curio", "fire"), "curio-fire")
        ids = ["room.curio-fire-001", "room.curio-fire-002"]
        fake = FakeCall([
            _room(ids[0], "curio", "fire", name="Title One"),
            _room(ids[1], "curio", "fire", name="Title Two"),
        ])
        results = run_room_draws([cell], {"curio-fire": ids}, call=fake, **_kwargs())
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(results[0].entry["roomId"], ids[0])
        self.assertEqual(results[1].entry["roomId"], ids[1])

    def test_an_empty_target_cell_produces_zero_results(self) -> None:
        cell = Cell("dungeon-room", ("curio", "fire"), "curio-fire")
        fake = FakeCall([])
        results = run_room_draws([cell], {"curio-fire": []}, call=fake, **_kwargs())
        self.assertEqual(results, [])

    def test_a_name_collision_triggers_a_quality_retry(self) -> None:
        cell = Cell("dungeon-room", ("curio", "fire"), "curio-fire")
        ids = ["room.curio-fire-001", "room.curio-fire-002"]
        fake = FakeCall([
            _room(ids[0], "curio", "fire", name="The Same Room"),
            _room(ids[1], "curio", "fire", name="The Same Room"),
            _room(ids[1], "curio", "fire", name="A Genuinely Different Room"),
        ])
        results = run_room_draws([cell], {"curio-fire": ids}, call=fake, **_kwargs())
        self.assertEqual(len(fake.calls), 3)
        self.assertEqual(results[1].entry["name"], "A Genuinely Different Room")

    def test_existing_names_seeds_the_collision_set_across_batches(self) -> None:
        cell = Cell("dungeon-room", ("curio", "fire"), "curio-fire")
        fake = FakeCall([
            _room("room.curio-fire-001", "curio", "fire", name="An Old Title"),
            _room("room.curio-fire-001", "curio", "fire", name="A Fresh Title"),
        ])
        results = run_room_draws([cell], {"curio-fire": ["room.curio-fire-001"]}, call=fake,
                                  existing_names=["An Old Title"], **_kwargs())
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(results[0].entry["name"], "A Fresh Title")

    def test_exhausting_every_retry_leaves_the_slot_unresolved(self) -> None:
        cell = Cell("dungeon-room", ("curio", "fire"), "curio-fire")
        bad = _room("room.curio-fire-001", "curio", "fire", name="Dup")
        fake = FakeCall([bad] * (MAX_QUALITY_RETRY + 1), )
        # seed the collision directly so every attempt collides
        results = run_room_draws([cell], {"curio-fire": ["room.curio-fire-001"]}, call=fake,
                                  existing_names=["Dup"], **_kwargs())
        self.assertEqual(len(fake.calls), MAX_QUALITY_RETRY + 1)
        self.assertIsNone(results[0].entry)
        self.assertTrue(results[0].reason.startswith("quality_retry"))

    def test_a_call_that_never_parses_reports_unresolved_not_a_crash(self) -> None:
        class NeverParses:
            def __call__(self, *args, **kwargs) -> str:
                return "not json"
        cell = Cell("dungeon-room", ("curio", "fire"), "curio-fire")
        results = run_room_draws([cell], {"curio-fire": ["room.curio-fire-001"]}, call=NeverParses(), **_kwargs())
        self.assertIsNone(results[0].entry)
        self.assertEqual(results[0].reason, "insufficient_valid_samples")

    def test_a_structurally_impossible_cell_raises_not_a_silent_unresolved(self) -> None:
        # wild with no real story event -- build_room_schema_for_cell's own ValueError, deliberately
        # let through rather than caught: the CALLER should never have included this cell.
        cell = Cell("dungeon-room", ("wild", "fire"), "wild-fire")
        fake = FakeCall([])
        with self.assertRaises(ValueError):
            run_room_draws([cell], {"wild-fire": ["room.wild-fire-001"]}, call=fake, **_kwargs())

    def test_never_calls_the_real_transport_when_a_stub_is_supplied(self) -> None:
        cell = Cell("dungeon-room", ("curio", "fire"), "curio-fire")
        fake = FakeCall([_room("room.curio-fire-001", "curio", "fire")])
        results = run_room_draws([cell], {"curio-fire": ["room.curio-fire-001"]}, call=fake, **_kwargs())
        self.assertIsNotNone(results[0].entry)


if __name__ == "__main__":
    unittest.main()
