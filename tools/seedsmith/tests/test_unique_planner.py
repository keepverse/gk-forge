"""Tests for seedsmith.adapters.items.uniques.planner (D4.29, spec-unique-pipeline.md "Metrics").

    python -m pytest gk-forge/tools/seedsmith/tests/test_unique_planner.py -v

Covers the frame x axis x band grid (2x5x3=30) and id minting from a high-water mark. Model-free
end to end -- nothing here imports `llm_caller` or takes a `call` parameter.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.uniques.planner import (  # noqa: E402
    AXES,
    BANDS,
    FRAMES,
    Cell,
    IdMinter,
    enumerate_cells,
    plan_ids_for_cells,
)


class EnumerateCellsTests(unittest.TestCase):
    def test_the_grid_is_exactly_30_cells(self) -> None:
        # spec "Metrics": "frame 2 x axis 5 x band 3 = 30 cells".
        self.assertEqual(len(FRAMES), 2)
        self.assertEqual(len(AXES), 5)
        self.assertEqual(len(BANDS), 3)
        cells = enumerate_cells()
        self.assertEqual(len(cells), 30)

    def test_every_cell_is_unique_and_covers_the_full_cartesian_product(self) -> None:
        cells = enumerate_cells()
        seen = {(c.frame, c.axis, c.band) for c in cells}
        self.assertEqual(len(seen), 30)
        for frame in FRAMES:
            for axis in AXES:
                for band in BANDS:
                    self.assertIn((frame, axis, band), seen)

    def test_cell_key_is_the_joined_dimensions(self) -> None:
        cells = enumerate_cells()
        plant_offense_firstseed = next(c for c in cells if (c.frame, c.axis, c.band) == ("plant", "offense", "firstseed"))
        self.assertEqual(plant_offense_firstseed.cell_key, "plant-offense-firstseed")

    def test_hybrid_frame_is_deliberately_excluded(self) -> None:
        self.assertNotIn("hybrid", FRAMES)
        cells = enumerate_cells()
        self.assertFalse(any(c.frame == "hybrid" for c in cells))

    def test_cells_are_deterministic_and_sorted_across_calls(self) -> None:
        cells_1 = enumerate_cells()
        cells_2 = enumerate_cells()
        self.assertEqual([c.cell_key for c in cells_1], [c.cell_key for c in cells_2])
        self.assertEqual([c.cell_key for c in cells_1], sorted(c.cell_key for c in cells_1))


class IdMinterTests(unittest.TestCase):
    def test_ids_are_sequential_per_cell(self) -> None:
        minter = IdMinter()
        self.assertEqual(minter.next_id("plant-offense-firstseed"), "unique.plant-offense-firstseed-001")
        self.assertEqual(minter.next_id("plant-offense-firstseed"), "unique.plant-offense-firstseed-002")
        self.assertEqual(minter.next_id("plant-control-sunwoven"), "unique.plant-control-sunwoven-001")

    def test_ids_continue_from_a_supplied_high_water_mark(self) -> None:
        minter = IdMinter(high_water_marks={"plant-offense-firstseed": 7})
        self.assertEqual(minter.next_id("plant-offense-firstseed"), "unique.plant-offense-firstseed-008")

    def test_high_water_marks_round_trip(self) -> None:
        minter = IdMinter()
        minter.next_id("plant-offense-firstseed")
        minter.next_id("plant-offense-firstseed")
        marks = minter.high_water_marks()
        self.assertEqual(marks["plant-offense-firstseed"], 2)
        resumed = IdMinter(high_water_marks=marks)
        self.assertEqual(resumed.next_id("plant-offense-firstseed"), "unique.plant-offense-firstseed-003")


class PlanIdsForCellsTests(unittest.TestCase):
    def test_first_ship_mints_exactly_one_id_per_cell(self) -> None:
        cells = enumerate_cells()
        minter = IdMinter()
        result = plan_ids_for_cells(cells, {c.cell_key: 1 for c in cells}, minter)
        self.assertEqual(len(result), 30)
        for cell in cells:
            self.assertEqual(len(result[cell.cell_key]), 1)
            self.assertTrue(result[cell.cell_key][0].startswith(f"unique.{cell.cell_key}-"))

    def test_a_cell_with_zero_requested_count_mints_nothing(self) -> None:
        cells = [Cell("plant", "offense", "firstseed", "plant-offense-firstseed")]
        result = plan_ids_for_cells(cells, {}, IdMinter())
        self.assertEqual(result["plant-offense-firstseed"], [])

    def test_ids_never_collide_across_all_30_cells(self) -> None:
        cells = enumerate_cells()
        minter = IdMinter()
        result = plan_ids_for_cells(cells, {c.cell_key: 1 for c in cells}, minter)
        all_ids = [uid for ids in result.values() for uid in ids]
        self.assertEqual(len(all_ids), len(set(all_ids)))


if __name__ == "__main__":
    unittest.main()
