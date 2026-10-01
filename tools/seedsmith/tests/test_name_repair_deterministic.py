"""The DETERMINISTIC name-repair path in `setgen/name_repair.py`: derived from a row's own fields,
never from a model.

The model path (`brief`/`validate_answers`/`apply`) cannot repair this corpus — its own docstring
records the measured loop where a local model handed back the keeper's idea in another word order —
so `derive_names` builds each losing row's replacement from `scopeKey`/`slot`/`speciesId`/`tags` and
asks the C# authority (`validator_keys`, `--normalize-names`) and the authority's own grammar
(`name_defects`, `--check-names`) about every candidate it considers.

**What these tests do and do not prove.** The unit tests below run on a synthetic corpus with an
INJECTED `key_of`/`defects_of`, which is a deliberately naive stand-in — a test double, never the
authority. They prove the ladder, the refusals and the field-level write. The one live test proves
the part a double cannot: that on the real corpus every derived name is unique under the validator's
OWN normalizer and clean under its OWN grammar. Neither substitutes for the other, and no test here
re-implements `naming.v1.json`'s collision rule and then calls it the rule.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.setgen import name_repair  # noqa: E402


def naive_key(name: str) -> str:
    """A TEST DOUBLE for `validator_keys`: casefold, tokenize, sort. No connectives dropped, no
    surface-form resolution, no fusion split. Deliberately cruder than `NameNormalizer`, so a test
    that passes here has not quietly come to depend on the authority's exact algorithm."""
    return " ".join(sorted(re.findall(r"[a-z0-9]+", name.casefold())))


def keys_of(names):
    return {name: naive_key(name) for name in names}


def clean_defects(_names):
    return {}


def write_document(root: Path, relative: str, kind: str, rows: list[dict]) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schemaVersion": 1, "kind": kind, "entries": rows}, indent=2),
                    encoding="utf-8")
    return path


def material_row(entry_id: str, name: str, **overrides) -> dict:
    row = {"id": entry_id, "nameKey": f"material.trophy-family-oak-{overrides.get('slot', 1)}",
           "name": name, "runtimeId": "trophy.family.oak.1", "materialClass": "trophy",
           "scope": "family", "scopeKey": "oak", "slot": 1,
           "iconKey": f"icon.material.trophy-family-oak-{overrides.get('slot', 1)}",
           "tags": ["organic", "sturdy"], "flavor": "unchanged"}
    row.update(overrides)
    return row


def group(key: str, members: list[tuple[str, str]]) -> list[dict]:
    return [{"reason": "name", "key": key,
             "members": [{"id": i, "name": n, "kind": "material"} for i, n in members]}]


class DerivedCandidateTests(unittest.TestCase):
    """The ladder is a pure function of the row — same input, same output, no corpus, no model."""

    def test_a_material_candidate_carries_the_rows_own_slot_ordinal_and_scope_key(self) -> None:
        names = [name for name, _rule in name_repair.derived_name_candidates(
            material_row("material.001", "Verdant Lineage", slot=5, scopeKey="botany"), "material")]
        self.assertIn("Fifth Lineage", names)
        self.assertIn("Lineage of the Fifth Botany", names)
        self.assertIn("Botany Lineage", names)
        self.assertIn("Lineage of the Fifth Sturdy", names)
        # The first rung is the one the corpus already speaks for a family's trophies.
        self.assertEqual(names[0], "Fifth Lineage")
        # A `runtimeId`-shaped qualifier is never printed: an id in a display name is the defect the
        # model brief forbids, and `NamingCheck.Word` would not accept it anyway.
        self.assertFalse([n for n in names if "-" in n])

    def test_a_set_candidate_uses_the_of_construct_with_the_rows_own_species(self) -> None:
        row = {"id": "set.superhypno-001", "name": "Spore of the Bloom", "speciesId": "superhypno",
               "themeKey": "creature.superhypno", "setClass": "general", "nameKey": "set.old"}
        names = [name for name, _rule in name_repair.derived_name_candidates(row, "set")]
        self.assertEqual(names[0], "Spore of the Superhypno")

    def test_a_head_noun_already_inside_the_qualifier_is_replaced_by_the_other_noun(self) -> None:
        row = {"id": "set.ultimatecabbagecannon-001", "name": "Cabbage of the Mortar",
               "speciesId": "ultimatecabbagecannon", "setClass": "general", "nameKey": "set.old"}
        names = [name for name, _rule in name_repair.derived_name_candidates(row, "set")]
        self.assertEqual(names[0], "Mortar of the Ultimatecabbagecannon")

    def test_the_ordinal_of_a_multi_word_name_is_not_mistaken_for_the_head_noun(self) -> None:
        # "Second Seal of Lineage" is a SEAL; reading the first word would name the row a "Second".
        names = [name for name, _rule in name_repair.derived_name_candidates(
            material_row("material.002", "The Second Seal of Lineage", slot=2, scopeKey="officer"),
            "material")]
        self.assertIn("Second Seal", names)

    def test_the_candidate_list_is_identical_on_every_call(self) -> None:
        row = material_row("material.003", "Ancestral Sap", slot=4, scopeKey="organic")
        first = name_repair.derived_name_candidates(row, "material")
        second = name_repair.derived_name_candidates(json.loads(json.dumps(row)), "material")
        self.assertEqual(first, second)

    def test_candidates_the_authoritys_grammar_would_refuse_are_never_offered(self) -> None:
        # `of`/`the` are the only lowercase words a name may carry; a hyphen or a dot is a key, not a
        # word; and a single word is read as a fusion that must decompose into two pool words.
        for rejected in ("Lineage of the family oak", "Lineage of the Trophy-Family-Oak",
                         "Lineage of the Trophy.Family.Oak", "of the Oak", "Lineage",
                         "Lineage and Seal"):
            with self.subTest(name=rejected):
                self.assertFalse(name_repair._acceptable_candidate(rejected))
        # `<Base> of [the] <Concept>` is a legal shape with a ONE-word concept, so this one is legal.
        for accepted in ("Fifth Lineage", "Lineage of the Fifth Botany", "Spore of the Superhypno",
                         "Lineage of the Eighth Carriers", "Lineage of the Fifth"):
            with self.subTest(name=accepted):
                self.assertTrue(name_repair._acceptable_candidate(accepted))


class DerivationTests(unittest.TestCase):
    """`derive_names`: the ladder is walked against the authority's keys, and every refusal is loud."""

    def _root(self, temporary: str, rows: list[dict]) -> Path:
        root = Path(temporary)
        write_document(root, "materials/materials.json", "material", rows)
        return root

    def test_the_losing_row_is_renamed_and_the_keeper_is_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary, [
                material_row("material.001", "Verdant Lineage", slot=1, scopeKey="bamboo"),
                material_row("material.002", "Verdant Lineage", slot=5, scopeKey="botany")])
            repairs = name_repair.plan(
                root, groups=group("verdant lineage",
                                   [("material.001", "Verdant Lineage"),
                                    ("material.002", "Verdant Lineage")]))
            derived = name_repair.derive_names(repairs, items_root=root, key_of=keys_of,
                                               defects_of=clean_defects)
            self.assertEqual([(d.entry_id, d.new_name) for d in derived],
                             [("material.002", "Fifth Lineage")])

    def test_a_candidate_reusing_the_old_ideas_key_is_skipped_for_the_next_rung(self) -> None:
        """`Fifth Lineage` is taken here, so the row must move to the rung that still says which
        family it is — silently reusing a spoken-for idea is how a repair mints a new collision."""
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary, [
                material_row("material.001", "Verdant Lineage", slot=5, scopeKey="botany"),
                material_row("material.002", "Verdant Lineage", slot=5, scopeKey="botany"),
                material_row("material.900", "Fifth Lineage", slot=1, scopeKey="oak")])
            repairs = name_repair.plan(
                root, groups=group("verdant lineage",
                                   [("material.001", "Verdant Lineage"),
                                    ("material.002", "Verdant Lineage")]))
            derived = name_repair.derive_names(repairs, items_root=root, key_of=keys_of,
                                               defects_of=clean_defects)
            self.assertEqual([d.new_name for d in derived], ["Lineage of the Fifth Botany"])

    def test_two_losing_rows_of_one_cluster_never_receive_the_same_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary, [
                material_row("material.001", "Verdant Lineage", slot=2, scopeKey="vegetation"),
                material_row("material.002", "Verdant Lineage", slot=3, scopeKey="vegetation"),
                material_row("material.003", "Verdant Lineage", slot=5, scopeKey="vegetation")])
            repairs = name_repair.plan(
                root, groups=group("verdant lineage",
                                   [("material.001", "Verdant Lineage"),
                                    ("material.002", "Verdant Lineage"),
                                    ("material.003", "Verdant Lineage")]))
            derived = name_repair.derive_names(repairs, items_root=root, key_of=keys_of,
                                               defects_of=clean_defects)
            names = [d.new_name for d in derived]
            # `material.001` is the keeper and keeps its name; the two losers separate by their own
            # slot ordinals.
            self.assertEqual(names, ["Third Lineage", "Fifth Lineage"])
            self.assertEqual(len(set(naive_key(n) for n in names)), len(names), names)

    def test_a_row_whose_whole_ladder_is_taken_is_refused_by_name(self) -> None:
        """The refusal must NAME the row: a repair that writes a colliding name to avoid a crash is
        worse than one that stops."""
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary, [
                material_row("material.001", "Verdant Lineage", slot=5, scopeKey="botany"),
                material_row("material.002", "Verdant Lineage", slot=5, scopeKey="botany")])
            repairs = name_repair.plan(
                root, groups=group("verdant lineage",
                                   [("material.001", "Verdant Lineage"),
                                    ("material.002", "Verdant Lineage")]))
            with self.assertRaisesRegex(RuntimeError, "material.002: every derived candidate"):
                name_repair.derive_names(repairs, items_root=root,
                                         key_of=lambda names: {n: "one key" for n in names},
                                         defects_of=clean_defects)

    def test_a_name_the_authoritys_grammar_rejects_is_refused_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary, [
                material_row("material.001", "Verdant Lineage", slot=5, scopeKey="botany"),
                material_row("material.002", "Verdant Lineage", slot=5, scopeKey="botany")])
            repairs = name_repair.plan(
                root, groups=group("verdant lineage",
                                   [("material.001", "Verdant Lineage"),
                                    ("material.002", "Verdant Lineage")]))
            with self.assertRaisesRegex(RuntimeError, "rejected by the authority's own grammar"):
                name_repair.derive_names(
                    repairs, items_root=root, key_of=keys_of,
                    defects_of=lambda names: {n: ["name: invented connective"] for n in names})
            self.assertIn("Verdant Lineage",
                          json.loads((root / "materials/materials.json").read_text(
                              encoding="utf-8"))["entries"][1]["name"],
                          "a refused derivation must not have written anything")

    def test_the_result_is_byte_identical_when_the_derivation_runs_twice(self) -> None:
        rows = [material_row("material.001", "Verdant Lineage", slot=1, scopeKey="bamboo"),
                material_row("material.002", "Verdant Lineage", slot=5, scopeKey="botany"),
                material_row("material.003", "Verdant Lineage", slot=7, scopeKey="grass")]
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary, rows)
            repairs = name_repair.plan(
                root, groups=group("verdant lineage",
                                   [(r["id"], r["name"]) for r in rows]))
            first = name_repair.derive_names(repairs, items_root=root, key_of=keys_of,
                                             defects_of=clean_defects)
            second = name_repair.derive_names(repairs, items_root=root, key_of=keys_of,
                                              defects_of=clean_defects)
            self.assertEqual([d.as_answer() for d in first], [d.as_answer() for d in second])


class DerivedApplyTests(unittest.TestCase):
    """The write: only `name`, and only a `nameKey` that is PROVABLY the slug of the old name."""

    def test_a_runtime_id_derived_material_key_and_icon_are_left_byte_identical(self) -> None:
        """A material's `nameKey` comes from its `runtimeId`, not its name
        (`material.trophy-family-oak-5` beside the name `Verdant Lineage`), and `iconKey` is
        `icon.<nameKey>`. Re-deriving the key from a renamed display string would repoint the icon
        at an identity the row no longer has."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            keeper = material_row("material.001", "Verdant Lineage", slot=1, scopeKey="bamboo")
            loser = material_row("material.002", "Verdant Lineage", slot=5, scopeKey="botany")
            path = write_document(root, "materials/materials.json", "material", [keeper, loser])
            repairs = name_repair.plan(
                root, groups=group("verdant lineage", [(keeper["id"], keeper["name"]),
                                                       (loser["id"], loser["name"])]))
            derived = name_repair.derive_names(repairs, items_root=root, key_of=keys_of,
                                               defects_of=clean_defects)
            self.assertEqual([d.entry_id for d in derived], ["material.002"])
            name_repair.apply_derived(derived, write=True, items_root=root)
            rows = {row["id"]: row for row in json.loads(path.read_text(encoding="utf-8"))["entries"]}
            self.assertEqual(rows["material.001"], keeper, "the keeper must not be touched")
            row = rows["material.002"]
            self.assertEqual(row["name"], "Fifth Lineage")
            self.assertEqual(row["nameKey"], "material.trophy-family-oak-5")
            self.assertEqual(row["iconKey"], "icon.material.trophy-family-oak-5")
            for field in ("id", "runtimeId", "materialClass", "scope", "scopeKey", "slot", "tags",
                          "flavor"):
                self.assertEqual(row[field], loser[field], field)

    def test_a_name_derived_set_key_moves_with_the_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            keeper = {"id": "set.cherrytorch-001", "name": "Torch of the Stump",
                      "nameKey": "set.torch-of-the-stump", "speciesId": "cherrytorch"}
            loser = {"id": "set.nuttorch-001", "name": "Stump of the Torch",
                     "nameKey": "set.stump-of-the-torch", "speciesId": "nuttorch"}
            path = write_document(root, "sets/sets.json", "set", [keeper, loser])
            repairs = name_repair.plan(
                root, groups=[{"reason": "name", "key": "stump torch the",
                               "members": [{"id": keeper["id"], "name": keeper["name"],
                                            "kind": "set"},
                                           {"id": loser["id"], "name": loser["name"],
                                            "kind": "set"}]}])
            derived = name_repair.derive_names(repairs, items_root=root, key_of=keys_of,
                                               defects_of=clean_defects)
            self.assertEqual([d.new_name for d in derived], ["Stump of the Nuttorch"])
            name_repair.apply_derived(derived, write=True, items_root=root)
            rows = {row["id"]: row for row in json.loads(path.read_text(encoding="utf-8"))["entries"]}
            self.assertEqual(rows["set.nuttorch-001"]["nameKey"], "set.stump-of-the-nuttorch")
            self.assertEqual(rows["set.cherrytorch-001"], keeper, "the keeper must not be touched")

    def test_a_disambiguated_key_is_not_overwritten_by_the_rename(self) -> None:
        """`set.spike-king-s-thicket` is the name's slug PLUS a disambiguation suffix
        (`naming.v1.json nameKey.disambiguationRule`). It is not the pure slug, so the rename leaves
        it alone rather than guessing what the suffix was standing in for."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            keeper = {"id": "set.firespikerock-001", "name": "Spike of the King",
                      "nameKey": "set.spike-of-the-king", "speciesId": "firespikerock"}
            loser = {"id": "set.spikerock-001", "name": "Spike King",
                     "nameKey": "set.spike-king-s-thicket", "speciesId": "spikerock"}
            path = write_document(root, "sets/sets.json", "set", [keeper, loser])
            repairs = name_repair.plan(
                root, groups=[{"reason": "name", "key": "king spike",
                               "members": [{"id": keeper["id"], "name": keeper["name"],
                                            "kind": "set"},
                                           {"id": loser["id"], "name": loser["name"],
                                            "kind": "set"}]}])
            derived = name_repair.derive_names(repairs, items_root=root, key_of=keys_of,
                                               defects_of=clean_defects)
            name_repair.apply_derived(derived, write=True, items_root=root)
            row = {row["id"]: row for row in json.loads(path.read_text(encoding="utf-8"))["entries"]}
            self.assertEqual(row["set.spikerock-001"]["name"], "King of the Spikerock")
            self.assertEqual(row["set.spikerock-001"]["nameKey"], "set.spike-king-s-thicket")


class RealCorpusDerivationTests(unittest.TestCase):
    """The live half: the real corpus, the REAL authority. No skip and no double — a test that
    degrades to comparing nothing when the SDK is missing is a worse guard than a loud failure."""

    def test_every_derived_name_is_unique_and_grammar_clean_under_the_authority(self) -> None:
        repairs = name_repair.plan()
        derived = name_repair.derive_names(repairs)
        self.assertEqual(len(derived), len(repairs), "every planned row needs a derived name")
        keys = name_repair.validator_keys([d.new_name for d in derived])
        self.assertTrue(all(keys.values()), "a derived name that normalizes to nothing is unsluggable")
        self.assertEqual(len(set(keys.values())), len(keys),
                         "two derived names normalize to one idea: the repair would mint a collision")
        # The authority's own grammar, on the names this module chose.
        defects = name_repair.name_defects([d.new_name for d in derived])
        self.assertEqual({name: found for name, found in defects.items() if found}, {})
        # And each derived name must be a NEW key, not the row's own old idea re-spelled.
        old_keys = name_repair.validator_keys([d.old_name for d in derived])
        for entry in derived:
            self.assertNotEqual(keys[entry.new_name], old_keys[entry.old_name],
                                f"{entry.entry_id}: {entry.new_name!r} is the old name's own idea")


class TempCopyAcceptanceTests(unittest.TestCase):
    """The acceptance gate, executed on a TEMP COPY of the real corpus — never on the shipped one.

    Two gates, because they are two different comparisons and clearing one is not clearing the
    other: `ItemSeedValidator --collision-groups` (the authority: lowercase, tokenize, whole-token
    resolution, DROP the four connectives, sort) and the key `test_authored_item_names_are_unique_
    across_kinds` used before it was corrected to the authority (`: sorted(re.findall(r"[a-z0-9]+",
    name.casefold()))` over non-exempt kinds, dropping nothing). The retired key FINDS LESS, so a
    repair proved only against the authority has not been proved against anything else.
    """

    EXEMPT_KINDS = frozenset({"display-template", "curve", "recipe"})

    def setUp(self) -> None:
        import shutil
        temporary = tempfile.mkdtemp(prefix="gk-name-repair-")
        self.addCleanup(shutil.rmtree, temporary, ignore_errors=True)
        self.root = Path(temporary) / "items"
        shutil.copytree(name_repair.ITEM_SEED_ROOT, self.root)

    def retired_key_groups(self) -> "dict[str, list]":
        """The retired Python key's own groups, over the kinds it covered. A TEST-SIDE reading, and
        the only place in this file that computes one: it is the second gate, not the rule."""
        groups: dict[str, list] = {}
        for path in sorted(self.root.glob("**/*.json")):
            if path.name.startswith("_") or "_exemplars" in path.parts or "_runs" in path.parts:
                continue
            document = json.loads(path.read_text(encoding="utf-8"))
            if document.get("kind") in self.EXEMPT_KINDS:
                continue
            for row in document.get("entries") or ():
                if not isinstance(row, dict) or not isinstance(row.get("name"), str):
                    continue
                key = " ".join(sorted(re.findall(r"[a-z0-9]+", row["name"].casefold())))
                groups.setdefault(key, []).append((row.get("id"), row.get("name")))
        return {key: rows for key, rows in groups.items() if len(rows) > 1}

    def test_the_derivation_clears_both_keys_on_a_temp_copy_of_the_real_corpus(self) -> None:
        before = name_repair.collision_groups(items_root=self.root)
        self.assertTrue(before, "the live corpus is expected to carry collisions for this repair")
        report = name_repair.repair_names_deterministically(items_root=self.root, write=True)
        self.assertEqual(len(report["derived"]), sum(len(g.get("members") or ()) - 1
                                                     for g in before if len(g.get("members") or ()) > 1),
                         "every losing row the authority reports must be derived exactly once")
        after = name_repair.collision_groups(items_root=self.root)
        self.assertEqual(after, [], f"{len(after)} collision group(s) survive the derivation")
        self.assertEqual(self.retired_key_groups(), {},
                         "the retired Python key still sees a duplicate name: the authority's "
                         "connective drop is what it cannot see, so this is the other half of the "
                         "same defect")

    def test_a_planted_collision_is_caught_and_repaired(self) -> None:
        """Nothing has ever shown CATCHING a planted defect. Two rows, one name, planted in the temp
        copy: the authority must report it, and the derivation must rename the loser — proving the
        detection above is real rather than a comparison that matches nothing."""
        planted = "Gilded Vigil Crest"
        path = self.root / "materials" / "materials.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        victims = [row for row in document["entries"]
                   if isinstance(row, dict) and row.get("id") in ("material.3631", "material.3632")]
        self.assertEqual(len(victims), 2, "the planted rows must exist for this to mean anything")
        for row in victims:
            row["name"] = planted
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        groups = name_repair.collision_groups(items_root=self.root)
        planted_groups = [g for g in groups
                          if {m.get("id") for m in g.get("members") or ()} ==
                          {"material.3631", "material.3632"}]
        self.assertEqual(len(planted_groups), 1,
                         f"the planted collision was not reported as one group: {groups}")
        self.assertEqual(planted_groups[0].get("key"), "crest gilded vigil")

        report = name_repair.repair_names_deterministically(items_root=self.root, write=True)
        renamed = {row["entryId"]: row["newName"] for row in report["derived"]}
        self.assertIn("material.3632", renamed, "the lexically later row must be the one renamed")
        self.assertNotEqual(renamed["material.3632"], planted)
        rows = {row["id"]: row for row in json.loads(path.read_text(encoding="utf-8"))["entries"]}
        self.assertEqual(rows["material.3631"]["name"], planted, "the keeper keeps the planted name")
        self.assertEqual(name_repair.collision_groups(items_root=self.root), [],
                         "the planted collision was not repaired")


if __name__ == "__main__":
    unittest.main()
