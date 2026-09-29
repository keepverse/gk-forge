"""Tests for the encounter half of seedsmith.adapters.dungeon.pipelines (D1.10's real remaining
scope, 2026-09-07).

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_encounter_pipelines.py -v

`FakeCall` proves the one-call-per-slot / deterministic-posture-injection / rankOrder /
threatWindow quality-retry logic without any network dependency, matching
`test_dungeon_event_pipelines.py`'s own established shape.
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
    run_encounter_draws,
)
from seedsmith.adapters.dungeon.planner import Cell, posture_multisets_for  # noqa: E402

ZOMBOSS_IDS = frozenset({"force-pure"})
THREAT_BAND = ("nuisance", "pest", "tyrant")


def _slot() -> dict:
    # posture is NOT part of the model's own schema (see briefs._SLOT_ITEM_SCHEMA) -- a fake
    # response never carries one; run_encounter_draws injects it after the fact.
    return {"reach": "none", "targetPreference": "none", "countBand": "few"}


def _encounter(encounter_id: str, formation: str, element_spread: str, *, n_slots: int,
               rank_order: "list[int] | None" = None, boss: bool = False,
               threat_window: "tuple[str, str]" = ("nuisance", "tyrant"), name: str = "Title") -> dict:
    entry = {
        "encounterId": encounter_id, "formation": formation, "elementSpread": element_spread,
        "name": name, "reason": "because",
        "slots": [_slot() for _ in range(n_slots)],
        "threatWindow": {"floorRung": threat_window[0], "ceilRung": threat_window[1]},
        "rankOrder": rank_order if rank_order is not None else list(range(n_slots)),
        "tempo": "none", "synergyHint": "none", "affixRoll": "none",
    }
    if boss:
        entry["boss"] = {"build": "force-pure", "phasing": "none", "phaseTrigger": "none",
                          "signatureAction": "slam", "retinue": 0}
    return entry


class FakeCall:
    def __init__(self, responses: "list[dict]") -> None:
        self._responses = collections.deque(responses)
        self.calls: "list[tuple[str, str]]" = []
        self.schemas: "list[dict]" = []

    def __call__(self, system: str, user: str, *, config=None, schema=None) -> str:
        self.calls.append((system, user))
        self.schemas.append(schema)
        if not self._responses:
            raise AssertionError("FakeCall exhausted -- more calls made than responses supplied")
        return json.dumps(self._responses.popleft())


def _kwargs():
    return dict(threat_band=THREAT_BAND, zomboss_pattern_ids=ZOMBOSS_IDS)


class RunEncounterDrawsTests(unittest.TestCase):
    def test_one_call_per_slot_no_vote(self) -> None:
        cell = Cell("dungeon-encounter", ("pack", "mono"), "pack-mono")
        fake = FakeCall([_encounter("encounter.pack-mono-001", "pack", "mono", n_slots=2)])
        results = run_encounter_draws([cell], {"pack-mono": ["encounter.pack-mono-001"]}, call=fake, **_kwargs())
        self.assertEqual(len(fake.calls), 1)
        self.assertIsNotNone(results[0].entry)

    def test_an_empty_target_cell_produces_zero_results(self) -> None:
        cell = Cell("dungeon-encounter", ("pack", "mono"), "pack-mono")
        fake = FakeCall([])
        results = run_encounter_draws([cell], {"pack-mono": []}, call=fake, **_kwargs())
        self.assertEqual(results, [])

    def test_posture_is_never_offered_to_the_model_at_all(self) -> None:
        cell = Cell("dungeon-encounter", ("pack", "mono"), "pack-mono")
        fake = FakeCall([_encounter("encounter.pack-mono-001", "pack", "mono", n_slots=2)])
        run_encounter_draws([cell], {"pack-mono": ["encounter.pack-mono-001"]}, call=fake, **_kwargs())
        slot_schema_props = fake.schemas[0]["properties"]["slots"]["items"]["properties"]
        self.assertNotIn("posture", slot_schema_props)

    def test_posture_is_injected_from_the_real_deterministic_multiset_cycle(self) -> None:
        cell = Cell("dungeon-encounter", ("pack", "mono"), "pack-mono")
        fake = FakeCall([_encounter("encounter.pack-mono-001", "pack", "mono", n_slots=2)])
        results = run_encounter_draws([cell], {"pack-mono": ["encounter.pack-mono-001"]}, call=fake, **_kwargs())
        postures = tuple(s["posture"] for s in results[0].entry["slots"])
        self.assertEqual(postures, posture_multisets_for(2)[0])  # slot_index 0 -> the first shape

    def test_sibling_slots_in_the_same_cell_get_different_shapes_never_a_collision(self) -> None:
        cell = Cell("dungeon-encounter", ("pack", "mono"), "pack-mono")
        ids = ["encounter.pack-mono-001", "encounter.pack-mono-002", "encounter.pack-mono-003"]
        fake = FakeCall([_encounter(i, "pack", "mono", n_slots=2, name=f"Title {i}") for i in ids])
        results = run_encounter_draws([cell], {"pack-mono": ids}, call=fake, **_kwargs())
        shapes = [tuple(s["posture"] for s in r.entry["slots"]) for r in results]
        self.assertEqual(len(shapes), len(set(shapes)), shapes)  # all distinct
        self.assertEqual(shapes, list(posture_multisets_for(2)[:3]))

    def test_boss_single_slot_cycles_through_all_three_real_postures(self) -> None:
        cell = Cell("dungeon-encounter", ("boss", "mono"), "boss-mono")
        ids = [f"encounter.boss-mono-{i:03d}" for i in range(1, 4)]
        fake = FakeCall([_encounter(i, "boss", "mono", n_slots=1, boss=True, name=f"Title {i}") for i in ids])
        results = run_encounter_draws([cell], {"boss-mono": ids}, call=fake, **_kwargs())
        postures = {r.entry["slots"][0]["posture"] for r in results}
        self.assertEqual(postures, {"Bastion", "Finesse", "Force"})

    def test_a_name_collision_triggers_a_quality_retry(self) -> None:
        cell = Cell("dungeon-encounter", ("pack", "mono"), "pack-mono")
        ids = ["encounter.pack-mono-001", "encounter.pack-mono-002"]
        fake = FakeCall([
            _encounter(ids[0], "pack", "mono", n_slots=2, name="Swarming Skirmishers"),
            _encounter(ids[1], "pack", "mono", n_slots=2, name="Swarming Skirmishers"),
            _encounter(ids[1], "pack", "mono", n_slots=2, name="A Genuinely Different Title"),
        ])
        results = run_encounter_draws([cell], {"pack-mono": ids}, call=fake, **_kwargs())
        self.assertEqual(len(fake.calls), 3)
        self.assertEqual(results[1].entry["name"], "A Genuinely Different Title")

    def test_existing_names_seeds_the_collision_set_across_batches(self) -> None:
        cell = Cell("dungeon-encounter", ("pack", "mono"), "pack-mono")
        fake = FakeCall([
            _encounter("encounter.pack-mono-001", "pack", "mono", n_slots=2, name="An Old Title"),
            _encounter("encounter.pack-mono-001", "pack", "mono", n_slots=2, name="A Fresh Title"),
        ])
        results = run_encounter_draws([cell], {"pack-mono": ["encounter.pack-mono-001"]}, call=fake,
                                       existing_names=["An Old Title"], **_kwargs())
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(results[0].entry["name"], "A Fresh Title")

    def test_more_entries_than_the_formations_own_shape_ceiling_raises(self) -> None:
        # boss has exactly 3 real distinct posture shapes -- a 4th entry in one cell is a caller
        # error (planner.allocate_encounter_targets exists specifically to prevent this).
        cell = Cell("dungeon-encounter", ("boss", "mono"), "boss-mono")
        ids = [f"encounter.boss-mono-{i:03d}" for i in range(1, 5)]
        fake = FakeCall([_encounter(i, "boss", "mono", n_slots=1, boss=True, name=f"Title {i}") for i in ids])
        with self.assertRaises(ValueError):
            run_encounter_draws([cell], {"boss-mono": ids}, call=fake, **_kwargs())

    def test_an_invalid_rankOrder_triggers_a_quality_retry(self) -> None:
        cell = Cell("dungeon-encounter", ("pack", "mono"), "pack-mono")
        fake = FakeCall([
            _encounter("encounter.pack-mono-001", "pack", "mono", n_slots=2, rank_order=[0, 0]),  # not a permutation
            _encounter("encounter.pack-mono-001", "pack", "mono", n_slots=2, rank_order=[1, 0]),
        ])
        results = run_encounter_draws([cell], {"pack-mono": ["encounter.pack-mono-001"]}, call=fake, **_kwargs())
        self.assertEqual(len(fake.calls), 2)
        self.assertIsNotNone(results[0].entry)
        self.assertEqual(results[0].entry["rankOrder"], [1, 0])

    def test_an_inverted_threatWindow_triggers_a_quality_retry(self) -> None:
        # The real defect a live smoke test caught before any batch ran: floorRung ordinally ABOVE
        # ceilRung is satisfiable by no real anchor at all.
        cell = Cell("dungeon-encounter", ("pack", "mono"), "pack-mono")
        fake = FakeCall([
            _encounter("encounter.pack-mono-001", "pack", "mono", n_slots=2, threat_window=("tyrant", "nuisance")),
            _encounter("encounter.pack-mono-001", "pack", "mono", n_slots=2, threat_window=("nuisance", "tyrant")),
        ])
        results = run_encounter_draws([cell], {"pack-mono": ["encounter.pack-mono-001"]}, call=fake, **_kwargs())
        self.assertEqual(len(fake.calls), 2)
        self.assertIsNotNone(results[0].entry)
        self.assertEqual(results[0].entry["threatWindow"], {"floorRung": "nuisance", "ceilRung": "tyrant"})

    def test_a_threatWindow_with_floor_equal_to_ceil_is_legal_not_a_defect(self) -> None:
        cell = Cell("dungeon-encounter", ("pack", "mono"), "pack-mono")
        fake = FakeCall([_encounter("encounter.pack-mono-001", "pack", "mono", n_slots=2, threat_window=("tyrant", "tyrant"))])
        results = run_encounter_draws([cell], {"pack-mono": ["encounter.pack-mono-001"]}, call=fake, **_kwargs())
        self.assertEqual(len(fake.calls), 1)
        self.assertIsNotNone(results[0].entry)

    def test_exhausting_every_retry_leaves_the_slot_unresolved(self) -> None:
        cell = Cell("dungeon-encounter", ("pack", "mono"), "pack-mono")
        bad = _encounter("encounter.pack-mono-001", "pack", "mono", n_slots=2, rank_order=[0, 0])
        fake = FakeCall([bad] * (MAX_QUALITY_RETRY + 1))
        results = run_encounter_draws([cell], {"pack-mono": ["encounter.pack-mono-001"]}, call=fake, **_kwargs())
        self.assertEqual(len(fake.calls), MAX_QUALITY_RETRY + 1)
        self.assertIsNone(results[0].entry)
        self.assertTrue(results[0].reason.startswith("quality_retry"))

    def test_boss_formation_round_trips_with_the_boss_field(self) -> None:
        cell = Cell("dungeon-encounter", ("boss", "rainbow"), "boss-rainbow")
        fake = FakeCall([_encounter("encounter.boss-rainbow-001", "boss", "rainbow", n_slots=1, boss=True)])
        results = run_encounter_draws([cell], {"boss-rainbow": ["encounter.boss-rainbow-001"]}, call=fake, **_kwargs())
        self.assertIsNotNone(results[0].entry)
        self.assertEqual(results[0].entry["boss"]["retinue"], 0)

    def test_a_call_that_never_parses_reports_unresolved_not_a_crash(self) -> None:
        class NeverParses:
            def __call__(self, *args, **kwargs) -> str:
                return "not json"
        cell = Cell("dungeon-encounter", ("pack", "mono"), "pack-mono")
        results = run_encounter_draws([cell], {"pack-mono": ["encounter.pack-mono-001"]},
                                       call=NeverParses(), **_kwargs())
        self.assertIsNone(results[0].entry)
        self.assertEqual(results[0].reason, "insufficient_valid_samples")

    def test_never_calls_the_real_transport_when_a_stub_is_supplied(self) -> None:
        cell = Cell("dungeon-encounter", ("pack", "mono"), "pack-mono")
        fake = FakeCall([_encounter("encounter.pack-mono-001", "pack", "mono", n_slots=2)])
        results = run_encounter_draws([cell], {"pack-mono": ["encounter.pack-mono-001"]}, call=fake, **_kwargs())
        self.assertIsNotNone(results[0].entry)


if __name__ == "__main__":
    unittest.main()
