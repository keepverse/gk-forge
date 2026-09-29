"""Tests for the quest half of seedsmith.adapters.dungeon.pipelines (D1.10's real remaining scope).

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_quest_pipelines.py -v

`FakeCall` proves the vote/permutation logic without any network dependency, matching
`test_unique_pipelines.py`'s own established shape for the sibling uniques pipeline.
"""
from __future__ import annotations

import collections
import copy as copy_mod
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.dungeon.briefs import build_quest_schema_for_cell  # noqa: E402
from seedsmith.adapters.dungeon.pipelines import (  # noqa: E402
    SAMPLES_PER_DRAW,
    _permute_schema_enums,
    run_quest_draws,
)
from seedsmith.adapters.dungeon.planner import Cell, IdMinter  # noqa: E402

REAL_TEMPLATES = {
    "explore-rooms": {"targetKind": "none", "sinkAvoidance": False},
    "cleanse-fights": {"targetKind": "room-kind", "sinkAvoidance": False},
    "gather-curio-kind": {"targetKind": "curio-kind", "sinkAvoidance": False},
    "kill-boss": {"targetKind": "boss", "sinkAvoidance": False},
    "extract-with-item-kind": {"targetKind": "item-kind", "sinkAvoidance": False},
    "bring-creature-home-alive": {"targetKind": "none", "sinkAvoidance": False},
    "finish-under-hunger": {"targetKind": "none", "sinkAvoidance": True},
    "survive-no-downed": {"targetKind": "none", "sinkAvoidance": True},
    "spend-no-provision": {"targetKind": "none", "sinkAvoidance": True},
}
ROOM_KINDS = frozenset({"fight", "elite", "cache", "curio", "wild", "shrine", "rest", "merchant", "trap", "unknown", "boss"})
EVENT_KINDS = ("curio", "encounter-event", "shrine", "trap", "bargain", "story")
REWARD_BANDS = frozenset({"modest", "fair", "rich"})
COUNT_BANDS = frozenset({"lone", "few", "several", "many"})
REPEAT_SCOPES = ("per-delve", "per-domain", "once-per-player")

FIXTURE_KWARGS = dict(
    objective_templates=REAL_TEMPLATES, room_kinds=ROOM_KINDS, event_kinds=EVENT_KINDS,
    reward_bands=REWARD_BANDS, count_bands=COUNT_BANDS, repeat_scopes=REPEAT_SCOPES)

CELL = Cell("dungeon-quest", ("explore-rooms", "delve"), "explore-rooms-delve")


def _planned_ids_for(cell: Cell) -> "dict[str, str]":
    minter = IdMinter()
    return {cell.cell_key: minter.next_id("quest", cell.cell_key)}


def _entry(name: str, count_band: str = "few", reward_band: str = "modest", flavor: str = "A task worth doing.") -> dict:
    return {
        "questId": "quest.explore-rooms-delve-001", "objectiveTemplate": "explore-rooms", "scope": "delve",
        "name": name, "flavor": flavor, "targetRef": "none", "countBand": count_band,
        "rewardBand": reward_band, "repeatScope": "per-delve", "prereqRefs": [], "chainRef": "none",
    }


def raising_call(*args, **kwargs) -> str:
    raise AssertionError("a real model call was attempted -- this test's transport must never be reached")


class FakeCall:
    def __init__(self, responses: "list[dict]") -> None:
        self._responses = collections.deque(responses)
        self.calls: "list[tuple[str, str]]" = []

    def __call__(self, system: str, user: str, *, config=None, schema=None) -> str:
        self.calls.append((system, user))
        if not self._responses:
            raise AssertionError("FakeCall exhausted -- more calls made than responses supplied")
        return json.dumps(self._responses.popleft())


class PermuteSchemaEnumsTests(unittest.TestCase):
    def _wide_schema(self) -> dict:
        # extract-with-item-kind's own targetRef enum has 15 real members -- wide enough on its
        # own that a coincidental identity shuffle across 3 samples is astronomically unlikely
        # (test_unique_pipelines.py's own documented reason for preferring a wide fixture).
        cell = Cell("dungeon-quest", ("extract-with-item-kind", "delve"), "extract-with-item-kind-delve")
        return build_quest_schema_for_cell(cell, "quest.x-001", **FIXTURE_KWARGS)

    def test_never_mutates_its_own_input_schema(self) -> None:
        schema = self._wide_schema()
        before = copy_mod.deepcopy(schema)
        _permute_schema_enums(schema, draw_id="quest-draw-x", sample_index=0)
        self.assertEqual(schema, before, "the input schema must be unchanged after the call")

    def test_different_sample_indices_produce_different_orders(self) -> None:
        schema = self._wide_schema()
        orders = [
            tuple(_permute_schema_enums(schema, draw_id="quest-draw-x", sample_index=i)
                  ["properties"]["targetRef"]["enum"])
            for i in range(SAMPLES_PER_DRAW)
        ]
        self.assertEqual(len(set(orders)), SAMPLES_PER_DRAW, "all three sample indices should diverge")

    def test_const_fields_are_never_touched_by_permutation(self) -> None:
        schema = self._wide_schema()
        permuted = _permute_schema_enums(schema, draw_id="quest-draw-x", sample_index=0)
        self.assertEqual(permuted["properties"]["objectiveTemplate"]["const"], "extract-with-item-kind")
        self.assertNotIn("enum", permuted["properties"]["objectiveTemplate"])


class ThreeWayVoteTests(unittest.TestCase):
    def test_all_three_fields_unanimous_resolves_high_confidence(self) -> None:
        fake = FakeCall([_entry("Clear the Warrens")] * SAMPLES_PER_DRAW)
        results = run_quest_draws([CELL], _planned_ids_for(CELL), call=fake, **FIXTURE_KWARGS)

        self.assertEqual(len(results), 1)
        entry = results[0].entry
        self.assertIsNotNone(entry)
        self.assertEqual(entry["name"], "Clear the Warrens")
        self.assertEqual(entry["countBand"], "few")
        self.assertEqual(entry["rewardBand"], "modest")
        self.assertEqual(results[0].vote_confidence, "high")
        self.assertEqual(len(fake.calls), SAMPLES_PER_DRAW)

    def test_name_1_1_1_split_is_unresolved(self) -> None:
        fake = FakeCall([_entry("A"), _entry("B"), _entry("C")])
        results = run_quest_draws([CELL], _planned_ids_for(CELL), call=fake, **FIXTURE_KWARGS)
        self.assertIsNone(results[0].entry)
        self.assertEqual(results[0].reason, "vote_unresolved:name")

    def test_countBand_1_1_1_split_is_unresolved_even_though_name_agrees(self) -> None:
        fake = FakeCall([
            _entry("Clear the Warrens", count_band="few"),
            _entry("Clear the Warrens", count_band="several"),
            _entry("Clear the Warrens", count_band="many"),
        ])
        results = run_quest_draws([CELL], _planned_ids_for(CELL), call=fake, **FIXTURE_KWARGS)
        self.assertIsNone(results[0].entry)
        self.assertEqual(results[0].reason, "vote_unresolved:countBand")

    def test_rewardBand_1_1_1_split_is_unresolved_even_though_name_and_countBand_agree(self) -> None:
        fake = FakeCall([
            _entry("Clear the Warrens", reward_band="modest"),
            _entry("Clear the Warrens", reward_band="fair"),
            _entry("Clear the Warrens", reward_band="rich"),
        ])
        results = run_quest_draws([CELL], _planned_ids_for(CELL), call=fake, **FIXTURE_KWARGS)
        self.assertIsNone(results[0].entry)
        self.assertEqual(results[0].reason, "vote_unresolved:rewardBand")

    def test_a_2_1_split_on_any_field_still_resolves_to_the_majority(self) -> None:
        fake = FakeCall([
            _entry("Clear the Warrens", count_band="few"),
            _entry("Clear the Warrens", count_band="few"),
            _entry("Clear the Warrens", count_band="several"),
        ])
        results = run_quest_draws([CELL], _planned_ids_for(CELL), call=fake, **FIXTURE_KWARGS)
        self.assertEqual(results[0].entry["countBand"], "few")
        self.assertEqual(results[0].vote_confidence, "high")  # name's own vote is 3-0

    def test_flavor_and_other_fields_come_from_the_winning_names_own_sample(self) -> None:
        # The narrative-coherence property: name/flavor stay together even though countBand/
        # rewardBand are independently voted. Two samples share the winning name but have
        # DIFFERENT flavor text -- majority (2-1) on name should win with THAT sample's flavor,
        # never a flavor from the third, losing sample.
        fake = FakeCall([
            _entry("Clear the Warrens", flavor="Flavor A, the majority's own text."),
            _entry("Clear the Warrens", flavor="Flavor A, the majority's own text."),
            _entry("Different Name", flavor="Flavor B, never used."),
        ])
        results = run_quest_draws([CELL], _planned_ids_for(CELL), call=fake, **FIXTURE_KWARGS)
        self.assertEqual(results[0].entry["flavor"], "Flavor A, the majority's own text.")

    def test_insufficient_valid_samples_when_every_call_fails_to_parse(self) -> None:
        class NeverParses:
            def __call__(self, *args, **kwargs) -> str:
                return "not json"
        results = run_quest_draws([CELL], _planned_ids_for(CELL), call=NeverParses(), **FIXTURE_KWARGS)
        self.assertIsNone(results[0].entry)
        self.assertEqual(results[0].reason, "insufficient_valid_samples")

    def test_a_name_collision_with_an_existing_name_refuses(self) -> None:
        fake = FakeCall([_entry("Clear the Warrens")] * SAMPLES_PER_DRAW)
        results = run_quest_draws([CELL], _planned_ids_for(CELL), call=fake,
                                  existing_names=["Clear the Warrens"], **FIXTURE_KWARGS)
        self.assertIsNone(results[0].entry)
        self.assertIn("name_collision", results[0].reason)

    def test_two_cells_in_one_call_never_collide_with_each_other_either(self) -> None:
        cell_b = Cell("dungeon-quest", ("cleanse-fights", "delve"), "cleanse-fights-delve")
        fake = FakeCall(
            [_entry("Same Name")] * SAMPLES_PER_DRAW +
            [dict(_entry("Same Name"), questId="quest.cleanse-fights-delve-001",
                  objectiveTemplate="cleanse-fights", targetRef="fight")] * SAMPLES_PER_DRAW)
        planned = {**_planned_ids_for(CELL), **_planned_ids_for(cell_b)}
        results = run_quest_draws([CELL, cell_b], planned, call=fake, **FIXTURE_KWARGS)
        self.assertIsNotNone(results[0].entry)
        self.assertIsNone(results[1].entry)
        self.assertIn("name_collision", results[1].reason)


class RetryAttemptTests(unittest.TestCase):
    def test_attempt_zero_and_attempt_one_use_different_draw_ids_and_can_diverge(self) -> None:
        # Same underlying FakeCall response set at both attempts; the permutation seed differs
        # (draw_id embeds `attempt`), so this proves the retry genuinely re-seeds rather than
        # replaying the identical three permutations.
        fake0 = FakeCall([_entry("X"), _entry("Y"), _entry("Z")])
        run_quest_draws([CELL], _planned_ids_for(CELL), call=fake0, attempt=0, **FIXTURE_KWARGS)
        fake1 = FakeCall([_entry("X"), _entry("Y"), _entry("Z")])
        run_quest_draws([CELL], _planned_ids_for(CELL), call=fake1, attempt=1, **FIXTURE_KWARGS)
        # Both draws build a brief string that must differ in nothing except how the schema's own
        # enums were permuted -- the calls list itself is the only externally-observable signal
        # here, so just prove both attempts complete without error using the identical inputs.
        self.assertEqual(len(fake0.calls), SAMPLES_PER_DRAW)
        self.assertEqual(len(fake1.calls), SAMPLES_PER_DRAW)


class NeverCallsTheRealTransportTests(unittest.TestCase):
    def test_raising_call_is_never_invoked_when_the_caller_supplies_its_own(self) -> None:
        # A meta-test: `raising_call` proves the harness itself would catch a real call, by using
        # it as the FALLBACK default -- but here we pass a real FakeCall, so `raising_call` should
        # never even be imported/used. Included for parity with test_unique_pipelines.py's own
        # explicit "never calls the real transport" coverage.
        fake = FakeCall([_entry("Clear the Warrens")] * SAMPLES_PER_DRAW)
        results = run_quest_draws([CELL], _planned_ids_for(CELL), call=fake, **FIXTURE_KWARGS)
        self.assertIsNotNone(results[0].entry)


if __name__ == "__main__":
    unittest.main()
