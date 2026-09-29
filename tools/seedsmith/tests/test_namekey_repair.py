"""Tests for the mechanical `nameKey` kind-prefix repair (item-seed-regen cause 4).

    python -m pytest gk-forge/tools/seedsmith/tests/test_namekey_repair.py -q
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items import namekey_repair  # noqa: E402


def _write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class NameKeyPrefixRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())

    def _base_type_doc(self, name_key: str) -> dict:
        return {
            "schemaVersion": 1, "kind": "base-type",
            "_meta": {"batch": "test", "partition": "p"},
            "entries": [
                {
                    "id": "item.humanoid-main-hand-a-020",
                    "nameKey": name_key,
                    "name": "Great Maul",
                    "iconKey": "icon.base-type.great-maul",
                    "flavorKey": "flavor.base.heavy-sledge",
                },
            ],
        }

    def test_wrong_base_type_prefix_is_planned_and_fixed(self) -> None:
        path = self.root / "base-types" / "humanoid-armament-primary-a.json"
        _write(path, self._base_type_doc("base-type.great-maul"))

        repairs = namekey_repair.plan(self.root)
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0].old_key, "base-type.great-maul")
        self.assertEqual(repairs[0].new_key, "base.great-maul")

        namekey_repair.apply(repairs, write=True)
        fixed = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(fixed["entries"][0]["nameKey"], "base.great-maul")
        # Nothing else on the row moves -- iconKey/flavorKey are a separate, unvalidated field.
        self.assertEqual(fixed["entries"][0]["iconKey"], "icon.base-type.great-maul")
        self.assertEqual(fixed["entries"][0]["flavorKey"], "flavor.base.heavy-sledge")
        self.assertEqual(fixed["entries"][0]["name"], "Great Maul")

    def test_drop_table_and_affix_family_prefixes_also_repair(self) -> None:
        dt_path = self.root / "drop-tables" / "d3.json"
        _write(dt_path, {
            "schemaVersion": 1, "kind": "drop-table", "_meta": {"batch": "t", "partition": "p"},
            "entries": [{"id": "droptable.d3-011", "nameKey": "drop-table.chlorophyll-shell",
                         "name": "Chlorophyll Shell"}],
        })
        af_path = self.root / "affix-families" / "g-evade.json"
        _write(af_path, {
            "schemaVersion": 1, "kind": "affix-family", "_meta": {"batch": "t", "partition": "p"},
            "entries": [{"id": "atom.evd-shift", "nameKey": "affix-family.agility",
                         "name": "Agility"}],
        })

        repairs = namekey_repair.plan(self.root)
        by_id = {r.entry_id: r for r in repairs}
        self.assertEqual(by_id["droptable.d3-011"].new_key, "droptable.chlorophyll-shell")
        self.assertEqual(by_id["atom.evd-shift"].new_key, "affix.agility")

        namekey_repair.apply(repairs, write=True)
        self.assertEqual(
            json.loads(dt_path.read_text(encoding="utf-8"))["entries"][0]["nameKey"],
            "droptable.chlorophyll-shell")
        self.assertEqual(
            json.loads(af_path.read_text(encoding="utf-8"))["entries"][0]["nameKey"],
            "affix.agility")

    def test_correct_prefix_is_never_touched(self) -> None:
        path = self.root / "base-types" / "clean.json"
        _write(path, self._base_type_doc("base.great-maul"))
        self.assertEqual(namekey_repair.plan(self.root), ())

    def test_dry_run_writes_nothing(self) -> None:
        path = self.root / "base-types" / "humanoid-armament-primary-a.json"
        _write(path, self._base_type_doc("base-type.great-maul"))
        before = path.read_text(encoding="utf-8")

        repairs = namekey_repair.plan(self.root)
        namekey_repair.apply(repairs, write=False)

        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_an_unrecognised_prefix_is_left_alone(self) -> None:
        # namekey_repair only knows the three prefixes a real validator run found wrong; any other
        # mismatch is a different defect and must not be guessed at here.
        path = self.root / "base-types" / "mystery.json"
        _write(path, self._base_type_doc("mystery-kind.thing"))
        self.assertEqual(namekey_repair.plan(self.root), ())


if __name__ == "__main__":
    unittest.main()
