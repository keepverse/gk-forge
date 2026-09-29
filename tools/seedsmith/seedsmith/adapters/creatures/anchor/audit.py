"""The numeric audit (creature-seed module 2, spec-anchor-contract.md §4) — mechanical, not
editorial. Extends seedsmith's existing `audit_schema` (`seedsmith.pipeline.model`) with three
smuggling shapes that check would miss: a string `pattern` that admits a bare number, an `enum`
whose members are numeric strings, and a field named in the magnitudes deny-list.

Deliberately does **not** reuse `audit_schema`'s "every schema needs a `blocked` variant" rule —
that rule belongs to a per-call pipeline generation schema (`pipeline/model.py`'s own guardrail
#6). `build_anchor_schema()` is the STORED anchor's full validation schema (CAPTURED + DERIVED +
CLASSIFIED together), never itself sent to a model as one call's `response_format` — the model
only ever sees the CLASSIFIED subset, one attribute (or a related few) per pipeline, per Q22 —
so the "blocked" convention is out of scope here and checked instead wherever that subset is
actually assembled into a per-call schema (classify-pipelines, T2.3).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from ....pipeline.model import NUMERIC_JSON_TYPES
from .schema import ALLOWLISTED_INTEGER_FIELDS

#: Field names (case-insensitive) that name a magnitude outright — deny-listed regardless of
#: their declared JSON type, because a magnitude smuggled as a "closed" string enum of digits
#: would otherwise pass every other check.
MAGNITUDE_DENY_NAMES = frozenset({
    "hp", "atk", "attack", "damage", "defense", "armor", "cost", "weight", "chance", "permille",
})

#: Any field name ending in this suffix is a magnitude by convention (e.g. `powerMilli`,
#: `speedMilli`) — matches the shipped C# `*Milli` integer-per-mille naming convention.
MAGNITUDE_DENY_SUFFIX = "Milli"

_DIGIT_PROBES = ("0", "1", "7", "42", "999", "1000000")


@dataclass(frozen=True)
class NumericDefect:
    path: str
    case: str
    reason: str

    def __str__(self) -> str:
        return f"{self.path} [{self.case}]: {self.reason}"


def _is_bare_numeric_type(node: Mapping[str, Any]) -> bool:
    declared = node.get("type")
    types = {declared} if isinstance(declared, str) else set(declared or ())
    return bool(types & NUMERIC_JSON_TYPES) and "enum" not in node and "const" not in node


def _pattern_admits_bare_number(node: Mapping[str, Any]) -> bool:
    pattern = node.get("pattern")
    if not isinstance(pattern, str):
        return False
    try:
        compiled = re.compile(pattern)
    except re.error:
        return False
    # If the pattern matches every one of a handful of plain digit strings, it admits a bare
    # number regardless of what else it might also admit — that is enough to smuggle a magnitude.
    return all(compiled.fullmatch(probe) for probe in _DIGIT_PROBES)


_NUMERIC_STRING = re.compile(r"^-?\d+(\.\d+)?$")


def _enum_is_all_numeric_strings(node: Mapping[str, Any]) -> bool:
    values = node.get("enum")
    if not isinstance(values, list) or not values:
        return False
    return all(isinstance(v, str) and _NUMERIC_STRING.match(v) for v in values)


def _field_name_is_magnitude(name: str) -> bool:
    lname = name.lower()
    if lname in MAGNITUDE_DENY_NAMES:
        return True
    return name.endswith(MAGNITUDE_DENY_SUFFIX)


def numeric_audit(schema: Mapping[str, Any], *, path: str = "$", field_name: "str | None" = None) -> list[NumericDefect]:
    """Walks `properties`/`items`/`anyOf`/`oneOf`/`allOf` exactly like `audit_schema`, reporting
    all five smuggling shapes. `field_name` is the last-seen property name, threaded through
    recursion so the deny-list check (case 5) sees it at any nesting depth.
    """
    defects: "list[NumericDefect]" = []

    allowlisted = field_name in ALLOWLISTED_INTEGER_FIELDS

    if not allowlisted and _is_bare_numeric_type(schema):
        declared = schema.get("type")
        types = {declared} if isinstance(declared, str) else set(declared or ())
        kind = "integer" if "integer" in types else "number"
        defects.append(NumericDefect(
            path, f"bare-{kind}",
            f"bare numeric field (type {kind}) with no enum/const — magnitudes are GENERATED, "
            f"never authored; allow-list by name if this is a real identifier"))

    if not allowlisted and _pattern_admits_bare_number(schema):
        defects.append(NumericDefect(
            path, "pattern-admits-number",
            f"string field's pattern {schema.get('pattern')!r} matches a bare digit string — "
            f"a model can smuggle a magnitude through a 'closed' pattern"))

    if _enum_is_all_numeric_strings(schema):
        defects.append(NumericDefect(
            path, "enum-numeric-strings",
            f"every enum member is a numeric string {schema.get('enum')!r} — this is a magnitude "
            f"wearing a vocabulary, not a real closed set of named values"))

    if field_name is not None and _field_name_is_magnitude(field_name) and not allowlisted:
        defects.append(NumericDefect(
            path, "deny-listed-name",
            f"field name {field_name!r} names a magnitude by convention — even if its declared "
            f"type looks safe today, the name itself is the deny-list violation"))

    for name, sub in (schema.get("properties") or {}).items():
        if isinstance(sub, dict):
            defects.extend(numeric_audit(sub, path=f"{path}.{name}", field_name=name))

    items = schema.get("items")
    if isinstance(items, dict):
        defects.extend(numeric_audit(items, path=f"{path}[]", field_name=field_name))
    elif isinstance(items, list):
        for i, sub in enumerate(items):
            if isinstance(sub, dict):
                defects.extend(numeric_audit(sub, path=f"{path}[{i}]", field_name=field_name))

    for keyword in ("anyOf", "oneOf", "allOf"):
        for i, sub in enumerate(schema.get(keyword) or ()):
            if isinstance(sub, dict):
                defects.extend(numeric_audit(sub, path=f"{path}.{keyword}[{i}]", field_name=field_name))

    return defects
