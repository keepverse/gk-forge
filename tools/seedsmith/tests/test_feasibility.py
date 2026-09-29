"""P1 — feasibility. One test per acceptance criterion in `tasks/seedsmith-plan.md` Phase 1, plus
the falsifiers that keep each of them from passing for the wrong reason.

The three criteria, quoted rather than paraphrased:

1. "A synthetic 5-themes x 15-uniques-into-8-roles x 5-axes fixture (mirrors the real 75-into-40
   incident) is refused with the specific bottleneck named, not 'infeasible'"
2. "A balanced 5-theme fixture's Latin-square construction produces 0 axis collisions across all
   25 (role, theme) pairs"
3. "A feasible-but-locally-starved fixture (totals fit, one subset doesn't) is caught by layer 2
   where layer 1 would incorrectly pass it"
"""
from __future__ import annotations

import pytest

from seedsmith.planner import (
    Demand,
    check_feasibility,
    latin_square_axes,
    latin_square_collisions,
    maximum_matching,
    minimum_vertex_cover,
)


# ---- Criterion 1: the 75-into-40 incident, refused BY NAME ------------------------------------


def _overloaded_corpus() -> tuple[list[Demand], dict[str, int]]:
    """5 themes x 15 uniques = 75 demands into 8 roles x 5 axes = 40 seats."""
    slots = {f"role{r}.axis{a}": 1 for r in range(8) for a in range(5)}
    demands = [
        Demand(key=f"theme{t}.unique{u}", allowed_slots=frozenset(slots))
        for t in range(5)
        for u in range(15)
    ]
    return demands, slots


def test_the_seventy_five_into_forty_incident_is_refused():
    demands, slots = _overloaded_corpus()
    assert len(demands) == 75 and sum(slots.values()) == 40

    result = check_feasibility(demands, slots)

    assert result.feasible is False
    assert result.layer == "pigeonhole"          # 75 > 40 needs no matching to see


def test_the_refusal_names_the_bottleneck_rather_than_saying_infeasible():
    """The whole point of the criterion. A refusal a human cannot act on is barely better than a
    crash — the original incident cost a manual bisect precisely because it said nothing."""
    demands, slots = _overloaded_corpus()

    result = check_feasibility(demands, slots)

    assert result.constraint is not None
    explained = result.constraint.explain()
    assert "cannot be placed" in explained
    assert result.constraint.unmatched, "a refusal with no named demand is the original defect"
    # 75 demands, 40 seats -> exactly 35 have nowhere to go, and the message says which.
    assert len(result.constraint.unmatched) == 35
    assert "35 demand(s)" in explained


# ---- Criterion 3: totals fit, a SUBSET does not ------------------------------------------------


def test_a_locally_starved_corpus_passes_layer_one_and_is_caught_by_layer_two():
    """The case that justifies paying for a matching at all.

    Four demands, four seats — layer 1 is satisfied and would wave it through. But three of the
    four demands can only take `role0`, which holds one. Only a matching sees that.
    """
    demands = [
        Demand("a", frozenset({"role0"})),
        Demand("b", frozenset({"role0"})),
        Demand("c", frozenset({"role0"})),
        Demand("d", frozenset({"role1"})),
    ]
    slots = {"role0": 1, "role1": 1, "role2": 1, "role3": 1}
    assert len(demands) <= sum(slots.values()), "layer 1 must be satisfied, or this proves nothing"

    result = check_feasibility(demands, slots)

    assert result.feasible is False
    assert result.layer == "koenig", "layer 1 should have passed this; only the matching catches it"


def test_koenig_names_the_contested_slot_not_merely_the_losers():
    """Koenig's payoff: the cover is the *reason*, not just the casualties. Naming `role0` is what
    turns the finding into an instruction."""
    demands = [
        Demand("a", frozenset({"role0"})),
        Demand("b", frozenset({"role0"})),
        Demand("c", frozenset({"role0"})),
        Demand("d", frozenset({"role1"})),
    ]
    result = check_feasibility(demands, {"role0": 1, "role1": 1, "role2": 1, "role3": 1})

    assert result.constraint is not None
    assert result.constraint.slots == ("role0",)
    assert len(result.constraint.unmatched) == 2      # three want role0; one gets it


def test_a_feasible_corpus_is_matched_and_every_assignment_is_legal():
    """The positive control. Without it, every assertion above is satisfied by a checker that
    refuses everything."""
    demands = [
        Demand("a", frozenset({"role0", "role1"})),
        Demand("b", frozenset({"role1"})),
        Demand("c", frozenset({"role2"})),
    ]
    slots = {"role0": 1, "role1": 1, "role2": 1}

    result = check_feasibility(demands, slots)

    assert result.feasible is True
    assert result.layer == "matching"
    assert set(result.assignment) == {"a", "b", "c"}
    assert len(set(result.assignment.values())) == 3, "two demands landed in one single-seat slot"
    for demand in demands:
        assert result.assignment[demand.key] in demand.allowed_slots


def test_a_multi_seat_slot_holds_exactly_its_capacity():
    """Capacity > 1 is the caller's model; seats are the algorithm's. The seam has to hold in both
    directions — three into a 2-seat slot fails, two succeeds."""
    demands = [Demand(k, frozenset({"shared"})) for k in ("a", "b", "c")]

    assert check_feasibility(demands, {"shared": 2}).feasible is False
    assert check_feasibility(demands[:2], {"shared": 2}).feasible is True


# ---- Criterion 2: the balanced case is CONSTRUCTED, and collision-free ------------------------


def test_a_balanced_five_theme_fixture_has_zero_axis_collisions_across_all_twenty_five_pairs():
    roles = [f"role{i}" for i in range(5)]
    themes = [f"theme{i}" for i in range(5)]

    assignment = latin_square_axes(roles, themes)

    assert len(assignment) == 25
    assert latin_square_collisions(assignment, roles, themes) == []


def test_every_role_and_every_theme_sees_each_axis_exactly_once():
    """What 'Latin square' actually means. The collision check alone would also pass for an
    assignment that used only one axis and never repeated it within a row, which is not a Latin
    square at all."""
    roles = [f"role{i}" for i in range(5)]
    themes = [f"theme{i}" for i in range(5)]
    assignment = latin_square_axes(roles, themes)

    for role in roles:
        axes = sorted(a for (r, _), a in assignment.items() if r == role)
        assert axes == list(range(5))
    for theme in themes:
        axes = sorted(a for (_, t), a in assignment.items() if t == theme)
        assert axes == list(range(5))


def test_the_collision_detector_actually_detects_a_collision():
    """A verifier that never fails verifies nothing. Plant one and watch it fire."""
    roles, themes = ["r0", "r1"], ["t0", "t1"]
    broken = {("r0", "t0"): 0, ("r0", "t1"): 0, ("r1", "t0"): 1, ("r1", "t1"): 1}

    findings = latin_square_collisions(broken, roles, themes)

    assert findings, "a row using axis 0 twice must be reported"
    assert any("r0" in f for f in findings)


def test_a_non_square_demand_is_refused_rather_than_half_built():
    """A near-miss Latin square is a collision at generation time, far from its cause."""
    with pytest.raises(ValueError, match="square demand"):
        latin_square_axes(["r0", "r1", "r2"], ["t0", "t1"])


# ---- The algorithms themselves ----------------------------------------------------------------


def test_the_matching_is_maximum_not_merely_maximal():
    """The classic greedy trap: match `a->x` first and `b` is stranded, even though matching
    `a->y, b->x` places both. Hopcroft-Karp must augment out of that.
    """
    adjacency = {"a": ("x", "y"), "b": ("x",)}
    matching = maximum_matching(["a", "b"], adjacency)

    assert len(matching) == 2
    assert matching["b"] == "x"
    assert matching["a"] == "y"


def test_the_matching_is_deterministic_across_runs():
    """An assignment that changes between runs is not reproducible, and a planner whose output
    moves on its own cannot be diffed."""
    adjacency = {f"d{i}": tuple(f"s{j}" for j in range(6)) for i in range(6)}
    first = maximum_matching(list(adjacency), adjacency)
    for _ in range(5):
        assert maximum_matching(list(adjacency), adjacency) == first


def test_the_cover_touches_every_edge_and_is_no_larger_than_the_matching():
    """Koenig's two guarantees, asserted rather than trusted: it *is* a cover, and it is *minimum*
    (|cover| == |maximum matching|)."""
    adjacency = {
        "a": ("x",),
        "b": ("x",),
        "c": ("x", "y"),
        "d": ("y",),
    }
    left = list(adjacency)
    matching = maximum_matching(left, adjacency)
    cover_left, cover_right = minimum_vertex_cover(left, adjacency, matching)

    for u, vs in adjacency.items():
        for v in vs:
            assert u in cover_left or v in cover_right, f"edge {u}->{v} is uncovered"

    assert len(cover_left) + len(cover_right) == len(matching)


def test_an_empty_demand_is_feasible_and_says_so():
    result = check_feasibility([], {"role0": 1})
    assert result.feasible is True
    assert result.detail == "no demand"


def test_a_demand_with_no_legal_slot_is_refused_not_silently_dropped():
    """The quietest failure mode available: a demand nothing can hold, matched by nothing, counted
    by nothing, and shipped as if it had been placed."""
    demands = [Demand("orphan", frozenset()), Demand("ok", frozenset({"role0"}))]

    result = check_feasibility(demands, {"role0": 1, "role1": 1})

    assert result.feasible is False
    assert "orphan" in result.constraint.unmatched
