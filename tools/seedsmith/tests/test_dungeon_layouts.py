"""Tests for seedsmith.adapters.dungeon.layouts (D4.30's real prerequisite chain).

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_layouts.py -v

`dungeon-layout` is 100% PLANNED (schema.py's own `LAYOUT_OWNERSHIP` has no AUTHORED/VALIDATED
member) -- this is the one dungeon kind provably generatable with zero model calls, so its own
tests can assert exact values rather than "a legal value was chosen", the way every AUTHORED/
VALIDATED kind's own tests must.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.dungeon.audit import planned_const_audit  # noqa: E402
from seedsmith.adapters.dungeon.emit import write_corpus  # noqa: E402
from seedsmith.adapters.dungeon.kinds import LAYOUT  # noqa: E402
from seedsmith.adapters.dungeon.layouts import build_layout_entries  # noqa: E402
from seedsmith.adapters.dungeon.planner import IdMinter  # noqa: E402
from seedsmith.adapters.dungeon.registries import load_bands, load_raid_modes  # noqa: E402
from seedsmith.adapters.dungeon.schema import build_layout_schema  # noqa: E402


class BuildLayoutEntriesTests(unittest.TestCase):
    def test_exactly_six_templates(self) -> None:
        self.assertEqual(len(build_layout_entries()), 6)

    def test_every_entry_has_exactly_the_kindspecs_own_required_fields(self) -> None:
        for layout_id, entry in build_layout_entries().items():
            self.assertEqual(set(entry), LAYOUT.required, layout_id)

    def test_layoutId_field_matches_its_own_dict_key(self) -> None:
        for layout_id, entry in build_layout_entries().items():
            self.assertEqual(entry["layoutId"], layout_id)

    def test_every_id_is_layout_namespaced_and_unique(self) -> None:
        entries = build_layout_entries()
        self.assertEqual(len(entries), len(set(entries)))
        for layout_id in entries:
            self.assertTrue(layout_id.startswith("layout."), layout_id)

    def test_every_band_field_is_a_real_registered_member(self) -> None:
        # sizeBand validates against the registry's own "depthBand" (schema.py's own field->band
        # mapping, confirmed by reading build_layout_schema directly -- NOT the same string).
        bands = load_bands()
        for layout_id, entry in build_layout_entries().items():
            self.assertIn(entry["sizeBand"], bands["depthBand"], layout_id)
            self.assertIn(entry["widthBand"], bands["widthBand"], layout_id)
            self.assertIn(entry["branchiness"], bands["branchiness"], layout_id)
            for density_field in ("gateDensity", "secretDensity", "oneWayDensity"):
                self.assertIn(entry[density_field], bands["density"], f"{layout_id}.{density_field}")

    def test_widthBand_is_narrow_mid_wide_never_the_spec_prose_regular_broad(self) -> None:
        # The real, load-bearing regression for the drift this module's own docstring names: the
        # spec's prose says "regular"/"broad", the real registry says "mid"/"wide" -- if a future
        # edit reverts to the spec's stale wording, this test catches it immediately.
        widths = {entry["widthBand"] for entry in build_layout_entries().values()}
        self.assertTrue(widths.issubset({"narrow", "mid", "wide"}))
        self.assertTrue(widths.isdisjoint({"regular", "broad"}))

    def test_raidModes_is_always_a_nonempty_subset_of_the_real_registry(self) -> None:
        real = load_raid_modes()
        for layout_id, entry in build_layout_entries().items():
            modes = entry["raidModes"]
            self.assertIsInstance(modes, list)
            self.assertTrue(modes, f"{layout_id}: raidModes must never be empty")
            self.assertTrue(set(modes).issubset(real), layout_id)
            self.assertEqual(len(modes), len(set(modes)), f"{layout_id}: raidModes has a duplicate")

    def test_every_real_band_and_width_value_is_used_at_least_once(self) -> None:
        # Real coverage, not just legality -- proves the six templates were reasoned across the
        # actual band space, not six copies of one comfortable corner of it.
        entries = list(build_layout_entries().values())
        self.assertEqual({e["sizeBand"] for e in entries}, {"short", "medium", "long"})
        self.assertEqual({e["widthBand"] for e in entries}, {"narrow", "mid", "wide"})
        self.assertEqual({e["branchiness"] for e in entries}, {"linear", "forked", "webbed"})
        all_densities = {e[f] for e in entries for f in ("gateDensity", "secretDensity", "oneWayDensity")}
        self.assertEqual(all_densities, {"none", "sparse", "dense"})

    def test_complexity_narrows_raidModes_the_biggest_template_is_quad_only(self) -> None:
        entries = build_layout_entries()
        simplest = entries["layout.short-narrow-linear-001"]
        biggest = entries["layout.long-wide-webbed-001"]
        self.assertEqual(simplest["raidModes"], ["solo", "pair"])
        self.assertEqual(biggest["raidModes"], ["quad"])

    def test_deterministic_a_fresh_call_reproduces_byte_identical_ids_and_values(self) -> None:
        first = build_layout_entries()
        second = build_layout_entries()
        self.assertEqual(first, second)

    def test_a_supplied_minter_continues_from_its_own_high_water_mark(self) -> None:
        minter = IdMinter({("layout", "short-narrow-linear"): 5})
        entries = build_layout_entries(minter)
        self.assertIn("layout.short-narrow-linear-006", entries)
        self.assertNotIn("layout.short-narrow-linear-001", entries)


class SchemaConsistencyTests(unittest.TestCase):
    """Cross-checks the hand-authored content against the SAME schema `build_layout_schema()`
    exposes for audit/documentation, so the two can never silently drift apart.

    **Self-caught while writing this file, not from review**: every layout field is built via
    `_enum(..., const=True)` (matching its own PLANNED ownership level) -- `schema.py`'s own
    `_enum` only writes an `"enum"` key when `const=False`; a `const=True` node carries `"const"`
    instead, holding a per-call placeholder (`"<planned:field>"`), never the full legal-value list.
    A first-draft test here tried reading `props[field]["enum"]` and got a bare `KeyError` on the
    very first run -- the schema's own const-shaped nodes are not the right place to re-derive
    "which values are legal"; `test_every_band_field_is_a_real_registered_member` above already
    checks that directly against the registry, which is schema.py's OWN source for these values
    too, so re-deriving it a second way here would just be the same check under a different name.
    """

    def test_the_schema_itself_is_fully_planned_no_audit_defect(self) -> None:
        # dungeon-layout carries no AUTHORED/VALIDATED field at all -- planned_const_audit's own
        # job is confirming every property the schema exposes is genuinely pinned `const`.
        schema = build_layout_schema()
        defects = planned_const_audit("dungeon-layout", schema)
        self.assertEqual(defects, [], [str(d) for d in defects])


class EmissionRoundTripTests(unittest.TestCase):
    """The byte-identical-rerun discipline (D1.11) applied to this kind's own real content."""

    def test_write_then_reload_reproduces_the_same_entries(self) -> None:
        import json

        entries = build_layout_entries()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "layouts"
            write_corpus(directory, entries)

            reloaded = {
                p.stem: json.loads(p.read_text(encoding="utf-8"))
                for p in directory.glob("*.json") if p.name != "_index.json"
            }
            self.assertEqual(reloaded, entries)

    def test_a_second_write_is_byte_identical(self) -> None:
        entries = build_layout_entries()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "layouts"
            first_paths = write_corpus(directory, entries)
            first_bytes = [p.read_bytes() for p in sorted(first_paths)]

            second_paths = write_corpus(directory, entries)
            second_bytes = [p.read_bytes() for p in sorted(second_paths)]

            self.assertEqual(first_bytes, second_bytes)


if __name__ == "__main__":
    unittest.main()
