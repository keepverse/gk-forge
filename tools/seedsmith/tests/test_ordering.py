"""P2 — ordering. One test per acceptance criterion in `tasks/seedsmith-plan.md` Phase 1.

The three criteria, quoted rather than paraphrased:

1. "Reproduces the real historical order on the real corpus — `drop-table` lands after
   `unique`/`base-type`/`set`/`gem`/`charm`/`consumable` (the 274-error incident this fixes
   structurally, not by a human remembering to relabel a stage)"
2. "A synthetic two-kind cycle fixture is caught and both kinds are named by Tarjan's SCC"
3. "The derived order needs no hand-maintained stage label anywhere in the adapter"
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from seedsmith.planner import derive_kind_order, kind_edges, strongly_connected


@dataclass(frozen=True)
class _Kind:
    """Duck-typed KindSpec stand-in — `kind_edges` reads only these two attributes, so a graph test
    need not drag in the whole adapter."""

    kind: str
    reference_fields: frozenset


@dataclass(frozen=True)
class _Edge:
    from_id: str
    to_id: str
    via: str


# ---- Criterion 1: the real order, derived ------------------------------------------------------


def test_drop_table_lands_after_everything_it_references():
    """The 274-error incident, structurally.

    `drop-table` references content through `sourceAllow`/`groups`; every one of those errors was a
    reference to a kind that had not been generated yet. Derived ordering makes that arrangement
    impossible rather than remembered.
    """
    kinds = [
        _Kind("base-type", frozenset()),
        _Kind("unique", frozenset({"baseType"})),
        _Kind("set", frozenset({"members"})),
        _Kind("gem", frozenset()),
        _Kind("charm", frozenset()),
        _Kind("consumable", frozenset()),
        _Kind("drop-table", frozenset({"sourceAllow", "groups"})),
    ]
    entry_kind = {
        "bt1": "base-type", "u1": "unique", "s1": "set",
        "g1": "gem", "c1": "charm", "cons1": "consumable", "dt1": "drop-table",
    }
    edges = [
        _Edge("u1", "bt1", "baseType"),
        _Edge("s1", "u1", "members[0].ref"),
        _Edge("dt1", "u1", "groups[0].entries[0].ref"),
        _Edge("dt1", "g1", "groups[1].entries[0].ref"),
        _Edge("dt1", "c1", "sourceAllow[0]"),
        _Edge("dt1", "cons1", "groups[2].entries[0].ref"),
        _Edge("dt1", "s1", "groups[3].entries[0].ref"),
    ]

    order = derive_kind_order(kind_edges(kinds, entry_kind, edges))

    assert order.ok
    drop = order.stage_of("drop-table")
    for earlier in ("unique", "base-type", "set", "gem", "charm", "consumable"):
        assert order.stage_of(earlier) < drop, f"{earlier} must generate before drop-table"


def test_a_nested_reference_path_still_counts_against_its_declared_root_field():
    """`members[0].ref` is the `members` field. Without collapsing the path to its root, every
    nested reference is silently ignored and the order looks clean while being wrong — the exact
    shape of the original incident."""
    kinds = [_Kind("set", frozenset({"members"})), _Kind("unique", frozenset())]
    graph = kind_edges(
        kinds,
        {"s1": "set", "u1": "unique"},
        [_Edge("s1", "u1", "members[0].ref")],
    )

    assert graph["set"] == {"unique"}


def test_a_reference_through_an_undeclared_field_is_ignored():
    """A `nameKey` that happens to look like an id must not invent a dependency. This is the same
    distinction `discover_edges` draws with `skip_fields`, applied one level up — and without it the
    graph acquires edges nobody authored."""
    kinds = [_Kind("set", frozenset({"members"})), _Kind("unique", frozenset())]
    graph = kind_edges(
        kinds,
        {"s1": "set", "u1": "unique"},
        [_Edge("s1", "u1", "flavorKey")],
    )

    assert graph["set"] == set(), "an edge through an undeclared field is not a dependency"


def test_kinds_that_reference_nothing_all_generate_in_the_first_layer():
    """Layers, not a flat sequence: independent kinds may be generated in parallel, and flattening
    that away costs real time for no reason."""
    kinds = [_Kind(k, frozenset()) for k in ("gem", "charm", "curve")]

    order = derive_kind_order(kind_edges(kinds, {}, []))

    assert order.layers == (("charm", "curve", "gem"),)


def test_the_order_is_deterministic_across_runs():
    """An order that moves between runs cannot be compared against a historical one, which is
    criterion 1's whole method."""
    kinds = [
        _Kind("a", frozenset({"r"})), _Kind("b", frozenset({"r"})),
        _Kind("c", frozenset()), _Kind("d", frozenset()),
    ]
    entry_kind = {"a1": "a", "b1": "b", "c1": "c", "d1": "d"}
    edges = [_Edge("a1", "c1", "r"), _Edge("b1", "d1", "r")]

    first = derive_kind_order(kind_edges(kinds, entry_kind, edges)).layers
    for _ in range(5):
        assert derive_kind_order(kind_edges(kinds, entry_kind, edges)).layers == first


# ---- Criterion 2: a cycle is caught, and BOTH kinds are named ----------------------------------


def test_a_two_kind_cycle_is_caught_and_both_members_are_named():
    kinds = [_Kind("recipe", frozenset({"outputRef"})), _Kind("unique", frozenset({"baseType"}))]
    entry_kind = {"r1": "recipe", "u1": "unique"}
    edges = [_Edge("r1", "u1", "outputRef"), _Edge("u1", "r1", "baseType")]

    order = derive_kind_order(kind_edges(kinds, entry_kind, edges))

    assert order.ok is False
    assert len(order.cycles) == 1
    assert order.cycles[0].members == ("recipe", "unique")
    explained = order.cycles[0].explain()
    assert "recipe" in explained and "unique" in explained


def test_a_self_referencing_kind_is_not_reported_as_a_cycle():
    """A kind referencing its own kind orders nothing — `unique.baseType` pointing at another
    unique is an intra-stage concern, not a stage-ordering one. Reporting it would make the common
    case look broken."""
    kinds = [_Kind("unique", frozenset({"baseType"}))]
    graph = kind_edges(kinds, {"u1": "unique", "u2": "unique"}, [_Edge("u1", "u2", "baseType")])

    order = derive_kind_order(graph)

    assert order.ok
    assert order.layers == (("unique",),)


def test_a_three_kind_cycle_names_all_three():
    kinds = [_Kind(k, frozenset({"r"})) for k in ("a", "b", "c")]
    entry_kind = {"a1": "a", "b1": "b", "c1": "c"}
    edges = [_Edge("a1", "b1", "r"), _Edge("b1", "c1", "r"), _Edge("c1", "a1", "r")]

    order = derive_kind_order(kind_edges(kinds, entry_kind, edges))

    assert order.cycles[0].members == ("a", "b", "c")


def test_tarjan_separates_two_independent_cycles():
    """One SCC per cycle, not one blob. A caller told "a, b, c, d are in a cycle" goes looking for
    an edge between b and c that does not exist."""
    graph = {"a": {"b"}, "b": {"a"}, "c": {"d"}, "d": {"c"}}

    components = [sorted(c) for c in strongly_connected(graph) if len(c) > 1]

    assert sorted(components) == [["a", "b"], ["c", "d"]]


def test_a_deep_chain_does_not_blow_the_stack():
    """Tarjan is iterative on purpose. The recursive form dies with a RecursionError on a deep
    graph — a failure that reads as a bug in this module rather than the depth it actually is."""
    depth = 2_000
    graph = {f"k{i}": {f"k{i + 1}"} for i in range(depth)}
    graph[f"k{depth}"] = set()

    order = derive_kind_order(graph)

    assert order.ok
    assert len(order.layers) == depth + 1


# ---- Criterion 3: no hand-maintained stage label anywhere ---------------------------------------


def test_the_real_items_adapter_declares_reference_fields_and_no_stage_label():
    """Criterion 3, asserted against the shipped adapter rather than a fixture.

    Two halves: the reference fields the plan names are actually declared, and no kind carries a
    stage/order attribute for anyone to hand-maintain. The second half is what makes drift
    impossible rather than merely unlikely.
    """
    from seedsmith.adapters.items.kinds import KINDS

    by_kind = {k.kind: k for k in KINDS}
    assert "baseType" in by_kind["unique"].reference_fields
    assert "outputRef" in by_kind["recipe"].reference_fields
    assert {"sourceAllow", "groups"} <= by_kind["drop-table"].reference_fields

    for spec in KINDS:
        for banned in ("stage", "order", "generation_stage", "wave"):
            assert not hasattr(spec, banned), (
                f"{spec.kind} carries a hand-maintained {banned!r} — the 274-error incident's own "
                f"shape: a fact stated twice, where the copy nobody edits goes stale"
            )


def test_stage_of_refuses_an_unknown_kind_rather_than_returning_a_sentinel():
    """A -1 sentinel sorts first, silently, which is the failure mode this module exists to end."""
    order = derive_kind_order({"a": set()})

    assert order.stage_of("a") == 0
    with pytest.raises(KeyError, match="not in the derived order"):
        order.stage_of("nope")
