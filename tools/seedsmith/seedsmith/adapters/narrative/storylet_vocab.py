"""The storylet vocabulary registries and their readers (spec-storylet-vocab.md §3, NS20).

Three closed registries — which places can show a storylet (`host-kinds`), what a player can do
(`choice-kinds`) and the authored shapes the planner allocates (`choice-patterns`) — plus the rules that
make them a vocabulary rather than three lists:

- **The Delve rows join the real room-kind registry**, and their `climateNeutral` flag must equal that
  row's own flag. A non-Delve row carries `roomKind: none` and no join.
- **Climate has one source per host**: `room` (the Delve, today's path), `sector` (world — owner ruling
  R20: the sector-type registry is RETIRED, all seven climates are legal at every world host) or `none`.
- **A pattern's `position` is the vote position**, and the shape rules (one `leave` with one outcome,
  exactly two unconditioned slots, no kind twice, outcomes 1-3, every kind covered) are what make the
  slots votable by position.

Every member list here is a declaration and every value in the files carries its own `description` and
`negative` clause, so a test can prove the negative exists.

Read fresh on every call, never transcribed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...workspace_roots import content_root
from ..dungeon.schema import ELEMENTS, EVENT_KIND

__all__ = [
    "REGISTRY_DIR", "STORYLET_KINDS", "CLIMATES", "PLACES", "CLIMATE_SOURCES", "GATES", "ARG_FAMILIES",
    "load_host_kinds", "load_choice_kinds", "load_choice_patterns", "load_room_kinds",
    "load_conditions", "load_consequence_kinds", "load_role_tags", "built_leaves", "proposed_leaves",
    "validate_host_kinds", "validate_choice_kinds", "validate_patterns", "validate_conditions",
    "validate_consequence_kinds", "validate_role_tags", "requirement_defects", "all_defects",
    "USABLE_IN", "RELATION_FACT_KINDS", "ROLE_KINDS", "REQUIREMENT_FAMILIES", "REQUIREMENT_SHAPE",
    "CONDITION_ARG_FAMILIES", "FIRST_SESSION_CHECKPOINTS", "load_value_notes", "load_teaches",
    "value_note_sources", "loop_headings", "validate_value_notes", "validate_teaches",
    "TEACHING_CARRIERS", "TEACHING_ORDER",
]

REGISTRY_DIR = "data/seed/narrative/_registry"
HOST_KINDS_REL = f"{REGISTRY_DIR}/host-kinds.v1.json"
CHOICE_KINDS_REL = f"{REGISTRY_DIR}/choice-kinds.v1.json"
CHOICE_PATTERNS_REL = f"{REGISTRY_DIR}/choice-patterns.v1.json"
ROOM_KINDS_REL = "data/seed/dungeon/_registry/room-kinds.v1.json"
CONDITIONS_REL = f"{REGISTRY_DIR}/conditions.v1.json"
CONSEQUENCE_KINDS_REL = f"{REGISTRY_DIR}/consequence-kinds.v1.json"
ROLE_TAGS_REL = f"{REGISTRY_DIR}/role-tags.v1.json"
PREDICATE_NODE_REL = "src/FusionRpg.Core/Effects/Atoms/PredicateNode.cs"

#: The storylet kinds are the dungeon's own event kinds — one vocabulary, imported rather than copied.
STORYLET_KINDS: "tuple[str, ...]" = tuple(EVENT_KIND)
#: The seven climates, in the rotation order the event planner already uses.
CLIMATES: "tuple[str, ...]" = tuple(ELEMENTS) + ("none",)
PLACES: "tuple[str, ...]" = ("delve", "world", "homeworld", "expedition")
CLIMATE_SOURCES: "tuple[str, ...]" = ("room", "sector", "none")
GATES: "tuple[str, ...]" = ("none", "intrinsic")
USABLE_IN: "tuple[str, ...]" = ("slot", "eligibility")#: The five relation fact kinds `relation.shift` may carry — the runtime derives bands from these.
RELATION_FACT_KINDS: "tuple[str, ...]" = ("met", "helped", "refused", "betrayed", "spared")
ROLE_KINDS: "tuple[str, ...]" = ("required", "optional", "forbidden", "none")
REQUIREMENT_FAMILIES: "tuple[str, ...]" = ("source", "side", "element", "characterRole")
#: One shape for every requirement, on disk and in every schema.
REQUIREMENT_SHAPE = "<family>:<value>"
#: The closed argument families a CONDITION may name (its own list: a condition's argument is a named
#: value from a registry — a band, the disposition ladder, the character-state wire ids, a flag, a gate id or
#: a role — never one of the role-requirement families).
CONDITION_ARG_FAMILIES: "tuple[str, ...]" = ("none", "dangerBand", "disposition", "characterState",
                                            "storyFlag", "levelGate", "roleId")
ARG_FAMILIES: "tuple[str, ...]" = ("none", "supplyTag", "stock", "element")

_HOST_KEYS = frozenset({"id", "place", "roomKind", "admits", "climateNeutral", "climateSource",
                        "climates", "description", "negative"})
_CHOICE_KEYS = frozenset({"id", "gate", "argFamily", "description", "negative"})
_PATTERN_KEYS = frozenset({"id", "slots", "fitsKinds", "description", "negative"})
_SLOT_KEYS = frozenset({"choiceKind", "outcomes", "position"})


def _path(rel: str, path: "Path | str | None") -> Path:
    return Path(path) if path is not None else content_root() / rel


def _read(rel: str, key: str, allowed: "frozenset[str]", path: "Path | str | None" = None) -> "list[dict]":
    document = json.loads(_path(rel, path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or "schemaVersion" not in document:
        raise ValueError(f"{rel}: every registry carries a schemaVersion")
    rows = document.get(key)
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{rel}: {key!r} must be a non-empty list")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{rel}: every row must be an object")
        unknown = sorted(set(row) - allowed)
        if unknown:
            raise ValueError(f"{rel}: row {row.get('id')!r} has unknown key(s) {unknown} — allowed: "
                             f"{sorted(allowed)}")
        missing = sorted(allowed - set(row))
        if missing:
            raise ValueError(f"{rel}: row {row.get('id')!r} is missing required key(s) {missing}")
    return rows


def load_host_kinds(path: "Path | str | None" = None) -> "list[dict]":
    return _read(HOST_KINDS_REL, "hostKinds", _HOST_KEYS, path)


def load_choice_kinds(path: "Path | str | None" = None) -> "list[dict]":
    return _read(CHOICE_KINDS_REL, "choiceKinds", _CHOICE_KEYS, path)


def load_choice_patterns(path: "Path | str | None" = None) -> "list[dict]":
    return _read(CHOICE_PATTERNS_REL, "choicePatterns", _PATTERN_KEYS, path)


def load_room_kinds(path: "Path | str | None" = None) -> "dict[str, dict]":
    document = json.loads(_path(ROOM_KINDS_REL, path).read_text(encoding="utf-8"))
    rows = document.get("roomKinds")
    if not isinstance(rows, dict):
        raise ValueError(f"{ROOM_KINDS_REL}: roomKinds must be an object")
    return rows


def _prose_defects(rows: "Sequence[Mapping[str, Any]]", label: str) -> "list[str]":
    defects = []
    for row in rows:
        for key in ("description", "negative"):
            if not str(row.get(key) or "").strip():
                defects.append(f"{label} {row.get('id')!r} has no {key}")
    return defects


def validate_host_kinds(hosts: "Sequence[Mapping[str, Any]]", room_kinds: "Mapping[str, Mapping[str, Any]]",
                        *, storylet_kinds: "Sequence[str]" = STORYLET_KINDS) -> "list[str]":
    """The join and climate rules. Returns defect strings; empty means clean."""
    defects = _prose_defects(hosts, "host")
    seen: "set[str]" = set()
    for host in hosts:
        host_id = str(host["id"])
        if host_id in seen:
            defects.append(f"duplicate host id {host_id!r}")
        seen.add(host_id)
        if host["place"] not in PLACES:
            defects.append(f"host {host_id!r}: place {host['place']!r} is outside {list(PLACES)}")
        if host["climateSource"] not in CLIMATE_SOURCES:
            defects.append(f"host {host_id!r}: climateSource {host['climateSource']!r} is outside "
                           f"{list(CLIMATE_SOURCES)}")
        admits = list(host["admits"])
        if not admits:
            defects.append(f"host {host_id!r} admits no storylet kind")
        for kind in admits:
            if kind not in storylet_kinds:
                defects.append(f"host {host_id!r}: admits {kind!r}, which is no storylet kind")
        room_kind = host["roomKind"]
        if host["place"] == "delve":
            row = room_kinds.get(str(room_kind))
            if row is None:
                defects.append(f"host {host_id!r}: roomKind {room_kind!r} is not a real room kind")
            elif bool(row.get("climateNeutral")) != bool(host["climateNeutral"]):
                defects.append(f"host {host_id!r}: climateNeutral {host['climateNeutral']} disagrees with "
                               f"room kind {room_kind!r}'s own flag {row.get('climateNeutral')}")
        elif room_kind != "none":
            defects.append(f"host {host_id!r}: a non-Delve host must carry roomKind 'none'")
        climates = list(host["climates"])
        if host["climateSource"] == "sector":
            if sorted(climates) != sorted(CLIMATES):
                defects.append(f"host {host_id!r}: a sector host must admit all seven climates, got "
                               f"{climates}")
        elif climates:
            defects.append(f"host {host_id!r}: climateSource {host['climateSource']!r} carries no climates "
                           f"of its own, got {climates}")
    return defects


def validate_choice_kinds(kinds: "Sequence[Mapping[str, Any]]") -> "list[str]":
    defects = _prose_defects(kinds, "choice kind")
    seen: "set[str]" = set()
    for kind in kinds:
        kind_id = str(kind["id"])
        if kind_id in seen:
            defects.append(f"duplicate choice kind {kind_id!r}")
        seen.add(kind_id)
        if kind["gate"] not in GATES:
            defects.append(f"choice kind {kind_id!r}: gate {kind['gate']!r} is outside {list(GATES)}")
        if kind["argFamily"] not in ARG_FAMILIES:
            defects.append(f"choice kind {kind_id!r}: argFamily {kind['argFamily']!r} is outside "
                           f"{list(ARG_FAMILIES)}")
        if (kind["gate"] == "none") != (kind["argFamily"] == "none"):
            defects.append(f"choice kind {kind_id!r}: only an intrinsically gated kind takes an argument "
                           f"family (gate={kind['gate']!r}, argFamily={kind['argFamily']!r})")
    return defects


def validate_patterns(patterns: "Sequence[Mapping[str, Any]]",
                      choice_kinds: "Sequence[Mapping[str, Any]]",
                      *, storylet_kinds: "Sequence[str]" = STORYLET_KINDS) -> "list[str]":
    """The §3.3 shape rules, one condition per rule. Returns defect strings; empty means clean."""
    defects = _prose_defects(patterns, "pattern")
    gates = {str(kind["id"]): str(kind["gate"]) for kind in choice_kinds}
    seen: "set[str]" = set()
    seen_kinds: "set[str]" = set()
    fits: "set[str]" = set()
    for pattern in patterns:
        pattern_id = str(pattern["id"])
        if pattern_id in seen:
            defects.append(f"duplicate pattern id {pattern_id!r}")
        seen.add(pattern_id)
        slots = list(pattern["slots"])
        if not 2 <= len(slots) <= 4:
            defects.append(f"pattern {pattern_id!r}: {len(slots)} slots, outside 2-4")
        if [slot["position"] for slot in slots] != list(range(len(slots))):
            defects.append(f"pattern {pattern_id!r}: positions must be 0..n-1 in order (the vote order)")
        slot_kinds = [str(slot["choiceKind"]) for slot in slots]
        if len(set(slot_kinds)) != len(slot_kinds):
            defects.append(f"pattern {pattern_id!r}: a choice kind appears twice")
        for slot in slots:
            if str(slot["choiceKind"]) not in gates:
                defects.append(f"pattern {pattern_id!r}: slot names unknown choice kind "
                               f"{slot['choiceKind']!r}")
            if not 1 <= int(slot["outcomes"]) <= 3:
                defects.append(f"pattern {pattern_id!r}: slot {slot['choiceKind']!r} has "
                               f"{slot['outcomes']} outcomes, outside 1-3")
        leaves = [(slot, slot_kinds.count("leave")) for slot in slots if str(slot["choiceKind"]) == "leave"]
        if len(leaves) != 1:
            defects.append(f"pattern {pattern_id!r}: exactly one `leave` slot is required, found "
                           f"{len(leaves)}")
        elif int(leaves[0][0]["outcomes"]) != 1:
            defects.append(f"pattern {pattern_id!r}: `leave` must have exactly one outcome")
        unconditioned = [k for k in slot_kinds if gates.get(k) == "none"]
        if len(unconditioned) != 2:
            defects.append(f"pattern {pattern_id!r}: exactly two unconditioned slots are required, found "
                           f"{len(unconditioned)} ({unconditioned})")
        intrinsic = [k for k in slot_kinds if gates.get(k) == "intrinsic"]
        if len(intrinsic) > 2:
            defects.append(f"pattern {pattern_id!r}: at most two intrinsic slots, found {len(intrinsic)}")
        for kind in slot_kinds:
            seen_kinds.add(kind)
        for kind in list(pattern["fitsKinds"]):
            if kind not in storylet_kinds:
                defects.append(f"pattern {pattern_id!r}: fitsKinds names {kind!r}, no storylet kind")
            fits.add(str(kind))
    for kind in sorted(set(gates) - seen_kinds):
        defects.append(f"choice kind {kind!r} appears in no pattern")
    for kind in sorted(set(storylet_kinds) - fits):
        defects.append(f"storylet kind {kind!r} has no fitting pattern")
    return defects


_CONDITION_KEYS = frozenset({"id", "argFamily", "usableIn", "compilesTo", "description", "negative"})
_CONSEQUENCE_KEYS = frozenset({"id", "refForms", "params", "routesTo", "description", "negative"})


def load_conditions(path: "Path | str | None" = None) -> "list[dict]":
    return _read(CONDITIONS_REL, "conditions", _CONDITION_KEYS, path)


def load_consequence_kinds(path: "Path | str | None" = None) -> "list[dict]":
    return _read(CONSEQUENCE_KINDS_REL, "consequenceKinds", _CONSEQUENCE_KEYS, path)


def load_role_tags(path: "Path | str | None" = None) -> dict:
    document = json.loads(_path(ROLE_TAGS_REL, path).read_text(encoding="utf-8"))
    for key in ("roleKinds", "requireFamilies", "requirementShape"):
        if key not in document:
            raise ValueError(f"{ROLE_TAGS_REL}: missing {key!r}")
    return document


def proposed_leaves(path: "Path | str | None" = None) -> "tuple[str, ...]":
    """The leaves this file names as owed to `narrative-predicates`."""
    document = json.loads(_path(CONDITIONS_REL, path).read_text(encoding="utf-8"))
    return tuple(document.get("proposedLeaves") or ())


def built_leaves(path: "Path | str | None" = None) -> "tuple[str, ...]":
    """The `LeafId` members the RUNTIME actually has, parsed from `PredicateNode.cs` — the file, never a
    comment or a doc, is the authority on which leaves are built."""
    source = _path(PREDICATE_NODE_REL, path).read_text(encoding="utf-8")
    match = re.search(r"enum\s+LeafId\s*\{(?P<body>[^}]*)\}", source, re.S)
    if match is None:
        raise ValueError(f"{PREDICATE_NODE_REL}: no LeafId enum found — the runtime owns this vocabulary")
    names = re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)", match.group("body"), re.M)
    return tuple(sorted({name for name in names if name != "None"}))


def validate_conditions(conditions: "Sequence[Mapping[str, Any]]", proposed: "Sequence[str]",
                        built: "Sequence[str]",
                        *, families: "Sequence[str]" = CONDITION_ARG_FAMILIES) -> "list[str]":
    """A named leaf is BUILT or PROPOSED — never both, never neither. `role requirement` is neither:
    casting decides it before eligibility is evaluated."""
    defects = _prose_defects(conditions, "condition")
    both = sorted(set(proposed) & set(built))
    if both:
        defects.append(f"leaf/leaves are both built and proposed: {both}")
    proposed_set, built_set = set(proposed), set(built)
    known_families = set(families) | {"none"}
    for condition in conditions:
        condition_id = str(condition["id"])
        for value in list(condition["usableIn"]):
            if value not in USABLE_IN:
                defects.append(f"condition {condition_id!r}: usableIn {value!r} is outside {list(USABLE_IN)}")
        arg = str(condition["argFamily"])
        if condition_id == "none":
            if arg != "none":
                defects.append(f"condition 'none' must carry argFamily 'none', got {arg!r}")
        elif arg not in known_families:
            defects.append(f"condition {condition_id!r}: argFamily {arg!r} is outside "
                           f"{sorted(known_families)}")
        compiles = str(condition["compilesTo"])
        if condition_id == "none" or compiles.startswith("role requirement"):
            continue   # `none` compiles to nothing, and casting resolves a role requirement
        if compiles not in built_set and compiles not in proposed_set:
            defects.append(f"condition {condition_id!r}: leaf {compiles!r} is neither built nor proposed")
    return defects


def validate_consequence_kinds(kinds: "Sequence[Mapping[str, Any]]") -> "list[str]":
    """`refForms` non-empty exactly where `ref` is required, every form `<prefix>:<id>`, and
    `relation.shift`'s params the five relation fact kinds (the runtime derives bands from exactly those)."""
    defects = _prose_defects(kinds, "consequence kind")
    optional_ref = {"none", "loot", "encounter", "scout", "battle.start", "doctrine.setback"}
    params_by_kind = {str(kind["id"]): list(kind["params"]) for kind in kinds}
    for kind in kinds:
        kind_id = str(kind["id"])
        forms = list(kind["refForms"])
        if not forms and kind_id not in optional_ref:
            defects.append(f"consequence kind {kind_id!r}: `ref` is required, so refForms must not be empty")
        for form in forms:
            if ":" not in str(form) or not str(form).split(":", 1)[1].strip():
                defects.append(f"consequence kind {kind_id!r}: refForm {form!r} is not `<prefix>:<id>`")
    if params_by_kind.get("relation.shift") != list(RELATION_FACT_KINDS):
        defects.append(f"relation.shift params must be the relation fact kinds "
                       f"{list(RELATION_FACT_KINDS)}, got {params_by_kind.get('relation.shift')}")
    if "none" not in params_by_kind.get("none", []):
        defects.append("consequence kind 'none' must carry a `none` param row")
    return defects


def requirement_defects(requires: "Sequence[str]", *,
                        families: "Sequence[str]" = REQUIREMENT_FAMILIES) -> "list[str]":
    """Every requirement is one shape, `<family>:<value>`, with a closed family and a non-empty value."""
    defects = []
    for requirement in requires:
        text = str(requirement)
        family, separator, value = text.partition(":")
        if not separator or not value.strip() or family not in families:
            defects.append(f"requirement {text!r} is not {REQUIREMENT_SHAPE} with a family of "
                           f"{list(families)}")
    return defects


def validate_role_tags(tags: "Mapping[str, Any]") -> "list[str]":
    defects: "list[str]" = []
    kinds = [str(row["id"]) for row in tags["roleKinds"]]
    if kinds != list(ROLE_KINDS):
        defects.append(f"roleKinds must be {list(ROLE_KINDS)}, got {kinds}")
    for row in tags["roleKinds"]:
        for key in ("description", "negative"):
            if not str(row.get(key) or "").strip():
                defects.append(f"role kind {row['id']!r} has no {key}")
    families = tags["requireFamilies"]
    if sorted(families) != sorted(REQUIREMENT_FAMILIES):
        defects.append(f"requireFamilies must be {list(REQUIREMENT_FAMILIES)}, got {sorted(families)}")
    for family, row in families.items():
        if family == "characterRole":
            if row.get("valuesFrom") != "roles.v1.json":
                defects.append("characterRole must take its values from roles.v1.json")
            continue
        if not list(row.get("values") or []):
            defects.append(f"requirement family {family!r} declares no values")
    if sorted(families["element"]["values"]) != sorted(ELEMENTS):
        defects.append("the element family must be the six elements")
    if tags["requirementShape"] != REQUIREMENT_SHAPE:
        defects.append(f"requirementShape must be {REQUIREMENT_SHAPE!r}")
    return defects


VALUE_NOTES_REL = f"{REGISTRY_DIR}/value-notes.v1.json"
TEACHES_REL = f"{REGISTRY_DIR}/teaches.v1.json"
LOOPS_DOC_REL = "docs/guide/the-loops.md"

#: The first-session checkpoints another spec owns — no `teaches` value may name one of these mechanics.
FIRST_SESSION_CHECKPOINTS: "tuple[str, ...]" = ("lawn-first-win", "dave-sheet", "species-xp-level-3",
                                              "dave-first-item")
#: The carriers that can teach, and the teaching order the spine reads.
TEACHING_CARRIERS: "tuple[str, ...]" = ("spine", "storylet")
TEACHING_ORDER: "tuple[str, ...]" = ("expedition-dispatch", "talk-verbs", "offer-cost", "bring-option",
                                    "relation-bands", "quest-log", "delve-extract", "world-command",
                                    "fusion", "counter-doctrine")

_VALUE_NOTE_KEYS = frozenset({"key", "source", "value", "note", "negative"})
_TEACHES_KEYS = frozenset({"value", "teachingOrder", "loop", "carriers", "requires", "teachingLine",
                           "negative"})


def load_value_notes(path: "Path | str | None" = None) -> "list[dict]":
    return _read(VALUE_NOTES_REL, "valueNotes", _VALUE_NOTE_KEYS, path)


def load_teaches(path: "Path | str | None" = None) -> "list[dict]":
    return _read(TEACHES_REL, "teaches", _TEACHES_KEYS, path)


def value_note_sources() -> "dict[str, list[str]]":
    """The borrowed lists a model sees, with the members read from the thing that owns them: the
    dungeon event schema's two enums, the dungeon registries (atom families, power bands) and this
    module's own pinned families."""
    from ..dungeon import registries as dungeon_registries
    from ..dungeon.schema import EVENT_KIND, build_event_schema

    item = build_event_schema()["properties"]["outcomes"]["items"]["properties"]
    return {
        "outcomeOrdinal": list(item["ordinal"]["enum"]),
        "dropBand": list(item["dropBand"]["enum"]),
        "eventKind": list(EVENT_KIND),
        "atomFamily": sorted(dungeon_registries.load_grantable_atom_families()),
        "powerBand": sorted(dungeon_registries.load_power_bands()),
        "conditionArgFamily": [f for f in CONDITION_ARG_FAMILIES if f != "none"],
        "requirementFamily": list(REQUIREMENT_FAMILIES),
        "relationFact": list(RELATION_FACT_KINDS),
        "choiceGate": [g for g in GATES if g != "none"],
    }


def loop_headings(path: "Path | str | None" = None) -> "tuple[str, ...]":
    """The loop headings of `docs/guide/the-loops.md`, parsed from the document (the loops SSOT)."""
    source = _path(LOOPS_DOC_REL, path).read_text(encoding="utf-8")
    return tuple(re.findall(r"^### (.+)$", source, re.M))


def validate_value_notes(rows: "Sequence[Mapping[str, Any]]",
                         sources: "Mapping[str, Sequence[str]] | None" = None) -> "list[str]":
    """Note keys equal each source's members plus `none` EXACTLY, and every model-facing list carries a
    `none` row — so the notes can never drift from the lists they describe."""
    sources = sources if sources is not None else value_note_sources()
    defects: "list[str]" = []
    expected = {f"{lst}.{value}" for lst, members in sources.items()
                for value in list(members) + ["none"]}
    actual = {str(row["key"]) for row in rows}
    for key in sorted(expected - actual):
        defects.append(f"value note {key!r} is missing (every source member and `none` needs one)")
    for key in sorted(actual - expected):
        defects.append(f"value note {key!r} describes no source member")
    for row in rows:
        if str(row["key"]) != f"{row['source']}.{row['value']}":
            defects.append(f"value note {row['key']!r} does not match its own source.value")
        for field in ("note", "negative"):
            if not str(row.get(field) or "").strip():
                defects.append(f"value note {row['key']!r} has no {field}")
    for lst in sources:
        if f"{lst}.none" not in actual:
            defects.append(f"model-facing list {lst!r} has no `none` note")
    return defects


def validate_teaches(rows: "Sequence[Mapping[str, Any]]",
                     headings: "Sequence[str] | None" = None) -> "list[str]":
    """The teaching list closes and keeps its order: ids unique, `teachingOrder` 1..n in file order, every
    `loop` an actual heading of the loops SSOT, carriers closed, the authored teaching line present and
    digit-free, and no first-session checkpoint mechanic named."""
    headings = tuple(headings) if headings is not None else loop_headings()
    defects: "list[str]" = []
    seen: "set[str]" = set()
    for index, row in enumerate(rows, start=1):
        value = str(row["value"])
        if value in seen:
            defects.append(f"duplicate teaches value {value!r}")
        seen.add(value)
        if int(row["teachingOrder"]) != index:
            defects.append(f"teaches {value!r}: teachingOrder {row['teachingOrder']} is not its file position "
                           f"{index}")
        if str(row["loop"]) not in headings:
            defects.append(f"teaches {value!r}: loop {row['loop']!r} is no heading of the-loops.md")
        carriers = list(row["carriers"])
        if not carriers:
            defects.append(f"teaches {value!r} names no carrier")
        for carrier in carriers:
            if carrier not in TEACHING_CARRIERS:
                defects.append(f"teaches {value!r}: carrier {carrier!r} is outside {list(TEACHING_CARRIERS)}")
        line = str(row["teachingLine"])
        if not line.strip():
            defects.append(f"teaches {value!r} has no authored teachingLine")
        if any(ch.isdigit() for ch in line):
            defects.append(f"teaches {value!r}: the teachingLine carries a digit (a number belongs to tuning)")
        if "checkpoint" in line.lower():
            defects.append(f"teaches {value!r}: the teachingLine names a first-session checkpoint mechanic")
        if value in FIRST_SESSION_CHECKPOINTS:
            defects.append(f"teaches {value!r} names a first-session checkpoint")
        if not str(row.get("negative") or "").strip():
            defects.append(f"teaches {value!r} has no negative clause")
    return defects


def all_defects() -> "list[str]":
    """Every rule over the COMMITTED files — the reader a report or a test can call."""
    return (validate_host_kinds(load_host_kinds(), load_room_kinds())
            + validate_choice_kinds(load_choice_kinds())
            + validate_patterns(load_choice_patterns(), load_choice_kinds())
            + validate_conditions(load_conditions(), proposed_leaves(), built_leaves())
            + validate_consequence_kinds(load_consequence_kinds())
            + validate_role_tags(load_role_tags())
            + validate_value_notes(load_value_notes())
            + validate_teaches(load_teaches()))
