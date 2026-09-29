"""The uniques audit (D4.29, spec-unique-pipeline.md §1/§7) -- deterministic. Two audit levels,
matching the spec's own `contract --audit` / `audit` command split:

* **Contract-level** (`contract_audit`): schema smuggling shapes (a bare numeric field, a pattern
  admitting a bare digit string, a fully-numeric enum, a deny-listed field name) plus the
  set-stem check (`set*`/`*setId*`/`*setBonus*`/`members`/`thresholds` refused on a unique
  anchor, spec §1: *"the §2 audit gains a set-stem check"*).
* **Post-generation** (`stale_ids`, `budget_report`, `validate_source_locked_once`): checks that
  need a real batch of minted entries, not just the schema.

`validate_source_locked_once` is genuinely new logic, not a port. A dedicated research pass
(D4.29's own, and separately D4.28's C# research the same session) confirmed neither the Python
`adapters/items/acquisition.py` (checks REACHABILITY -- zero vs. one-or-more, never one vs.
two-or-more) nor the C# `UniqueCorpusValidator.ValidateDropReferences` (explicitly skips every
source-locked reference) enforces "referenced by exactly one table" today, in either language --
this function and its C# counterpart (`DungeonLootTableGen.ValidateSourceLockedOnce`, same
session) are each the first real check of that specific rule in their own language.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from ....pipeline.model import NUMERIC_JSON_TYPES

#: Field names (case-insensitive, exact) that name a magnitude outright regardless of declared
#: type -- the creatures/anchor/audit.py precedent, duplicated here rather than imported (that
#: module's allow-list is a hardcoded relative import of its OWN sibling schema.py; dungeon's own
#: copy duplicates for the identical reason). No field in this schema is numeric today -- this
#: check exists to catch one that is added carelessly later, the same preventative posture
#: dungeon's own numeric_audit already takes.
MAGNITUDE_DENY_NAMES = frozenset({
    "hp", "atk", "attack", "damage", "defense", "armor", "cost", "weight", "chance", "permille",
})
MAGNITUDE_DENY_SUFFIX = "Milli"
_STEM_PATTERN = re.compile(r"weight|chance", re.IGNORECASE)

#: spec §1's own set-stem list, verbatim: "`set*`, `*setId*`, `*setBonus*`, `members`,
#: `thresholds` on a unique anchor are refused" -- `set` is its own KindSpec
#: (`themeKey`/`members`/`thresholds`, kinds.py), so any of these names on a `unique` anchor is a
#: set field smuggled onto the wrong kind, never a legitimate unique field under a coincidental name.
_SET_STEM_PATTERN = re.compile(r"^set|setid|setbonus", re.IGNORECASE)
_SET_EXACT_NAMES = frozenset({"members", "thresholds"})

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


def _field_name_is_magnitude(name: str) -> bool:
    lname = name.lower()
    return lname in MAGNITUDE_DENY_NAMES or name.endswith(MAGNITUDE_DENY_SUFFIX)


def _field_name_is_set_stem(name: str) -> bool:
    return bool(_SET_STEM_PATTERN.match(name)) or name.lower() in _SET_EXACT_NAMES


def numeric_audit(schema: Mapping[str, Any], *, path: str = "$", field_name: "str | None" = None) -> "list[AuditDefect]":
    """Walks `properties`/`items`/`anyOf`/`oneOf`/`allOf`, reporting every smuggling shape
    (dungeon/creatures/structures adapters' own shared precedent, duplicated per that convention)
    plus this kind's own set-stem check."""
    defects: "list[AuditDefect]" = []

    if _is_bare_numeric_type(schema):
        declared = schema.get("type")
        types = {declared} if isinstance(declared, str) else set(declared or ())
        kind = "integer" if "integer" in types else "number"
        defects.append(AuditDefect(
            path, f"bare-{kind}",
            f"bare numeric field (type {kind}) with no enum/const -- magnitudes are resolved by "
            f"UniqueContainerBuild.From's own tuning at roll time, never authored in a seed"))

    if _pattern_admits_bare_number(schema):
        defects.append(AuditDefect(
            path, "pattern-admits-number",
            f"string field's pattern {schema.get('pattern')!r} matches a bare digit string -- a "
            f"model can smuggle a magnitude through a 'closed' pattern"))

    if _enum_is_all_numeric_strings(schema):
        defects.append(AuditDefect(
            path, "enum-numeric-strings",
            f"every enum member is a numeric string {schema.get('enum')!r} -- a magnitude wearing "
            f"a vocabulary, not a real closed set of named values"))

    if field_name is not None and _field_name_is_magnitude(field_name):
        defects.append(AuditDefect(
            path, "deny-listed-name",
            f"field name {field_name!r} names a magnitude by convention"))

    if field_name is not None and _STEM_PATTERN.search(field_name):
        defects.append(AuditDefect(
            path, "weight-or-chance-stem",
            f"field name {field_name!r} matches the *weight*/*chance* stem -- rename to a real "
            f"band with its own tuning row"))

    if field_name is not None and _field_name_is_set_stem(field_name):
        defects.append(AuditDefect(
            path, "set-stem",
            f"field name {field_name!r} matches the set-stem list (set*/*setId*/*setBonus*/"
            f"members/thresholds) -- a unique may never be a set member (ssot-uniques.md §3.8, "
            f"'Hard no'); `set` is its own KindSpec"))

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


def contract_audit(schema: "Mapping[str, Any] | None" = None) -> "list[AuditDefect]":
    """`python -m seedsmith items uniques contract --audit`'s own check -- `numeric_audit` over a
    representative schema. Builds one against the REAL registries (placeholder planned ids only)
    when the caller supplies none, since a contract audit checks the SHAPE against production
    vocabularies, never a fixture standing in for them."""
    if schema is None:
        from .briefs import build_unique_schema
        from .planner import Cell
        placeholder_ids = {"id": "<planned:id>", "nameKey": "<planned:nameKey>",
                            "iconKey": "<planned:iconKey>", "flavorKey": "<planned:flavorKey>"}
        cell = Cell("plant", "offense", "firstseed", "plant-offense-firstseed")
        schema = build_unique_schema(cell, placeholder_ids)
    return numeric_audit(schema)


def stale_ids(minted_ids: "Iterable[str]", live_cell_keys: "Iterable[str]") -> "list[str]":
    """An id whose own cell-key portion (`unique.<cell_key>-<nnn>` -> `<cell_key>`) no longer
    names a live grid cell -- e.g. the grid's own axis/band vocabulary changed under a
    previously-minted id. Never mutates or deletes anything; naming the id is the caller's own
    next decision (seedsmith-map Appendix A's tracking-id discipline)."""
    live = frozenset(live_cell_keys)
    stale: "list[str]" = []
    for uid in minted_ids:
        body = uid.removeprefix("unique.")
        cell_key = body.rsplit("-", 1)[0] if "-" in body else body
        if cell_key not in live:
            stale.append(uid)
    return sorted(stale)


def budget_report(count_per_cell: "Mapping[str, int]", actual_per_cell: "Mapping[str, int]") -> "dict[str, dict]":
    """Metrics section: "actual-vs-declared per cell is a pass condition." Reports every cell the
    plan declared, its declared count, its actual (generated) count, and whether they match --
    never a global total, since a global total can hide one starved cell behind a surplus in
    another (the exact anti-convergence failure mode `AxisCollision` exists to catch elsewhere)."""
    cells = sorted(set(count_per_cell) | set(actual_per_cell))
    return {
        cell: {
            "declared": count_per_cell.get(cell, 0),
            "actual": actual_per_cell.get(cell, 0),
            "matches": count_per_cell.get(cell, 0) == actual_per_cell.get(cell, 0),
        }
        for cell in cells
    }


@dataclass(frozen=True)
class SourceLockReference:
    unique_id: str
    table_id: str


@dataclass(frozen=True)
class SourceLockViolation:
    unique_id: str
    table_ids: "tuple[str, ...]"


def validate_source_locked_once(references: "Iterable[SourceLockReference]") -> "list[SourceLockViolation]":
    """"The lock lives in which table references the id" (ideal :1521-1524) -- a source-locked
    unique must be listed by EXACTLY one domain table. Groups by unique id; any id spanning more
    than one DISTINCT table id is a violation, naming every table (so the fix is obvious). A
    unique referenced twice by the SAME table is not a violation -- the rule is about tables, not
    row count."""
    by_unique: "dict[str, set[str]]" = {}
    for ref in references:
        by_unique.setdefault(ref.unique_id, set()).add(ref.table_id)

    violations = [
        SourceLockViolation(uid, tuple(sorted(tables)))
        for uid, tables in by_unique.items() if len(tables) > 1
    ]
    return sorted(violations, key=lambda v: v.unique_id)
