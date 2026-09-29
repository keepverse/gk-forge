"""Running a pipeline: validate before accept, retry with the defect named, then escalate.

The loop itself is `llm_caller.call_with_self_heal` (S0) — **reused, not rebuilt**, exactly as the
plan requires. What this module adds is the schema-shaped verification S0's flat string-keyed
version could not express, and the scratch → gate → move discipline.

**Nothing is persisted until the gate passes.** Accepting first and validating afterwards is how a
bad batch reaches the corpus and has to be unpicked by hand; the ordering here makes that impossible
rather than unlikely.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from .llm_caller import LlmCallerConfig, call_with_self_heal
from .model import BLOCKED_FIELD, Pipeline, PipelineResult

__all__ = ["run_pipeline", "validate_against_schema"]


def validate_against_schema(payload: Mapping[str, Any], schema: Mapping[str, Any]) -> list[str]:
    """A deliberately small local validator: required keys, declared types, and enum membership.

    Small on purpose. This is the *always-on* half of guardrail 1 — the model's own structured-output
    mode is the upgrade, and a guard that only runs when the endpoint happens to support it is not a
    guard. Depth is less important here than being unconditional; the gate callback carries the
    domain rules.
    """
    problems: list[str] = []
    props = schema.get("properties") or {}

    for name in schema.get("required") or ():
        if name not in payload:
            problems.append(f"missing required field {name!r}")

    type_names = {
        "string": str, "boolean": bool, "object": dict, "array": list,
        "number": (int, float), "integer": int,
    }
    for name, value in payload.items():
        spec = props.get(name)
        if not isinstance(spec, dict):
            if props and name not in props:
                problems.append(f"field {name!r} is not in the schema")
            continue
        declared = spec.get("type")
        types = (declared,) if isinstance(declared, str) else tuple(declared or ())
        if value is None:
            if "null" not in types and types:
                problems.append(f"field {name!r} is null but schema does not allow null")
            continue
        concrete = next((t for t in types if t != "null"), None)
        if concrete and concrete in type_names:
            expected = type_names[concrete]
            # bool is an int in Python; a bool where a number belongs is a real defect.
            if concrete in ("number", "integer") and isinstance(value, bool):
                problems.append(f"field {name!r} is a boolean, not {concrete}")
            elif not isinstance(value, expected):
                problems.append(f"field {name!r} should be {concrete}")
        allowed = spec.get("enum")
        if allowed is not None and value not in allowed:
            problems.append(f"field {name!r} value {value!r} is not one of {list(allowed)}")

    return problems


def run_pipeline(
    pipeline: Pipeline,
    items: Mapping[str, Any],
    *,
    system: str,
    build_user,
    config: LlmCallerConfig | None = None,
) -> PipelineResult:
    """One run. Returns what was accepted, what the model declined, and what escalated.

    `verify_fn` is where the guardrails become a re-prompt: every defect is attached to its own key
    with a named reason, so the heal round tells the model *what* was wrong rather than merely that
    something was.
    """
    attempts = 0

    def verify(_items: Mapping[str, Any], out: Mapping[str, Any]):
        nonlocal attempts
        attempts += 1
        hard: dict[str, str] = {}
        soft: dict[str, str] = {}

        for key, value in out.items():
            if not isinstance(value, dict):
                hard[key] = "response is not an object"
                continue
            # A declared block is an answer, not a defect: never retried, never persisted.
            if value.get(BLOCKED_FIELD):
                soft[key] = f"BLOCKED:{value.get('reason') or 'no reason given'}"
                continue
            problems = validate_against_schema(value, pipeline.schema)
            problems.extend(pipeline.gate(value))
            if problems:
                hard[key] = "; ".join(problems)

        for key in _items:
            if key not in out:
                hard[key] = "no response for this key"
        return hard, soft

    out, soft = call_with_self_heal(
        dict(items), system, build_user, verify,
        config=config, max_heal=pipeline.max_retries,
        default_for=lambda key, original: {BLOCKED_FIELD: True, "reason": "escalated"},
    )

    accepted: dict[str, Any] = {}
    blocked: dict[str, str] = {}
    escalated: dict[str, str] = {}

    for key, note in soft.items():
        if isinstance(note, str) and note.startswith("BLOCKED:"):
            blocked[key] = note[len("BLOCKED:"):]
        elif isinstance(note, str) and note.startswith("FAILED:"):
            escalated[key] = note[len("FAILED:"):]

    for key, value in out.items():
        if key in blocked or key in escalated:
            continue
        if not isinstance(value, dict) or value.get(BLOCKED_FIELD):
            continue
        # Scratch -> gate -> move. The gate ran in `verify`; re-running it here is the cheap
        # guarantee that nothing reaches `on_persist` unvalidated even if the heal loop changes.
        if validate_against_schema(value, pipeline.schema) or pipeline.gate(value):
            escalated[key] = "failed the gate at persist time"
            continue
        accepted[key] = value

    for key, value in accepted.items():
        pipeline.on_persist(key, value)

    return PipelineResult(accepted=accepted, blocked=blocked,
                          escalated=escalated, attempts=attempts)
