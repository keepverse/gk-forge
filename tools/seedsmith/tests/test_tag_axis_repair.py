"""Tests for the shared tag-axis-exclusivity check and its repair pipeline
(item-seed-regen cause 8).

    python -m pytest gk-forge/tools/seedsmith/tests/test_tag_axis_repair.py -q
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items import registries  # noqa: E402
from seedsmith.adapters.items import tag_axis_repair as repair_mod  # noqa: E402


class TagAxisViolationTests(unittest.TestCase):
    def test_two_tags_on_one_exclusive_axis_is_a_violation(self) -> None:
        axes = {"combat-posture": ("defensive", "offensive", "utility")}
        v = registries.tag_axis_violation(["defensive", "utility"], axes)
        self.assertIsNotNone(v)
        self.assertIn("combat-posture", v)

    def test_one_tag_per_axis_is_clean(self) -> None:
        axes = {"combat-posture": ("defensive", "offensive", "utility")}
        self.assertIsNone(registries.tag_axis_violation(["defensive"], axes))

    def test_non_exclusive_axis_is_never_flagged(self) -> None:
        axes = {"economy-source": ("looted", "crafted")}
        v = registries.tag_axis_violation(
            ["looted", "crafted"], axes, non_exclusive=frozenset({"economy-source"}))
        self.assertIsNone(v)

    def test_a_tag_outside_any_axis_is_ignored(self) -> None:
        axes = {"combat-posture": ("defensive", "offensive", "utility")}
        self.assertIsNone(registries.tag_axis_violation(["organic"], axes))


def _write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _base_type_doc(entry_id: str, tags: list[str]) -> dict:
    return {"schemaVersion": 1, "kind": "base-type", "_meta": {"batch": "t", "partition": "p"},
            "entries": [{"id": entry_id, "name": "Ward Buckler", "flavor": "A steady guard.",
                        "class": "cloth", "role": "ward-array", "tags": tags}]}


class PlanTests(unittest.TestCase):
    def test_plan_finds_the_conflicting_axis_and_ignores_clean_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "base-types" / "a.json",
                  _base_type_doc("item.a-001", ["defensive", "utility", "organic"]))
            found = (repair_mod.TagAxisFinding(
                "item.a-001", "base-types/a.json",
                "axis 'combat-posture' is exclusive but carries 2 tags: defensive, utility"),)
            repairs = repair_mod.plan(root, found=found)
            self.assertEqual(len(repairs), 1)
            self.assertEqual(repairs[0].conflicts, (("combat-posture", ("defensive", "utility")),))
            # A non-conflicting tag on the entry is untouched by the conflict list.
            self.assertIn("organic", repairs[0].tags)


class ApplyTests(unittest.TestCase):
    def test_apply_drops_only_the_losing_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "base-types" / "a.json"
            _write(path, _base_type_doc("item.a-001", ["defensive", "utility", "organic"]))
            repair = repair_mod.TagAxisRepair(
                entry_id="item.a-001", path=path, kind="base-type",
                tags=("defensive", "utility", "organic"),
                conflicts=(("combat-posture", ("defensive", "utility")),), context={})

            changed = repair_mod.apply({"item.a-001": ("defensive", "organic")}, (repair,), write=True)
            self.assertEqual(changed, (path,))
            row = json.loads(path.read_text(encoding="utf-8"))["entries"][0]
            self.assertEqual(row["tags"], ["defensive", "organic"])
            self.assertEqual(row["name"], "Ward Buckler")  # untouched


class ResolvedTagsTests(unittest.TestCase):
    def test_resolved_tags_preserves_order_and_drops_only_losers(self) -> None:
        repair = repair_mod.TagAxisRepair(
            entry_id="item.a-001", path=Path("x.json"), kind="base-type",
            tags=("organic", "defensive", "utility", "sturdy"),
            conflicts=(("combat-posture", ("defensive", "utility")),), context={})
        result = repair_mod.resolved_tags(repair, {"combat-posture": "utility"})
        self.assertEqual(result, ("organic", "utility", "sturdy"))


class RunBatchTests(unittest.TestCase):
    def test_the_model_choice_is_kept_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "base-types" / "a.json"
            _write(path, _base_type_doc("item.a-001", ["defensive", "utility"]))
            repairs = repair_mod.plan(root, found=(repair_mod.TagAxisFinding(
                "item.a-001", "base-types/a.json",
                "axis 'combat-posture' is exclusive but carries 2 tags: defensive, utility"),))

            def fake_caller(_prompt: str, _schema: dict) -> dict:
                return {"keep": "defensive"}

            answers, failed = repair_mod.run_batch(repairs, caller=fake_caller)
            self.assertEqual(failed, [])
            self.assertEqual(answers, {"item.a-001": ("defensive",)})

    def test_an_out_of_set_answer_is_refused_and_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "base-types" / "a.json"
            _write(path, _base_type_doc("item.a-001", ["defensive", "utility"]))
            repairs = repair_mod.plan(root, found=(repair_mod.TagAxisFinding(
                "item.a-001", "base-types/a.json",
                "axis 'combat-posture' is exclusive but carries 2 tags: defensive, utility"),))

            attempts: list[dict] = []

            def flaky_caller(_prompt: str, _schema: dict) -> dict:
                attempts.append({})
                if len(attempts) == 1:
                    return {"keep": "offensive"}  # not one of the two conflicting tags -- refused
                return {"keep": "utility"}

            answers, failed = repair_mod.run_batch(repairs, caller=flaky_caller)
            self.assertEqual(failed, [])
            self.assertEqual(answers, {"item.a-001": ("utility",)})
            self.assertEqual(len(attempts), 2)


class GemSyncTests(unittest.TestCase):
    def test_gem_tags_are_copied_from_the_resolved_family_not_asked_separately(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "gems" / "g1.json"
            _write(path, {"schemaVersion": 1, "kind": "gem", "_meta": {"batch": "t", "partition": "p"},
                         "entries": [{"id": "gem.g1-001", "name": "Ember Core",
                                     "family": "atom.evd-evd", "tags": ["defensive", "utility"]}]})
            gem_repair = repair_mod.TagAxisRepair(
                entry_id="gem.g1-001", path=path, kind="gem",
                tags=("defensive", "utility"), conflicts=(("combat-posture", ("defensive", "utility")),),
                context={}, source_family_id="atom.evd-evd")

            changed = repair_mod.sync_gem_from_family(gem_repair, ("defensive",), write=True)
            self.assertEqual(changed, path)
            row = json.loads(path.read_text(encoding="utf-8"))["entries"][0]
            self.assertEqual(row["tags"], ["defensive"])

    def test_sync_is_a_noop_when_already_matching(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "gems" / "g1.json"
            _write(path, {"schemaVersion": 1, "kind": "gem", "entries": [
                {"id": "gem.g1-001", "tags": ["defensive"]}]})
            gem_repair = repair_mod.TagAxisRepair(
                entry_id="gem.g1-001", path=path, kind="gem", tags=("defensive",),
                conflicts=(), context={}, source_family_id="atom.evd-evd")
            self.assertIsNone(repair_mod.sync_gem_from_family(gem_repair, ("defensive",), write=True))


if __name__ == "__main__":
    unittest.main()
