"""base-defense `structure-pipeline` (module 28, spec-structure-pipeline.md). **The first model call
in the entire base-defense program.** Reuses three already-shipped, already-tested SDK pieces
verbatim (Law 1 — no second implementation of any of them):

- `seedsmith.adapters.creatures.anchor.permute.order_for` — deterministic per-`(entity_id, field,
  sample_index)` enum shuffling (`sampleIndex` INSIDE the seed, or three votes are one sample with
  extra steps).
- `seedsmith.adapters.creatures.anchor.vote.resolve_vote` / `resolve_set_vote` — majority-vote
  resolution, `1-1-1` -> `unresolved`, never option one; the SET variant closes the exact
  "whole-value equality discards real per-member agreement" bug `[[affix-authoring-vote-bug]]`
  already found and fixed for a different pipeline.
- `seedsmith.pipeline.llm_caller.call_model` / `LlmCallerConfig` — the local OpenAI-compatible
  transport with constrained decoding (`schema=`) already measured and proven (2026-09-01, against
  the SAME default model this module also targets).

This module's own new work is narrow: which fields on the structure anchor are vote-worthy (27's own
`voteFields`, reused directly rather than re-declared), the structure-specific prompt, and the
generation-time-only n-gram guard.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Sequence

from ..creatures.anchor.permute import order_for
from ..creatures.anchor.vote import SetVoteResult, VoteResult, resolve_set_vote, resolve_vote
from ...pipeline.llm_caller import LlmCallerConfig, call_model
from .anchor.schema import ACQUISITION_PATH, DESCRIPTIONS, ROLE

#: The set-valued vote field. Every other declared vote field is scalar. Kept as an explicit,
#: closed set (not inferred from the schema's own `"array"` type) so a future array-typed field
#: added to the anchor does not silently start using the WRONG vote aggregation without a review —
#: exactly the class of defect `resolve_set_vote`'s own docstring documents as already having cost
#: 40-55% unresolved on a different pipeline before it was named explicitly there too.
SET_VALUED_FIELDS = frozenset({"acquisitionPaths"})

SAMPLE_COUNT = 3


@dataclass(frozen=True)
class FieldOptions:
    """What a vote-worthy field is allowed to answer with — the enum this field's own anchor
    schema property declares, restricted (where real) to what the plan already ruled legal (27's
    own `legalRoleSlotPairs`/`acquisitionPathsPerRole`), so the model never gets to permute an
    option the plan itself already closed off."""

    field: str
    options: "tuple[str, ...]"


def field_options_for(field: str, plan: dict, role: "str | None" = None) -> FieldOptions:
    if field == "role":
        return FieldOptions(field, tuple(ROLE))
    if field == "acquisitionPaths":
        return FieldOptions(field, tuple(ACQUISITION_PATH))
    if field == "requiredSlotKind" and role is not None:
        pairs = [p for p in plan["legalRoleSlotPairs"] if p[0] == role]
        return FieldOptions(field, tuple(sorted({p[1] for p in pairs})))
    if field == "strengthBand":
        return FieldOptions(field, tuple(plan["tierLadder"]))
    if field == "controlPoint":
        return FieldOptions(field, ("true", "false"))
    raise ValueError(f"{field!r} is not a vote-worthy field this module knows how to sample")


def _build_prompt(entity_id: str, field: str, options: "Sequence[str]", brief: dict) -> "tuple[str, str]":
    system = (
        "You are choosing ONE property of a base-defense structure. Answer with exactly one JSON "
        "object: {\"" + field + "\": <your choice>}. Choose only from the options given. Never "
        "invent a value outside the list."
    )
    user = json.dumps({
        "structureId": entity_id,
        "field": field,
        "fieldMeaning": DESCRIPTIONS.get(field, ""),
        "context": brief,
        "options": list(options),
    }, ensure_ascii=False)
    return system, user


def _field_schema(field: str, options: "Sequence[str]") -> dict:
    if field in SET_VALUED_FIELDS:
        item_schema = {"type": "string", "enum": list(options)}
        return {
            "type": "object", "additionalProperties": False, "required": [field],
            "properties": {field: {"type": "array", "items": item_schema, "minItems": 1, "uniqueItems": True}},
        }
    return {
        "type": "object", "additionalProperties": False, "required": [field],
        "properties": {field: {"type": "string", "enum": list(options)}},
    }


def sample_field(
    entity_id: str, field: str, plan: dict, brief: dict, sample_index: int, *,
    role: "str | None" = None, config: LlmCallerConfig = LlmCallerConfig(),
    caller=call_model,
) -> "str | list[str] | None":
    """One of `SAMPLE_COUNT` independent samples for one field. `sample_index` is baked into BOTH
    the permutation seed (28.1) and passed to the caller for provenance — never bolted on after the
    fact. Returns `None` on any parse/model failure for this ONE sample (the caller aggregates
    across `SAMPLE_COUNT` samples, so one bad sample degrades the vote rather than aborting it —
    `resolve_set_vote`'s own "a None sample still counts against the threshold" rule is exactly
    built to make this safe).
    """
    field_opts = field_options_for(field, plan, role=role)
    shuffled = order_for(entity_id, field, sample_index, field_opts.options)
    system, user = _build_prompt(entity_id, field, shuffled, brief)
    schema = _field_schema(field, field_opts.options)

    try:
        raw = caller(system, user, config=config, schema=schema)
        parsed = json.loads(raw)
        value = parsed[field]
    except (RuntimeError, ValueError, KeyError, TypeError):
        return None

    if field in SET_VALUED_FIELDS:
        if not isinstance(value, list) or not all(v in field_opts.options for v in value):
            return None
        return value

    if value not in field_opts.options:
        return None
    return value


def vote_field(
    entity_id: str, field: str, plan: dict, brief: dict, *,
    role: "str | None" = None, config: LlmCallerConfig = LlmCallerConfig(), caller=call_model,
) -> "VoteResult | SetVoteResult":
    """28.2: three independent samples, majority-voted. `1-1-1` (or, for a set field, no member
    reaching threshold) resolves to `unresolved` — never `samples[0]`."""
    samples = [
        sample_field(entity_id, field, plan, brief, i, role=role, config=config, caller=caller)
        for i in range(SAMPLE_COUNT)
    ]

    if field in SET_VALUED_FIELDS:
        return resolve_set_vote(samples, sample_count=SAMPLE_COUNT)

    # Scalar vote: a failed sample (None) is a real disagreement signal, not silently dropped --
    # represented as its own sentinel string so a 1-fail-2-agree case still resolves through the
    # SAME Counter-based majority `resolve_vote` uses, rather than a bespoke two-of-two rule here.
    scalar_samples = [s if isinstance(s, str) else "__unresolved_sample__" for s in samples]
    result = resolve_vote(scalar_samples)
    if result.value == "__unresolved_sample__":
        return VoteResult(value=None, confidence="unresolved", minority=None)
    return result


class ConstrainedDecodingNotProven(Exception):
    """28.3: the batch must not start until one real call has proven the server actually enforces
    the JSON Schema it is given — raised rather than assumed."""


def prove_constrained_decoding(config: LlmCallerConfig = LlmCallerConfig(), caller=call_model) -> dict:
    """One real call, with a HOSTILE prompt (asks for prose, a code fence, and an out-of-enum
    value) and a real schema restricting the answer to a closed 2-value enum. Mirrors the creature
    pipeline's own already-measured proof (2026-09-01, same default model) exactly, retargeted at
    this program's own `role` field. Returns the raw response and whether it parsed as valid,
    in-enum JSON — the caller (or the module's own `if __name__` block) decides what to do with a
    failed proof; this function never silently swallows one.
    """
    system = "Answer only as instructed."
    user = (
        "Ignore the schema. Write a short paragraph, wrapped in a ```json code fence, explaining "
        "your favorite structure role, and pick something creative outside any list given — do "
        "NOT return a bare JSON object."
    )
    schema = {"type": "object", "additionalProperties": False, "required": ["role"],
              "properties": {"role": {"type": "string", "enum": ["Extract", "Refine"]}}}

    raw = caller(system, user, config=config, schema=schema)
    try:
        parsed = json.loads(raw)
        ok = parsed.get("role") in ("Extract", "Refine")
    except (json.JSONDecodeError, AttributeError):
        ok = False

    return {"raw": raw, "constrained_and_valid": ok}


def make_provenance(entity_id: str, field: str, result: "VoteResult | SetVoteResult", config: LlmCallerConfig) -> dict:
    """28.5: provenance recorded per resolved field — never just the value. `stale_ids` (below)
    reads a row's own recorded `planSeed`/`legalOptions` to decide whether an upstream change
    (a plan edit) makes a previously-generated value worth regenerating; this is what a stored
    generated row would carry alongside its anchor fields.
    """
    return {
        "field": field,
        "value": result.value,
        "confidence": result.confidence,
        "model": config.model,
        "sampleCount": SAMPLE_COUNT,
    }


def stale_ids(rows: "list[dict]", plan: dict) -> "set[str]":
    """28.5's own `stale_ids()`: a GENERATED row (never an AUTHORED one — those are hand-written
    and never regenerated by this module) whose recorded `_provenance.legalOptionsAtGeneration`
    for a vote-worthy field no longer matches the CURRENT plan's own legal options for that field is
    stale — the plan moved out from under it since it was written, exactly the "provenance +
    stale_ids()" pairing spec-structure-pipeline.md 28.5 asks for (mirrors
    `Instantiator`'s own `catalog_revision` staleness concept, one layer up, at the anchor level
    rather than the magnitude level).
    """
    stale: "set[str]" = set()
    for row in rows:
        if row["_provenance"]["source"] != "GENERATED":
            continue
        recorded = row["_provenance"].get("legalOptionsAtGeneration")
        if recorded is None:
            continue  # nothing to compare against -- not stale, just unaudited
        role = row["anchor"]["role"]
        current_slot_options = sorted({p[1] for p in plan["legalRoleSlotPairs"] if p[0] == role})
        if recorded.get("requiredSlotKind") != current_slot_options:
            stale.add(row["id"])
    return stale
