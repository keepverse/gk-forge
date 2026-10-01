"""Validates the REAL shipped `dungeon-supply-ext` content (`gk-data/packs/fusion/data/seed/dungeon/supplies/*.json`)
against the real item corpus and the real schema -- the authoritative gate for this kind, mirroring
`test_dungeon_layouts.py`'s own "the real six shipped layouts round trip" pattern. No C# consumer
exists yet for supply-ext content (`ConsumableCatalog.Load` takes no extension parameter --
confirmed by reading it directly, 2026-09-07), so this Python-side check is the real gate until one
is built; naming that honestly rather than skipping validation altogether.

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_supply_ext_content.py -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.dungeon.briefs import SUPPLY_EXT_ELIGIBLE_CLASSES  # noqa: E402
from seedsmith.adapters.dungeon.kinds import SUPPLY_EXTENSION  # noqa: E402

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

SUPPLIES_DIR = _owned("data/seed/dungeon/supplies")
CONSUMABLES_DIR = _owned("data/seed/items/consumables")


def _real_consumables() -> "dict[str, dict]":
    by_id: "dict[str, dict]" = {}
    for path in CONSUMABLES_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data["entries"]:
            by_id[entry["id"]] = entry
    return by_id


def _shipped_entries() -> "dict[str, dict]":
    if not SUPPLIES_DIR.is_dir():
        return {}
    entries = {}
    for path in SUPPLIES_DIR.glob("*.json"):
        if path.name == "_index.json":
            continue
        entries[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return entries


class RealSupplyExtContentTests(unittest.TestCase):
    def test_every_shipped_entry_has_exactly_the_kindspecs_own_required_fields(self) -> None:
        for entry_id, entry in _shipped_entries().items():
            self.assertEqual(set(entry), SUPPLY_EXTENSION.required, entry_id)

    def test_every_consumableRef_names_a_real_shipped_consumable(self) -> None:
        real = _real_consumables()
        for entry_id, entry in _shipped_entries().items():
            self.assertIn(entry["consumableRef"], real, f"{entry_id}: unknown consumable")

    def test_every_consumableRef_is_from_an_eligible_class_never_draught(self) -> None:
        real = _real_consumables()
        for entry_id, entry in _shipped_entries().items():
            class_id = real[entry["consumableRef"]]["classId"]
            self.assertIn(class_id, SUPPLY_EXT_ELIGIBLE_CLASSES, f"{entry_id}: extends a {class_id!r} consumable")

    def test_overrideTags_is_always_empty_for_this_first_ship_batch(self) -> None:
        # The real, grounded finding this batch's own design is built on (briefs.py's own doc
        # comment): no shipped consumable is narratively a key/charm/bait item today.
        for entry_id, entry in _shipped_entries().items():
            self.assertEqual(entry["overrideTags"], [], entry_id)

    def test_useContextAdds_is_always_a_subset_of_rest_and_curio(self) -> None:
        for entry_id, entry in _shipped_entries().items():
            self.assertTrue(set(entry["useContextAdds"]).issubset({"rest", "curio"}), entry_id)
            self.assertEqual(len(entry["useContextAdds"]), len(set(entry["useContextAdds"])), f"{entry_id}: duplicate")

    def test_no_consumableRef_is_extended_twice(self) -> None:
        refs = [e["consumableRef"] for e in _shipped_entries().values()]
        self.assertEqual(len(refs), len(set(refs)))


if __name__ == "__main__":
    unittest.main()
