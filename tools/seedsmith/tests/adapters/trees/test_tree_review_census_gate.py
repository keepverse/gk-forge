"""Tests for seedsmith.adapters.trees.review.census_gate (task H7, spec-tree-review.md §5.5).

The two proofs the todo's own H7 verification line names: a census against a MISSING sheetRead
row refuses, and a census against a STALE one (naming a revision the sheet no longer carries)
refuses too. Plus the boundary cases: no sheet rendered at all, and a matching-current-row pass.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from seedsmith.adapters.trees.review import census_gate


def _write_sheet(sheet_dir: Path, lot: str, revision: str) -> None:
    lot_dir = sheet_dir / lot
    lot_dir.mkdir(parents=True, exist_ok=True)
    (lot_dir / "sheet.json").write_text(
        json.dumps({"lot": lot, "sheetRevision": revision, "generatedAt": "2026-09-06T00:00:00Z"}),
        encoding="utf-8")


def _write_review_queue(review_dir: Path, lot: str, *, sheet_reads: "list[dict] | None" = None,
                        entries: "list[dict] | None" = None) -> None:
    review_dir.mkdir(parents=True, exist_ok=True)
    doc = {"lot": lot, "entries": entries or [], "sheetReads": sheet_reads or []}
    (review_dir / f"{lot}.json").write_text(json.dumps(doc), encoding="utf-8")


class MissingRowRefusesTests(unittest.TestCase):
    def test_a_census_refuses_when_the_lot_has_no_review_queue_file_at_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sheet_dir = Path(tmp) / "sheets"
            review_dir = Path(tmp) / "review"
            _write_sheet(sheet_dir, "might", "rev-1")
            # No _review/<lot>.json written at all — never dismissed.
            with self.assertRaises(census_gate.CensusRefused) as ctx:
                census_gate.assert_may_start_census(sheet_dir, review_dir, "might")
            self.assertIn("no sheetRead row", str(ctx.exception))

    def test_a_census_refuses_when_the_queue_exists_but_carries_no_sheet_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sheet_dir = Path(tmp) / "sheets"
            review_dir = Path(tmp) / "review"
            _write_sheet(sheet_dir, "might", "rev-1")
            _write_review_queue(review_dir, "might", entries=[{"treeId": "might", "status": "accept"}])
            with self.assertRaises(census_gate.CensusRefused) as ctx:
                census_gate.assert_may_start_census(sheet_dir, review_dir, "might")
            self.assertIn("no sheetRead row", str(ctx.exception))

    def test_a_sheet_read_for_a_different_lot_does_not_satisfy_this_ones_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sheet_dir = Path(tmp) / "sheets"
            review_dir = Path(tmp) / "review"
            _write_sheet(sheet_dir, "might", "rev-1")
            # A row present, but naming a different lot than the file itself claims.
            _write_review_queue(review_dir, "might",
                                sheet_reads=[{"lot": "fortitude", "sheetRevision": "rev-1",
                                             "by": "tester", "utc": "2026-09-06T00:00:00Z"}])
            with self.assertRaises(census_gate.CensusRefused):
                census_gate.assert_may_start_census(sheet_dir, review_dir, "might")


class StaleRowRefusesTests(unittest.TestCase):
    def test_a_census_refuses_when_the_row_names_a_stale_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sheet_dir = Path(tmp) / "sheets"
            review_dir = Path(tmp) / "review"
            _write_sheet(sheet_dir, "might", "rev-2")  # the sheet moved on since the read
            _write_review_queue(review_dir, "might",
                                sheet_reads=[{"lot": "might", "sheetRevision": "rev-1",
                                             "by": "tester", "utc": "2026-09-05T00:00:00Z"}])
            with self.assertRaises(census_gate.CensusRefused) as ctx:
                census_gate.assert_may_start_census(sheet_dir, review_dir, "might")
            self.assertIn("changed since it was last read", str(ctx.exception))
            self.assertIn("rev-1", str(ctx.exception))
            self.assertIn("rev-2", str(ctx.exception))

    def test_only_the_latest_of_several_sheet_reads_is_consulted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sheet_dir = Path(tmp) / "sheets"
            review_dir = Path(tmp) / "review"
            _write_sheet(sheet_dir, "might", "rev-3")
            _write_review_queue(review_dir, "might", sheet_reads=[
                {"lot": "might", "sheetRevision": "rev-1", "by": "a", "utc": "t1"},
                {"lot": "might", "sheetRevision": "rev-2", "by": "b", "utc": "t2"},
            ])
            with self.assertRaises(census_gate.CensusRefused) as ctx:
                census_gate.assert_may_start_census(sheet_dir, review_dir, "might")
            # Names the LATEST stale revision (rev-2), not the oldest (rev-1).
            self.assertIn("rev-2", str(ctx.exception))


class CurrentRowPassesTests(unittest.TestCase):
    def test_a_census_proceeds_when_the_latest_row_names_the_current_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sheet_dir = Path(tmp) / "sheets"
            review_dir = Path(tmp) / "review"
            _write_sheet(sheet_dir, "might", "rev-1")
            _write_review_queue(review_dir, "might",
                                sheet_reads=[{"lot": "might", "sheetRevision": "rev-1",
                                             "by": "tester", "utc": "2026-09-06T00:00:00Z"}])
            row = census_gate.assert_may_start_census(sheet_dir, review_dir, "might")
            self.assertEqual(row.sheet_revision, "rev-1")
            self.assertEqual(row.by, "tester")

    def test_a_re_dismissal_after_a_stale_read_clears_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sheet_dir = Path(tmp) / "sheets"
            review_dir = Path(tmp) / "review"
            _write_sheet(sheet_dir, "might", "rev-2")
            _write_review_queue(review_dir, "might", sheet_reads=[
                {"lot": "might", "sheetRevision": "rev-1", "by": "a", "utc": "t1"},
                {"lot": "might", "sheetRevision": "rev-2", "by": "a", "utc": "t2"},
            ])
            row = census_gate.assert_may_start_census(sheet_dir, review_dir, "might")
            self.assertEqual(row.sheet_revision, "rev-2")


class SheetNotRenderedTests(unittest.TestCase):
    def test_no_sheet_json_at_all_raises_sheet_not_rendered_not_census_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sheet_dir = Path(tmp) / "sheets"
            review_dir = Path(tmp) / "review"
            with self.assertRaises(census_gate.SheetNotRendered):
                census_gate.assert_may_start_census(sheet_dir, review_dir, "might")

    def test_a_sheet_json_with_no_revision_field_raises_sheet_not_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sheet_dir = Path(tmp) / "sheets"
            review_dir = Path(tmp) / "review"
            lot_dir = sheet_dir / "might"
            lot_dir.mkdir(parents=True)
            (lot_dir / "sheet.json").write_text(json.dumps({"lot": "might"}), encoding="utf-8")
            with self.assertRaises(census_gate.SheetNotRendered):
                census_gate.read_current_sheet_revision(sheet_dir, "might")


if __name__ == "__main__":
    unittest.main()
