"""P5 — the declare/fulfil split. Acceptance quoted from `tasks/seedsmith-plan.md` Phase 2:

1. "A synthetic 3-set-theme fixture with overlapping role/frame demand reuses existing base types
   where they satisfy the demand and requests new ones only for the genuine shortfall, without
   concentrating all three sets' demand onto the same handful of base types (a distribution check
   on the *demand* graph, not the corpus)"
2. "A recipe fixture proves materials are demanded, and therefore generated, before the recipe that
   consumes them — structurally, not by a human remembering the order"
"""
from __future__ import annotations

from dataclasses import dataclass

from seedsmith.planner import derive_kind_order
from seedsmith.planner.demand import Candidate, DemandGraph, NeedSpec, declare, fulfil


@dataclass(frozen=True)
class _Entry:
    id: str
    kind: str
    data: dict


def _set_stage(entry: _Entry) -> list[NeedSpec]:
    """A set's deterministic stage: each member slot declares the base type it needs."""
    return [
        NeedSpec(
            demander=entry.id, demander_kind="set", needs_kind="base-type",
            traits={"role": m["role"], "frame": m["frame"]}, slot=str(i),
        )
        for i, m in enumerate(entry.data["members"])
    ]


def _recipe_stage(entry: _Entry) -> list[NeedSpec]:
    return [
        NeedSpec(
            demander=entry.id, demander_kind="recipe", needs_kind="material",
            traits={"materialClass": c}, slot=str(i),
        )
        for i, c in enumerate(entry.data["costLines"])
    ]


STAGES = {"set": _set_stage, "recipe": _recipe_stage}

ROLES = ("core-guard", "head-guard", "footing")


def _three_themes() -> list[_Entry]:
    """Three sets whose role/frame demand deliberately overlaps — the shape that concentrates."""
    return [
        _Entry(
            id=f"set.theme{t}", kind="set",
            data={"members": [{"role": r, "frame": "plant"} for r in ROLES]},
        )
        for t in range(3)
    ]


def _base_types(per_role: int) -> list[Candidate]:
    return [
        Candidate(id=f"bt.{role}.{i}", kind="base-type", traits={"role": role, "frame": "plant"})
        for role in ROLES
        for i in range(per_role)
    ]


# ---- Criterion 1: reuse what fits, request only the shortfall, and spread -----------------------


def test_existing_base_types_are_reused_rather_than_regenerated():
    graph = declare(_three_themes(), STAGES)
    assert len(graph.needs) == 9

    result = fulfil(graph, _base_types(per_role=3))

    assert result.shortfall == (), "everything was satisfiable; nothing should be generated"
    assert len(result.reused) == 9
    assert result.reuse_rate == 1.0


def test_only_the_genuine_shortfall_is_requested():
    """Reuse is the default, not the whole story: a need nothing existing satisfies must still be
    generated, or the plan quietly ships an unfulfillable set."""
    graph = declare(_three_themes(), STAGES)

    # No `footing` base type exists at all — three needs (one per theme) genuinely short.
    partial = [c for c in _base_types(per_role=3) if c.traits["role"] != "footing"]
    result = fulfil(graph, partial)

    assert len(result.shortfall) == 3
    assert {n.traits["role"] for n in result.shortfall} == {"footing"}
    assert len(result.reused) == 6


def test_demand_is_spread_rather_than_concentrated_on_a_handful():
    """The distribution check the criterion names, over the *demand graph*.

    Three themes each need one base type per role, and three exist per role. A resolver that always
    picked the first match would put all three themes on `bt.<role>.0` — concentration 3. Spreading
    gives every candidate exactly one.
    """
    graph = declare(_three_themes(), STAGES)

    result = fulfil(graph, _base_types(per_role=3), spread=True)

    assert result.max_concentration == 1
    assert len(result.concentration) == 9, "all nine candidates should be in play"


def test_without_spreading_the_same_fixture_concentrates_which_is_what_the_policy_prevents():
    """The contrast that makes the test above mean something. Without it, `spread=True` could be a
    no-op and the concentration assertion would still pass on a fixture that never concentrates."""
    graph = declare(_three_themes(), STAGES)

    result = fulfil(graph, _base_types(per_role=3), spread=False)

    assert result.max_concentration == 3


def test_spreading_degrades_gracefully_when_there_is_only_one_candidate():
    """§8.3's argument against a cap, asserted: a cap would refuse here. The policy reuses the only
    candidate a third time instead of failing the plan."""
    graph = declare(_three_themes(), STAGES)
    one_each = _base_types(per_role=1)

    result = fulfil(graph, one_each)

    assert result.shortfall == ()
    assert result.max_concentration == 3, "one candidate per role, three themes — reuse, not refuse"


def test_a_need_matches_on_declared_traits_only():
    """Absence of a trait means "don't care". An over-strict match silently generates duplicates of
    content that already fits — the opposite of the defect, and just as expensive."""
    need = NeedSpec(demander="set.a", demander_kind="set", needs_kind="base-type",
                    traits={"role": "core-guard"})
    loose = Candidate("bt.1", "base-type", {"role": "core-guard", "frame": "plant", "band": "b"})

    assert need.satisfied_by(loose) is True


def test_a_candidate_of_the_wrong_kind_never_satisfies_a_need():
    need = NeedSpec(demander="set.a", demander_kind="set", needs_kind="base-type", traits={})
    assert need.satisfied_by(Candidate("gem.1", "gem", {})) is False


def test_fulfilment_is_deterministic_across_runs():
    graph = declare(_three_themes(), STAGES)
    candidates = _base_types(per_role=3)

    first = fulfil(graph, candidates).reused
    for _ in range(5):
        assert fulfil(graph, candidates).reused == first


# ---- Criterion 2: materials before the recipe that consumes them, structurally ------------------


def test_a_recipe_declares_its_material_need_in_phase_a():
    """Phase A is what makes the ordering visible at all. Before it, a recipe's dependency on a
    material only appeared once the recipe was already being written."""
    recipe = _Entry("recipe.forge-01", "recipe", {"costLines": ["catalyst.forge"]})

    graph = declare([recipe], STAGES)

    assert len(graph.needs) == 1
    assert graph.needs[0].needs_kind == "material"
    assert graph.needs[0].traits == {"materialClass": "catalyst.forge"}


def test_materials_are_ordered_before_the_recipe_that_consumes_them():
    """The owner's own example, made impossible to get wrong. The edge comes from the declared
    demand, so nobody writes the order down and nobody can forget it."""
    recipe = _Entry("recipe.forge-01", "recipe", {"costLines": ["catalyst.forge"]})
    graph = declare([recipe], STAGES)

    order = derive_kind_order(graph.kind_dependencies())

    assert order.ok
    assert order.stage_of("material") < order.stage_of("recipe")


def test_the_ordering_edge_comes_from_the_declared_demand_not_a_hand_written_table():
    """Structural, not remembered: remove the declaration and the edge disappears with it. That is
    the property — the order is a consequence of the demand graph, not a parallel fact."""
    empty = DemandGraph()
    assert empty.kind_dependencies() == {}

    recipe = _Entry("recipe.forge-01", "recipe", {"costLines": ["catalyst.forge"]})
    deps = declare([recipe], STAGES).kind_dependencies()
    assert deps["recipe"] == {"material"}


def test_sets_and_recipes_declared_together_produce_one_consistent_order():
    entries = [
        *_three_themes(),
        _Entry("recipe.forge-01", "recipe", {"costLines": ["catalyst.forge"]}),
    ]
    graph = declare(entries, STAGES)

    order = derive_kind_order(graph.kind_dependencies())

    assert order.ok
    assert order.stage_of("base-type") < order.stage_of("set")
    assert order.stage_of("material") < order.stage_of("recipe")


def test_a_kind_with_no_stage_contributes_nothing_and_is_not_an_error():
    """Most kinds declare no cross-kind need. Requiring an empty stage for each of them is ceremony
    somebody eventually skips, and a skipped stage is indistinguishable from a forgotten one."""
    graph = declare([_Entry("gem.1", "gem", {})], STAGES)

    assert graph.needs == []
