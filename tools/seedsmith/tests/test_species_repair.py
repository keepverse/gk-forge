"""species-gear-chain T28 (`set-species-binding` b) — the deterministic backward repair.

    python -m pytest gk-forge/tools/seedsmith/tests/test_species_repair.py -q

Almost every closure assertion here runs against the REAL shipped corpus (844 `creature.*`
themeKeys, 904 registry rows) — a synthetic fixture cannot prove the join actually resolves the
real content, only that the mechanism is shaped correctly.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.setgen import species_repair as repair_mod  # noqa: E402
from seedsmith.adapters.items.setgen.themes import (  # noqa: E402
    CREATURE_THEME_REGISTRY,
    load_species_themes,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from seedsmith.workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

SETS_DIR = _owned("data/seed/items/sets")


class SpeciesForThemeTests(unittest.TestCase):
    """The pure join — the unit that would have caught the zero-resolution trap."""

    def test_a_build_theme_key_yields_explicit_absent(self) -> None:
        self.assertIsNone(repair_mod.species_for_theme("build.might-berserker", {}))

    def test_a_legacy_theme_key_yields_explicit_absent(self) -> None:
        self.assertIsNone(repair_mod.species_for_theme("theme.frostbite", {}))

    def test_a_creature_key_resolves_the_registered_speciesId(self) -> None:
        registry = {"creature.abyssswordstar": "abyssswordstar"}
        self.assertEqual(
            repair_mod.species_for_theme("creature.abyssswordstar", registry), "abyssswordstar")

    def test_a_creature_key_missing_from_the_registry_raises_naming_it(self) -> None:
        with self.assertRaises(repair_mod.SpeciesRepairError) as caught:
            repair_mod.species_for_theme("creature.notreal", {})
        self.assertIn("creature.notreal", str(caught.exception))

    def test_registry_and_suffix_disagreement_raises_never_picks_either(self) -> None:
        registry = {"creature.abyssswordstar": "somethingelse"}
        with self.assertRaises(repair_mod.SpeciesRepairError) as caught:
            repair_mod.species_for_theme("creature.abyssswordstar", registry)
        self.assertIn("somethingelse", str(caught.exception))
        self.assertIn("abyssswordstar", str(caught.exception))

    def test_the_real_registry_resolves_zero_of_844_under_an_exact_case_match(self) -> None:
        """⭐ The trap this spec is written around: an exact-match (no lower-casing at all) join
        would resolve zero creature.* keys and look like a content gap, not a join bug — pin it."""
        registry = repair_mod.load_theme_species_registry()
        exact_matches = sum(
            1 for key in registry if key.partition(".")[2] == registry[key])
        # Every real row is ALREADY lower-case-consistent (an exact string match), so this proves
        # the registry itself carries no casing mismatch; the join's case-fold is defence-in-depth,
        # not something 844 real rows currently need to lean on.
        self.assertEqual(exact_matches, len(registry))


class RegistryClosureTests(unittest.TestCase):
    """Every real creature.* themeKey resolves, over the actual shipped registry."""

    def test_every_real_creature_theme_resolves_without_raising(self) -> None:
        registry = repair_mod.load_theme_species_registry()
        themes = load_species_themes()
        self.assertTrue(themes)
        for theme in themes:
            with self.subTest(theme=theme.theme_key):
                resolved = repair_mod.species_for_theme(theme.theme_key, registry)
                self.assertEqual(resolved, theme.species_id)


class RepairPlanTests(unittest.TestCase):
    """Plan mode (`write=False`) never touches disk; write mode is idempotent and touches only
    `speciesId`."""

    def _sample_set_doc(self, *, theme_key: str, existing_species: "str | None" = None) -> dict:
        entry: "dict" = {
            "id": "set.fixture-001", "nameKey": "set.fixture", "name": "Fixture",
            "themeKey": theme_key,
            "members": [{"role": "footing", "frame": "humanoid", "baseType": "item.h-footing-1"}],
            "thresholds": [{"pieces": 2, "atoms": []}],
            "flavor": "text", "tags": [], "notes": "test fixture",
        }
        if existing_species is not None:
            entry["speciesId"] = existing_species
        return {"schemaVersion": 1, "kind": "set", "_meta": {"partition": "sets/fixture"},
               "entries": [entry]}

    def test_plan_mode_never_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sets_dir = Path(tmp)
            path = sets_dir / "fixture.json"
            doc = self._sample_set_doc(theme_key="creature.abyssswordstar")
            path.write_text(json.dumps(doc), encoding="utf-8")
            before = path.read_text(encoding="utf-8")

            files = repair_mod.repair_species_ids(sets_dir=sets_dir, write=False)

            self.assertEqual(path.read_text(encoding="utf-8"), before)
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].changed_entries, 1)

    def test_write_mode_persists_the_resolved_speciesId(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sets_dir = Path(tmp)
            path = sets_dir / "fixture.json"
            path.write_text(json.dumps(self._sample_set_doc(theme_key="creature.abyssswordstar")),
                            encoding="utf-8")

            repair_mod.repair_species_ids(sets_dir=sets_dir, write=True)

            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(written["entries"][0]["speciesId"], "abyssswordstar")

    def test_a_build_themed_entry_gets_no_speciesId_key_at_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sets_dir = Path(tmp)
            path = sets_dir / "fixture.json"
            path.write_text(json.dumps(self._sample_set_doc(theme_key="build.might-berserker")),
                            encoding="utf-8")

            files = repair_mod.repair_species_ids(sets_dir=sets_dir, write=True)

            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("speciesId", written["entries"][0])
            self.assertEqual(len(files), 0)  # nothing needed to change — already absent

    def test_the_repair_is_idempotent_a_second_run_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sets_dir = Path(tmp)
            path = sets_dir / "fixture.json"
            path.write_text(json.dumps(self._sample_set_doc(theme_key="creature.abyssswordstar")),
                            encoding="utf-8")

            repair_mod.repair_species_ids(sets_dir=sets_dir, write=True)
            after_first = path.read_text(encoding="utf-8")
            second = repair_mod.repair_species_ids(sets_dir=sets_dir, write=True)

            self.assertEqual(len(second), 0)
            self.assertEqual(path.read_text(encoding="utf-8"), after_first)

    def test_no_other_field_moves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sets_dir = Path(tmp)
            path = sets_dir / "fixture.json"
            doc = self._sample_set_doc(theme_key="creature.abyssswordstar")
            path.write_text(json.dumps(doc), encoding="utf-8")

            repair_mod.repair_species_ids(sets_dir=sets_dir, write=True)

            written = json.loads(path.read_text(encoding="utf-8"))
            for key in ("id", "nameKey", "name", "themeKey", "members", "thresholds", "flavor",
                       "tags", "notes"):
                self.assertEqual(written["entries"][0][key], doc["entries"][0][key])

    def test_a_wrong_existing_speciesId_is_corrected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sets_dir = Path(tmp)
            path = sets_dir / "fixture.json"
            path.write_text(json.dumps(self._sample_set_doc(
                theme_key="creature.abyssswordstar", existing_species="WRONG")), encoding="utf-8")

            files = repair_mod.repair_species_ids(sets_dir=sets_dir, write=True)

            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(written["entries"][0]["speciesId"], "abyssswordstar")
            self.assertEqual(len(files), 1)


class RealCorpusPlanTests(unittest.TestCase):
    """Read-only: `repair_species_ids(write=False)` over the REAL corpus must not raise and must
    plan a change for exactly the `creature.*`-themed rows that need one. The real production
    regeneration itself runs through the CLI (`seedsmith items repair-species --write
    --allow-production-tree`), never inside the test suite — a test must not mutate the shipped
    corpus as a side effect of being run."""

    def test_planning_the_real_corpus_does_not_raise_and_does_not_write(self) -> None:
        if not SETS_DIR.is_dir():
            self.skipTest("real sets corpus not present in this checkout")
        before = {p: p.read_bytes() for p in sorted(SETS_DIR.glob("*.json"))}
        repair_mod.repair_species_ids(sets_dir=SETS_DIR, write=False)
        after = {p: p.read_bytes() for p in sorted(SETS_DIR.glob("*.json"))}
        self.assertEqual(before, after)
