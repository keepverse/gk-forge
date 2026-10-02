"""The two-hash split: `contentHash` tracks bytes, `dataHash` tracks game data.

**Why these tests exist.** `dumpHash` is recorded in every anchor entry's `_provenance` and is the key
`stale_ids` compares to decide "what this was derived from has changed". It used to be the manifest's
single `contentHash` — a hash over the payload files' RAW BYTES — and those payloads carry 986 stamp
fields (677 plant + 227 zombie `rebuiltUtc`, 82 spawn-baseline `capturedUtc`). So the staleness key
moved on every re-capture even when no game data changed, which is exactly what spec-anchor-emit.md
forbids: "an entry is stale when what it was derived from has changed, compared by recorded value, not
by timestamp".

Two hashes answer two different questions, and BOTH properties matter here:

* `dataHash` must be blind to capture stamps and sensitive to data. Tested both ways, because a hash
  that ignored everything would pass a stamp-independence test alone.
* `contentHash` must STILL move when a stamp moves. Asserted deliberately: if that ever stopped being
  true, `--verify` would wave through a re-captured tree — and the tempting "simplification" of making
  one hash do both jobs would have quietly removed that gate.

Everything runs on a TEMP tree, so the suite never depends on the committed dump carrying a dataHash
and never writes under a data/ tree.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.creatures.preflight import (  # noqa: E402
    DATA_HASH_STAMP_SENTINEL, VOLATILE_STAMP_KEYS, MissingDataHash,
    _compute_content_hash, _compute_data_hash, manifest_data_hash,
)

PLANT = [
    {"typeId": 300, "typeName": "A", "hp": 10, "rebuiltUtc": "2026-08-23T10:09:17.4884012Z"},
    {"typeId": 301, "typeName": "B", "hp": 20, "rebuiltUtc": "2026-08-24T10:09:17.4884012Z"},
]
ZOMBIE = [{"typeId": 400, "typeName": "Z", "hp": 30, "rebuiltUtc": "2026-08-25T10:09:17.4884012Z"}]
BASELINES = [{"typeId": 300, "side": "plant", "statsJson": "{}",
              "capturedUtc": "2026-08-20T20:19:30.9223415Z"}]
RECIPES = [{"parentA": 300, "parentB": 301, "result": 302, "resultName": "R"}]

FUTURE = "2031-01-01T00:00:00.0000000Z"


def _restamped(rows):
    return [{**r, "rebuiltUtc": FUTURE} for r in rows]


def _restamped_baselines(rows):
    return [{**r, "capturedUtc": FUTURE} for r in rows]


def _write_tree(root: Path, *, plant=None, zombie=None, baselines=None, recipes=None) -> Path:
    (root / "almanac").mkdir(parents=True, exist_ok=True)

    def dump(name, rows):
        (root / name).write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")

    dump("almanac/plant.json", PLANT if plant is None else plant)
    dump("almanac/zombie.json", ZOMBIE if zombie is None else zombie)
    dump("spawn-baseline.json", BASELINES if baselines is None else baselines)
    dump("recipes.json", RECIPES if recipes is None else recipes)
    return root


class StampIndependenceTests(unittest.TestCase):
    """`dataHash` must not move when only the capture stamps move."""

    def test_a_stamp_change_does_not_move_the_data_hash(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = _write_tree(Path(a) / "dump")
            later = _write_tree(Path(b) / "dump", plant=_restamped(PLANT),
                                zombie=_restamped(ZOMBIE), baselines=_restamped_baselines(BASELINES))
            # The stamps really did differ, so this would be a vacuous pass if the hashes were equal
            # because the fixtures were identical.
            self.assertNotEqual(_compute_content_hash(first), _compute_content_hash(later))
            self.assertEqual(_compute_data_hash(first), _compute_data_hash(later))

    def test_a_data_change_does_move_the_data_hash(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = _write_tree(Path(a) / "dump")
            changed = _write_tree(Path(b) / "dump", plant=[{**PLANT[0], "hp": 11}, PLANT[1]])
            self.assertNotEqual(_compute_data_hash(first), _compute_data_hash(changed))

    def test_a_row_appearing_moves_it_too(self):
        """A row appearing is a data change, not a formatting one."""
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = _write_tree(Path(a) / "dump")
            grown = _write_tree(Path(b) / "dump", recipes=RECIPES + [
                {"parentA": 300, "parentB": 301, "result": 303, "resultName": "R2"}])
            self.assertNotEqual(_compute_data_hash(first), _compute_data_hash(grown))


class ContentHashStillTracksBytesTests(unittest.TestCase):
    """The gate `--verify` depends on must keep catching ANY byte change."""

    def test_a_stamp_change_still_moves_the_content_hash(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = _write_tree(Path(a) / "dump")
            later = _write_tree(Path(b) / "dump", plant=_restamped(PLANT))
            self.assertNotEqual(_compute_content_hash(first), _compute_content_hash(later))

    def test_only_the_stamps_are_normalised_away_not_the_formatting(self):
        """What the data hash actually promises, stated rather than wished for.

        The first draft of this test asserted the data hash ignored re-indentation. It does not, and
        the test failed on the unmutated implementation — which is the correct outcome, because the
        contract is narrower than the guess. `dataHash` is a BYTE hash over the stamp-normalised text:
        it removes the capture clock and nothing else.

        That is sufficient rather than a shortfall, because the payloads are rendered canonically by
        the writer (sorted keys, fixed indent), so formatting cannot drift while the data holds still.
        Widening the normalisation to whitespace would mean canonicalising JSON in two languages, and
        a divergence there would silently re-key the whole corpus - a far worse failure than a data
        hash that also notices a reformat."""
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = _write_tree(Path(a) / "dump")
            loose = _write_tree(Path(b) / "dump")
            (loose / "recipes.json").write_text(
                json.dumps(RECIPES, indent=4, sort_keys=True), encoding="utf-8")
            self.assertNotEqual(_compute_content_hash(first), _compute_content_hash(loose))
            self.assertNotEqual(_compute_data_hash(first), _compute_data_hash(loose),
                                "documented: formatting is NOT normalised, only stamps are")


class ManifestDataHashTests(unittest.TestCase):
    """`manifest_data_hash` re-verifies rather than trusting the declared string."""

    def _tree_with_manifest(self, tmp: str, **overrides) -> Path:
        root = _write_tree(Path(tmp) / "dump")
        manifest = {
            "baselineCount": len(BASELINES), "capturedUtc": "2026-08-23T10:09:17.4884012Z",
            "contentHash": _compute_content_hash(root), "dataHash": _compute_data_hash(root),
            "dumpFormatVersion": 1, "plantCount": len(PLANT),
            "recipeCount": len(RECIPES), "zombieCount": len(ZOMBIE),
        }
        manifest.update(overrides)
        (root / "_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True),
                                            encoding="utf-8")
        return root

    def test_it_returns_the_data_hash_when_the_manifest_agrees(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree_with_manifest(tmp)
            self.assertEqual(manifest_data_hash(root), _compute_data_hash(root))

    def test_a_manifest_without_a_data_hash_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_tree(Path(tmp) / "dump")
            (root / "_manifest.json").write_text(json.dumps({
                "contentHash": _compute_content_hash(root), "capturedUtc": "x",
                "dumpFormatVersion": 1, "plantCount": 2, "recipeCount": 1,
                "zombieCount": 1, "baselineCount": 1}, indent=2), encoding="utf-8")
            with self.assertRaises(MissingDataHash) as ctx:
                manifest_data_hash(root)
            self.assertIn("no dataHash", str(ctx.exception))

    def test_a_manifest_whose_data_hash_disagrees_is_refused_not_returned(self):
        """The load-bearing case: a stale envelope must never drive a corpus-wide rewrite."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree_with_manifest(tmp, dataHash="0" * 64)
            with self.assertRaises(MissingDataHash) as ctx:
                manifest_data_hash(root)
            self.assertIn("but the payloads hash to", str(ctx.exception))


class SharedConstantsTests(unittest.TestCase):
    """The two implementations must agree on WHICH keys and WHICH sentinel.

    A rename on one side only would leave every anchor keyed to a hash the other side cannot produce,
    and it would surface as a silent mass-staleness rather than as an error.
    """

    def _csharp(self) -> str:
        # parents: [0]=tests [1]=seedsmith [2]=tools - so tools/CreatureCorpusDump, not tools/tools/...
        path = Path(__file__).resolve().parents[2] / "CreatureCorpusDump" / "DumpWriter.cs"
        if not path.is_file():
            self.skipTest("C# writer not present in this checkout")
        return path.read_text(encoding="utf-8")

    def test_the_key_list_is_the_named_pair(self):
        self.assertEqual(tuple(VOLATILE_STAMP_KEYS), ("rebuiltUtc", "capturedUtc"))

    def test_the_sentinel_is_a_constant_not_a_clock(self):
        self.assertEqual(DATA_HASH_STAMP_SENTINEL, "0001-01-01T00:00:00.0000000Z")
        self.assertNotRegex(DATA_HASH_STAMP_SENTINEL, r"^20\d\d-")

    def test_the_sentinel_matches_what_the_csharp_side_writes(self):
        """Read the C# constant rather than restating it, so a one-sided rename fails HERE."""
        m = re.search(r'DataHashStampSentinel\s*=\s*"([^"]+)"', self._csharp())
        self.assertIsNotNone(m, "DumpWriter no longer declares DataHashStampSentinel")
        self.assertEqual(m.group(1), DATA_HASH_STAMP_SENTINEL)

    def test_the_key_list_matches_the_csharp_side(self):
        m = re.search(r"VolatileStampKeys\s*=\s*\{([^}]*)\}", self._csharp())
        self.assertIsNotNone(m, "DumpWriter no longer declares VolatileStampKeys")
        self.assertEqual(tuple(re.findall(r'"([^"]+)"', m.group(1))), tuple(VOLATILE_STAMP_KEYS))


class RealCommittedTreeTests(unittest.TestCase):
    """Against the committed dump, when this checkout has one carrying a dataHash."""

    def test_the_python_data_hash_matches_the_committed_manifest(self):
        from seedsmith.workspace_roots import content_root
        root = content_root() / "data" / "seed" / "creatures" / "_dump"
        if not (root / "_manifest.json").is_file():
            self.skipTest("committed dump not present in this checkout")
        declared = json.loads((root / "_manifest.json").read_text(encoding="utf-8")).get("dataHash")
        if not declared:
            self.skipTest("committed manifest predates the two-hash split")
        self.assertEqual(_compute_data_hash(root), declared)


if __name__ == "__main__":
    unittest.main()