"""Validates the REAL shipped `dungeon-room` content (`gk-data/packs/fusion/data/seed/dungeon/rooms/*.json`) against the
real room-kind registry, the real emitted encounter/event corpora, and the schema -- the
authoritative gate for this kind, mirroring `test_dungeon_supply_ext_content.py`'s own established
pattern. No full-anchor C# consumer exists for `dungeon-room` (`RoomPaletteEntry(RoomId, Kind,
Climate)`, `DelveGraph.cs:14`, is an even thinner projection than `EncounterAnchor` -- it carries
none of hazardBand/sightBand/dispositionBase/encounterRef/eventPool/secretEligible/tags at all), so
this Python-side check is the real gate until one is built; named honestly rather than skipping
validation altogether, the same posture this program already established for supply-ext.

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_room_content.py -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.dungeon import registries as reg  # noqa: E402
from seedsmith.adapters.dungeon.kinds import ROOM  # noqa: E402

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

ROOMS_DIR = _owned("data/seed/dungeon/rooms")
ENCOUNTERS_DIR = _owned("data/seed/dungeon/encounters")
EVENTS_DIR = _owned("data/seed/dungeon/events")

ENCOUNTER_FORMATION_BY_ROOM_KIND = {"fight": "pack", "wild": "pack", "elite": "party", "boss": "boss"}
EVENT_KIND_BY_ROOM_KIND = {
    "curio": "curio", "shrine": "shrine", "trap": "trap", "merchant": "bargain",
    "wild": "story", "rest": "encounter-event", "unknown": "any",
}


def _shipped_entries() -> "dict[str, dict]":
    if not ROOMS_DIR.is_dir():
        return {}
    entries = {}
    for path in ROOMS_DIR.glob("*.json"):
        if path.name == "_index.json":
            continue
        entries[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return entries


def _real_encounters() -> "dict[str, dict]":
    if not ENCOUNTERS_DIR.is_dir():
        return {}
    out = {}
    for path in ENCOUNTERS_DIR.glob("*.json"):
        if path.name == "_index.json":
            continue
        out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return out


def _real_events() -> "dict[str, dict]":
    if not EVENTS_DIR.is_dir():
        return {}
    out = {}
    for path in EVENTS_DIR.glob("*.json"):
        if path.name == "_index.json":
            continue
        out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return out


class RealRoomContentTests(unittest.TestCase):
    def test_every_shipped_entry_has_exactly_the_kindspecs_own_required_fields(self) -> None:
        for entry_id, entry in _shipped_entries().items():
            self.assertEqual(set(entry), ROOM.required, entry_id)

    def test_every_kind_is_a_real_registered_room_kind(self) -> None:
        real_kinds = set(reg.load_room_kinds())
        for entry_id, entry in _shipped_entries().items():
            self.assertIn(entry["kind"], real_kinds, entry_id)

    def test_wild_kind_entries_exist_and_carry_a_real_dispositionBase_not_none(self) -> None:
        # SUPERSEDES the earlier "no wild-kind entry shipped, no real story event exists yet"
        # premise: a real story event now exists (this same session), unblocking a real 12-room
        # wild batch (2 per climate). `wild` is the ONE kind whose dispositionBase is a real
        # DispositionCatalog member, never "none" (seed contract: "required on every kind but wild").
        real_dispositions = frozenset(reg.load_disposition())
        wild_entries = [e for e in _shipped_entries().values() if e["kind"] == "wild"]
        self.assertGreaterEqual(len(wild_entries), 1, "expected at least one real wild-kind room")
        for entry in wild_entries:
            self.assertIn(entry["dispositionBase"], real_dispositions, entry["roomId"])

    def test_wild_dispositionBase_is_not_the_same_single_value_for_every_wild_room(self) -> None:
        # A live batch measured all 12 first wild rooms picking `hostile` uniformly before
        # dispositionBase moved to planner-computed cycling -- the same single-value-bias shape
        # this session already found for encounter's posture, domain's entranceHint and (twice)
        # this exact field. This proves the fix, not just that each value is individually legal.
        wild_entries = [e for e in _shipped_entries().values() if e["kind"] == "wild"]
        dispositions = {e["dispositionBase"] for e in wild_entries}
        self.assertGreater(len(dispositions), 1, f"every wild room picked the same dispositionBase: {dispositions}")

    def test_climate_neutral_kinds_are_always_none_others_are_a_real_legal_value(self) -> None:
        # "none" is legal for EVERY kind (spec-dungeon-seed-contract.md §3.6's own converse rule:
        # "none legal, elements legal" for the seven climate-bearing kinds too -- a climate-blind
        # cache room is honest content, not a defect) -- only the four neutral kinds are PINNED to
        # it exclusively. A real emitted `cache` room at climate "none" caught this test's own
        # first, wrong assumption (`assertNotEqual` on "none" for non-neutral kinds) before it
        # shipped as a false content-quality gate.
        room_kinds = reg.load_room_kinds()
        elements = {"fire", "ice", "air", "earth", "light", "dark", "none"}
        for entry_id, entry in _shipped_entries().items():
            is_neutral = room_kinds[entry["kind"]]["climateNeutral"]
            if is_neutral:
                self.assertEqual(entry["climate"], "none", entry_id)
            else:
                self.assertIn(entry["climate"], elements, entry_id)

    def test_secretEligible_is_yes_or_no_only_ever_yes_for_the_three_eligible_kinds(self) -> None:
        room_kinds = reg.load_room_kinds()
        for entry_id, entry in _shipped_entries().items():
            self.assertIn(entry["secretEligible"], ("yes", "no"), entry_id)
            if entry["secretEligible"] == "yes":
                self.assertTrue(room_kinds[entry["kind"]]["secretEligible"], entry_id)

    def test_dispositionBase_is_none_for_every_non_wild_entry(self) -> None:
        # SUPERSEDES the earlier "none for every entry" premise: `wild` is now real-shipped and its
        # own dispositionBase is a real DispositionCatalog member, never "none" -- see the two
        # wild-specific dispositionBase tests above for that half of the seed contract's own rule
        # ("required on every kind but wild").
        for entry_id, entry in _shipped_entries().items():
            if entry["kind"] == "wild":
                continue
            self.assertEqual(entry["dispositionBase"], "none", entry_id)

    def test_encounterRef_is_none_or_names_a_real_encounter_with_the_matching_formation(self) -> None:
        real_encounters = _real_encounters()
        for entry_id, entry in _shipped_entries().items():
            ref = entry["encounterRef"]
            kind = entry["kind"]
            expected_formation = ENCOUNTER_FORMATION_BY_ROOM_KIND.get(kind)
            if expected_formation is None:
                self.assertEqual(ref, "none", entry_id)
                continue
            self.assertIn(ref, real_encounters, f"{entry_id}: encounterRef {ref!r} does not name a real encounter")
            self.assertEqual(real_encounters[ref]["formation"], expected_formation, entry_id)

    def test_eventPool_entries_all_name_a_real_event_of_the_kind_fit_kind(self) -> None:
        real_events = _real_events()
        for entry_id, entry in _shipped_entries().items():
            kind = entry["kind"]
            expected_event_kind = EVENT_KIND_BY_ROOM_KIND.get(kind)
            if expected_event_kind is None:
                self.assertEqual(entry["eventPool"], [], entry_id)
                continue
            self.assertGreaterEqual(len(entry["eventPool"]), 1, entry_id)
            for ref in entry["eventPool"]:
                self.assertIn(ref, real_events, f"{entry_id}: eventPool id {ref!r} does not name a real event")
                if expected_event_kind != "any":
                    self.assertEqual(real_events[ref]["kind"], expected_event_kind, entry_id)

    def test_eventPool_has_no_duplicate_entries(self) -> None:
        # A real, pre-existing defect found by probing, not assumed: `room.rest-none-002.json`
        # shipped the SAME event id three times, because the local model's constrained decoding
        # does NOT reliably enforce the schema's own `uniqueItems: true` for a string-enum array.
        # `run_room_draws` now deduplicates post-response (pipelines.py) -- this test is the
        # permanent proof that fix, and any future batch, actually holds.
        for entry_id, entry in _shipped_entries().items():
            pool = entry["eventPool"]
            self.assertEqual(len(pool), len(set(pool)), f"{entry_id}: eventPool has a duplicate entry: {pool}")

    def test_tags_is_always_empty_no_real_dungeon_tag_registry_exists_yet(self) -> None:
        for entry_id, entry in _shipped_entries().items():
            self.assertEqual(entry["tags"], [], entry_id)

    def test_no_roomId_is_shipped_twice(self) -> None:
        ids = [e["roomId"] for e in _shipped_entries().values()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_roomId_matches_its_own_filename(self) -> None:
        for entry_id, entry in _shipped_entries().items():
            self.assertEqual(entry["roomId"], entry_id)


if __name__ == "__main__":
    unittest.main()
