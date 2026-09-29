"""The dungeon schema audit (D1.7, spec-dungeon-seed-contract.md §2). Reuses the four smuggling
shapes `adapters/creatures/anchor/audit.py`'s `numeric_audit` already checks (a bare numeric type, a
pattern admitting a bare digit string, an all-numeric-string enum, a deny-listed field name) —
duplicated here rather than imported, because that function's allow-list is a hard-coded relative
import of its OWN sibling `schema.py`; this module needs the SAME shape against the dungeon
adapter's own `ALLOWLISTED_INTEGER_FIELDS` instead. Adds three dungeon-specific rules: the stem
check (S2-12: `*weight*`/`*chance*` anywhere in a property name), the spelled-number enum check,
and the PLANNED-const check (a PLANNED field offered as a free enum is a contract defect, §1).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from ...pipeline.model import NUMERIC_JSON_TYPES
from .schema import ALLOWLISTED_INTEGER_FIELDS, PLANNED_FIELDS_BY_KIND, SCHEMA_BUILDERS, build_schema

#: Field names (case-insensitive, exact) that name a magnitude outright regardless of declared
#: type — the creatures/anchor/audit.py precedent, mirrored so a magnitude smuggled as a "closed"
#: string enum of digits cannot pass either.
MAGNITUDE_DENY_NAMES = frozenset({
    "hp", "atk", "attack", "damage", "defense", "armor", "cost", "weight", "chance", "permille",
})
MAGNITUDE_DENY_SUFFIX = "Milli"

#: S2-12's stem check — unlike the exact-match deny list above, this catches a name that merely
#: CONTAINS the stem anywhere ("weightBand", "spawnChance") — the exact incident this rule exists
#: for: "weightBand" is a second frequency vocabulary hiding behind a name that reads as a band.
_STEM_PATTERN = re.compile(r"weight|chance", re.IGNORECASE)

#: "one" through "ten" — an enum smuggling a count as a spelled word instead of a true band.
SPELLED_NUMBERS = frozenset({
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
})

_DIGIT_PROBES = ("0", "1", "7", "42", "999", "1000000")
_NUMERIC_STRING = re.compile(r"^-?\d+(\.\d+)?$")


@dataclass(frozen=True)
class AuditDefect:
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
    return all(compiled.fullmatch(probe) for probe in _DIGIT_PROBES)


def _enum_is_all_numeric_strings(node: Mapping[str, Any]) -> bool:
    values = node.get("enum")
    if not isinstance(values, list) or not values:
        return False
    return all(isinstance(v, str) and _NUMERIC_STRING.match(v) for v in values)


def _enum_has_spelled_number(node: Mapping[str, Any]) -> "list[str]":
    values = node.get("enum")
    if not isinstance(values, list):
        return []
    return [v for v in values if isinstance(v, str) and v.lower() in SPELLED_NUMBERS]


def _field_name_is_magnitude(name: str) -> bool:
    lname = name.lower()
    if lname in MAGNITUDE_DENY_NAMES:
        return True
    return name.endswith(MAGNITUDE_DENY_SUFFIX)


def numeric_audit(schema: Mapping[str, Any], *, path: str = "$", field_name: "str | None" = None) -> "list[AuditDefect]":
    """Walks `properties`/`items`/`anyOf`/`oneOf`/`allOf`, reporting all smuggling shapes: the four
    base cases (creatures/anchor/audit.py precedent) plus the dungeon-specific stem check and
    spelled-number check."""
    defects: "list[AuditDefect]" = []
    allowlisted = field_name in ALLOWLISTED_INTEGER_FIELDS

    if not allowlisted and _is_bare_numeric_type(schema):
        declared = schema.get("type")
        types = {declared} if isinstance(declared, str) else set(declared or ())
        kind = "integer" if "integer" in types else "number"
        defects.append(AuditDefect(
            path, f"bare-{kind}",
            f"bare numeric field (type {kind}) with no enum/const — magnitudes are resolved by the "
            f"consuming module's own tuning, never authored in a seed; allow-list by name if this "
            f"is a real structural identifier"))

    if not allowlisted and _pattern_admits_bare_number(schema):
        defects.append(AuditDefect(
            path, "pattern-admits-number",
            f"string field's pattern {schema.get('pattern')!r} matches a bare digit string — a "
            f"model can smuggle a magnitude through a 'closed' pattern"))

    if _enum_is_all_numeric_strings(schema):
        defects.append(AuditDefect(
            path, "enum-numeric-strings",
            f"every enum member is a numeric string {schema.get('enum')!r} — a magnitude wearing "
            f"a vocabulary, not a real closed set of named values"))

    if field_name is not None and _field_name_is_magnitude(field_name) and not allowlisted:
        defects.append(AuditDefect(
            path, "deny-listed-name",
            f"field name {field_name!r} names a magnitude by convention — even a safe-looking "
            f"declared type does not clear a deny-listed name"))

    if field_name is not None and _STEM_PATTERN.search(field_name):
        defects.append(AuditDefect(
            path, "weight-or-chance-stem",
            f"field name {field_name!r} matches the *weight*/*chance* stem (S2-12) — rename to a "
            f"real band (e.g. dropBand) with its own {{min,max}} tuning row; weightBand died for "
            f"exactly this reason"))

    spelled = _enum_has_spelled_number(schema)
    if spelled:
        defects.append(AuditDefect(
            path, "spelled-number-enum",
            f"enum member(s) {spelled} spell a number — use a true band with a {{min,max}} tuning "
            f"row (e.g. countBand: lone) or an allow-listed structural int with a comment"))

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


def planned_const_audit(kind: str, schema: Mapping[str, Any]) -> "list[AuditDefect]":
    """§2's fourth dungeon-specific rule: every PLANNED field must be pinned `const` in the
    per-call schema — a PLANNED field exposed as a free `enum` is the exact defect §1 forbids
    ("a wrong ordinal that resolves to a Θ delta is as invisible as a wrong number")."""
    defects: "list[AuditDefect]" = []
    planned = PLANNED_FIELDS_BY_KIND.get(kind, frozenset())
    properties = schema.get("properties") or {}
    for field in planned:
        node = properties.get(field)
        if node is None:
            continue  # a missing PLANNED field is every_field_has_exactly_one_level's finding, not this one's
        if "const" not in node:
            defects.append(AuditDefect(
                f"$.{field}", "planned-not-const",
                f"'{field}' is PLANNED but the per-call schema offers it as a free choice "
                f"('const' is absent) — the model may not choose a PLANNED value, only see it"))
    return defects


def run_audit(kind: "str | None" = None) -> "dict[str, list[AuditDefect]]":
    """The full §2 audit — `numeric_audit` plus `planned_const_audit` — over one kind or all seven.
    An empty list per kind means clean; `contract --audit` exits 1 if any list is non-empty."""
    kinds = [kind] if kind else list(SCHEMA_BUILDERS)
    results: "dict[str, list[AuditDefect]]" = {}
    for k in kinds:
        schema = build_schema(k)
        results[k] = numeric_audit(schema) + planned_const_audit(k, schema)
    return results
