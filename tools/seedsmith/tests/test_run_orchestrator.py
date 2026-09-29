"""Tests for the run-control orchestrator (spec-run-control.md §2, creature-seed module 9).
`workflow.graphs.*` imports LangGraph (an optional extra) — same guard as test_workflow_runtime.py.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("langgraph.graph")

from seedsmith.adapters.creatures.anchor.prompts import PIPELINES, SpeciesLore  # noqa: E402
from seedsmith.adapters.creatures.run.orchestrator import run_one_species, run_selection  # noqa: E402

LORE_A = SpeciesLore("a", "plant", "A", "flavor A", None)
LORE_B = SpeciesLore("b", "plant", "B", "flavor B", None)
LORE_C = SpeciesLore("c", "zombie", "C", "flavor C", None)


def always_valid_call(system, user, *, config=None, schema=None):
    """Returns whatever the schema's first enum-valued property wants, satisfying every
    pipeline's own required fields generically enough to always validate on the first try.

    `elementSecondary`/`aptitudeSecondary` get 'none' specifically (not their own enum's first
    value) — otherwise a generic "pick enum[0]" stub answers 'fire' for BOTH elementPrimary and
    elementSecondary (both enums start with 'fire'), which the element_distinct validator
    correctly rejects every attempt (the stub doesn't read repair feedback), driving that
    pipeline to escalate after MAX_ATTEMPTS. 'none' is the realistic, common answer anyway."""
    props = (schema or {}).get("properties", {})
    out = {}
    for key, prop in props.items():
        if key == "blocked":
            out[key] = ""
        elif key in ("elementSecondary", "aptitudeSecondary"):
            out[key] = "none"
        elif prop.get("type") == "array":
            item_enum = (prop.get("items") or {}).get("enum")
            out[key] = [item_enum[0]] if item_enum else ["x"]
        elif "enum" in prop:
            out[key] = prop["enum"][0]
        else:
            out[key] = "x"
    return json.dumps(out)


def test_run_one_species_calls_every_pipeline_and_votes_the_six_load_bearing_fields():
    """basis='inferred' makes THREAT_AUDIT voted too (Q26: inferred/blocked genuinely choose the
    rung), so all 6 VOTED_FIELDS pipelines fire 3 samples and the other 2 fire 1 — 6*3 + 2*1 = 20,
    never a flat 8 (spec-option-permutation.md §6's own budget: 2 EXTRA calls per voted field).
    `attackTempo` (kit-shape) joined the voted 6 on 2026-09-04 (creature-corpus-self-heal C1) — was
    18 (5*3 + 3*1) before."""
    calls = []

    def counting_call(system, user, *, config=None, schema=None):
        calls.append(1)
        return always_valid_call(system, user, config=config, schema=schema)

    result = run_one_species("a", LORE_A, basis="inferred", call=counting_call)
    assert len(calls) == 20
    assert set(result["_pipelineOutcomes"]) == set(PIPELINES)
    assert all(o == "persisted" for o in result["_pipelineOutcomes"].values())
    # every voted field resolved 3-0 (the stub is deterministic per prompt) -> high confidence
    assert set(result["_votes"]) == {
        "elementPrimary", "aptitudePrimary", "rarity", "deployMode", "threatBand", "attackTempo"}
    assert all(v["confidence"] == "high" for v in result["_votes"].values())


def test_pause_never_splits_a_species():
    """A pause requested mid-species must not stop the orchestrator until that species' full
    eight-pipeline pass is done — `should_pause` is only ever POLLED between species."""
    poll_count = {"n": 0}

    def pause_after_first_poll():
        poll_count["n"] += 1
        return poll_count["n"] > 1  # allow species "a" to start, pause before "b"

    result = run_selection(
        ["a", "b", "c"], {"a": LORE_A, "b": LORE_B, "c": LORE_C},
        {"a": "inferred", "b": "inferred", "c": "inferred"},
        call=always_valid_call, should_pause=pause_after_first_poll)

    assert result["paused"] is True
    assert result["completed"] == ["a"]
    # "a" is fully present with all 8 pipelines resolved — never half-classified.
    assert len(result["results"]["a"]["_pipelineOutcomes"]) == 8
    assert "b" not in result["results"]  # never started, not half-done


def test_pause_resume_makes_no_new_model_call_for_already_completed_species():
    calls_first_pass = []
    calls_second_pass = []

    def call_a(system, user, *, config=None, schema=None):
        calls_first_pass.append(1)
        return always_valid_call(system, user, config=config, schema=schema)

    def call_b(system, user, *, config=None, schema=None):
        calls_second_pass.append(1)
        return always_valid_call(system, user, config=config, schema=schema)

    first = run_selection(["a", "b"], {"a": LORE_A, "b": LORE_B},
                          {"a": "inferred", "b": "inferred"},
                          call=call_a, should_pause=lambda: len(calls_first_pass) >= 1)
    assert first["paused"] is True
    assert first["completed"] == ["a"]
    # should_pause is polled only BETWEEN species, so species "a" always finishes ALL of its
    # calls (20 for basis='inferred' since C1, not a flat 8) before the >=1 threshold is checked.
    assert len(calls_first_pass) == 20

    # "Resume": call again with only the REMAINING species (run-control's own resume contract —
    # already-completed species are never re-passed in).
    remaining = [sid for sid in ["a", "b"] if sid not in first["completed"]]
    second = run_selection(remaining, {"b": LORE_B}, {"b": "inferred"}, call=call_b)
    assert second["completed"] == ["b"]
    assert len(calls_second_pass) == 20  # only "b"'s own calls — "a" was never re-touched
