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


# =================================================================================================
# A declared attribute the model never answered must be WRITTEN DOWN as unanswered, not omitted
# =================================================================================================

def test_a_declared_attribute_the_model_omitted_is_written_not_absent():
    """Measured 2026-10-04 against the real corpus: 280 entries were missing an attribute its own
    pipeline had RUN — 84 `aptitudeSecondary`, 88 `elementSecondary`, 54 each of `reach` and
    `targetPreference`, every one on an entry whose `_provenance.attempts` recorded the owning
    pipeline at the current prompt version.

    Nothing dropped them. The merge loop folds in whatever keys the draft happens to carry, so a
    reply that omitted a `required` key produced an entry with that key simply ABSENT — and
    `_provenance` still read `attempts: 1` with a `confidence` entry, so nothing anywhere recorded
    that the model had not answered. Two of those fields (`reach`, `targetPreference`) are required
    by the C# anchor reader, which is why the whole C# tool exits 1 on the first such entry and
    abandons the load.

    FAIL-BEFORE: `"reach" not in result`.
    """
    def omits_reach(system, user, *, config=None, schema=None):
        out = json.loads(always_valid_call(system, user, config=config, schema=schema))
        if "reach" in (schema or {}).get("properties", {}):
            out.pop("reach", None)          # the model simply did not answer these two
            out.pop("targetPreference", None)
        return json.dumps(out)

    result = run_one_species("a", LORE_A, basis="inferred", call=omits_reach)

    assert result["reach"] == "unresolved", (
        "an unanswered declared attribute must be recorded explicitly; an absent key is "
        "indistinguishable from 'never ran this pipeline', which is what hid this across the corpus")
    assert result["targetPreference"] == "unresolved"
    # And the fields the stub DID answer are untouched — this is a fill, not a replacement.
    assert result["elementPrimary"] == "fire"
    assert result["attackTempo"] in {"ponderous", "slow", "steady", "quick", "flurry"}


def test_the_filler_reads_the_pipelines_own_declared_attributes_so_it_cannot_invent_a_field():
    """The attributes come from the same `PipelineSpec` whose per-call JSON Schema marks them
    `required`, so rename one and this follows. An attribute nobody declared is left absent."""
    from seedsmith.adapters.creatures.run.orchestrator import NO_ANSWER, _fill_unanswered

    assert NO_ANSWER == "unresolved"
    assert PIPELINES["kit-shape"].attributes == (
        "attackTempo", "reach", "targetPreference", "resourceProfile")

    draft = _fill_unanswered({"attackTempo": "quick"}, PIPELINES["kit-shape"])
    assert draft == {"attackTempo": "quick", "reach": "unresolved",
                     "targetPreference": "unresolved", "resourceProfile": "unresolved"}


def test_a_field_whose_vocabulary_declares_a_null_gets_it_instead_of_the_failure_sentinel():
    """The distinction that stopped corpus repair deadlocking against itself, and it is read from the
    pipeline's own schema rather than a list here, so it cannot drift from the vocabulary.

    `elementSecondary`/`aptitudeSecondary` declare `"none"` (`_enum_prop(nullable=True)`) — a legal
    answer both consumers map to null. `reach`/`targetPreference`/`attackTempo` declare nothing, so
    `"unresolved"` is outside their vocabulary and the pre-write guard refuses the entry, which is
    what routes it to a rerun.

    FAIL-BEFORE: every one of these got `"unresolved"`, so a species with an absent `reach` AND an
    absent `aptitudeSecondary` could be written by neither pipeline. Measured: 71 of 134 `kit-shape`
    reruns failed that way.
    """
    from seedsmith.adapters.creatures.run.orchestrator import (
        DECLARED_NULL, NO_ANSWER, _declared_null, _fill_unanswered,
    )
    from seedsmith.adapters.creatures.anchor.schema import DECLARED_NULL as SCHEMA_DECLARED_NULL

    # One value, two names: the reader's spelling and the writer's are the same string.
    assert DECLARED_NULL == SCHEMA_DECLARED_NULL == "none"

    for pipeline in ("element-secondary", "aptitude-secondary"):
        spec = PIPELINES[pipeline]
        assert _declared_null(spec, spec.attributes[0]) == DECLARED_NULL, pipeline
        filled = _fill_unanswered({}, spec)
        assert filled[spec.attributes[0]] == DECLARED_NULL, filled
        # And no field of that pipeline is left with the failure sentinel.
        assert NO_ANSWER not in filled.values(), filled

    for pipeline, attribute in (("kit-shape", "reach"), ("kit-shape", "targetPreference"),
                                ("kit-shape", "attackTempo"), ("deployment", "deployMode")):
        spec = PIPELINES[pipeline]
        assert _declared_null(spec, attribute) is None, (pipeline, attribute)
        assert _fill_unanswered({}, spec)[attribute] == NO_ANSWER, (pipeline, attribute)
