"""Tests for seedsmith.adapters.trees.species.roster (task J5, spec-species-tree.md §2.1, §4).

The blind spot §2.1 names was real, not hypothetical: `zombie/_needs-review.json` parked a stale
`SnorkleZombie` duplicate from 2026-09-02 (when this task first caught it) until 2026-09-07 (when a
real J9 de-risking batch run tripped over it blocking `load_roster()` for the whole real corpus, and
it was removed as a confirmed-rejected draft). `RealCorpusTests` below now proves `load_roster()`
loads the actual committed data cleanly — the rest of this file proves every individual failure
shape in isolation, with a fixture built to have exactly that one defect, so the detection itself
stays covered even though the real corpus no longer exercises it.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path, PurePosixPath

from seedsmith.adapters.creatures.run.runner import _slugify_family
from seedsmith.adapters.trees.species import roster


def _write(root: Path, rel: str, doc) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _anchor(species_id: str, **overrides) -> dict:
    base = {
        "speciesId": species_id, "elementPrimary": "fire", "aptitudePrimary": "Might",
        "posture": "Force", "traits": ["flurry"], "reason": "test fixture",
    }
    base.update(overrides)
    return base


class CleanRosterTests(unittest.TestCase):
    def test_a_consistent_two_species_roster_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "_index.json", {"Alpha": "a.json", "Beta": "b.json"})
            _write(root, "a.json", [_anchor("Alpha")])
            _write(root, "b.json", [_anchor("Beta", elementPrimary="earth")])
            result = roster.load_roster(root)
            self.assertEqual(("Alpha", "Beta"), result.species_ids)
            self.assertEqual("fire", result.anchors["Alpha"].element_primary)
            self.assertEqual("earth", result.anchors["Beta"].element_primary)

    def test_the_roster_order_matches_the_index_own_declared_key_order_not_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Declared out of alphabetical order on purpose -- the reader must not silently re-sort.
            _write(root, "_index.json", {"Zeta": "z.json", "Alpha": "a.json"})
            _write(root, "z.json", [_anchor("Zeta")])
            _write(root, "a.json", [_anchor("Alpha")])
            result = roster.load_roster(root)
            self.assertEqual(("Zeta", "Alpha"), result.species_ids)

    def test_a_file_with_multiple_anchor_entries_is_read_as_a_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "_index.json", {"Alpha": "shared.json", "Beta": "shared.json"})
            _write(root, "shared.json", [_anchor("Alpha"), _anchor("Beta")])
            result = roster.load_roster(root)
            self.assertEqual({"Alpha", "Beta"}, set(result.species_ids))

    def test_the_index_manifest_itself_is_never_walked_as_a_species_content_file(self) -> None:
        # _index.json is a flat {speciesId: path} map -- if the walker ever tried to parse it as an
        # anchor document, this would blow up (no "speciesId" key on its own top-level object).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "_index.json", {"Alpha": "a.json"})
            _write(root, "a.json", [_anchor("Alpha")])
            result = roster.load_roster(root)
            self.assertEqual(("Alpha",), result.species_ids)

    def test_anchor_fields_round_trip_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "_index.json", {"Alpha": "a.json"})
            _write(root, "a.json", [_anchor(
                "Alpha", aptitudePrimary="Bulwark", posture="Guard",
                traits=["armored", "slow"], reason="a stated reason")])
            anchor = roster.load_roster(root).anchors["Alpha"]
            self.assertEqual("Bulwark", anchor.aptitude_primary)
            self.assertEqual("Guard", anchor.posture)
            self.assertEqual(("armored", "slow"), anchor.traits)
            self.assertEqual("a stated reason", anchor.reason)
            self.assertEqual("a.json", anchor.source_path)


class OnDiskButNotIndexedTests(unittest.TestCase):
    def test_a_species_on_disk_but_not_indexed_halts_naming_the_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "_index.json", {"Alpha": "a.json"})
            _write(root, "a.json", [_anchor("Alpha")])
            # Orphan.json is on disk, walked (no `_` skip applies to it anyway), but never indexed.
            _write(root, "orphan.json", [_anchor("Orphan")])
            with self.assertRaises(roster.RosterError) as ctx:
                roster.load_roster(root)
            message = str(ctx.exception)
            self.assertIn("Orphan", message)
            self.assertIn("orphan.json", message)
            self.assertIn("not in", message)

    def test_an_underscore_prefixed_file_is_walked_too_and_its_orphan_is_still_a_finding(self) -> None:
        # The exact shape of the real SnorkleZombie incident, isolated: a species that exists ONLY
        # in an underscore-prefixed file, never indexed at all.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "_index.json", {"Alpha": "a.json"})
            _write(root, "a.json", [_anchor("Alpha")])
            _write(root, "zombie/_needs-review.json", [_anchor("Parked")])
            with self.assertRaises(roster.RosterError) as ctx:
                roster.load_roster(root)
            self.assertIn("Parked", str(ctx.exception))
            self.assertIn("_needs-review.json", str(ctx.exception))


class IndexedTwiceTests(unittest.TestCase):
    def test_a_species_defined_in_two_files_halts_naming_both_paths(self) -> None:
        # The real SnorkleZombie shape exactly: indexed at one path, ALSO defined (never indexed)
        # at another -- a duplicate that a `_`-skip convention would hide entirely.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "_index.json", {"Snorkle": "zombie/undead.json"})
            _write(root, "zombie/undead.json", [_anchor("Snorkle", elementPrimary="earth")])
            _write(root, "zombie/_needs-review.json", [_anchor("Snorkle", elementPrimary="dark")])
            with self.assertRaises(roster.RosterError) as ctx:
                roster.load_roster(root)
            message = str(ctx.exception)
            self.assertIn("Snorkle", message)
            self.assertIn("zombie/undead.json", message)
            self.assertIn("zombie/_needs-review.json", message)
            self.assertIn("indexed twice", message)

    def test_the_index_names_a_path_that_does_not_define_that_species(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "_index.json", {"Alpha": "a.json"})
            _write(root, "a.json", [_anchor("SomeoneElse")])
            with self.assertRaises(roster.RosterError) as ctx:
                roster.load_roster(root)
            self.assertIn("Alpha", str(ctx.exception))
            self.assertIn("does not define it", str(ctx.exception))

    def test_the_index_names_a_path_that_does_not_exist_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "_index.json", {"Alpha": "missing.json"})
            with self.assertRaises(roster.RosterError) as ctx:
                roster.load_roster(root)
            self.assertIn("does not exist on disk", str(ctx.exception))


class MissingIndexTests(unittest.TestCase):
    def test_no_index_file_at_all_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(roster.RosterError):
                roster.load_roster(Path(tmp))


class RealCorpusTests(unittest.TestCase):
    """Against the actual committed `gk-data/packs/fusion/data/seed/creatures/species/` root -- not a synthetic stand-in.

    **Resolved 2026-09-07** (this file's own docstring anticipated exactly this update): the
    `zombie/_needs-review.json` parked duplicate this test used to name was a single-entry,
    self-declared REJECTED draft (`verdict: "too-low"`, `aptitudePrimary`/`posture` both
    `"unresolved"`) -- confirmed by reading its real content directly, not assumed safe -- and was
    removed as part of J9's own real de-risking batch run finding it blocked `load_roster()` for the
    real corpus outright. `load_roster()` now loads the real corpus cleanly; this test proves that,
    matching the file's own stated intent to update this exact assertion once the defect closed.

    **The path assertion is DERIVED, by owner ruling 2026-10-04, and no literal replaced the old
    one.** This test used to pin `SnorkleZombie`'s `source_path` to `'zombie/undead.json'`. That
    literal had been wrong twice: the anchor moved unclassified -> undead -> plant as the anchor
    corpus was regenerated through the delegated authoring pass, and the runner's own comment says
    a species' `family` is model-decided and not stable across runs. Re-pinning
    `'zombie/plant.json'` would satisfy today's suite and re-arm the identical trap on the next
    reclassification, so the path is derived twice over instead:

      - against `_index.json`, which `load_roster()` already reconciles against and RAISES on any
        divergence; and
      - against the corpus-wide filing convention `<file stem> == slug(species.family[0])`.

    The second derivation is what gives this teeth. A bare comparison against `_index.json` after a
    successful `load_roster()` is guaranteed by construction -- `load_roster` raises on any
    index/disk disagreement before returning -- so on its own it could not fail at all. Comparing a
    parser to the file that same parser validated is not a test. The convention half is derived
    from the DATA (each species' own declared `family`), so a genuinely misfiled species fails it.
    """

    def test_the_real_corpus_loads_cleanly_now_that_the_snorklezombie_parked_duplicate_is_removed(
            self) -> None:
        real_roster = roster.load_roster()
        # The species roster is a growing content population, never pinned (population-pin SE3.5,
        # 2026-09-20; the exact AGENTS.md worked example).
        self.assertTrue(len(real_roster.species_ids) > 0)
        self.assertIn("SnorkleZombie", real_roster.species_ids)

        # Derived, per the ruling: the index's own recorded path. Never a literal -- the literal is
        # what was wrong twice.
        index = json.loads(
            (roster.SPECIES_ROOT / roster.INDEX_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(
            index["SnorkleZombie"], real_roster.anchors["SnorkleZombie"].source_path,
            "the rostered source_path disagrees with the path _index.json records")

    def test_every_species_is_filed_at_the_slug_of_its_own_first_family(self) -> None:
        """The convention `runner._family_for` establishes: a species' `family` is model-decided, so
        the FILING is derived from it rather than authored. `_slugify_family` is the runner's own
        implementation, used here rather than a fourth transcription of the same regex."""
        real_roster = roster.load_roster()
        misfiled: list[str] = []
        for species_id in real_roster.species_ids:
            anchor = real_roster.anchors[species_id]
            doc = json.loads(
                (roster.SPECIES_ROOT / anchor.source_path).read_text(encoding="utf-8"))
            entries = doc if isinstance(doc, list) else [doc]
            entry = next((e for e in entries if e.get("speciesId") == species_id), None)
            if entry is None:
                misfiled.append(f"{species_id}: indexed at {anchor.source_path} but not defined there")
                continue
            family = entry.get("family") or []
            if not family:
                misfiled.append(f"{species_id}: no `family` at {anchor.source_path}")
                continue
            expected = _slugify_family(family[0])
            stem = PurePosixPath(anchor.source_path).stem
            if stem != expected:
                misfiled.append(
                    f"{species_id}: family[0]={family[0]!r} files it at {anchor.source_path}, "
                    f"so the stem should be {expected!r} not {stem!r}")
        self.assertEqual(misfiled, [], f"{len(misfiled)} species misfiled:\\n" + "\\n".join(misfiled[:10]))
