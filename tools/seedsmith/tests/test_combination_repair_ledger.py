"""The combination half of the name repairs: a rename must reach `combination-gen.ledger.json`.

    python -m pytest gk-forge/tools/seedsmith/tests/test_combination_repair_ledger.py -q

`combinations/*.json` is a full rewrite of `authored.entries_from_ledger` on every
`run_batch --write`, so a repair that edits only the seed file is reverted by the next generation
run. That is exactly what `fae533a519` (2026-09-13) did: it renamed 20 combination entries in the
seed file and left the ledger holding the old names, so SSH2.5's first `--write` put all 20 back
(SSH2.5 finding 1). These tests pin the two halves of the fix — the ledger is updated, and a
combination's PLANNED `nameKey` is never re-derived from the display name.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items import naming_grammar_repair as grammar_mod  # noqa: E402
from seedsmith.adapters.items.combogen import authored as authored_mod  # noqa: E402
from seedsmith.adapters.items.setgen import name_repair as name_mod  # noqa: E402
from seedsmith.pipeline.run_ledger import RunLedger  # noqa: E402

ENTRY_ID = "combo.splice-might-fortitude"
SUBJECT_ID = "combination-splice-might-fortitude"
PLANNED_KEY = "combination.splice-might-fortitude"


def _entry(name):
    return {
        "id": ENTRY_ID,
        "name": name,
        "nameKey": PLANNED_KEY,
        "flavor": "A standing rebuke.",
        "shape": "splice",
        "aptitudes": ["Might", "Fortitude"],
        "hostRole": "core-guard",
        "hostFrame": "humanoid",
        "minSockets": 4,
        "ingredients": [{"family": "atom.might", "minTier": 1, "quantity": 1}],
        "grants": ["atom.might"],
        "grantedTier": 1,
    }


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.combinations = self.root / "combinations"
        self.combinations.mkdir()
        self.path = self.combinations / "splices.json"
        self.path.write_text(json.dumps({
            "schemaVersion": 1, "kind": "combination",
            "_meta": {"partition": "combinations/splice"},
            "entries": [_entry("Kinetic Bastion")],
        }, indent=2) + "\n", encoding="utf-8")
        self.ledger_path = self.combinations / authored_mod.DEFAULT_LEDGER_NAME
        RunLedger(self.ledger_path).mark_done(SUBJECT_ID, {"entryId": ENTRY_ID,
                                                           "entry": _entry("Kinetic Bastion")})

    def _ledger_name(self):
        return RunLedger(self.ledger_path).read_done()[SUBJECT_ID]["entry"]["name"]

    def _file_row(self):
        return json.loads(self.path.read_text(encoding="utf-8"))["entries"][0]


class CollisionRepairTests(_Fixture):
    def test_a_combination_rename_leaves_the_planned_nameKey_and_reaches_the_ledger(self):
        repair = name_mod.NameRepair(entry_id=ENTRY_ID, kind="combination", path=self.path,
                                     old_name="Kinetic Bastion", keeper_id="combo.splice-x-y")
        changed = name_mod.apply((repair,), {ENTRY_ID: {"name": "Ashen Rebuttal"}},
                                 write=True, items_root=self.root)

        self.assertEqual((self.path,), changed)
        row = self._file_row()
        self.assertEqual("Ashen Rebuttal", row["name"])
        # `emit.name_key` mints the key from the grid cell, never from the display name.
        self.assertEqual(PLANNED_KEY, row["nameKey"])
        # The ledger carries the rename, so the next `run_batch --write` cannot revert it.
        self.assertEqual("Ashen Rebuttal", self._ledger_name())

    def test_a_dry_run_touches_neither_store(self):
        repair = name_mod.NameRepair(entry_id=ENTRY_ID, kind="combination", path=self.path,
                                     old_name="Kinetic Bastion", keeper_id="combo.splice-x-y")
        before = self.path.read_text(encoding="utf-8")
        name_mod.apply((repair,), {ENTRY_ID: {"name": "Ashen Rebuttal"}},
                       write=False, items_root=self.root)

        self.assertEqual(before, self.path.read_text(encoding="utf-8"))
        self.assertEqual("Kinetic Bastion", self._ledger_name())


class GrammarRepairTests(_Fixture):
    def test_a_grammar_rename_reaches_the_ledger_too(self):
        repair = grammar_mod.NamingGrammarRepair(entry_id=ENTRY_ID, path=self.path,
                                                 kind="combination",
                                                 old_name="Bastion's Rebuttal",
                                                 codes=("PossessiveForbidden",))
        changed = grammar_mod.apply({ENTRY_ID: "Rebuttal of Bastion"}, (repair,), write=True)

        self.assertEqual((self.path,), changed)
        self.assertEqual("Rebuttal of Bastion", self._file_row()["name"])
        self.assertEqual("Rebuttal of Bastion", self._ledger_name())
        # Still the planned key.
        self.assertEqual(PLANNED_KEY, self._file_row()["nameKey"])


class SyncHelperTests(_Fixture):
    def test_only_changed_fields_are_written_and_a_no_op_returns_none(self):
        self.assertIsNone(authored_mod.sync_repair_to_ledger(
            self.path, {ENTRY_ID: {"name": "Kinetic Bastion"}}, write=True))
        self.assertEqual("Kinetic Bastion", self._ledger_name())

        self.assertIsNotNone(authored_mod.sync_repair_to_ledger(
            self.path, {ENTRY_ID: {"name": "Sunder Verdict"}}, write=True))
        self.assertEqual("Sunder Verdict", self._ledger_name())

    def test_a_non_combination_entry_id_is_refused_by_the_shared_mapping(self):
        with self.assertRaises(ValueError):
            authored_mod.subject_id_for_entry("item.humanoid-main-hand-a-001")


class ReconcileTests(_Fixture):
    def test_a_stale_ledger_row_is_aligned_to_the_shipped_row(self):
        """The `fae533a519` history: the seed file was renamed directly and the ledger kept the old
        name. `entries_from_ledger` would revert the file on the next --write."""
        document = json.loads(self.path.read_text(encoding="utf-8"))
        document["entries"][0]["name"] = "Shipped Name"
        self.path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

        report = authored_mod.reconcile_ledger_from_seed_files(out_dir=self.combinations,
                                                              write=True)

        self.assertEqual(1, report["updated"])
        self.assertEqual("Shipped Name", self._ledger_name())
        # And the generator's own resume read now agrees with the file, byte for byte.
        self.assertEqual(authored_mod.entries_from_ledger("splice",
                                                          ledger_path=self.ledger_path),
                         json.loads(self.path.read_text(encoding="utf-8"))["entries"])

    def test_a_dry_run_reports_without_touching_disk(self):
        document = json.loads(self.path.read_text(encoding="utf-8"))
        document["entries"][0]["name"] = "Shipped Name"
        self.path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

        report = authored_mod.reconcile_ledger_from_seed_files(out_dir=self.combinations,
                                                              write=False)

        self.assertEqual(1, report["updated"])
        self.assertEqual("Kinetic Bastion", self._ledger_name())

    def test_an_already_aligned_ledger_reports_zero(self):
        self.assertEqual(0, authored_mod.reconcile_ledger_from_seed_files(
            out_dir=self.combinations, write=True)["updated"])


if __name__ == "__main__":
    unittest.main()
