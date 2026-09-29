"""G1 — pipeline scaffold and guardrails. Acceptance quoted from `tasks/seedsmith-plan.md` Phase 4:

1. "A schema-audit test rejects any registered pipeline whose schema has a bare numeric field"
2. "A fixture pipeline run against a fake model server (the `MockModelServer` pattern from S0,
   reused) proves retry-with-named-defect then escalate-on-persistent-failure, with zero real model
   calls"
3. "A `blocked` response writes nothing and is reported, not treated as a failure"

`MockModelServer` is imported from the existing S0 tests rather than re-rolled — a second fake
server would drift from the one the transport is actually tested against.
"""
from __future__ import annotations

import json

import pytest

from seedsmith.pipeline.llm_caller import LlmCallerConfig
from seedsmith.pipeline.model import BLOCKED_FIELD, Pipeline, audit_schema
from seedsmith.pipeline.run import run_pipeline, validate_against_schema

from test_llm_caller import MockModelServer

FLAVOUR_SCHEMA = {
    "type": "object",
    "required": ["flavor"],
    "properties": {
        "flavor": {"type": "string"},
        "tone": {"type": "string", "enum": ["grim", "wry", "plain"]},
        BLOCKED_FIELD: {"type": "boolean"},
        "reason": {"type": "string"},
    },
}


@pytest.fixture()
def server():
    s = MockModelServer()
    yield s
    s.close()


def _pipeline(persisted: dict, *, schema=None, gate=None, max_retries=2) -> Pipeline:
    return Pipeline(
        metric="Quality/FlavourGeneric", scope="uniques/theme-a",
        schema=schema or FLAVOUR_SCHEMA,
        gate=gate or (lambda v: []),
        on_persist=lambda k, v: persisted.__setitem__(k, v),
        max_retries=max_retries,
    )


# ---- Criterion 1: a bare numeric field is rejected mechanically ---------------------------------


def test_a_bare_numeric_field_is_rejected():
    """Numbers come from `numerics`, resolved from bands and the shipped progression. A model that
    invents one produces a value that looks plausible and is anchored to nothing."""
    defects = audit_schema({
        "type": "object",
        "properties": {"magnitude": {"type": "number"}, BLOCKED_FIELD: {"type": "boolean"}},
    })

    assert [d.path for d in defects] == ["$.magnitude"]
    assert "numerics" in defects[0].reason


def test_an_integer_is_a_number_too():
    """A per-mille integer is exactly the shape a model most plausibly invents, and it is still a
    magnitude. Allowing `integer` would leave the guard open on its most likely case."""
    defects = audit_schema({
        "type": "object",
        "properties": {"perMille": {"type": "integer"}, BLOCKED_FIELD: {"type": "boolean"}},
    })

    assert any(d.path == "$.perMille" for d in defects)


def test_a_number_nested_inside_an_array_of_objects_is_still_found():
    """The whole argument for auditing mechanically: a numeric field three levels down is exactly as
    dangerous as a top-level one and considerably easier to miss by eye."""
    defects = audit_schema({
        "type": "object",
        "properties": {
            BLOCKED_FIELD: {"type": "boolean"},
            "lines": {"type": "array", "items": {
                "type": "object", "properties": {"weight": {"type": "number"}}}},
        },
    })

    assert any(d.path == "$.lines[].weight" for d in defects)


def test_an_enum_of_numbers_is_allowed_because_choosing_is_not_inventing():
    """A closed set of legal values is a vocabulary. The rule is against derivation, not against
    every appearance of a digit — over-refusing would push authors to encode numbers as strings.

    Property named `grade`, not `tier` — 2026-09-04, `validate-heal` (A-S4) added a property-NAME
    deny-list to `audit_schema` that fires on `tier` regardless of type/enum (spec-validate-heal.md
    SS2 Stage 0), which is a real, separate rule from the one this test proves. `tier` was only ever
    an incidental choice here; renaming it keeps this test proving what it says it proves."""
    defects = audit_schema({
        "type": "object",
        "properties": {
            "grade": {"type": "integer", "enum": [1, 2, 3]},
            BLOCKED_FIELD: {"type": "boolean"},
        },
    })

    assert defects == []


def test_a_schema_with_no_blocked_variant_is_rejected():
    """A model with no way to decline invents instead — and a pipeline that reads 'I cannot' as an
    error retries it forever."""
    defects = audit_schema({"type": "object", "properties": {"flavor": {"type": "string"}}})

    assert any(BLOCKED_FIELD in d.reason for d in defects)


def test_a_pipeline_refuses_to_construct_with_an_unusable_schema():
    """The audit is wired into construction, so an unusable schema cannot be *registered* — which is
    what the criterion asks for. A lint nobody runs is not a guardrail."""
    with pytest.raises(ValueError, match="unusable schema"):
        Pipeline(
            metric="m", scope="s",
            schema={"type": "object", "properties": {"amount": {"type": "number"},
                                                     BLOCKED_FIELD: {"type": "boolean"}}},
            gate=lambda v: [], on_persist=lambda k, v: None,
        )


def test_the_shipped_flavour_schema_passes_its_own_audit():
    """The positive control: without it, every assertion above is satisfied by an audit that
    rejects everything."""
    assert audit_schema(FLAVOUR_SCHEMA) == []


# ---- Criterion 2: retry with the defect named, then escalate — no real model calls --------------


def test_a_named_defect_is_retried_and_the_retry_carries_the_reason(server):
    """A bare retry teaches the model nothing. The heal prompt must name what was wrong."""
    persisted: dict = {}
    server.queue(
        json.dumps({"u1": {"flavor": "x", "tone": "sardonic"}}),      # enum violation
        json.dumps({"u1": {"flavor": "x", "tone": "wry"}}),           # healed
    )
    config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)

    result = run_pipeline(
        _pipeline(persisted), {"u1": {"id": "unique.1"}},
        system="sys", build_user=lambda items: json.dumps(items), config=config,
    )

    assert result.ok
    assert persisted["u1"]["tone"] == "wry"
    assert len(server.requests) == 2
    heal_prompt = server.requests[1]["messages"][-1]["content"]
    assert "tone" in heal_prompt and "sardonic" in heal_prompt


def test_persistent_failure_escalates_rather_than_looping_forever(server):
    """Bounded retry. The budget is `max_retries`, and exhausting it is an escalation a human sees —
    not a silent give-up and not an infinite loop."""
    persisted: dict = {}
    bad = json.dumps({"u1": {"flavor": "x", "tone": "sardonic"}})
    server.queue(bad, bad, bad, bad)
    config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)

    result = run_pipeline(
        _pipeline(persisted, max_retries=2), {"u1": {"id": "unique.1"}},
        system="sys", build_user=lambda items: json.dumps(items), config=config,
    )

    assert result.ok is False
    assert "u1" in result.escalated
    assert persisted == {}, "nothing may be written when the gate never passed"
    assert len(server.requests) == 3, "1 initial + 2 heals — the retry budget is bounded"


def test_the_domain_gate_can_reject_what_the_schema_accepts(server):
    """Two layers on purpose: the schema says what shape is legal, the gate says what content is.
    A schema cannot express "this flavour text is generic"."""
    persisted: dict = {}
    server.queue(json.dumps({"u1": {"flavor": "A powerful item."}}),
                 json.dumps({"u1": {"flavor": "Cut from the last ember-tree."}}))
    config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)

    result = run_pipeline(
        _pipeline(persisted, gate=lambda v: (["flavour is generic"]
                                             if "powerful" in v.get("flavor", "") else [])),
        {"u1": {"id": "unique.1"}},
        system="sys", build_user=lambda items: json.dumps(items), config=config,
    )

    assert result.ok
    assert "ember-tree" in persisted["u1"]["flavor"]


def test_no_real_model_is_ever_contacted(server):
    """The criterion's own words: "with zero real model calls". Every request in this file went to a
    loopback port the test itself opened."""
    server.queue(json.dumps({"u1": {"flavor": "x"}}))
    config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)

    run_pipeline(_pipeline({}), {"u1": {}}, system="s",
                 build_user=lambda i: "u", config=config)

    assert server.url.startswith("http://127.0.0.1:")
    assert len(server.requests) == 1


# ---- Criterion 3: blocked writes nothing, and is not a failure ---------------------------------


def test_a_blocked_response_writes_nothing(server):
    persisted: dict = {}
    server.queue(json.dumps({"u1": {BLOCKED_FIELD: True, "reason": "no theme supplied"}}))
    config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)

    result = run_pipeline(_pipeline(persisted), {"u1": {}}, system="s",
                          build_user=lambda i: "u", config=config)

    assert persisted == {}
    assert result.wrote_anything is False


def test_a_blocked_response_is_reported_with_its_reason_and_is_not_a_failure(server):
    """The distinction that matters: blocked means the model declined and said why — reportable.
    Escalated means retries ran out with the defect still there — actionable. Collapsing them hides
    the difference exactly when someone is deciding whether to intervene."""
    server.queue(json.dumps({"u1": {BLOCKED_FIELD: True, "reason": "no theme supplied"}}))
    config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)

    result = run_pipeline(_pipeline({}), {"u1": {}}, system="s",
                          build_user=lambda i: "u", config=config)

    assert result.ok is True, "a declared block is an answer, not a failure"
    assert result.blocked["u1"] == "no theme supplied"
    assert result.escalated == {}


def test_a_block_is_never_retried(server):
    """A pipeline that retries "I cannot" burns its whole budget learning nothing."""
    server.queue(json.dumps({"u1": {BLOCKED_FIELD: True, "reason": "no theme"}}))
    config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)

    run_pipeline(_pipeline({}), {"u1": {}}, system="s",
                 build_user=lambda i: "u", config=config)

    assert len(server.requests) == 1


# ---- The always-on local validator --------------------------------------------------------------


def test_the_local_validator_runs_regardless_of_structured_output_support():
    """Guardrail 1's always-on half. A guard that only runs when the endpoint happens to support
    structured output is not a guard."""
    assert validate_against_schema({"flavor": "x"}, FLAVOUR_SCHEMA) == []
    assert validate_against_schema({}, FLAVOUR_SCHEMA) == ["missing required field 'flavor'"]
    assert validate_against_schema({"flavor": 3}, FLAVOUR_SCHEMA) == ["field 'flavor' should be string"]


def test_a_boolean_is_not_accepted_where_a_number_belongs():
    """`bool` is an `int` in Python, so a naive isinstance check passes `True` as a number."""
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}}

    assert validate_against_schema({"n": True}, schema) == ["field 'n' is a boolean, not integer"]
