from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.setgen import name_repair  # noqa: E402


def _document(kind: str, entry_id: str, name: str) -> dict:
    return {"schemaVersion": 1, "kind": kind, "entries": [
        {"id": entry_id, "name": name, "nameKey": f"{kind}.old", "flavor": "old"}]}


def _groups(*, key: str, members: list[tuple[str, str]]) -> list[dict]:
    """A collision group in the validator's own --collision-groups shape."""
    return [{"key": key, "members": [{"id": i, "name": n, "kind": "set"} for i, n in members]}]


class NameRepairTests(unittest.TestCase):
    def test_plan_and_apply_change_only_the_losing_identity_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "sets").mkdir()
            set_path = root / "sets" / "a.json"
            set_path.write_text(json.dumps(_document("set", "set.b-002", "Shared Name")),
                                encoding="utf-8")

            repairs = name_repair.plan(
                root, groups=_groups(key="shared name", members=[("set.a-001", "Shared Name"),
                                                                 ("set.b-002", "Shared Name")]))
            self.assertEqual([(r.entry_id, r.keeper_id) for r in repairs],
                             [("set.b-002", "set.a-001")])
            answers = {"set.b-002": {"name": "Distinct Name", "flavor": "new"}}
            changed = name_repair.apply(repairs, answers, write=True, items_root=root)

            self.assertEqual(changed, (set_path,))
            repaired = json.loads(set_path.read_text(encoding="utf-8"))["entries"][0]
            self.assertEqual(repaired["name"], "Distinct Name")
            self.assertEqual(repaired["nameKey"], "set.distinct-name")
            self.assertEqual(repaired["flavor"], "new")
            self.assertEqual(repaired["id"], "set.b-002")  # identity preserved (seed-contract 7.2)

    def test_the_keeper_is_the_lexically_first_id_in_the_group(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "sets").mkdir()
            for eid in ("set.m-003", "set.a-001", "set.z-009"):
                (root / "sets" / f"{eid}.json").write_text(
                    json.dumps(_document("set", eid, "Same Idea")), encoding="utf-8")
            repairs = name_repair.plan(
                root, groups=_groups(key="same idea", members=[
                    ("set.z-009", "Same Idea"), ("set.a-001", "Same Idea"),
                    ("set.m-003", "Same Idea")]))
            self.assertEqual({r.entry_id for r in repairs}, {"set.m-003", "set.z-009"})
            self.assertTrue(all(r.keeper_id == "set.a-001" for r in repairs))

    def test_the_brief_names_the_keeper_in_words_not_only_by_id(self) -> None:
        """The keeper's DISPLAY name is the one string the model must avoid. Naming the keeper
        only by id (measured 2026-09-21 on the real corpus: five attempts at renaming
        `combo.strain-ferocity-balance` produced nothing but the keeper's idea in the other word
        order) is what a repair brief must never do."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "sets").mkdir()
            (root / "sets" / "a.json").write_text(
                json.dumps(_document("set", "set.a-001", "Ferocity Bastion")), encoding="utf-8")
            (root / "sets" / "b.json").write_text(
                json.dumps(_document("set", "set.b-002", "Bastion of Ferocity")), encoding="utf-8")
            repairs = name_repair.plan(
                root, groups=_groups(key="ferocity bastion", members=[
                    ("set.a-001", "Ferocity Bastion"), ("set.b-002", "Bastion of Ferocity")]))
            self.assertEqual(["Ferocity Bastion"], [r.keeper_name for r in repairs])
            text = name_repair.brief(repairs[0])
            self.assertIn("set.a-001", text)
            self.assertIn("Ferocity Bastion", text)

    def test_replacement_may_not_reuse_any_current_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "sets").mkdir()
            (root / "sets" / "a.json").write_text(
                json.dumps(_document("set", "set.b-002", "Shared Name")), encoding="utf-8")
            repairs = name_repair.plan(
                root, groups=_groups(key="shared name",
                                     members=[("set.a-001", "Shared Name"),
                                              ("set.b-002", "Shared Name")]))
            with self.assertRaisesRegex(ValueError, "already exists"):
                name_repair.apply(repairs, {"set.b-002": {"name": "Shared Name"}},
                                  write=False, items_root=root)

    def test_a_replacement_that_reuses_an_existing_idea_is_refused(self) -> None:
        """The casefold comparison cannot see `Ferocity Bulwark` against the shipped set `Bulwark of
        Ferocity`; the validator's own normalizer can, and a repair that mints a fresh collision is
        worse than no repair. Measured 2026-09-21 on `combo.strain-ferocity-balance`."""
        keys = name_repair.validator_keys(["Bulwark of Ferocity", "Ferocity Bulwark",
                                           "Ferocity Bastion"])
        self.assertEqual(keys["Bulwark of Ferocity"], keys["Ferocity Bulwark"])
        self.assertNotEqual(keys["Bulwark of Ferocity"], keys["Ferocity Bastion"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "sets").mkdir()
            (root / "sets" / "a.json").write_text(
                json.dumps(_document("set", "set.b-002", "Bulwark of Ferocity")), encoding="utf-8")
            repairs = name_repair.plan(
                root, groups=_groups(key="bulwark ferocity", members=[
                    ("set.a-001", "Bulwark of Ferocity"),
                    ("set.b-002", "Bulwark of Ferocity")]))
            with self.assertRaisesRegex(ValueError, "same idea as a name already in the corpus"):
                name_repair.apply(repairs, {"set.b-002": {"name": "Ferocity Bulwark"}},
                                  write=False, items_root=root,
                                  key_of=lambda names: name_repair.validator_keys(names))

    def test_an_unsluggable_replacement_is_refused_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "sets").mkdir()
            (root / "sets" / "a.json").write_text(
                json.dumps(_document("set", "set.b-002", "Shared Name")), encoding="utf-8")
            repairs = name_repair.plan(
                root, groups=_groups(key="shared name",
                                     members=[("set.a-001", "Shared Name"),
                                              ("set.b-002", "Shared Name")]))
            with self.assertRaisesRegex(ValueError, "no ASCII slug"):
                name_repair.apply(repairs, {"set.b-002": {"name": "毁灭豌豆之友"}},
                                  write=False, items_root=root)

    def test_answers_must_cover_exactly_the_planned_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "sets").mkdir()
            (root / "sets" / "a.json").write_text(
                json.dumps(_document("set", "set.b-002", "Shared Name")), encoding="utf-8")
            repairs = name_repair.plan(
                root, groups=_groups(key="shared name",
                                     members=[("set.a-001", "Shared Name"),
                                              ("set.b-002", "Shared Name")]))
            with self.assertRaisesRegex(ValueError, "must name exactly"):
                name_repair.apply(repairs, {}, write=False, items_root=root)

    def test_a_single_member_group_is_not_a_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "sets").mkdir()
            (root / "sets" / "a.json").write_text(
                json.dumps(_document("set", "set.a-001", "Lonely Name")), encoding="utf-8")
            repairs = name_repair.plan(
                root, groups=_groups(key="lonely name", members=[("set.a-001", "Lonely Name")]))
            self.assertEqual(repairs, ())


class RealCorpusPlanTests(unittest.TestCase):
    """The real plan, computed from the validator's own --collision-groups output."""

    def test_the_real_plan_matches_the_validators_remaining_collisions(self) -> None:
        """⛔ CORRECTED 2026-09-12. This used to assert the plan was NON-EMPTY, which was true only
        while the 2026-09-12 repair was outstanding: the plan is the outstanding work, so an empty
        plan is the SUCCESS state once every collision is fixed. Asserting non-emptiness would fail
        on a clean corpus and, worse, invite re-introducing a collision to satisfy it. The invariant
        is that the plan agrees with the validator: every remaining group (other than a nameKey
        group whose rows the deterministic key pass handles) produces exactly the losing rows."""
        groups = name_repair.collision_groups()
        repairs = name_repair.plan(groups=groups)
        expected = sum(len(g.get("members") or ()) - 1 for g in groups
                       if len(g.get("members") or ()) > 1)
        # A nameKey group only needs a rename when the key is a placeholder (an unsluggable name);
        # otherwise repair_name_keys covers it, so the plan is a subset of the raw losing count.
        self.assertLessEqual(len(repairs), expected)
        if groups:
            kinds = {r.kind for r in repairs}
            self.assertTrue(kinds, "collisions exist, so the plan must name the kinds to repair")

    def test_no_plan_row_is_its_own_keeper(self) -> None:
        for repair in name_repair.plan():
            self.assertNotEqual(repair.entry_id, repair.keeper_id,
                                "a row cannot keep a name it is being renamed away from")


if __name__ == "__main__":
    unittest.main()
