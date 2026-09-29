"""Tests for the mechanical `_meta.registryVersions` stamp repair (item-seed-regen cause 5).

    python -m pytest gk-forge/tools/seedsmith/tests/test_meta_registry_repair.py -q
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items import meta_registry_repair as repair_mod  # noqa: E402


def _write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _doc(**registry_versions: int) -> dict:
    return {
        "schemaVersion": 1, "kind": "base-type",
        "_meta": {"batch": "t", "partition": "p", "registryVersions": dict(registry_versions)},
        "entries": [],
    }


class MetaRegistryRepairTests(unittest.TestCase):
    def test_plan_finds_only_the_exact_old_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "base-types" / "a.json", _doc(core=1, naming=7))
            _write(root / "base-types" / "b.json", _doc(core=2, naming=7))  # already current
            _write(root / "base-types" / "c.json", _doc(naming=7))  # no core key at all

            bumps = repair_mod.plan("core", 1, 2, items_root=root)
            self.assertEqual(len(bumps), 1)
            self.assertEqual(bumps[0].path, root / "base-types" / "a.json")
            self.assertEqual(bumps[0].old_version, 1)
            self.assertEqual(bumps[0].new_version, 2)

    def test_apply_changes_only_the_named_registry_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "base-types" / "a.json"
            _write(path, _doc(core=1, naming=7))

            bumps = repair_mod.plan("core", 1, 2, items_root=root)
            changed = repair_mod.apply(bumps, write=True)

            self.assertEqual(changed, (path,))
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["_meta"]["registryVersions"]["core"], 2)
            self.assertEqual(document["_meta"]["registryVersions"]["naming"], 7)  # untouched
            self.assertEqual(document["_meta"]["batch"], "t")  # untouched
            self.assertEqual(document["entries"], [])  # untouched

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "base-types" / "a.json"
            _write(path, _doc(core=1))
            before = path.read_text(encoding="utf-8")

            bumps = repair_mod.plan("core", 1, 2, items_root=root)
            repair_mod.apply(bumps, write=False)

            self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_a_file_with_no_meta_block_is_skipped_not_crashed_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "base-types" / "no-meta.json",
                   {"schemaVersion": 1, "kind": "base-type", "entries": []})
            self.assertEqual(repair_mod.plan("core", 1, 2, items_root=root), ())

    def test_unrelated_escaped_unicode_is_byte_preserved(self) -> None:
        # Regression: a full json.load/json.dump(ensure_ascii=False) round-trip silently
        # un-escapes every `\uXXXX` elsewhere in the file (found live on
        # uniques/verdant-graft-90.json's flavor text, a 7-line reformatting side effect on what
        # should be a one-field bump). The surgical text edit must never touch it.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "uniques" / "a.json"
            path.parent.mkdir(parents=True)
            raw = (
                '{\n'
                '  "schemaVersion": 1,\n'
                '  "kind": "unique",\n'
                '  "_meta": {\n'
                '    "batch": "t",\n'
                '    "registryVersions": {\n'
                '      "core": 1,\n'
                '      "bands": 1\n'
                '    }\n'
                '  },\n'
                '  "entries": [\n'
                '    { "id": "unique.a-001", "flavor": "one thing \\u2014 another thing" }\n'
                '  ]\n'
                '}\n'
            )
            path.write_text(raw, encoding="utf-8")

            bumps = repair_mod.plan("core", 1, 2, items_root=root)
            repair_mod.apply(bumps, write=True)

            after = path.read_text(encoding="utf-8")
            self.assertIn('\\u2014', after)  # escape form preserved, not un-escaped to em dash
            self.assertIn('"core": 2', after)
            self.assertNotIn('"core": 1', after)
            # Every byte outside the one changed digit is identical.
            self.assertEqual(after, raw.replace('"core": 1', '"core": 2'))


if __name__ == "__main__":
    unittest.main()
