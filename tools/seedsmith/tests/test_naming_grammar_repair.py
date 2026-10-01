"""Tests for the shared naming-grammar prompt text and its model-authored repair pipeline
(item-seed-regen cause 3).

    python -m pytest gk-forge/tools/seedsmith/tests/test_naming_grammar_repair.py -q
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.naming_grammar import NAMING_GRAMMAR_RULES  # noqa: E402
from seedsmith.adapters.items import naming_grammar_repair as repair_mod  # noqa: E402
from seedsmith.adapters.items.setgen import name_repair as name_repair_mod  # noqa: E402
from seedsmith.workspace_roots import RootNotFound  # noqa: E402

_NUMBER_WORDS = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


class NamingGrammarRulesTextTests(unittest.TestCase):
    """`combogen.brief`'s own `spells_the_count` guard refuses a brief that spells a per-cell
    ingredient count (1-10) as digits or as an English number word, outside a numbered-list marker
    line. This shared text is embedded verbatim into that brief (and four siblings), so it must
    never contain a spelled number or a bare digit 1-10 that is not part of a `A.`/`B.`/`C.`
    non-numeric marker -- found live: an earlier draft's "two words" / "a four-part name" raised
    `BriefRefused` the moment it reached combogen's own test suite.
    """

    def test_contains_no_spelled_number_word(self) -> None:
        lowered = NAMING_GRAMMAR_RULES.lower()
        hits = [w for w in _NUMBER_WORDS if re.search(rf"\b{w}\b", lowered)]
        self.assertEqual(hits, [], f"naming grammar rules text spells a number word: {hits}")

    def test_contains_no_bare_digit_one_through_ten(self) -> None:
        hits = re.findall(r"(?<!\.)\b([1-9]|10)\b(?!\.)", NAMING_GRAMMAR_RULES)
        self.assertEqual(hits, [], f"naming grammar rules text contains a bare digit: {hits}")


def _write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _set_doc(entry_id: str, name: str) -> dict:
    return {"schemaVersion": 1, "kind": "set", "_meta": {"batch": "t", "partition": "p"},
            "entries": [{"id": entry_id, "nameKey": "set.old", "name": name}]}


class BriefTests(unittest.TestCase):
    def test_brief_has_a_real_default_for_refused_not_a_string_literal_one(self) -> None:
        # Regression: `refused: "tuple[str, ...] = ()"` (the WHOLE thing quoted) is a string
        # annotation with no real default -- `brief(repair)` then raises TypeError. Caught only by
        # calling it without the keyword, not by reading the signature.
        repair = repair_mod.NamingGrammarRepair(
            entry_id="set.a-001", path=Path("sets/a.json"), kind="set",
            old_name="Old Name", codes=("NameGrammarViolation",))
        text = repair_mod.brief(repair)
        self.assertIn("Old Name", text)
        self.assertNotIn("were refused", text)


class PlanTests(unittest.TestCase):
    def test_plan_dedupes_multiple_codes_on_the_same_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "sets" / "a.json", _set_doc("set.a-001", "Kirov's Tethered Husk"))
            found = (
                repair_mod.NamingGrammarFinding("set.a-001", "NameGrammarViolation",
                                                "sets/a.json", "..."),
                repair_mod.NamingGrammarFinding("set.a-001", "PossessiveForbidden",
                                                "sets/a.json", "..."),
                repair_mod.NamingGrammarFinding("set.a-001", "InventedConnective",
                                                "sets/a.json", "..."),
            )
            repairs = repair_mod.plan(root, found=found)
            self.assertEqual(len(repairs), 1)
            self.assertEqual(repairs[0].old_name, "Kirov's Tethered Husk")
            self.assertEqual(repairs[0].codes,
                             ("InventedConnective", "NameGrammarViolation", "PossessiveForbidden"))

    def test_plan_skips_an_entry_the_file_no_longer_contains(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "sets" / "a.json", _set_doc("set.a-001", "Ember Legion"))
            found = (repair_mod.NamingGrammarFinding("set.missing-999", "NameGrammarViolation",
                                                      "sets/a.json", "..."),)
            self.assertEqual(repair_mod.plan(root, found=found), ())


class ValidateAndApplyTests(unittest.TestCase):
    def test_apply_changes_only_the_name_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "sets" / "a.json"
            _write(path, _set_doc("set.a-001", "Kirov's Tethered Husk"))
            repairs = (repair_mod.NamingGrammarRepair(
                entry_id="set.a-001", path=path, kind="set",
                old_name="Kirov's Tethered Husk", codes=("PossessiveForbidden",)),)

            changed = repair_mod.apply({"set.a-001": "Tethered Husk"}, repairs, write=True)
            self.assertEqual(changed, (path,))
            row = json.loads(path.read_text(encoding="utf-8"))["entries"][0]
            self.assertEqual(row["name"], "Tethered Husk")
            self.assertEqual(row["nameKey"], "set.old")  # untouched — a separate, unvalidated field
            self.assertEqual(row["id"], "set.a-001")

    def test_validate_answer_refuses_an_empty_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repair = repair_mod.NamingGrammarRepair(
                entry_id="set.a-001", path=root / "sets" / "a.json", kind="set",
                old_name="Old Name", codes=("NameGrammarViolation",))
            with self.assertRaises(ValueError):
                repair_mod.validate_answer(repair, {"name": "  "}, items_root=root)

    def test_validate_answer_refuses_the_unchanged_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repair = repair_mod.NamingGrammarRepair(
                entry_id="set.a-001", path=root / "sets" / "a.json", kind="set",
                old_name="Old Name", codes=("NameGrammarViolation",))
            with self.assertRaises(ValueError):
                repair_mod.validate_answer(repair, {"name": "Old Name"}, items_root=root)

    def test_validate_answer_refuses_a_name_already_shipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "sets" / "existing.json", _set_doc("set.existing-001", "Ember Legion"))
            repair = repair_mod.NamingGrammarRepair(
                entry_id="set.a-001", path=root / "sets" / "a.json", kind="set",
                old_name="Old Name", codes=("NameGrammarViolation",))
            with self.assertRaises(ValueError):
                repair_mod.validate_answer(repair, {"name": "Ember Legion"}, items_root=root)


class RunBatchTests(unittest.TestCase):
    def test_a_good_first_answer_needs_no_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "sets" / "a.json"
            _write(path, _set_doc("set.a-001", "Kirov's Tethered Husk"))
            repairs = repair_mod.plan(root, found=(
                repair_mod.NamingGrammarFinding("set.a-001", "PossessiveForbidden",
                                                "sets/a.json", "..."),))

            calls: list[str] = []

            def fake_caller(prompt: str, _schema: dict) -> dict:
                calls.append(prompt)
                return {"name": "Tethered Husk"}

            answers, failed = repair_mod.run_batch(repairs, caller=fake_caller, items_root=root)
            self.assertEqual(answers, {"set.a-001": "Tethered Husk"})
            self.assertEqual(failed, [])
            self.assertEqual(len(calls), 1)

    def test_a_refused_answer_retries_with_the_refusal_named(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "sets" / "a.json"
            _write(path, _set_doc("set.a-001", "Kirov's Tethered Husk"))
            repairs = repair_mod.plan(root, found=(
                repair_mod.NamingGrammarFinding("set.a-001", "PossessiveForbidden",
                                                "sets/a.json", "..."),))

            attempts: list[dict] = []

            def flaky_caller(prompt: str, _schema: dict) -> dict:
                attempts.append({"prompt": prompt})
                if len(attempts) == 1:
                    return {"name": "Kirov's Tethered Husk"}  # unchanged -- refused
                return {"name": "Tethered Husk"}

            answers, failed = repair_mod.run_batch(repairs, caller=flaky_caller, items_root=root)
            self.assertEqual(answers, {"set.a-001": "Tethered Husk"})
            self.assertEqual(failed, [])
            self.assertEqual(len(attempts), 2)
            self.assertIn("Kirov's Tethered Husk", attempts[1]["prompt"])

    def test_exhausting_retries_reports_failure_not_a_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "sets" / "a.json"
            _write(path, _set_doc("set.a-001", "Kirov's Tethered Husk"))
            repairs = repair_mod.plan(root, found=(
                repair_mod.NamingGrammarFinding("set.a-001", "PossessiveForbidden",
                                                "sets/a.json", "..."),))

            def always_bad_caller(_prompt: str, _schema: dict) -> dict:
                return {"name": ""}

            answers, failed = repair_mod.run_batch(
                repairs, caller=always_bad_caller, items_root=root, max_attempts=2)
            self.assertEqual(answers, {})
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0]["entryId"], "set.a-001")

    def test_a_transport_failure_is_reported_and_does_not_abort_the_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "sets" / "a.json", _set_doc("set.a-001", "Kirov's Tethered Husk"))
            _write(root / "sets" / "b.json", _set_doc("set.b-002", "The Maw's Hunger"))
            repairs = repair_mod.plan(root, found=(
                repair_mod.NamingGrammarFinding("set.a-001", "PossessiveForbidden",
                                                "sets/a.json", "..."),
                repair_mod.NamingGrammarFinding("set.b-002", "PossessiveForbidden",
                                                "sets/b.json", "..."),
            ))

            def one_fails_caller(prompt: str, _schema: dict) -> dict:
                if "set.a-001" in prompt:
                    raise RuntimeError("transport timeout")
                return {"name": "Maw's Bounty".replace("'", "")}

            answers, failed = repair_mod.run_batch(repairs, caller=one_fails_caller, items_root=root)
            self.assertEqual(answers, {"set.b-002": "Maws Bounty"})
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0]["entryId"], "set.a-001")
            self.assertIn("transport timeout", failed[0]["reason"])


class ValidatorProjectResolutionTests(unittest.TestCase):
    """⛔ `findings()` is this module's only door onto real data, and it opens by locating
    `ItemSeedValidator`. Measured on the real workspace, that helper returned None and every call
    refused with `ItemSeedValidator project not found near
    <gk-data>/packs/fusion/data/seed/items` -- while gk-forge's
    `tools/ItemSeedValidator/ItemSeedValidator.csproj` was present and resolvable.

    The corpus root and the validator are in SIBLING repositories, so no number of `..` hops from
    one reaches the other: the walk up from the pack exhausts itself. These tests plant the two
    roots in unrelated temporary directories, so they fail on the walk-only shape without depending
    on where this checkout happens to live."""

    def test_resolves_through_the_resolver_when_the_walk_cannot_reach_a_sibling_repository(self):
        with tempfile.TemporaryDirectory() as forge, tempfile.TemporaryDirectory() as pack:
            project = Path(forge) / "tools" / "ItemSeedValidator" / "ItemSeedValidator.csproj"
            project.parent.mkdir(parents=True)
            project.write_text("<Project />", encoding="utf-8")
            corpus = Path(pack) / "packs" / "fusion" / "data" / "seed" / "items"
            corpus.mkdir(parents=True)
            with patch.object(repair_mod, "forge_root", return_value=Path(forge)):
                found = repair_mod._default_validator_project(corpus)
            self.assertEqual(found, project)

    def test_the_walk_still_wins_when_an_ancestor_carries_the_project(self):
        """Nearest-match: a legacy monorepo clone and a planted fixture both resolve by the walk, so
        the resolver must be consulted only after it, never instead of it."""
        with tempfile.TemporaryDirectory() as monorepo, tempfile.TemporaryDirectory() as forge:
            walked = Path(monorepo) / "tools" / "ItemSeedValidator" / "ItemSeedValidator.csproj"
            walked.parent.mkdir(parents=True)
            walked.write_text("<Project />", encoding="utf-8")
            other = Path(forge) / "tools" / "ItemSeedValidator" / "ItemSeedValidator.csproj"
            other.parent.mkdir(parents=True)
            other.write_text("<Project />", encoding="utf-8")
            corpus = Path(monorepo) / "data" / "seed" / "items"
            corpus.mkdir(parents=True)
            with patch.object(repair_mod, "forge_root", return_value=Path(forge)):
                found = repair_mod._default_validator_project(corpus)
            self.assertEqual(found, walked)

    def test_absent_gk_forge_preserves_the_none_answer_rather_than_inventing_a_path(self):
        """`forge_root` RAISES when gk-forge is absent. That is the same absence the walk already
        reported, so it is caught and None is preserved -- `findings()` then raises its own clear
        `RepairRefused`. Nothing here may fabricate a path that does not exist."""
        with tempfile.TemporaryDirectory() as pack:
            corpus = Path(pack) / "data" / "seed" / "items"
            corpus.mkdir(parents=True)

            def absent(_start=None):
                raise RootNotFound("gk-forge is not present")

            with patch.object(repair_mod, "forge_root", absent):
                self.assertIsNone(repair_mod._default_validator_project(corpus))

    def test_the_resolver_and_the_sibling_agree_on_where_the_validator_is(self):
        """This helper is a COPY of `name_repair`'s. The copy is how it silently lost the
        `forge_root` fallback and left one module refusing while its twin worked, so the invariant
        that matters is that the two cannot drift into disagreeing about the validator's location."""
        root = Path(repair_mod.ITEM_SEED_ROOT)
        self.assertEqual(repair_mod._default_validator_project(root),
                         name_repair_mod._default_validator_project(root))


if __name__ == "__main__":
    unittest.main()
