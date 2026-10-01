"""Validates the REAL shipped `dungeon-domain` content (`gk-data/packs/fusion/data/seed/dungeon/domains/*.json`) against
the real registries and the sibling corpora it references -- the authoritative gate for this kind
until a real C# consumer exists (no `dungeon_domain` SQL row is written yet, D4.16's own honest gap;
`DomainRow`/`DomainCatalog.Load`, D4.15, already exist but have nothing to read from on disk today),
mirroring `test_dungeon_room_content.py`'s own established pattern for the same situation.

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_domain_content.py -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.dungeon import registries as reg  # noqa: E402
from seedsmith.adapters.dungeon.briefs import DOMAIN_LOOT_BOUND_KINDS  # noqa: E402
from seedsmith.adapters.dungeon.kinds import DOMAIN  # noqa: E402

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

DOMAINS_DIR = _owned("data/seed/dungeon/domains")
ROOMS_DIR = _owned("data/seed/dungeon/rooms")
QUESTS_DIR = _owned("data/seed/dungeon/quests")
LAYOUTS_DIR = _owned("data/seed/dungeon/layouts")

SIX_FIRST_SHIP_CLIMATES = frozenset({"fire", "ice", "air", "earth", "light", "dark"})


def _shipped_entries() -> "dict[str, dict]":
    if not DOMAINS_DIR.is_dir():
        return {}
    entries = {}
    for path in DOMAINS_DIR.glob("*.json"):
        if path.name == "_index.json":
            continue
        entries[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return entries


def _real_ids(directory: Path) -> "frozenset[str]":
    if not directory.is_dir():
        return frozenset()
    return frozenset(p.stem for p in directory.glob("*.json") if p.name != "_index.json")


def _real_rooms() -> "dict[str, dict]":
    if not ROOMS_DIR.is_dir():
        return {}
    out = {}
    for path in ROOMS_DIR.glob("*.json"):
        if path.name == "_index.json":
            continue
        out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return out


class RealDomainContentTests(unittest.TestCase):
    def test_every_shipped_entry_has_exactly_the_kindspecs_own_required_fields(self) -> None:
        for entry_id, entry in _shipped_entries().items():
            self.assertEqual(set(entry) - DOMAIN.optional, DOMAIN.required, entry_id)

    def test_domainId_matches_its_own_filename_and_no_id_is_shipped_twice(self) -> None:
        entries = _shipped_entries()
        ids = [e["domainId"] for e in entries.values()]
        self.assertEqual(len(ids), len(set(ids)))
        for entry_id, entry in entries.items():
            self.assertEqual(entry["domainId"], entry_id)

    def test_first_ship_is_exactly_one_domain_per_climate_all_six(self) -> None:
        entries = _shipped_entries()
        climates = [e["climate"] for e in entries.values()]
        self.assertEqual(sorted(climates), sorted(SIX_FIRST_SHIP_CLIMATES))

    def test_dangerBand_is_shallow_and_entry_is_many_for_every_first_ship_domain(self) -> None:
        # spec-domain-catalog.md §7: "one `many` domain per climate ... at `dangerBand: shallow`".
        for entry_id, entry in _shipped_entries().items():
            self.assertEqual(entry["dangerBand"], "shallow", entry_id)
            self.assertEqual(entry["entry"], "many", entry_id)

    def test_theme_is_a_real_registered_theme_id(self) -> None:
        real_themes = reg.load_theme_ids()
        for entry_id, entry in _shipped_entries().items():
            self.assertIn(entry["theme"], real_themes, entry_id)

    def test_bossSpeciesRef_is_real_and_boss_eligible_for_its_own_climate(self) -> None:
        by_climate = reg.load_boss_species_by_climate()
        for entry_id, entry in _shipped_entries().items():
            candidates = by_climate.get(entry["climate"], frozenset())
            self.assertIn(entry["bossSpeciesRef"], candidates, entry_id)

    def test_retinueFamily_is_a_real_registered_family(self) -> None:
        real_families = reg.load_creature_families()
        for entry_id, entry in _shipped_entries().items():
            self.assertIn(entry["retinueFamily"], real_families, entry_id)

    def test_entranceHint_is_one_of_the_four_real_slot_kinds(self) -> None:
        for entry_id, entry in _shipped_entries().items():
            self.assertIn(entry["entranceHint"], ("Lair", "Tear", "Vault", "Anomaly"), entry_id)

    def test_entranceHint_is_not_the_same_single_value_for_every_domain(self) -> None:
        # A live batch measured a real single-value bias here (all six picked "Anomaly") before
        # entranceHint moved to planner-computed cycling -- the same shape encounter's posture bias
        # took. This proves the fix is real, not just that each individual value is legal.
        entries = _shipped_entries()
        hints = {e["entranceHint"] for e in entries.values()}
        self.assertGreater(len(hints), 1, f"every domain picked the same entranceHint: {hints}")

    def test_layoutTemplateId_names_a_real_shipped_layout(self) -> None:
        real_layouts = _real_ids(LAYOUTS_DIR)
        for entry_id, entry in _shipped_entries().items():
            self.assertIn(entry["layoutTemplateId"], real_layouts, entry_id)

    def test_roomPalette_names_only_real_rooms_matching_its_own_climate_or_climate_neutral(self) -> None:
        rooms = _real_rooms()
        for entry_id, entry in _shipped_entries().items():
            self.assertGreaterEqual(len(entry["roomPalette"]), 1, entry_id)
            for room_id in entry["roomPalette"]:
                self.assertIn(room_id, rooms, f"{entry_id}: roomPalette id {room_id!r} is not a real room")
                self.assertIn(rooms[room_id]["climate"], (entry["climate"], "none"), entry_id)

    def test_roomPalette_covers_every_real_shipped_room_kind_for_its_own_climate(self) -> None:
        # spec-domain-catalog.md §2 row 3: "every (kind, climate) cell the layout can place has >= 1
        # archetype in roomPalette" -- layouts carry no room-kind field (confirmed by reading all six
        # real shipped layouts directly), so this reduces to "every real shipped room kind".
        rooms = _real_rooms()
        all_kinds = {r["kind"] for r in rooms.values()}
        for entry_id, entry in _shipped_entries().items():
            covered_kinds = {rooms[rid]["kind"] for rid in entry["roomPalette"]}
            self.assertEqual(covered_kinds, all_kinds, entry_id)

    def test_questPool_has_at_least_two_real_quest_ids(self) -> None:
        real_quests = _real_ids(QUESTS_DIR)
        for entry_id, entry in _shipped_entries().items():
            self.assertGreaterEqual(len(entry["questPool"]), 2, entry_id)
            for qid in entry["questPool"]:
                self.assertIn(qid, real_quests, f"{entry_id}: questPool id {qid!r} is not a real quest")

    def test_lootBinding_names_exactly_the_four_bound_kinds_with_the_real_naming_convention(self) -> None:
        for entry_id, entry in _shipped_entries().items():
            self.assertEqual(set(entry["lootBinding"]), set(DOMAIN_LOOT_BOUND_KINDS), entry_id)
            for kind, table_id in entry["lootBinding"].items():
                self.assertEqual(table_id, f"drop.dungeon.{entry['climate']}.{kind}", entry_id)

    def test_variants_and_tags_are_both_empty_no_real_registry_for_either_yet(self) -> None:
        for entry_id, entry in _shipped_entries().items():
            self.assertEqual(entry["variants"], [], entry_id)
            self.assertEqual(entry["tags"], [], entry_id)


if __name__ == "__main__":
    unittest.main()
