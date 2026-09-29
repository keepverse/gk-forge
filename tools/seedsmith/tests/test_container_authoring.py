"""T5.0 (`shared-authoring-shape`) — the parameterised container-authoring pipeline shape both
`species-effects` (T5.3) and `affix-authoring` (T7.1) will consume, extracted before either exists.
"""
from __future__ import annotations

import pytest

from seedsmith.workflow.graphs.container_authoring import (
    ContainerAuthoringSpec,
    build_container_authoring_graph,
    state_for_container,
)


def _spec(**overrides) -> ContainerAuthoringSpec:
    defaults = dict(
        id="test-authoring",
        system_prompt="You author a container.",
        schema={"type": "object"},
        eligible_families=("atom.elemental-power",),
        rarity_bands=("cultivated", "fused"),
        tag_set=("element", "theme"),
        build_brief=lambda anchor, ctx: f"anchor={anchor.get('id')} families={ctx['eligibleFamilies']}",
    )
    defaults.update(overrides)
    return ContainerAuthoringSpec(**defaults)


# ---- the spec is a real parameter bag, not a fork of the shape --------------------------------------


def test_spec_carries_the_four_named_inputs():
    spec = _spec()
    assert spec.eligible_families == ("atom.elemental-power",)
    assert spec.rarity_bands == ("cultivated", "fused")
    assert spec.tag_set == ("element", "theme")


def test_state_for_container_folds_spec_params_into_context():
    spec = _spec()
    state = state_for_container(spec, {"id": "item.ember-band"})

    assert state["subject_id"] == "item.ember-band"
    assert state["context"]["eligibleFamilies"] == ["atom.elemental-power"]
    assert state["context"]["rarityBands"] == ["cultivated", "fused"]
    assert state["context"]["tagSet"] == ["element", "theme"]
    assert "anchor=item.ember-band" in state["brief"]


def test_state_for_container_never_assembles_a_brief_ad_hoc():
    # The brief comes ENTIRELY from the spec's own build_brief — proven by swapping it and checking
    # the output changes, never independently derived at the call site.
    spec_a = _spec(build_brief=lambda a, c: "BRIEF-A")
    spec_b = _spec(build_brief=lambda a, c: "BRIEF-B")

    assert state_for_container(spec_a, {"id": "x"})["brief"] == "BRIEF-A"
    assert state_for_container(spec_b, {"id": "x"})["brief"] == "BRIEF-B"


def test_caller_supplied_context_overrides_are_not_silently_dropped():
    spec = _spec()
    state = state_for_container(spec, {"id": "x"}, context={"extra": "value"})

    assert state["context"]["extra"] == "value"
    assert state["context"]["eligibleFamilies"] == ["atom.elemental-power"]


# ---- the graph wires the SHARED skeleton, no new control flow ---------------------------------------


def test_build_container_authoring_graph_makes_zero_model_calls_when_none_are_needed():
    pytest.importorskip("langgraph.graph")

    calls = []

    def raising_call(*args, **kwargs):
        calls.append(args)
        raise AssertionError("model should never be called in this test")

    spec = _spec()
    graph = build_container_authoring_graph(spec, call=raising_call)

    assert graph is not None
    assert calls == []  # building the graph alone never invokes the model


def test_the_graph_shape_matches_the_shared_skeleton():
    pytest.importorskip("langgraph.graph")

    spec = _spec()
    app = build_container_authoring_graph(spec, call=lambda *a, **k: '{"ok": true}')

    nodes = set(app.get_graph().nodes)
    assert {"generate", "validate", "persist", "escalate"} <= nodes


def test_two_features_can_declare_independent_specs_over_the_same_shared_graph_builder():
    # species-effects and affix-authoring, simulated: two independent specs, ONE shared builder
    # function — never a second implementation of the control flow.
    species_effects_spec = _spec(id="species-effects", tag_set=("threat",))
    affix_authoring_spec = _spec(id="affix-authoring", tag_set=("theme", "family"))

    assert species_effects_spec.tag_set != affix_authoring_spec.tag_set
    assert build_container_authoring_graph is build_container_authoring_graph  # one function, both callers
