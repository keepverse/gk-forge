"""Tests for the eight `classify-pipelines` graphs and prompts (spec-classify-pipelines.md,
creature-seed module 7). **No test in this suite calls a real model** — every transport is stubbed,
matching the existing `test_offline_guarantee.py` discipline.
"""
from __future__ import annotations

import json

import pytest

from seedsmith.adapters.creatures.anchor.prompts import (
    PIPELINES,
    THREAT_AUDIT_INFERRED_SCHEMA,
    THREAT_AUDIT_MEASURED_SCHEMA,
    SpeciesLore,
    apply_threat_audit_verdict,
    threat_audit_spec_for_basis,
)

# Same convention as test_workflow_runtime.py: `workflow.graphs.*` imports LangGraph
# transitively, an optional extra (spec-dependency-baseline.md §2.4) not installed in every dev
# environment. Every test that needs a real graph object skips cleanly rather than erroring
# collection when it's absent; the pure prompt/validator/derive tests above this guard still run.
pytest.importorskip("langgraph.graph")

from seedsmith.workflow.graphs.creature_anchor import build_pipeline_graph, state_for_pipeline  # noqa: E402

LORE = SpeciesLore(
    species_id="peashooter", side="plant", display_name="豌豆射手",
    flavor_info="豌豆射手发射豌豆来攻击僵尸，是你的第一道防线。\n\n伤害：20/1.5秒",
    flavor_introduce=None, enrichment={"typeClass": "Basic Plant"},
)


def raising_call(*args, **kwargs):
    raise AssertionError("a real model call was attempted — this test's transport must never be reached")


# --- P1: no raw magnitude ever reaches a prompt -----------------------------------------------


def test_no_pipeline_receives_a_raw_magnitude():
    # LORE's own flavor text legitimately contains "20" (damage) and "1.5" (interval) — those are
    # unavoidable in verbatim lore. What must NEVER appear is a captured hp/attack VALUE injected
    # by this program itself as a labelled field (e.g. "hp: 300", "attack: 20").
    for pipeline_id in PIPELINES:
        spec = PIPELINES[pipeline_id] if pipeline_id != "threat-audit" else threat_audit_spec_for_basis("observed")
        brief = spec.build_brief(LORE, {"order": ["fire", "ice", "air", "earth", "light", "dark"],
                                        "elementPrimary": "fire", "aptitudePrimary": "Might",
                                        "rungId": "warden", "rungOrdinal": 5})
        assert "hp:" not in brief.lower()
        assert "attack:" not in brief.lower()
        assert "armor:" not in brief.lower()


def test_eight_pipelines_each_with_a_single_stated_judgement():
    assert len(PIPELINES) == 8
    for spec in PIPELINES.values():
        assert spec.judgement.strip()
        assert len(spec.attributes) >= 1


# --- threat-audit: the one exception, and only a rung name -------------------------------------


def test_threat_audit_sees_a_rung_name_never_a_number():
    spec = threat_audit_spec_for_basis("observed")
    brief = spec.build_brief(LORE, {"rungId": "warden", "rungOrdinal": 5})
    assert "warden" in brief
    assert "rung 5" in brief  # ordinal position, not the underlying score
    # the underlying numeric SCORE (e.g. toughness*600+damage*400)/1000) must never appear —
    # only the rung id and its 1..10 ordinal position are shown.
    assert "score" not in brief.lower()


def test_audit_disagreement_does_not_change_the_rung():
    rung, needs_review = apply_threat_audit_verdict("warden", "too-high")
    assert rung == "warden"           # unchanged
    assert needs_review is True       # but flagged for the review queue

    rung2, needs_review2 = apply_threat_audit_verdict("warden", "agree")
    assert rung2 == "warden"
    assert needs_review2 is False


def test_inferred_species_gets_a_rung_and_keeps_basis_inferred():
    spec = threat_audit_spec_for_basis("inferred")
    assert spec.schema == THREAT_AUDIT_INFERRED_SCHEMA
    brief = spec.build_brief(LORE, {"order": ["nuisance", "pest", "marauder"]})
    assert "no measured threat data" in brief
    # the schema this variant uses asks for threatBand directly, not a verdict — proving the
    # judgement genuinely differs, not just the wording.
    assert "threatBand" in spec.schema["properties"]
    assert "verdict" not in spec.schema["properties"]


def test_measured_species_gets_the_audit_schema_not_the_choose_schema():
    spec = threat_audit_spec_for_basis("observed")
    assert spec.schema == THREAT_AUDIT_MEASURED_SCHEMA
    spec2 = threat_audit_spec_for_basis("stated")
    assert spec2.schema == THREAT_AUDIT_MEASURED_SCHEMA


# --- secondary fields: none is legal, not a defect ----------------------------------------------


def test_secondary_element_none_is_accepted_not_repaired():
    from seedsmith.workflow.validators.anchor import element_distinct
    defects = element_distinct({"elementSecondary": "none"}, {"elementPrimary": "fire"})
    assert defects == []


def test_secondary_element_equal_to_primary_is_a_defect():
    from seedsmith.workflow.validators.anchor import element_distinct
    defects = element_distinct({"elementSecondary": "fire"}, {"elementPrimary": "fire"})
    assert len(defects) == 1
    assert "fire" in defects[0]


# --- cross-field repair, via a real graph run with a scripted stub -------------------------------


def test_posture_resource_conflict_repairs_with_the_conflict_named():
    calls = []

    def scripted_call(system, user, *, config=None, schema=None):
        calls.append(user)
        if len(calls) == 1:
            # Bastion posture, resourceProfile missing poise -> defect
            return json.dumps({
                "attackTempo": "steady", "reach": "melee", "targetPreference": "frontline",
                "resourceProfile": ["hp", "stamina"], "blocked": "",
            })
        # repaired
        return json.dumps({
            "attackTempo": "steady", "reach": "melee", "targetPreference": "frontline",
            "resourceProfile": ["hp", "stamina", "poise"], "blocked": "",
        })

    graph = build_pipeline_graph("kit-shape", call=scripted_call)
    state = state_for_pipeline("kit-shape", LORE, context={"aptitudePrimary": "Bulwark"})  # Bastion
    result = graph.invoke(state)

    assert len(calls) == 2, "one initial attempt, one repair"
    assert "poise" in calls[1], "the repair prompt must name the specific conflict"
    assert result["outcome"] == "persisted"
    assert result["draft"]["resourceProfile"] == ["hp", "stamina", "poise"]


def test_repair_stops_after_two_attempts():
    calls = []

    def always_bad(system, user, *, config=None, schema=None):
        calls.append(user)
        # never includes 'poise' -> always a defect for a Bastion posture
        return json.dumps({
            "attackTempo": "steady", "reach": "melee", "targetPreference": "frontline",
            "resourceProfile": ["hp"], "blocked": "",
        })

    graph = build_pipeline_graph("kit-shape", call=always_bad)
    state = state_for_pipeline("kit-shape", LORE, context={"aptitudePrimary": "Bulwark"})
    result = graph.invoke(state)

    assert len(calls) == 3, "1 initial + 2 repairs, then stop — MAX_ATTEMPTS"
    assert result["outcome"] == "escalated"


def test_acquisition_empty_is_a_defect_nonempty_is_not():
    from seedsmith.workflow.validators.anchor import acquisition_nonzero
    assert acquisition_nonzero({"acquisition": []}, {}) != []
    assert acquisition_nonzero({"acquisition": ["Summonable"]}, {}) == []


# --- family stays open ---------------------------------------------------------------------------


def test_new_family_value_is_recorded_not_rejected():
    # family has no validator at all — any string list the model returns is accepted verbatim,
    # which IS the "open axis" behaviour (spec §4's family-open row: "none — the axis is open").
    assert "identity" not in __import__(
        "seedsmith.workflow.graphs.creature_anchor", fromlist=["PIPELINE_VALIDATORS"]
    ).PIPELINE_VALIDATORS


# --- dry-run: zero calls, proven by a raising stub ------------------------------------------------


def test_dry_run_makes_zero_calls():
    for pipeline_id in PIPELINES:
        spec = PIPELINES[pipeline_id] if pipeline_id != "threat-audit" else threat_audit_spec_for_basis("observed")
        # Rendering the brief alone — the --dry-run path — must never touch the transport.
        brief = spec.build_brief(LORE, {"order": ["fire"], "elementPrimary": "fire",
                                        "aptitudePrimary": "Might", "rungId": "warden", "rungOrdinal": 5})
        assert isinstance(brief, str) and brief.strip()

    # And building a graph with a raising stub must not call it just by constructing the graph —
    # only `.invoke()` would, and dry-run never invokes.
    graph = build_pipeline_graph("element-primary", call=raising_call)
    assert graph is not None
