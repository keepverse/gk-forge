"""The `Pipeline` scaffold and its guardrails (spec-pipeline.md §2-§3, plan G1).

Six guardrails, and the load-bearing one is the third:

1. **Schema-validated locally, always.** A model's structured-output mode is an upgrade, never the
   only check — an endpoint that silently ignores the mode would otherwise remove the guard.
2. **Narrow scope per call.** One partition, one kind.
3. **⛔ Never a number.** A schema carrying a numeric magnitude field is rejected *mechanically*, by
   `audit_schema`, not by review. Numbers come from `numerics`, which resolves them from bands and
   the shipped progression — a model inventing one produces a value that looks plausible and is
   unanchored to anything, which is the hardest kind of wrong to find later.
4. **Closed vocabularies inlined** — reusing `briefkit`'s inlining rather than a second copy.
5. **Validate before accept.** Scratch → gate → move. Nothing reaches the corpus unvalidated.
6. **Bounded retry with the exact defect named, then escalate.** A bare retry teaches the model
   nothing; naming the defect is what fixes it. This is `llm_caller.call_with_self_heal` (S0)
   generalized to an arbitrary schema, **reused rather than rebuilt**.

Every schema carries a `blocked` variant: a model that cannot do the job must be able to say so with
a reason. A `blocked` response writes nothing and is **reported, not counted as a failure** — the
difference matters, because a pipeline that treats "I can't" as an error retries it forever.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

__all__ = [
    "Pipeline",
    "PipelineResult",
    "SchemaDefect",
    "audit_schema",
    "BLOCKED_FIELD",
    "NUMERIC_JSON_TYPES",
    "MAGNITUDE_DENY_NAMES",
    "MAGNITUDE_DENY_SUFFIX",
]

#: Every schema must accept this instead of forcing the model to invent something.
BLOCKED_FIELD = "blocked"

#: JSON Schema types a magnitude would be expressed in. `integer` is included deliberately: a
#: per-mille integer is exactly the shape a model most plausibly invents, and it is still a number.
NUMERIC_JSON_TYPES = frozenset({"number", "integer"})

# ---------------------------------------------------------------------------------------------
# Three extensions added for `validate-heal` (A-S4, spec-validate-heal.md SS2 Stage 0) and kept
# HERE rather than in an action-corpus-local copy, so every seedsmith pipeline inherits them the
# moment it constructs a `Pipeline` (guardrail #6's own audit-at-construction-time discipline).
# `adapters/creatures/anchor/audit.py`'s `numeric_audit` already proved this exact shape of check for
# the creature-seed program (same three smuggling cases, plus a couple of creature-specific deny names)
# -- it stays exactly as-is (a separate, already-tested module with its own callers) rather than
# being refactored into this one; the implementation below mirrors its `_DIGIT_PROBES` /
# `fullmatch` technique deliberately, because it is a more correct test for "does this pattern
# admit a bare number" than a literal-substring search over the pattern text.
# ---------------------------------------------------------------------------------------------

#: Property names that name a magnitude outright, regardless of declared JSON type -- a value
#: smuggled through a "closed" string enum or a narrowly-worded pattern is still a magnitude a
#: model invented. This is the floor every seedsmith schema shares; a program with its own wider
#: vocabulary (creatures' `MAGNITUDE_DENY_NAMES` in `adapters/creatures/anchor/audit.py`) keeps that
#: list local rather than widening this one for everybody.
MAGNITUDE_DENY_NAMES = frozenset({
    "hp", "atk", "damage", "cost", "chance", "duration", "weight", "rung", "tier",
})

#: Any property name ending in this suffix is a magnitude by the shipped C# `*Milli` per-mille
#: integer naming convention (e.g. `powerMilli`, `rungMilli`) -- exactly the suffix named in
#: spec-validate-heal.md SS2 Stage 0, and no other (a sibling convention like `*Multi` is not
#: covered, since the spec names only `Milli`).
MAGNITUDE_DENY_SUFFIX = "Milli"

_DIGIT_PROBES = ("0", "1", "7", "42", "999", "1000000")
_NUMERIC_STRING_RE = re.compile(r"^-?\d+(\.\d+)?$")


def _pattern_admits_bare_number(node: Mapping[str, Any]) -> bool:
    """A `pattern` "admits a bare number" when it matches every one of a handful of plain digit
    probes -- a real regex-compile-and-run check, not a search for the LITERAL substrings
    `^[0-9]`/`[0-9]+$`/`\\d` the spec's own prose uses as examples (those are illustrations of the
    shape, not the check itself; a pattern spelled `^[[:digit:]]+$` admits the same bare number and
    would slip past a substring search)."""
    pattern = node.get("pattern")
    if not isinstance(pattern, str):
        return False
    try:
        compiled = re.compile(pattern)
    except re.error:
        return False
    return all(compiled.fullmatch(probe) for probe in _DIGIT_PROBES)


def _enum_is_all_numeric_strings(node: Mapping[str, Any]) -> bool:
    values = node.get("enum")
    if not isinstance(values, list) or not values:
        return False
    return all(isinstance(v, str) and _NUMERIC_STRING_RE.match(v) for v in values)


def _field_name_is_magnitude(name: str) -> bool:
    return name.lower() in MAGNITUDE_DENY_NAMES or name.endswith(MAGNITUDE_DENY_SUFFIX)


@dataclass(frozen=True)
class SchemaDefect:
    path: str
    reason: str

    def __str__(self) -> str:
        return f"{self.path}: {self.reason}"


def audit_schema(schema: Mapping[str, Any], *, path: str = "$", field_name: "str | None" = None,
                 name_allowlist: "frozenset[str]" = frozenset()) -> list[SchemaDefect]:
    """Reject a schema that lets a model emit a number, or that offers it no way to decline.

    Walks `properties`, `items`, and the composition keywords, because a numeric field nested three
    levels inside an array of objects is exactly as dangerous as a top-level one and considerably
    easier to miss by eye. That is the whole argument for auditing mechanically.

    An `enum` of numbers is **allowed**: a closed set of legal values is a vocabulary, not an
    invention — the model is choosing, not deriving. This is the ORIGINAL rule and applies only to
    numbers of JSON type `number`/`integer`; it does not exempt a NAME from the three checks below.

    Three further checks, added for `validate-heal` (A-S4, spec-validate-heal.md SS2 Stage 0) and
    inherited by every seedsmith pipeline because they live HERE rather than in a program-local
    copy: a `string` property whose `pattern` admits a bare number is exactly as good a hiding place
    for a magnitude as a numeric `type`; an `enum` of numeric STRINGS (`"1"`, `"2"`) is the same
    invention wearing a string's clothes; and a property NAME drawn from the magnitude vocabulary
    (`MAGNITUDE_DENY_NAMES`, or anything ending `MAGNITUDE_DENY_SUFFIX`) is refused regardless of
    its declared type, because the name alone invites a downstream reader to treat it as a real
    magnitude — this one fires even when the value is a legal, enum-closed vocabulary, on purpose.

    `name_allowlist` is the escape hatch the spec requires for the name check ONLY: a property that
    is genuinely an identifier (never entering arithmetic) is exempted BY NAME, per call, with the
    CALLER's own comment saying why — never a blanket exemption baked in here. `field_name` is the
    last-seen property name, threaded through recursion (mirrors `adapters/creatures/anchor/audit.py`'s
    `numeric_audit`) so the name-based checks see it at any nesting depth, including inside an
    array's `items`.
    """
    defects: list[SchemaDefect] = []
    allowlisted = field_name is not None and field_name in name_allowlist

    declared = schema.get("type")
    types = {declared} if isinstance(declared, str) else set(declared or ())
    if types & NUMERIC_JSON_TYPES and "enum" not in schema and "const" not in schema:
        defects.append(SchemaDefect(
            path,
            f"bare numeric field (type {sorted(types & NUMERIC_JSON_TYPES)}) — magnitudes come "
            f"from `numerics`, never from a model; an invented number looks plausible and is "
            f"anchored to nothing",
        ))

    if not allowlisted and _pattern_admits_bare_number(schema):
        defects.append(SchemaDefect(
            path,
            f"string field's pattern {schema.get('pattern')!r} admits a bare number — a magnitude "
            f"smuggled through a 'closed' pattern is still a magnitude a model invented",
        ))

    if not allowlisted and _enum_is_all_numeric_strings(schema):
        defects.append(SchemaDefect(
            path,
            f"enum {schema.get('enum')!r} is entirely numeric strings — a magnitude wearing a "
            f"vocabulary, not a real closed set of named values",
        ))

    if field_name is not None and not allowlisted and _field_name_is_magnitude(field_name):
        defects.append(SchemaDefect(
            path,
            f"property name {field_name!r} names a magnitude by convention (deny-list "
            f"{sorted(MAGNITUDE_DENY_NAMES)} or a name ending {MAGNITUDE_DENY_SUFFIX!r}) — a "
            f"safe-looking declared type does not fix a dangerous name; allow-list it BY NAME, "
            f"with a comment saying why it never enters arithmetic, if it is genuinely an "
            f"identifier",
        ))

    for name, sub in (schema.get("properties") or {}).items():
        if isinstance(sub, dict):
            defects.extend(audit_schema(sub, path=f"{path}.{name}", field_name=name,
                                        name_allowlist=name_allowlist))

    items = schema.get("items")
    if isinstance(items, dict):
        defects.extend(audit_schema(items, path=f"{path}[]", field_name=field_name,
                                    name_allowlist=name_allowlist))
    elif isinstance(items, list):
        for i, sub in enumerate(items):
            if isinstance(sub, dict):
                defects.extend(audit_schema(sub, path=f"{path}[{i}]", field_name=field_name,
                                            name_allowlist=name_allowlist))

    for keyword in ("anyOf", "oneOf", "allOf"):
        for i, sub in enumerate(schema.get(keyword) or ()):
            if isinstance(sub, dict):
                defects.extend(audit_schema(sub, path=f"{path}.{keyword}[{i}]", field_name=field_name,
                                            name_allowlist=name_allowlist))

    if path == "$" and BLOCKED_FIELD not in (schema.get("properties") or {}):
        defects.append(SchemaDefect(
            path,
            f"no {BLOCKED_FIELD!r} variant — a model with no way to decline invents instead, and "
            f"a pipeline that reads 'I cannot' as an error retries it forever",
        ))

    return defects


@dataclass(frozen=True)
class PipelineResult:
    """What one pipeline run produced.

    `blocked` is separate from `escalated` on purpose. Blocked means the model declined with a
    reason — reportable, not a failure. Escalated means retries were exhausted with the defect still
    present, which is a real problem for a human. Collapsing them hides the difference exactly when
    someone is deciding whether to intervene.
    """

    accepted: Mapping[str, Any] = field(default_factory=dict)
    blocked: Mapping[str, str] = field(default_factory=dict)
    escalated: Mapping[str, str] = field(default_factory=dict)
    attempts: int = 0

    @property
    def wrote_anything(self) -> bool:
        return bool(self.accepted)

    @property
    def ok(self) -> bool:
        """Blocked is not failure. Only an escalation is."""
        return not self.escalated


@dataclass(frozen=True)
class Pipeline:
    """One generation pipeline, per spec-pipeline.md §2.

    `on_persist` is injected rather than imported so a run can be proven to write **nothing** —
    which is how the `blocked` acceptance is asserted without a filesystem.
    """

    metric: str
    scope: str
    schema: Mapping[str, Any]
    gate: Callable[[Mapping[str, Any]], Sequence[str]]
    on_persist: Callable[[str, Mapping[str, Any]], None]
    model: str = "sonnet"
    max_retries: int = 2

    def __post_init__(self) -> None:
        defects = audit_schema(self.schema)
        if defects:
            raise ValueError(
                f"pipeline {self.metric!r} has an unusable schema:\n"
                + "\n".join(f"  - {d}" for d in defects)
            )
