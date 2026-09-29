"""Tests for the model-authored `UniqueFrameImpossible` repair (item-seed-regen cause 8).

    python -m pytest gk-forge/tools/seedsmith/tests/test_unique_frame_repair.py -q
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items import unique_frame_repair as repair_mod  # noqa: E402


def _write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _unique_doc(entry_id: str, frame: str) -> dict:
    return {
        "schemaVersion": 1, "kind": "unique", "_meta": {"batch": "t", "partition": "p"},
        "entries": [{
            "id": entry_id, "name": "Encroaching Leash", "flavor": "A tether that keeps growing.",
            "frame": frame, "powerAxis": "utility", "tags": ["heavy", "metal"], "rarity": "chimeric",
            "fixedAtoms": [{"family": "atom.cleansing", "powerBand": "medium"},
                          {"family": "atom.quickening", "powerBand": "low"}],
            "varianceSlot": {"family": "atom.flourishing", "variance": "normal"},
        }],
    }


class PlanTests(unittest.TestCase):
    def test_plan_locates_the_illegal_family_in_fixed_atoms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "uniques" / "a.json", _unique_doc("unique.a-001", "humanoid"))
            found = (repair_mod.FrameFinding(
                "unique.a-001", "uniques/a.json",
                "'unique.a-001' is a humanoid unique carrying family 'atom.quickening', which the "
                "family corpus restricts to plant."),)
            repairs = repair_mod.plan(root, found=found)
            self.assertEqual(len(repairs), 1)
            self.assertEqual(repairs[0].illegal_family, "atom.quickening")
            self.assertEqual(repairs[0].slot, "fixedAtoms[1]")
            self.assertEqual(repairs[0].slot_index, 1)
            self.assertIn("atom.cleansing", repairs[0].other_families)
            self.assertIn("atom.flourishing", repairs[0].other_families)

    def test_plan_locates_the_illegal_family_in_variance_slot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "uniques" / "a.json", _unique_doc("unique.a-001", "humanoid"))
            found = (repair_mod.FrameFinding(
                "unique.a-001", "uniques/a.json",
                "'unique.a-001' is a humanoid unique carrying family 'atom.flourishing', which the "
                "family corpus restricts to plant."),)
            repairs = repair_mod.plan(root, found=found)
            self.assertEqual(repairs[0].slot, "varianceSlot")
            self.assertIsNone(repairs[0].slot_index)


class ValidateAnswerTests(unittest.TestCase):
    def _repair(self) -> "repair_mod.FrameRepair":
        return repair_mod.FrameRepair(
            entry_id="unique.a-001", path=Path("x.json"), frame="humanoid",
            illegal_family="atom.quickening", slot="fixedAtoms[1]", slot_index=1,
            context={}, other_families=("atom.cleansing", "atom.flourishing"))

    def test_an_illegal_frame_family_is_refused(self) -> None:
        repair = self._repair()
        with self.assertRaises(ValueError):
            repair_mod.validate_answer(repair, {"family": "atom.plant-only"},
                                       legal_families=frozenset({"atom.humanoid-only"}))

    def test_the_unchanged_family_is_refused(self) -> None:
        repair = self._repair()
        with self.assertRaises(ValueError):
            repair_mod.validate_answer(repair, {"family": "atom.quickening"},
                                       legal_families=frozenset({"atom.quickening"}))

    def test_a_family_already_on_the_entry_is_refused(self) -> None:
        repair = self._repair()
        with self.assertRaises(ValueError):
            repair_mod.validate_answer(repair, {"family": "atom.cleansing"},
                                       legal_families=frozenset({"atom.cleansing"}))

    def test_a_fresh_legal_family_is_accepted(self) -> None:
        repair = self._repair()
        result = repair_mod.validate_answer(
            repair, {"family": "atom.iron-hide"},
            legal_families=frozenset({"atom.iron-hide", "atom.cleansing"}))
        self.assertEqual(result, "atom.iron-hide")


class ApplyTests(unittest.TestCase):
    def test_apply_replaces_only_the_named_slot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "uniques" / "a.json"
            _write(path, _unique_doc("unique.a-001", "humanoid"))
            repair = repair_mod.FrameRepair(
                entry_id="unique.a-001", path=path, frame="humanoid",
                illegal_family="atom.quickening", slot="fixedAtoms[1]", slot_index=1,
                context={}, other_families=("atom.cleansing", "atom.flourishing"))

            changed = repair_mod.apply({"unique.a-001::fixedAtoms[1]": "atom.iron-hide"},
                                       (repair,), write=True)
            self.assertEqual(changed, (path,))
            row = json.loads(path.read_text(encoding="utf-8"))["entries"][0]
            self.assertEqual(row["fixedAtoms"][1]["family"], "atom.iron-hide")
            self.assertEqual(row["fixedAtoms"][0]["family"], "atom.cleansing")  # untouched
            self.assertEqual(row["varianceSlot"]["family"], "atom.flourishing")  # untouched

    def test_apply_replaces_the_variance_slot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "uniques" / "a.json"
            _write(path, _unique_doc("unique.a-001", "humanoid"))
            repair = repair_mod.FrameRepair(
                entry_id="unique.a-001", path=path, frame="humanoid",
                illegal_family="atom.flourishing", slot="varianceSlot", slot_index=None,
                context={}, other_families=("atom.cleansing", "atom.quickening"))

            repair_mod.apply({"unique.a-001::varianceSlot": "atom.resolve"}, (repair,), write=True)
            row = json.loads(path.read_text(encoding="utf-8"))["entries"][0]
            self.assertEqual(row["varianceSlot"]["family"], "atom.resolve")
            self.assertEqual(row["varianceSlot"]["variance"], "normal")  # untouched

    def test_unrelated_escaped_unicode_is_byte_preserved(self) -> None:
        # Regression: this corpus uses \uXXXX-escaped non-ASCII (unlike base-types/affix-families),
        # so the writer must use ensure_ascii=True or it silently un-escapes flavor text elsewhere
        # in the file (item-seed-regen cause 5's own finding, on the opposite convention).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "uniques" / "a.json"
            doc = _unique_doc("unique.a-001", "humanoid")
            doc["entries"][0]["flavor"] = "one thing — another thing"
            _write(path, doc)
            repair = repair_mod.FrameRepair(
                entry_id="unique.a-001", path=path, frame="humanoid",
                illegal_family="atom.quickening", slot="fixedAtoms[1]", slot_index=1,
                context={}, other_families=())

            repair_mod.apply({"unique.a-001::fixedAtoms[1]": "atom.iron-hide"}, (repair,), write=True)
            raw = path.read_text(encoding="utf-8")
            self.assertIn("\\u2014", raw)


if __name__ == "__main__":
    unittest.main()
