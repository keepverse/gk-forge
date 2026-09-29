"""Tests for `combogen.grant_repair` (ISG3).

    python -m pytest gk-forge/tools/seedsmith/tests/test_grant_repair.py -q

The one property that matters most here is the ANTI-DESYNC one: `apply` must move the ledger and the
seed file together, because `authored.run_batch` rewrites the whole file from the ledger on every
`--write`. A repair that edited only the JSON would be reverted by the next generation run — the
defect `fae533a519` left behind (SSH2.5 finding 1). That test reads the file back through the
generator's own `entries_from_ledger`, not through the repair's own eyes.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.combogen import grant_repair as repair_mod  # noqa: E402

ENTRY_ID = "combo.splice-composure-bulwark"
SUBJECT_ID = "combination-splice-composure-bulwark"


def _entry(grants):
    return {
        "id": ENTRY_ID,
        "name": "Bulwark of Composure",
        "flavor": "Stillness meets the wall.",
        "shape": "splice",
        "aptitudes": ["Composure", "Bulwark"],
        "hostRole": "core-guard",
        "hostFrame": "humanoid",
        "grants": list(grants),
        "ingredients": [{"family": "atom.bulwark", "minTier": 1, "quantity": 1}],
    }


class SubjectIdTests(unittest.TestCase):
    def test_the_ledger_key_is_the_entry_id_with_the_other_prefix(self):
        self.assertEqual(SUBJECT_ID, repair_mod.subject_id_for(ENTRY_ID))

    def test_a_non_combination_id_is_refused(self):
        with self.assertRaises(ValueError):
            repair_mod.subject_id_for("item.humanoid-main-hand-a-001")


class PlanTests(unittest.TestCase):
    def test_plan_intersects_the_finding_with_the_row_not_with_the_catalog(self):
        """The validator's reported target is the authority, NOT "not in the affix-family catalog":
        a milestone MINTS `atom.enhance-*`, which resolves through `MintedRuntimeIds` and a catalog
        check would wrongly flag. And a finding whose target is no longer in the row (stale) is
        dropped rather than chased."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "combinations").mkdir()
            (root / "combinations" / "splices.json").write_text(
                json.dumps({"kind": "combination",
                            "entries": [_entry(["atom.enhance-might", "atom.aura-onslaught"])]}),
                encoding="utf-8")
            found = (repair_mod.GrantFinding(
                ENTRY_ID, "combinations/splices.json",
                "'grants[1]' references 'atom.aura-onslaught', which no seed file authors"),)

            repairs = repair_mod.plan(root, found=found,
                                      catalog=frozenset({"atom.bulwark", "atom.retribution"}))

            self.assertEqual(1, len(repairs))
            repair = repairs[0]
            self.assertEqual((ENTRY_ID, SUBJECT_ID), (repair.entry_id, repair.subject_id))
            self.assertEqual("splice", repair.shape)
            # atom.enhance-might is absent from the catalog yet is NOT reported as bad.
            self.assertEqual(("atom.aura-onslaught",), repair.bad_families)

    def test_a_stale_finding_is_dropped_rather_than_chased(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "combinations").mkdir()
            (root / "combinations" / "splices.json").write_text(
                json.dumps({"kind": "combination", "entries": [_entry(["atom.bulwark"])]}),
                encoding="utf-8")
            found = (repair_mod.GrantFinding(
                ENTRY_ID, "combinations/splices.json",
                "'grants[0]' references 'atom.aura-onslaught', which no seed file authors"),)

            self.assertEqual((), repair_mod.plan(root, found=found))

    def test_two_findings_on_one_entry_collapse_to_one_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "combinations").mkdir()
            (root / "combinations" / "splices.json").write_text(
                json.dumps({"kind": "combination",
                            "entries": [_entry(["atom.aura-pierce", "atom.aura-retribution"])]}),
                encoding="utf-8")
            found = tuple(
                repair_mod.GrantFinding(ENTRY_ID, "combinations/splices.json",
                                        f"'grants[{i}]' references '{fam}', which no seed file authors")
                for i, fam in enumerate(("atom.aura-pierce", "atom.aura-retribution")))

            repairs = repair_mod.plan(root, found=found)

            self.assertEqual(1, len(repairs))
            self.assertEqual(("atom.aura-pierce", "atom.aura-retribution"),
                             repairs[0].bad_families)

    def test_an_entry_whose_grants_all_resolve_needs_no_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "combinations").mkdir()
            (root / "combinations" / "splices.json").write_text(
                json.dumps({"kind": "combination", "entries": [_entry(["atom.bulwark"])]}),
                encoding="utf-8")
            found = (repair_mod.GrantFinding(
                ENTRY_ID, "combinations/splices.json",
                "'grants[0]' references 'atom.aura-onslaught', which no seed file authors"),)

            self.assertEqual((), repair_mod.plan(root, found=found))


class AnswerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = frozenset({"atom.bulwark", "atom.evasion", "atom.retribution"})
        self.repair = repair_mod.GrantRepair(
            entry_id=ENTRY_ID, subject_id=SUBJECT_ID, shape="splice", path=Path("x"),
            grants=("atom.bulwark", "atom.aura-onslaught"),
            bad_families=("atom.aura-onslaught",), context={})

    def test_only_the_bad_slots_are_asked_for_and_spliced_back(self):
        self.assertEqual((1,), repair_mod.bad_positions(self.repair))
        self.assertEqual(
            ("atom.bulwark", "atom.retribution"),
            repair_mod.resolved_grants(
                self.repair,
                repair_mod.validate_answer(self.repair, self.catalog,
                                           {"replacements": ["atom.retribution"]})))

    def test_an_already_resolvable_grant_never_leaves_the_codes_hands(self):
        """A live `atom.enhance-*` grant (minted by a milestone, so it resolves) sits next to the
        bad slot; the answer names only the bad slot, so the live one is preserved by construction."""
        repair = repair_mod.GrantRepair(
            entry_id=ENTRY_ID, subject_id=SUBJECT_ID, shape="splice", path=Path("x"),
            grants=("atom.aura-pierce", "atom.enhance-fortify"),
            bad_families=("atom.aura-pierce",), context={})
        self.assertEqual((0,), repair_mod.bad_positions(repair))
        self.assertEqual(
            ("atom.evasion", "atom.enhance-fortify"),
            repair_mod.resolved_grants(repair, ("atom.evasion",)))

    def test_an_out_of_catalog_family_is_refused(self):
        with self.assertRaises(ValueError):
            repair_mod.validate_answer(self.repair, self.catalog,
                                       {"replacements": ["atom.aura-onslaught"]})

    def test_a_wrong_replacement_count_is_refused(self):
        with self.assertRaises(ValueError):
            repair_mod.validate_answer(self.repair, self.catalog, {"replacements": []})

    def test_the_schema_enumerates_the_catalog_and_pins_the_bad_slot_count(self):
        schema = repair_mod.schema(self.repair, self.catalog)
        replacements = schema["properties"]["replacements"]
        self.assertEqual(sorted(self.catalog), replacements["items"]["enum"])
        self.assertEqual(1, replacements["minItems"])
        self.assertEqual(1, replacements["maxItems"])

    def test_run_batch_retries_until_the_answer_validates(self):
        seen = {"n": 0}

        def caller(_brief: str, _schema: dict) -> dict:
            seen["n"] += 1
            if seen["n"] == 1:
                return {"replacements": ["atom.aura-onslaught"]}  # still unresolved
            return {"replacements": ["atom.retribution"]}

        answers, failed = repair_mod.run_batch((self.repair,), caller=caller, catalog=self.catalog)
        self.assertEqual([], failed)
        self.assertEqual(("atom.bulwark", "atom.retribution"), answers[ENTRY_ID])


class ApplyTests(unittest.TestCase):
    def _root(self, temp: str) -> Path:
        """Creates `<temp>/combinations/splices.json` and returns `<temp>` — the ITEMS root, which is
        what `findings()`' own `file` field ("combinations/splices.json") is relative to."""
        root = Path(temp)
        (root / "combinations").mkdir(parents=True)
        (root / "combinations" / "splices.json").write_text(json.dumps({
            "schemaVersion": 1, "kind": "combination",
            "_meta": {"model": "google/gemma-4-26b-a4b-qat",
                      "authoredUtc": "1970-01-01T00:00:00Z",
                      "partition": "combinations/splice"},
            "entries": [_entry(["atom.bulwark", "atom.aura-onslaught"])],
        }, indent=2) + "\n", encoding="utf-8")
        return root

    def _repair(self, root: Path) -> "tuple[repair_mod.GrantRepair, ...]":
        return repair_mod.plan(root, found=(
            repair_mod.GrantFinding(
                ENTRY_ID, "combinations/splices.json",
                "'grants[1]' references 'atom.aura-onslaught', which no seed file authors"),),
            catalog=frozenset({"atom.bulwark", "atom.retribution"}))

    def test_dry_run_reports_without_touching_disk(self):
        from seedsmith.pipeline.run_ledger import RunLedger

        with tempfile.TemporaryDirectory() as temp:
            items_root = self._root(temp)
            root = items_root / "combinations"
            repairs = self._repair(items_root)
            RunLedger(root / "combination-gen.ledger.json").mark_done(
                SUBJECT_ID, {"entryId": ENTRY_ID,
                             "entry": _entry(["atom.bulwark", "atom.aura-onslaught"])})
            before = (root / "splices.json").read_text(encoding="utf-8")

            changed = repair_mod.apply({ENTRY_ID: ("atom.bulwark", "atom.retribution")}, repairs,
                                       write=False)

            self.assertEqual((root / "splices.json",), changed)
            self.assertEqual(before, (root / "splices.json").read_text(encoding="utf-8"))
            self.assertEqual(
                ["atom.bulwark", "atom.aura-onslaught"],
                json.loads((root / "combination-gen.ledger.json").read_text(encoding="utf-8"))
                ["done"][SUBJECT_ID]["entry"]["grants"])

    def test_write_moves_the_ledger_and_the_seed_file_together(self):
        """The anti-reversion property: the grant must land in BOTH stores (the next `--write`
        rewrites the file from the ledger), and the shipped file's own fields must survive — a
        stale ledger row must not revert a name the file already carries."""
        from seedsmith.adapters.items.combogen import authored as authored_mod
        from seedsmith.pipeline.run_ledger import RunLedger

        with tempfile.TemporaryDirectory() as temp:
            items_root = self._root(temp)
            root = items_root / "combinations"
            repairs = self._repair(items_root)
            ledger_path = root / authored_mod.DEFAULT_LEDGER_NAME
            ledger = RunLedger(ledger_path)
            stale = _entry(["atom.bulwark", "atom.aura-onslaught"])
            stale["name"] = "Old Collision-Prone Name"  # the fae533a519 desync: file is newer
            stale["flavor"] = "stale flavor"
            ledger.mark_done(SUBJECT_ID, {"entryId": ENTRY_ID, "entry": stale})

            changed = repair_mod.apply({ENTRY_ID: ("atom.bulwark", "atom.retribution")}, repairs,
                                       write=True)

            self.assertEqual((root / "splices.json",), changed)
            on_disk = json.loads((root / "splices.json").read_text(encoding="utf-8"))
            self.assertEqual(["atom.bulwark", "atom.retribution"], on_disk["entries"][0]["grants"])
            # Every other field comes from the shipped file, untouched.
            self.assertEqual("Bulwark of Composure", on_disk["entries"][0]["name"])
            self.assertEqual("Stillness meets the wall.", on_disk["entries"][0]["flavor"])
            # The ledger carries the same grants, so the next generation write preserves them.
            ledger_row = RunLedger(ledger_path).read_done()[SUBJECT_ID]["entry"]
            self.assertEqual(["atom.bulwark", "atom.retribution"], ledger_row["grants"])


if __name__ == "__main__":
    unittest.main()
