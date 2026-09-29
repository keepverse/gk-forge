"""Tests for seedsmith.numerics.tier_bands_io (tasks/seedsmith-todo.md, S5).

    python -m pytest gk-forge/tools/seedsmith/tests/test_tier_bands_io.py -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.numerics import OpWeight, TierBands  # noqa: E402
from seedsmith.numerics import tier_bands_io  # noqa: E402


class LiveTierBandsFileTests(unittest.TestCase):
    def test_loads_the_real_v1_file(self) -> None:
        # v1 pinned by version, not by "latest": v2 (item-content T10) published the 95 rows
        # `FamilyExpansion` was refusing, and v1 stays on disk for revert exactly as the file's
        # own `_meta.rebalance` line promises.
        tuning = TierBands.load(1)
        self.assertEqual(tuning.version, 1)
        self.assertEqual(tuning.base_share_permille, 35)
        self.assertEqual(len(tuning.channel_weight_permille), 14)
        self.assertEqual(tuning.op_weight_permille[OpWeight.MORE], 550)

    def test_v1_holds_exactly_the_fourteen_primary_channels(self) -> None:
        from seedsmith.adapters.items.channels import PRIMARY_CHANNEL_IDS
        self.assertEqual(set(TierBands.load(1).channel_weight_permille), PRIMARY_CHANNEL_IDS)

    def test_latest_authors_a_weight_for_every_shipped_affix_family(self) -> None:
        """item-content T10's own acceptance, as a standing guard: `FamilyExpansion.cs:121-125`
        refuses any family whose channel stem this file does not name, so a family authored
        without a matching weight silently becomes undrawable. Fails loudly instead."""
        import json
        from seedsmith.numerics.tier_bands_io import TUNING_DIR

        families_dir = TUNING_DIR.parent / "affix-families"
        stems = set()
        for path in sorted(families_dir.glob("*.json")):
            if path.name.startswith("_"):
                continue
            for entry in json.loads(path.read_text(encoding="utf-8"))["entries"]:
                fid = entry["id"]
                stems.add(fid[len("atom."):] if fid.startswith("atom.") else fid)

        weighted = set(TierBands.load("latest").channel_weight_permille)
        self.assertEqual(sorted(stems - weighted), [],
                         "affix families with no authored channelWeight — undrawable")

    def test_latest_keeps_the_v1_primary_channels_untouched(self) -> None:
        from seedsmith.adapters.items.channels import PRIMARY_CHANNEL_IDS
        v1 = TierBands.load(1)
        latest = TierBands.load("latest")
        self.assertEqual(latest.base_share_permille, v1.base_share_permille)
        self.assertEqual(latest.op_weight_permille, v1.op_weight_permille)
        for channel in PRIMARY_CHANNEL_IDS:
            self.assertEqual(latest.channel_weight_permille[channel],
                             v1.channel_weight_permille[channel], channel)

    def test_every_published_version_keeps_its_meta_block(self) -> None:
        """A publish that dropped `_meta` would drop the file's own "Never hand-edit this file"
        instruction — the only place the authoring command is written down."""
        from seedsmith.numerics.tier_bands_io import TUNING_DIR, read_meta
        for path in sorted(TUNING_DIR.glob("tier-bands.v*.json")):
            version = int(path.stem.split(".v")[1])
            meta = read_meta(version)
            self.assertIsNotNone(meta, path.name)
            self.assertIn("Never hand-edit", meta["rebalance"], path.name)


class RoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def test_save_then_load_round_trips(self) -> None:
        original = TierBands(version=2, base_share_permille=36,
                             channel_weight_permille={"vitality": 900, "might": 1100})
        tier_bands_io.save(original, tuning_dir=self.tmp)
        loaded = tier_bands_io.load(2, tuning_dir=self.tmp)

        self.assertEqual(loaded.version, 2)
        self.assertEqual(loaded.base_share_permille, 36)
        self.assertEqual(loaded.channel_weight_permille, {"vitality": 900, "might": 1100})

    def test_latest_picks_the_highest_version(self) -> None:
        for v in (1, 2, 3):
            tier_bands_io.save(
                TierBands(version=v, base_share_permille=35, channel_weight_permille={"x": 1000}),
                tuning_dir=self.tmp)
        self.assertEqual(tier_bands_io.load("latest", tuning_dir=self.tmp).version, 3)

    def test_publishing_over_an_existing_version_raises(self) -> None:
        tuning = TierBands(version=1, base_share_permille=35, channel_weight_permille={"x": 1000})
        tier_bands_io.save(tuning, tuning_dir=self.tmp)
        with self.assertRaises(FileExistsError):
            tier_bands_io.save(tuning, tuning_dir=self.tmp)


if __name__ == "__main__":
    unittest.main()
