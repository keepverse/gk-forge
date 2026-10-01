"""Tests for seedsmith.adapters.dungeon.registries (D1.5, spec-dungeon-registries.md).

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_registries.py -v

Asserts the Python reader's vocabularies equal the same committed JSON the C# catalogs load
(`DungeonRegistryLoader.LoadAll`) — read fresh from disk on both sides, so the two cannot drift
without this test catching it the same run.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.dungeon.registries import (  # noqa: E402
    ATOMS_DIR,
    BAND_NAMES,
    CREATURES_REGISTRY_DIR,
    ITEMS_REGISTRY_DIR,
    REGISTRY_DIR,
    load_atom_families,
    load_band_display_names,
    load_bands,
    load_difficulty_rungs,
    load_disposition,
    load_door_kinds,
    load_grantable_atom_families,
    load_interaction_verbs,
    load_motifs,
    load_objective_templates,
    load_override_tags,
    load_power_bands,
    load_raid_modes,
    load_room_kinds,
    load_theme_ids,
    load_themes,
    load_versions,
    load_vocabularies,
    load_zomboss_pattern_ids,
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

LIVE_DUNGEON_REGISTRY_ROOT = _owned("data/seed/dungeon/_registry")
# Anchored on a file, for the same reason the module anchors its own directory on one:
# `data/seed/creatures/_registry` exists in gk-forge too, holding `families.v1.json` alone, and
# nearest-match-wins answers that copy - which is missing themes.v1.json and motifs.v1.json.
LIVE_CREATURES_REGISTRY_ROOT = _owned("data/seed/creatures/_registry/themes.v1.json").parent


def _raw(name: str) -> dict:
    return json.loads((LIVE_DUNGEON_REGISTRY_ROOT / name).read_text(encoding="utf-8"))


def _raw_creatures(name: str) -> dict:
    return json.loads((LIVE_CREATURES_REGISTRY_ROOT / name).read_text(encoding="utf-8"))


class RegistryDirTests(unittest.TestCase):
    def test_registry_dir_resolves_to_the_real_committed_folder(self) -> None:
        self.assertEqual(REGISTRY_DIR, LIVE_DUNGEON_REGISTRY_ROOT)
        self.assertTrue(REGISTRY_DIR.is_dir())


class RoomKindTests(unittest.TestCase):
    def test_eleven_room_kinds_matching_the_raw_file(self) -> None:
        kinds = load_room_kinds()
        # The count is fully implied by the set equality below against the real shipped file --
        # never pinned separately (population-pin SE3.5, 2026-09-20).
        self.assertEqual(set(kinds), set(_raw("room-kinds.v1.json")["roomKinds"]))

    def test_exactly_one_boss_row_allowed(self) -> None:
        kinds = load_room_kinds()
        boss_rows = [k for k, row in kinds.items() if row["bossRowAllowed"]]
        self.assertEqual(boss_rows, ["boss"])

    def test_only_unknown_carries_unknownResolvesTo(self) -> None:
        kinds = load_room_kinds()
        for kind_id, row in kinds.items():
            if kind_id == "unknown":
                self.assertEqual(row["unknownResolvesTo"], ["cache", "merchant", "fight"])
            else:
                self.assertEqual(row["unknownResolvesTo"], [])


class DoorKindTests(unittest.TestCase):
    def test_four_door_kinds(self) -> None:
        self.assertEqual(set(load_door_kinds()), {"passage", "gated", "one-way", "secret"})


class OverrideTagTests(unittest.TestCase):
    def test_five_override_tags(self) -> None:
        self.assertEqual(load_override_tags(), frozenset({"herbs", "key", "holy", "bait", "watch"}))


class ObjectiveTemplateTests(unittest.TestCase):
    def test_nine_templates_matching_ideal_11_3(self) -> None:
        templates = load_objective_templates()
        self.assertEqual(set(templates), {
            "explore-rooms", "cleanse-fights", "gather-curio-kind", "kill-boss",
            "extract-with-item-kind", "bring-creature-home-alive", "finish-under-hunger",
            "survive-no-downed", "spend-no-provision",
        })

    def test_sink_avoidance_is_true_on_exactly_three(self) -> None:
        templates = load_objective_templates()
        sink_avoidance = {t for t, row in templates.items() if row["sinkAvoidance"]}
        self.assertEqual(sink_avoidance, {"finish-under-hunger", "survive-no-downed", "spend-no-provision"})


class DifficultyRungTests(unittest.TestCase):
    def test_ten_rungs_ordinals_1_to_10_contiguous(self) -> None:
        rungs = load_difficulty_rungs()
        # The count is fully implied by the sequence equality below -- never pinned separately
        # (population-pin SE3.5, 2026-09-20).
        self.assertEqual(sorted(rungs.values()), list(range(1, 11)))

    def test_hard_is_ordinal_four(self) -> None:
        self.assertEqual(load_difficulty_rungs()["hard"], 4)


class DispositionTests(unittest.TestCase):
    def test_four_dispositions(self) -> None:
        self.assertEqual(load_disposition(), frozenset({"eager", "open", "wary", "hostile"}))


class InteractionVerbTests(unittest.TestCase):
    def test_six_verbs_with_decision_numbers(self) -> None:
        verbs = load_interaction_verbs()
        self.assertEqual(set(verbs), {"open", "disarm", "pray", "loot", "destroy", "garrison"})
        self.assertEqual(verbs["destroy"], 12)
        self.assertEqual(verbs["garrison"], 15)
        for verb_id in ("open", "disarm", "pray", "loot"):
            self.assertIsNone(verbs[verb_id])


class RaidModeTests(unittest.TestCase):
    def test_three_raid_modes(self) -> None:
        self.assertEqual(load_raid_modes(), frozenset({"solo", "pair", "quad"}))


class BandTests(unittest.TestCase):
    def test_twenty_bands_matching_the_owned_list(self) -> None:
        bands = load_bands()
        # The count is fully implied by the set equality above -- never pinned separately
        # (population-pin SE3.5, 2026-09-20).
        self.assertEqual(set(bands), set(BAND_NAMES))

    def test_countBand_is_S2_12_vocabulary_never_spelled_numbers(self) -> None:
        self.assertEqual(load_bands()["countBand"], frozenset({"lone", "few", "several", "many"}))
        spelled = {"one", "two", "three", "four", "five"}
        for band_name, members in load_bands().items():
            self.assertTrue(members.isdisjoint(spelled), f"{band_name} has a spelled-number member")

    def test_nerveStage_matches_delve_attrition(self) -> None:
        self.assertEqual(load_bands()["nerveStage"], frozenset({"unsettled", "shaken", "afflicted"}))

    def test_every_band_member_has_a_display_name(self) -> None:
        bands = load_bands()
        display_names = load_band_display_names()
        self.assertEqual(set(bands), set(display_names))
        for band_name, members in bands.items():
            self.assertEqual(set(display_names[band_name]), set(members),
                            f"{band_name}: display names don't match members exactly")


class VersionTests(unittest.TestCase):
    def test_nine_dungeon_files_plus_two_cross_program_theme_files_report_registryVersion_1_at_launch(self) -> None:
        # D1.10's own themes/motifs cross-read (2026-09-07) adds two more tracked versions
        # (`creatures.themes`, `creatures.motifs`) alongside the nine dungeon-native files — 9 -> 11,
        # named here rather than silently bumping the count.
        versions = load_versions()
        # pin: closed-vocabulary load_versions — a new tracked registry file is a reviewed change
        self.assertEqual(len(versions), 11)
        self.assertIn("creatures.themes", versions)
        self.assertIn("creatures.motifs", versions)
        self.assertTrue(all(v == 1 for v in versions.values()))


class ThemeTests(unittest.TestCase):
    """D1.10 (2026-09-07 correction): `theme` reads the creature-seed program's own already-shipped,
    already-reviewed registry as a frozen cross-program input — never a dungeon-authored vocabulary
    (`spec-dungeon-seed-contract.md:44`). The roster size is a READING (validation-ssot.md); the
    test asserts the loaded themes ARE the registry's themes, one entry each."""

    def test_creatures_registry_dir_resolves_to_the_real_committed_folder(self) -> None:
        """Was circular: it compared `_owned(...)` against a second `_owned(...)` of the same relative
        path, which cannot fail for any resolution at all - it passed while naming the repository that
        is MISSING themes.v1.json. Assert the property instead: the directory the code reads from
        carries every file the code reads, and both copies are accounted for.

        `data/seed/creatures/_registry` exists in gk-forge too, holding `families.v1.json` alone. That
        one is the generator's input and is correct where it is; the pack's is the superset. So the
        assertion is on what the directory CONTAINS, not on which repository won.
        """
        self.assertTrue(CREATURES_REGISTRY_DIR.is_dir(),
                        f"no creatures registry directory at {CREATURES_REGISTRY_DIR}")
        for name in ("families.v1.json", "motifs.v1.json", "themes.v1.json", "themes.v2.json"):
            with self.subTest(name=name):
                self.assertTrue((CREATURES_REGISTRY_DIR / name).is_file(),
                                f"{name} is not in {CREATURES_REGISTRY_DIR}")

    def test_themes_match_the_complete_published_roster(self) -> None:
        themes = load_themes()
        raw = _raw_creatures("themes.v1.json")["themes"]
        self.assertEqual(set(themes), set(raw))
        self.assertEqual(len(themes), len(raw), "one loaded theme per registry row, no duplicates")

    def test_every_theme_id_is_creature_prefixed_never_the_legacy_theme_prefix(self) -> None:
        # THEME_PREFIX in adapters/creatures/themes.py is "creature." specifically so it can never
        # collide with the items corpus's own legacy `theme.*` ids (spec-creature-themes.md §2.2a).
        for theme_id in load_themes():
            self.assertTrue(theme_id.startswith("creature."), theme_id)

    def test_load_theme_ids_is_a_frozenset_of_every_theme_key(self) -> None:
        ids = load_theme_ids()
        self.assertIsInstance(ids, frozenset)
        self.assertEqual(ids, frozenset(load_themes()))

    def test_a_retired_theme_still_resolves_never_filtered_out(self) -> None:
        # spec-creature-themes.md §6: "A creature that leaves the roster: its theme is retired, still
        # resolvable — never deleted." At least the shipped corpus's own retired rows (if any)
        # must still be legal vocabulary members, not silently dropped by this reader.
        themes = load_themes()
        retired = {tid for tid, row in themes.items() if row.get("retired")}
        self.assertTrue(retired.issubset(load_theme_ids()))


class MotifTests(unittest.TestCase):
    def test_motif_count_matches_the_raw_file(self) -> None:
        motifs = load_motifs()
        self.assertIsInstance(motifs, frozenset)
        self.assertEqual(motifs, frozenset(_raw_creatures("motifs.v1.json")["motifs"]))

    def test_every_themes_own_motifs_are_members_of_the_flat_union(self) -> None:
        # The flat file is supposed to be exactly the union of every theme's own motifs -- proven
        # here rather than assumed, so a future hand-edit drift is caught by this test, not by a
        # downstream planner silently rejecting a real theme's own real motif.
        flat = load_motifs()
        for theme_id, row in load_themes().items():
            for motif in row.get("motifs", []):
                self.assertIn(motif, flat, f"{theme_id}'s own motif {motif!r} missing from the flat union")


class AtomFamilyTests(unittest.TestCase):
    """D1.10 (2026-09-07, dungeon-event work): `outcomes[].effects[].family` needs the same real,
    closed atom-family vocabulary D4.24 (unique-pipeline) already measured — read fresh here too,
    a second reader of the same frozen cross-program input the seed contract's own "frozen inputs"
    list already named (`themes/motifs/families`)."""

    def test_atoms_dir_resolves_to_the_real_committed_folder(self) -> None:
        self.assertEqual(ATOMS_DIR, _owned("data/seed/atoms"))
        self.assertTrue(ATOMS_DIR.is_dir())

    def test_load_atom_families_matches_a_direct_scan(self) -> None:
        expected: "set[str]" = set()
        for path in ATOMS_DIR.rglob("*.json"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            for entry in doc.get("entries") or ():
                if isinstance(entry.get("family"), str):
                    expected.add(entry["family"])
        self.assertEqual(load_atom_families(), frozenset(expected))
        self.assertGreaterEqual(len(expected), 28)  # D4.24's own measured floor, never fewer

    def test_grantable_is_a_strict_subset_of_all_families(self) -> None:
        grantable = load_grantable_atom_families()
        every = load_atom_families()
        self.assertTrue(grantable.issubset(every))
        self.assertLess(len(grantable), len(every))

    def test_grantable_excludes_every_icdKey_bound_family(self) -> None:
        # The real, structural discriminator (found by reading the entries, not guessed from
        # filenames): an icdKey ties a family to one specific subsystem's own trigger wiring.
        bound: "set[str]" = set()
        for path in ATOMS_DIR.rglob("*.json"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            for entry in doc.get("entries") or ():
                if isinstance(entry.get("family"), str) and "icdKey" in entry:
                    bound.add(entry["family"])
        self.assertTrue(bound, "fixture assumption: at least one shipped family carries icdKey")
        self.assertEqual(load_grantable_atom_families() & bound, set())

    def test_grantable_is_exactly_the_unbound_atom_families(self) -> None:
        """The CONTRACT, not a snapshot. The atom catalog is a POPULATION that grows as content
        ships, so the grantable set changes with it; a pinned set here fails the moment an atom
        family is authored (validation-ssot.md). The rule the loader documents: grantable == every
        family that never carries an `icdKey`/`when` binding. Asserted independently by a direct scan
        so a loader that silently starts returning something else is caught."""
        grantable = load_grantable_atom_families()
        bound: "set[str]" = set()
        every: "set[str]" = set()
        for path in ATOMS_DIR.rglob("*.json"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            for entry in doc.get("entries") or ():
                family = entry.get("family")
                if isinstance(family, str):
                    every.add(family)
                    if "icdKey" in entry:
                        bound.add(family)
        self.assertEqual(grantable, every - bound,
                         "grantable is exactly the families with no icdKey binding")
        self.assertTrue(grantable.issubset(every))
        self.assertTrue(bound, "fixture assumption: at least one shipped family carries a binding")
        self.assertTrue(grantable, "the unbound pool must be non-empty")
        print(f"grantable atom families: {len(grantable)} of {len(every)}")


class PowerBandTests(unittest.TestCase):
    """D1.10 (2026-09-07, dungeon-event work): `powerBand` is a THIRD frozen cross-program input
    (alongside themes/motifs and atom families) — confirmed the dungeon-native `bands.v1.json` has
    no `powerBand` member of its own before building a reader for the items-side one."""

    def test_dungeon_native_bands_file_has_no_powerBand_of_its_own(self) -> None:
        self.assertNotIn("powerBand", load_bands())

    def test_matches_the_real_five_value_enum_the_csharp_side_already_uses(self) -> None:
        # UniqueBudget.TierOfPowerBand's own switch, read independently here so a drift between
        # the registry file and that C# switch is caught on the Python side too.
        self.assertEqual(load_power_bands(), frozenset({"trivial", "low", "medium", "high", "extreme"}))

    def test_reads_the_real_items_registry_file_not_a_hardcoded_copy(self) -> None:
        raw = json.loads((ITEMS_REGISTRY_DIR / "bands.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(load_power_bands(), frozenset(raw["powerBand"]["enum"]))


class ZombossPatternTests(unittest.TestCase):
    """D1.10 (2026-09-07, dungeon-encounter pre-work): `boss.build` needs the real nine
    `ZombossPatterns.cs` ids, read from the checked-in Python-tooling mirror that class's own doc
    comment names for exactly this purpose."""

    def test_nine_real_pattern_ids(self) -> None:
        ids = load_zomboss_pattern_ids()
        self.assertEqual(len(ids), 9)
        self.assertIn("force-pure", ids)
        self.assertIn("finesse-pure", ids)
        self.assertIn("bastion-pure", ids)

    def test_matches_a_direct_scan_of_the_mirror_file(self) -> None:
        from seedsmith.adapters.dungeon.registries import ZOMBOSS_PATTERNS_PATH
        raw = json.loads(ZOMBOSS_PATTERNS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(load_zomboss_pattern_ids(), frozenset(e["id"] for e in raw["entries"]))


class VocabularyAgreementTests(unittest.TestCase):
    """The load-bearing test: Python's vocabulary set equals the raw JSON's, both read fresh —
    proving the two readers (this one and DungeonRegistryLoader.cs) cannot silently drift, because
    both parse the SAME committed bytes with no intermediate cache on either side."""

    def test_load_vocabularies_agrees_with_the_raw_files_in_both_directions(self) -> None:
        vocab = load_vocabularies()

        raw_room_kinds = set(_raw("room-kinds.v1.json")["roomKinds"])
        self.assertEqual(vocab["roomKind"], raw_room_kinds)

        raw_door_kinds = set(_raw("door-kinds.v1.json")["doorKinds"])
        self.assertEqual(vocab["doorKind"], raw_door_kinds)

        raw_override_tags = set(_raw("override-tags.v1.json")["overrideTags"])
        self.assertEqual(vocab["overrideTag"], raw_override_tags)

        raw_bands = _raw("bands.v1.json")["bands"]
        for band_name, row in raw_bands.items():
            self.assertEqual(vocab[band_name], set(row["members"]), f"band '{band_name}' disagrees")

        raw_themes = set(_raw_creatures("themes.v1.json")["themes"])
        self.assertEqual(vocab["theme"], raw_themes)

        raw_motifs = set(_raw_creatures("motifs.v1.json")["motifs"])
        self.assertEqual(vocab["motif"], raw_motifs)

    def test_every_registry_file_is_read_by_at_least_one_loader(self) -> None:
        # A file this reader forgot would be invisible to every dungeon pipeline downstream —
        # walk the real directory and assert every *.v1.json is one of the nine this module names.
        from seedsmith.adapters.dungeon.registries import _REGISTRY_FILES  # noqa: SLF001

        on_disk = {p.name for p in LIVE_DUNGEON_REGISTRY_ROOT.glob("*.v1.json")}
        self.assertEqual(on_disk, set(_REGISTRY_FILES))


if __name__ == "__main__":
    unittest.main()
