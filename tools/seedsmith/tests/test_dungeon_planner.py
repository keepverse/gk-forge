"""Tests for seedsmith.adapters.dungeon.planner (D1.9, spec-dungeon-seed-contract.md §4).

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_planner.py -v

Covers what D1.9 builds: cell enumeration from the adapter's real legality function, id minting
from a high-water mark, and (2026-09-07) the motif-brief allocator (§4 step 2) — theme-subset
selection, per-cell target allocation, and the disjoint motif/anti-motif split. The Hopcroft-Karp
feasibility check is still a stated, deliberate gap (planner.py's own module docstring) — not
tested here because it is not built here.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.dungeon import DungeonAdapter  # noqa: E402
from seedsmith.adapters.dungeon.planner import (  # noqa: E402
    EVENT_CLIMATES,
    Cell,
    IdMinter,
    allocate_encounter_targets,
    assign_event_climates,
    event_kind_of,
    allocate_even_targets,
    allocate_event_targets,
    enumerate_cells,
    motif_brief_for_slot,
    plan_ids_for_cells,
    posture_multisets_for,
    select_planning_themes,
)
from seedsmith.adapters.dungeon.registries import load_themes  # noqa: E402


class EnumerateCellsTests(unittest.TestCase):
    def test_room_cells_match_the_53_legal_shape(self) -> None:
        adapter = DungeonAdapter()
        dims = {d.id: d for d in adapter.dimensions()}
        cells = enumerate_cells(
            "dungeon-room",
            [("roomKind", dims["roomKind"].values), ("climate", dims["climate"].values)],
            adapter.legal_combinations(),
        )
        # The cell count is the product of the two CLOSED dimension vocabularies filtered by the
        # adapter's own legality rule — derived here, not pinned, so adding a room kind or climate
        # moves the expectation automatically (and the per-kind structure below still guards it).
        room_kinds = dims["roomKind"].values
        climates = dims["climate"].values
        legal = adapter.legal_combinations()
        expected = sum(
            1
            for kind in room_kinds
            for climate in climates
            if legal("roomKind", kind, "climate", climate)
        )
        self.assertEqual(len(cells), expected)
        # A climate-neutral kind appears exactly once (climate=none); a climate-bearing kind
        # appears seven times (six elements + none).
        boss_cells = [c for c in cells if c.dimension_values[0] == "boss"]
        self.assertEqual(len(boss_cells), 1)
        self.assertEqual(boss_cells[0].dimension_values[1], "none")

        fight_cells = [c for c in cells if c.dimension_values[0] == "fight"]
        self.assertEqual(len(fight_cells), 7)

    def test_single_dimension_cells(self) -> None:
        cells = enumerate_cells("dungeon-encounter", [("formation", ("pack", "party", "boss"))], lambda *_: True)
        self.assertEqual({c.cell_key for c in cells}, {"pack", "party", "boss"})

    def test_cell_keys_are_deterministic_and_sorted(self) -> None:
        adapter = DungeonAdapter()
        dims = {d.id: d for d in adapter.dimensions()}
        cells_1 = enumerate_cells("dungeon-room", [("roomKind", dims["roomKind"].values), ("climate", dims["climate"].values)], adapter.legal_combinations())
        cells_2 = enumerate_cells("dungeon-room", [("roomKind", dims["roomKind"].values), ("climate", dims["climate"].values)], adapter.legal_combinations())
        self.assertEqual([c.cell_key for c in cells_1], [c.cell_key for c in cells_2])


class IdMinterTests(unittest.TestCase):
    def test_ids_are_sequential_per_namespace_and_cell(self) -> None:
        minter = IdMinter()
        self.assertEqual(minter.next_id("room", "cache-ice"), "room.cache-ice-001")
        self.assertEqual(minter.next_id("room", "cache-ice"), "room.cache-ice-002")
        self.assertEqual(minter.next_id("room", "fight-fire"), "room.fight-fire-001")  # separate cell, own sequence

    def test_ids_continue_from_a_supplied_high_water_mark(self) -> None:
        # The exact incident this exists to prevent: a second run must not restart at 1 and
        # collide with ids a prior run already minted for this cell.
        minter = IdMinter(high_water_marks={("room", "cache-ice"): 7})
        self.assertEqual(minter.next_id("room", "cache-ice"), "room.cache-ice-008")

    def test_high_water_marks_round_trip(self) -> None:
        minter = IdMinter()
        minter.next_id("room", "cache-ice")
        minter.next_id("room", "cache-ice")
        marks = minter.high_water_marks()
        self.assertEqual(marks[("room", "cache-ice")], 2)

        resumed = IdMinter(high_water_marks=marks)
        self.assertEqual(resumed.next_id("room", "cache-ice"), "room.cache-ice-003")


class PlanIdsForCellsTests(unittest.TestCase):
    def test_plan_ids_for_cells_mints_the_requested_count_per_cell(self) -> None:
        cells = [Cell("dungeon-room", ("cache", "ice"), "cache-ice"), Cell("dungeon-room", ("fight", "fire"), "fight-fire")]
        minter = IdMinter()
        result = plan_ids_for_cells(cells, "room", {"cache-ice": 2, "fight-fire": 1}, minter)
        self.assertEqual(result["cache-ice"], ["room.cache-ice-001", "room.cache-ice-002"])
        self.assertEqual(result["fight-fire"], ["room.fight-fire-001"])

    def test_a_cell_with_zero_requested_count_mints_nothing(self) -> None:
        cells = [Cell("dungeon-room", ("shrine", "none"), "shrine-none")]
        result = plan_ids_for_cells(cells, "room", {}, IdMinter())
        self.assertEqual(result["shrine-none"], [])


class SelectPlanningThemesTests(unittest.TestCase):
    def test_returns_eight_ids_by_default_two_per_real_rarity_band(self) -> None:
        themes = load_themes()
        chosen = select_planning_themes(themes)
        self.assertEqual(len(chosen), 8)
        self.assertEqual(len(set(chosen)), 8)  # no duplicates
        rarities = sorted({themes[t]["rarity"] for t in chosen})
        self.assertEqual(rarities, ["common", "epic", "legendary", "rare"])

    def test_deterministic_two_calls_agree(self) -> None:
        themes = load_themes()
        self.assertEqual(select_planning_themes(themes), select_planning_themes(themes))

    def test_never_selects_a_retired_theme(self) -> None:
        fixture = {
            "creature.a": {"rarity": "common", "retired": True, "motifs": ["x", "y"], "antiMotifs": []},
            "creature.b": {"rarity": "common", "retired": False, "motifs": ["x", "y"], "antiMotifs": []},
        }
        chosen = select_planning_themes(fixture, per_rarity=2)
        self.assertEqual(chosen, ("creature.b",))

    def test_ignores_source_only_fallback_rarities(self) -> None:
        fixture = {
            "creature.common": {"rarity": "common", "retired": False, "motifs": ["x", "y"],
                             "antiMotifs": []},
            "creature.fallback": {"rarity": "almanac", "retired": False,
                               "motifs": ["x", "y"], "antiMotifs": []},
        }
        self.assertEqual(select_planning_themes(fixture, per_rarity=2), ("creature.common",))

    def test_picks_alphabetically_first_within_a_band_not_by_richness(self) -> None:
        # A theme with a longer combined motif+antiMotif list must NOT win over an
        # alphabetically-earlier one -- the monoculture failure mode this function exists to avoid.
        fixture = {
            "creature.z-rich": {"rarity": "common", "retired": False,
                              "motifs": ["a", "b", "c", "d", "e"], "antiMotifs": ["f", "g", "h"]},
            "creature.a-plain": {"rarity": "common", "retired": False, "motifs": ["x", "y"], "antiMotifs": []},
        }
        chosen = select_planning_themes(fixture, per_rarity=1)
        self.assertEqual(chosen, ("creature.a-plain",))


class AllocateEventTargetsTests(unittest.TestCase):
    def test_first_two_themes_get_target_two_for_every_kind(self) -> None:
        themes = ("t1", "t2", "t3", "t4")
        kinds = ("curio", "trap")
        targets = allocate_event_targets(themes, kinds, doubled_per_kind=2)
        self.assertEqual(targets[("curio", "t1")], 2)
        self.assertEqual(targets[("curio", "t2")], 2)
        self.assertEqual(targets[("curio", "t3")], 1)
        self.assertEqual(targets[("trap", "t1")], 2)
        self.assertEqual(targets[("trap", "t4")], 1)

    def test_real_defaults_sum_to_the_real_firstShip_budget_of_sixty(self) -> None:
        themes = tuple(f"t{i}" for i in range(8))
        kinds = ("curio", "encounter-event", "shrine", "trap", "bargain", "story")
        targets = allocate_event_targets(themes, kinds)
        # Formula, not a literal (population-pin SE3.5, 2026-09-20): every (kind, theme) pair this
        # test itself constructed above.
        self.assertEqual(len(kinds) * len(themes), len(targets))
        self.assertEqual(sum(targets.values()), 60)  # budget.v1.json's own dungeon-event firstShip

    def test_every_target_is_one_or_two_never_zero_or_more(self) -> None:
        themes = tuple(f"t{i}" for i in range(8))
        kinds = ("curio",)
        targets = allocate_event_targets(themes, kinds)
        self.assertEqual(set(targets.values()), {1, 2})


class MotifBriefForSlotTests(unittest.TestCase):
    def test_a_single_slot_gets_the_whole_theme_untouched(self) -> None:
        theme_row = {"motifs": ["a", "b", "c"], "antiMotifs": ["z"]}
        brief = motif_brief_for_slot(theme_row, 0, 1)
        self.assertEqual(brief["motifs"], ["a", "b", "c"])
        self.assertEqual(brief["antiMotifs"], ["z"])

    def test_two_slots_split_disjoint_and_cross_list_as_anti(self) -> None:
        theme_row = {"motifs": ["a", "b", "c", "d"], "antiMotifs": ["z"]}
        slot0 = motif_brief_for_slot(theme_row, 0, 2)
        slot1 = motif_brief_for_slot(theme_row, 1, 2)
        self.assertEqual(slot0["motifs"], ["a", "c"])
        self.assertEqual(slot1["motifs"], ["b", "d"])
        self.assertEqual(set(slot0["motifs"]) & set(slot1["motifs"]), set())  # disjoint
        self.assertEqual(slot0["antiMotifs"], ["z", "b", "d"])  # own anti + sibling's motifs
        self.assertEqual(slot1["antiMotifs"], ["z", "a", "c"])

    def test_an_odd_length_motif_list_still_splits_with_neither_half_empty(self) -> None:
        theme_row = {"motifs": ["a", "b", "c"], "antiMotifs": []}
        slot0 = motif_brief_for_slot(theme_row, 0, 2)
        slot1 = motif_brief_for_slot(theme_row, 1, 2)
        self.assertTrue(slot0["motifs"])
        self.assertTrue(slot1["motifs"])
        self.assertEqual(set(slot0["motifs"]) | set(slot1["motifs"]), {"a", "b", "c"})

    def test_every_real_selected_theme_has_at_least_two_motifs(self) -> None:
        # The precondition motif_brief_for_slot's own 2-slot path depends on -- proven against the
        # real registry, not assumed, so a future thin theme entering the planner-fixed subset
        # would fail this test before it could ever produce an empty half in production.
        themes = load_themes()
        for theme_id in select_planning_themes(themes):
            self.assertGreaterEqual(len(themes[theme_id]["motifs"]), 2, theme_id)

    def test_more_than_two_slots_is_out_of_scope_today(self) -> None:
        with self.assertRaises(NotImplementedError):
            motif_brief_for_slot({"motifs": ["a", "b", "c"], "antiMotifs": []}, 0, 3)


class AllocateEvenTargetsTests(unittest.TestCase):
    def test_real_encounter_budget_nine_cells_forty_total(self) -> None:
        cells = [f"c{i}" for i in range(9)]
        targets = allocate_even_targets(cells, 40)
        self.assertEqual(sum(targets.values()), 40)
        self.assertEqual(set(targets), set(cells))
        self.assertEqual(set(targets.values()), {4, 5})  # 40/9 = 4 remainder 4

    def test_remainder_goes_to_the_alphabetically_first_cells_not_iteration_order(self) -> None:
        cells = ["z", "a", "m"]
        targets = allocate_even_targets(cells, 4)  # base 1, remainder 1 -> "a" gets the extra
        self.assertEqual(targets["a"], 2)
        self.assertEqual(targets["z"], 1)
        self.assertEqual(targets["m"], 1)

    def test_empty_cell_list_returns_empty(self) -> None:
        self.assertEqual(allocate_even_targets([], 40), {})

    def test_evenly_divisible_total_has_no_remainder_variance(self) -> None:
        targets = allocate_even_targets(["a", "b", "c", "d"], 8)
        self.assertEqual(set(targets.values()), {2})


class PostureMultisetsForTests(unittest.TestCase):
    def test_real_ceilings_boss_pack_party(self) -> None:
        self.assertEqual(len(posture_multisets_for(1)), 3)
        self.assertEqual(len(posture_multisets_for(2)), 6)
        self.assertEqual(len(posture_multisets_for(3)), 10)

    def test_order_independent_pairs_count_as_one_shape(self) -> None:
        combos = posture_multisets_for(2)
        # every element is already sorted (combinations_with_replacement's own contract) -- a
        # (Finesse, Bastion)-shaped entry maps to the SAME tuple as (Bastion, Finesse) once its own
        # slots are sorted, so this set has no reversed duplicate.
        self.assertEqual(len(combos), len(set(combos)))

    def test_every_real_posture_appears(self) -> None:
        singles = {c[0] for c in posture_multisets_for(1)}
        self.assertEqual(singles, {"Bastion", "Finesse", "Force"})


class AllocateEncounterTargetsTests(unittest.TestCase):
    SLOT_COUNT = {"pack": 2, "party": 3, "boss": 1}

    def _cells(self) -> "list[Cell]":
        return [Cell("dungeon-encounter", (f, s), f"{f}-{s}")
                for f in ("pack", "party", "boss") for s in ("mono", "dual", "rainbow")]

    def test_real_budget_forty_across_nine_cells_sums_correctly(self) -> None:
        result = allocate_encounter_targets(self._cells(), self.SLOT_COUNT, 40)
        self.assertEqual(sum(result.values()), 40)
        self.assertEqual(len(result), 9)

    def test_no_boss_cell_ever_exceeds_its_own_real_ceiling_of_three(self) -> None:
        result = allocate_encounter_targets(self._cells(), self.SLOT_COUNT, 40)
        for key, count in result.items():
            if key.startswith("boss-"):
                self.assertLessEqual(count, 3, key)

    def test_no_pack_cell_ever_exceeds_its_own_real_ceiling_of_six(self) -> None:
        result = allocate_encounter_targets(self._cells(), self.SLOT_COUNT, 40)
        for key, count in result.items():
            if key.startswith("pack-"):
                self.assertLessEqual(count, 6, key)

    def test_a_total_within_every_ceiling_places_everything(self) -> None:
        result = allocate_encounter_targets(self._cells(), self.SLOT_COUNT, 9)  # 1 per cell, trivial
        self.assertEqual(sum(result.values()), 9)

    def test_a_total_exceeding_the_combined_ceiling_stops_honestly_short(self) -> None:
        # combined ceiling = 3*3 + 3*6 + 3*10 = 57 -- asking for 100 cannot be placed honestly
        result = allocate_encounter_targets(self._cells(), self.SLOT_COUNT, 100)
        self.assertEqual(sum(result.values()), 57)
        for key, count in result.items():
            formation = key.split("-")[0]
            ceiling = len(posture_multisets_for(self.SLOT_COUNT[formation]))
            self.assertEqual(count, ceiling)


if __name__ == "__main__":
    unittest.main()


class AssignEventClimatesTests(unittest.TestCase):
    """NS11 (spec-dungeon-generator-repair.md §5) — the climate is PLANNED, inside today's cells."""

    def test_climate_rotation_covers_all_seven_per_kind(self) -> None:
        ids = {"curio-creature.a": [f"event.curio-creature.a-{i:03d}" for i in range(1, 8)]}
        assigned = assign_event_climates(ids)
        self.assertEqual(sorted(assigned.values()), sorted(EVENT_CLIMATES))
        self.assertEqual(len(set(assigned.values())), 7)
        # Deterministic: same input, same assignment, no clock and no RNG.
        self.assertEqual(assigned, assign_event_climates(ids))

    def test_each_kind_rotates_from_the_start_independently(self) -> None:
        ids = {"curio-creature.a": ["event.curio-creature.a-001"],
               "trap-creature.a": ["event.trap-creature.a-001"]}
        assigned = assign_event_climates(ids)
        self.assertEqual(assigned["event.curio-creature.a-001"], EVENT_CLIMATES[0])
        self.assertEqual(assigned["event.trap-creature.a-001"], EVENT_CLIMATES[0])

    def test_a_hyphenated_kind_is_placed_by_longest_prefix(self) -> None:
        # `encounter-event` contains a hyphen: splitting on the first one would name kind `encounter`.
        assigned = assign_event_climates(
            {"encounter-event-creature.a": ["event.encounter-event-creature.a-001"]})
        self.assertEqual(assigned["event.encounter-event-creature.a-001"], EVENT_CLIMATES[0])
        self.assertEqual(event_kind_of("encounter-event-creature.a"), "encounter-event")

    def test_a_cell_key_naming_no_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            assign_event_climates({"not-a-kind-x": ["event.not-a-kind-x-001"]})
