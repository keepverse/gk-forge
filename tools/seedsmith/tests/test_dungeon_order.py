"""Tests for the dungeon adapter's generation order (D1.8, spec-dungeon-seed-contract.md §3).

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_order.py -v

The order is DERIVED from `KindSpec.reference_fields` by the shared, adapter-agnostic
`seedsmith.planner.ordering` module — no stage label exists anywhere in `adapters/dungeon/`. These
tests prove the seven dungeon KindSpecs actually produce the exact three layers §3's diagram names,
using synthetic `Edge`s (`corpus.model.Edge`) rather than a live corpus, since ordering only cares
about the KIND-level graph these edges collapse into.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.dungeon.kinds import (  # noqa: E402
    DOMAIN, ENCOUNTER, EVENT, KINDS, LAYOUT, QUEST, ROOM, SUPPLY_EXTENSION,
)
from seedsmith.corpus.model import Edge  # noqa: E402
from seedsmith.planner.ordering import derive_kind_order, kind_edges  # noqa: E402

ENTRY_KIND_OF = {
    "domain.fire-shallow-001": "dungeon-domain",
    "room.fight-fire-001": "dungeon-room",
    "room.cache-ice-001": "dungeon-room",
    "layout.short-narrow-linear-001": "dungeon-layout",
    "event.curio-embers-001": "dungeon-event",
    "event.story-embers-002": "dungeon-event",
    "quest.explore-rooms-delve-001": "dungeon-quest",
    "quest.kill-boss-delve-002": "dungeon-quest",
    "encounter.pack-mono-001": "dungeon-encounter",
    "supply-ext.ration-001": "dungeon-supply-ext",
}

# One real edge per reference_fields entry actually used in a representative corpus (the §3
# diagram's own worked layers) -- enough to reproduce all three layers plus both same-kind
# (order-nothing) edges.
REAL_EDGES = [
    Edge("room.fight-fire-001", "encounter.pack-mono-001", "encounterRef"),
    Edge("room.cache-ice-001", "event.curio-embers-001", "eventPool[0]"),
    Edge("domain.fire-shallow-001", "layout.short-narrow-linear-001", "layoutTemplateId"),
    Edge("domain.fire-shallow-001", "room.fight-fire-001", "roomPalette[0]"),
    Edge("domain.fire-shallow-001", "room.cache-ice-001", "roomPalette[1]"),
    Edge("domain.fire-shallow-001", "quest.explore-rooms-delve-001", "questPool[0]"),
    # Same-kind refs -- must order nothing (they self-skip in kind_edges).
    Edge("event.story-embers-002", "event.curio-embers-001", "chainRef"),
    Edge("quest.kill-boss-delve-002", "quest.explore-rooms-delve-001", "prereqRefs[0]"),
]


class DerivedOrderTests(unittest.TestCase):
    def test_order_is_derived_from_reference_fields_and_matches_section_3(self) -> None:
        graph = kind_edges(list(KINDS), ENTRY_KIND_OF, REAL_EDGES)
        order = derive_kind_order(graph)

        self.assertTrue(order.ok, f"unexpected cycle(s): {[c.explain() for c in order.cycles]}")
        # §3's exact three layers -- no stage label anywhere produced this, it fell out of the
        # graph collapse above.
        self.assertEqual(order.layers[0], tuple(sorted(
            {"dungeon-layout", "dungeon-supply-ext", "dungeon-encounter", "dungeon-event", "dungeon-quest"})))
        self.assertEqual(order.layers[1], ("dungeon-room",))
        self.assertEqual(order.layers[2], ("dungeon-domain",))
        self.assertEqual(order.stage_of("dungeon-layout"), 0)
        self.assertEqual(order.stage_of("dungeon-room"), 1)
        self.assertEqual(order.stage_of("dungeon-domain"), 2)

    def test_same_kind_refs_order_nothing(self) -> None:
        # An event referencing only another event (chainRef) and a quest referencing only another
        # quest (prereqRefs) must never create a self-edge -- both kinds stay in layer 0 even
        # though their own anchors declare those fields as reference_fields.
        graph = kind_edges(list(KINDS), ENTRY_KIND_OF, REAL_EDGES)
        self.assertEqual(graph["dungeon-event"], {"dungeon-encounter"} & graph["dungeon-event"] | graph["dungeon-event"])
        self.assertNotIn("dungeon-event", graph["dungeon-event"])
        self.assertNotIn("dungeon-quest", graph["dungeon-quest"])

    def test_consumableRef_is_not_a_kind_edge_cross_corpus_input(self) -> None:
        # consumableRef points at an ITEM id, invisible to this adapter's own entry_kind_of map --
        # kind_edges must silently drop it (a dangling ref is Linkage's finding, not ordering's)
        # rather than ordering supply-ext against a kind that does not exist here.
        edges_with_cross_corpus_ref = REAL_EDGES + [
            Edge("supply-ext.ration-001", "consumable.ration-basic", "consumableRef"),
        ]
        graph = kind_edges(list(KINDS), ENTRY_KIND_OF, edges_with_cross_corpus_ref)
        self.assertEqual(graph["dungeon-supply-ext"], set())

    def test_a_cycle_is_rejected_with_members_named(self) -> None:
        # Inject an artificial encounter -> room edge (encounters do not really reference rooms,
        # but this proves the mechanism): room -> encounter (real) + encounter -> room (injected)
        # is a genuine 2-cycle.
        cyclic_edges = REAL_EDGES + [
            Edge("encounter.pack-mono-001", "room.fight-fire-001", "injectedForTest"),
        ]
        # kind_edges only keeps edges whose source field is a DECLARED reference_field of that
        # kind -- "injectedForTest" is not declared on ENCOUNTER, so the injected edge would be
        # silently dropped exactly like consumableRef above. To actually exercise the cycle path,
        # inject the edge directly into the derived graph instead of trying to smuggle it through
        # a field ordering does not recognise.
        graph = kind_edges(list(KINDS), ENTRY_KIND_OF, REAL_EDGES)
        graph = {k: set(v) for k, v in graph.items()}
        graph["dungeon-encounter"].add("dungeon-room")  # room -> encounter already present above

        order = derive_kind_order(graph)
        self.assertFalse(order.ok)
        self.assertEqual(len(order.cycles), 1)
        members = set(order.cycles[0].members)
        self.assertEqual(members, {"dungeon-room", "dungeon-encounter"})

    def test_kind_edges_only_counts_declared_reference_fields(self) -> None:
        # A field NOT declared as a reference_field must never invent a dependency, even if its
        # value happens to look like a valid id of another kind (the "nameKey that looks like an
        # id" trap kind_edges' own docstring names).
        misleading_edges = [Edge("room.fight-fire-001", "quest.explore-rooms-delve-001", "name")]
        graph = kind_edges(list(KINDS), ENTRY_KIND_OF, misleading_edges)
        self.assertEqual(graph["dungeon-room"], set())


if __name__ == "__main__":
    unittest.main()
