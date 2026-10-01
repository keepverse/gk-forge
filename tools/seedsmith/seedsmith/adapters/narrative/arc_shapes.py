"""The arc-shape registry and its reader (spec-arc-shapes.md §2-§4, NS27).

Each shape fixes its link count, each link's host kind and storylet kind, the roles that persist across
links, and the flags each link sets and reads. The model later writes an arc's name, premise and every link
**inside** a shape, in one work order, so a link can never point past its arc — which is what the committed
corpus shows today: two of four story `chainRef`s point at events that do not exist (map §3.4).

Two properties make this a shape rather than a list:

- **Flag closure.** Every flag a link reads is set by an EARLIER link of the same shape, so an arc's
  eligibility never depends on a link the player has not reached.
- **Role closure.** Every role a link uses is declared by the shape, every declared role is used, and every
  `requires` value resolves in `storylet-vocab` or `character-vocab`.

A shape with an `antagonist` role must set `antagonistRules`, and then owner ruling R13 applies: progress
flags only (no memory of an encounter), at most one antagonist role (no ranked cast), and no `recruit`
choice against it (no growth). Each rule is its own function, so a failure names the rule.

The link-count bounds are read from `gk-data/packs/fusion/data/seed/narrative/_plan/budget.v1.json` (`arc.linkCount`), never a
constant: a bound no file owns is the code-owned tunable this project forbids.

Read fresh on every call, never transcribed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...workspace_roots import content_root, core_root
from . import character_vocab, storylet_vocab
from .token_grammar import RESERVED_SUFFIXES, ROLE_ID_RE

__all__ = [
    "REGISTRY_REL",
    "BUDGET_REL",
    "SPINE_FRAME_REL",
    "SCENE_TUNING_REL",
    "AFTER_LAST",
    "SHAPE_IDS",
    "FLAG_KINDS",
    "ALLEGIANCES",
    "FLAG_RE",
    "load_arc_shapes",
    "load_link_count_bounds",
    "validate_arc_shapes",
    "all_defects",
    "shape",
    "links_in_order",
    "load_spine_frame",
    "scene_beats_cap",
    "spine_chain",
    "validate_spine_frame",
]

REGISTRY_REL = "data/seed/narrative/_registry/arc-shapes.v1.json"
BUDGET_REL = "data/seed/narrative/_plan/budget.v1.json"
SPINE_FRAME_REL = "data/seed/narrative/_registry/spine-frame.v1.json"
#: The scene player's own authored-content bound (`gk-core/data/tuning/story-scene-ui.v1.json`,
#: `scene.maxBeatsPerScene`). Read, never copied: a published `v{n+1}` moves the bound for free.
SCENE_TUNING_REL = "data/tuning/story-scene-ui.v1.json"
#: What continues after the final chapter — fixed to arcs and texture (owner ruling R3).
AFTER_LAST = "arcs-and-texture"

#: The four v1 shape ids — a declaration: a new shape is a reviewed change (spec §3).
SHAPE_IDS: "tuple[str, ...]" = ("rescue", "debt", "rival", "lost-piece")
FLAG_KINDS: "tuple[str, ...]" = ("progress", "outcome")
ALLEGIANCES: "tuple[str, ...]" = ("ally", "antagonist", "independent", "none")
#: The shape id, a dot, a name. No digit: the runtime's story ledger stores flags as facts and a text
#: condition may name them.
FLAG_RE = re.compile(r"^[a-z][a-z-]*\.[a-z][a-z-]*$")

_TOP_KEYS = frozenset({"schemaVersion", "registryVersion", "shapes"})
_SHAPE_KEYS = frozenset({"description", "negative", "antagonistRules", "roles", "links"})
_ROLE_KEYS = frozenset({"roleId", "kind", "allegiance", "requires"})
_LINK_KEYS = frozenset({"linkId", "host", "storyletKind", "requiredChoiceKinds", "rolesUsed", "flagsSet",
                        "flagsRead"})
_FLAG_KEYS = frozenset({"flag", "kind"})


def _refuse(message: str) -> "ValueError":
    return ValueError(message)


def _path(rel: str, path: "Path | str | None" = None, owner=None) -> Path:
    """`rel` from `path` when a caller injects one, else from the repository that OWNS it.

    The default owner is `content_root()`, which is the right answer ONLY for `data/seed/**` and
    `data/generated/**` — the pack. The Keepverse split gave `data/tuning/**` and `src/**` to gk-core
    and `docs/**` to the workspace, so a constant naming one of THOSE joined onto the pack names a file
    that is not there: the read raises `FileNotFoundError` three frames below the join that was wrong,
    reading as a missing data file rather than a wrong base.

    `owner` is the ACCESSOR, not a resolved path, so an injected `path` never triggers a root lookup it
    does not need — a planted fixture that has no qualifying ancestor must not die in the resolver.
    """
    if path is not None:
        return Path(path)
    return (content_root() if owner is None else owner()) / rel


def load_arc_shapes(path: "Path | str | None" = None) -> "dict[str, dict]":
    """Load and validate the registry's SHAPE (not its rules — `validate_arc_shapes` owns those).

    Refuses, naming the key: an unknown or missing key; a row that is not an object; a `shapes` block that
    is empty; a non-boolean `antagonistRules`; and a `links`/`roles` block that is not a list.
    """
    registry_path = _path(REGISTRY_REL, path)
    if not registry_path.exists():
        raise _refuse(f"the arc-shape registry does not exist: {registry_path}")
    document = json.loads(registry_path.read_text(encoding="utf-8"))
    label = str(registry_path)
    if not isinstance(document, dict):
        raise _refuse(f"{label}: the registry must be a JSON object")
    unknown = sorted(set(document) - _TOP_KEYS)
    if unknown:
        raise _refuse(f"{label}: unknown key(s) {unknown} — allowed: {sorted(_TOP_KEYS)}")
    missing = sorted(_TOP_KEYS - set(document))
    if missing:
        raise _refuse(f"{label}: missing required key(s) {missing}")
    if document["schemaVersion"] != 1:
        raise _refuse(f"{label}: schemaVersion must be 1")
    shapes = document["shapes"]
    if not isinstance(shapes, dict) or not shapes:
        raise _refuse(f"{label}: shapes must be a non-empty object keyed by shape id")
    for shape_id, row in shapes.items():
        shape_label = f"{label}: shape {shape_id!r}"
        if not isinstance(row, dict):
            raise _refuse(f"{shape_label} must be an object")
        unknown = sorted(set(row) - _SHAPE_KEYS)
        if unknown:
            raise _refuse(f"{shape_label} has unknown key(s) {unknown} — allowed: {sorted(_SHAPE_KEYS)}")
        missing = sorted(_SHAPE_KEYS - set(row))
        if missing:
            raise _refuse(f"{shape_label} is missing required key(s) {missing}")
        if not isinstance(row["antagonistRules"], bool):
            raise _refuse(f"{shape_label}: antagonistRules must be a boolean")
        for key in ("roles", "links"):
            if not isinstance(row[key], list):
                raise _refuse(f"{shape_label}: {key} must be a list")
        for role in row["roles"]:
            if not isinstance(role, dict):
                raise _refuse(f"{shape_label}: every role must be an object")
            unknown = sorted(set(role) - _ROLE_KEYS)
            if unknown:
                raise _refuse(f"{shape_label}: role {role.get('roleId')!r} has unknown key(s) {unknown}")
            missing = sorted(_ROLE_KEYS - set(role))
            if missing:
                raise _refuse(f"{shape_label}: role {role.get('roleId')!r} is missing {missing}")
        for link in row["links"]:
            if not isinstance(link, dict):
                raise _refuse(f"{shape_label}: every link must be an object")
            unknown = sorted(set(link) - _LINK_KEYS)
            if unknown:
                raise _refuse(f"{shape_label}: link {link.get('linkId')!r} has unknown key(s) {unknown}")
            missing = sorted(_LINK_KEYS - set(link))
            if missing:
                raise _refuse(f"{shape_label}: link {link.get('linkId')!r} is missing {missing}")
            for flag_row in link["flagsSet"]:
                if not isinstance(flag_row, dict):
                    raise _refuse(f"{shape_label}: {link.get('linkId')!r} flagsSet rows must be objects")
                unknown = sorted(set(flag_row) - _FLAG_KEYS)
                if unknown:
                    raise _refuse(f"{shape_label}: {link.get('linkId')!r} flag row has unknown key(s) "
                                  f"{unknown}")
                missing = sorted(_FLAG_KEYS - set(flag_row))
                if missing:
                    raise _refuse(f"{shape_label}: {link.get('linkId')!r} flag row is missing {missing}")
    return shapes


def load_link_count_bounds(path: "Path | str | None" = None) -> "tuple[int, int]":
    """`arc.linkCount.{min,max}` from the narrative generation budget. There is deliberately no fallback
    constant: a bound that no file owns is exactly the code-owned tunable this project forbids."""
    budget_path = _path(BUDGET_REL, path)
    document = json.loads(budget_path.read_text(encoding="utf-8"))
    block = (document.get("arc") or {}).get("linkCount")
    if not isinstance(block, dict):
        raise _refuse(f"{budget_path}: missing the arc.linkCount block")
    bounds = []
    for key in ("min", "max"):
        value = block.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise _refuse(f"{budget_path}: arc.linkCount.{key} must be a positive integer, got {value!r}")
        bounds.append(value)
    if bounds[0] > bounds[1]:
        raise _refuse(f"{budget_path}: arc.linkCount.min {bounds[0]} is above max {bounds[1]}")
    return bounds[0], bounds[1]


def _rule_1_link_count_and_ids(shape_id: str, row: Mapping[str, Any], bounds: "tuple[int, int]"
                               ) -> "list[str]":
    """Rule 1 — link count within the budget bounds; link ids unique within the shape and prefixed by it."""
    defects: "list[str]" = []
    links = list(row["links"])
    low, high = bounds
    if not low <= len(links) <= high:
        defects.append(f"shape {shape_id!r}: {len(links)} link(s), outside arc.linkCount {low}..{high}")
    seen: "set[str]" = set()
    for link in links:
        link_id = str(link["linkId"])
        if link_id in seen:
            defects.append(f"shape {shape_id!r}: duplicate link id {link_id!r}")
        seen.add(link_id)
        if not link_id.startswith(f"{shape_id}."):
            defects.append(f"shape {shape_id!r}: link id {link_id!r} is not prefixed by the shape id")
    return defects


def _rule_2_hosts_and_kinds(shape_id: str, row: Mapping[str, Any],
                            host_kinds: Mapping[str, Mapping[str, Any]]) -> "list[str]":
    """Rule 2 — every host is a host kind and every storylet kind is in that host's `admits`."""
    defects: "list[str]" = []
    for link in row["links"]:
        host = host_kinds.get(str(link["host"]))
        if host is None:
            defects.append(f"shape {shape_id!r}: link {link['linkId']!r} names host {link['host']!r}, "
                           f"which is no storylet-vocab host kind")
            continue
        if link["storyletKind"] not in list(host["admits"]):
            defects.append(f"shape {shape_id!r}: link {link['linkId']!r} names storylet kind "
                           f"{link['storyletKind']!r}, which host {link['host']!r} does not admit "
                           f"({list(host['admits'])})")
    return defects


def _rule_3_choice_kinds_allocatable(shape_id: str, row: Mapping[str, Any],
                                     patterns: "Sequence[Mapping[str, Any]]") -> "list[str]":
    """Rule 3 — every `requiredChoiceKinds` set is satisfied by at least one pattern that fits the link's
    kind, so the planner can always allocate one."""
    defects: "list[str]" = []
    for link in row["links"]:
        required = set(str(kind) for kind in link["requiredChoiceKinds"])
        if not required:
            continue
        fitting = [pattern for pattern in patterns
                   if link["storyletKind"] in list(pattern["fitsKinds"])]
        allocatable = any(required <= {str(slot["choiceKind"]) for slot in pattern["slots"]}
                          for pattern in fitting)
        if not allocatable:
            defects.append(f"shape {shape_id!r}: link {link['linkId']!r} requires choice kind(s) "
                           f"{sorted(required)}, which no pattern fitting {link['storyletKind']!r} "
                           f"contains")
    return defects


def _rule_4_flags_read_are_set_earlier(shape_id: str, row: Mapping[str, Any]) -> "list[str]":
    """Rule 4 — flag closure: every flag a link reads is set by an EARLIER link of the same shape. Also
    checks the flag id's shape and its closed `kind`."""
    defects: "list[str]" = []
    set_so_far: "set[str]" = set()
    for link in row["links"]:
        link_id = str(link["linkId"])
        for flag in link["flagsRead"]:
            text = str(flag)
            if not FLAG_RE.match(text):
                defects.append(f"shape {shape_id!r}: link {link_id!r} reads flag {text!r}, outside "
                               f"^[a-z][a-z-]*\\.[a-z][a-z-]*$")
            elif text not in set_so_far:
                defects.append(f"shape {shape_id!r}: link {link_id!r} reads flag {text!r}, which no "
                               f"earlier link of the shape sets")
        for flag_row in link["flagsSet"]:
            text = str(flag_row["flag"])
            if flag_row["kind"] not in FLAG_KINDS:
                defects.append(f"shape {shape_id!r}: link {link_id!r} sets flag {text!r} with kind "
                               f"{flag_row['kind']!r}, outside {list(FLAG_KINDS)}")
            if not FLAG_RE.match(text):
                defects.append(f"shape {shape_id!r}: link {link_id!r} sets flag {text!r}, outside "
                               f"^[a-z][a-z-]*\\.[a-z][a-z-]*$")
            set_so_far.add(text)
    return defects


def _rule_5_roles_close(shape_id: str, row: Mapping[str, Any],
                        role_tags: Mapping[str, Any], role_ids: "set[str]") -> "list[str]":
    """Rule 5 — role closure both ways, the role id's token shape, the closed `kind`/`allegiance`, and
    every `requires` value resolving in `storylet-vocab` or `character-vocab`."""
    defects: "list[str]" = []
    declared = {str(role["roleId"]) for role in row["roles"]}
    used: "set[str]" = set()
    for link in row["links"]:
        for role_id in link["rolesUsed"]:
            used.add(str(role_id))
            if role_id not in declared:
                defects.append(f"shape {shape_id!r}: link {link['linkId']!r} uses role {role_id!r}, "
                               f"which the shape does not declare")
    for role_id in sorted(declared - used):
        defects.append(f"shape {shape_id!r}: declares role {role_id!r}, which no link uses")

    kinds = [str(kind["id"]) for kind in role_tags["roleKinds"]]
    families = role_tags["requireFamilies"]
    for role in row["roles"]:
        role_id = str(role["roleId"])
        if not ROLE_ID_RE.match(role_id):
            defects.append(f"shape {shape_id!r}: role id {role_id!r} is outside ^[a-z][a-z_]*$")
        elif any(role_id.endswith(suffix) for suffix in RESERVED_SUFFIXES):
            defects.append(f"shape {shape_id!r}: role id {role_id!r} ends in a token-grammar reserved "
                           f"suffix, so a token could not parse one way")
        if role["kind"] not in kinds:
            defects.append(f"shape {shape_id!r}: role {role_id!r} kind {role['kind']!r} is outside "
                           f"{kinds}")
        if role["allegiance"] not in ALLEGIANCES:
            defects.append(f"shape {shape_id!r}: role {role_id!r} allegiance {role['allegiance']!r} is "
                           f"outside {list(ALLEGIANCES)}")
        requires = [str(value) for value in role["requires"]]
        defects.extend(f"shape {shape_id!r}: role {role_id!r}: {defect}"
                       for defect in storylet_vocab.requirement_defects(requires))
        for value in requires:
            family, _separator, tail = value.partition(":")
            if family == "characterRole":
                if tail not in role_ids:
                    defects.append(f"shape {shape_id!r}: role {role_id!r} requires {value!r}, and "
                                   f"{tail!r} is no character-vocab role")
            elif family in families and isinstance(families[family], dict):
                allowed = families[family].get("values")
                if isinstance(allowed, list) and tail not in allowed:
                    defects.append(f"shape {shape_id!r}: role {role_id!r} requires {value!r}, and "
                                   f"{tail!r} is outside {allowed}")
    return defects


def _rule_6_r13(shape_id: str, row: Mapping[str, Any]) -> "list[str]":
    """Rule 6 — owner ruling R13, one clause per rule number so a failure names it."""
    defects: "list[str]" = []
    antagonists = [role for role in row["roles"] if role["allegiance"] == "antagonist"]
    if antagonists and not row["antagonistRules"]:
        defects.append(f"shape {shape_id!r}: declares an antagonist role, so antagonistRules must be "
                       f"true (R13)")
    if not row["antagonistRules"]:
        return defects
    if len(antagonists) > 1:
        defects.append(f"shape {shape_id!r} (R13 rule 2, no hierarchy): {len(antagonists)} antagonist "
                       f"roles, at most one is allowed")
    for link in row["links"]:
        for flag_row in link["flagsSet"]:
            if flag_row["kind"] != "progress":
                defects.append(f"shape {shape_id!r} (R13 rule 3, no memory): link {link['linkId']!r} "
                               f"sets an {flag_row['kind']!r} flag — an antagonist shape carries progress "
                               f"flags only")
        if "recruit" in [str(kind) for kind in link["requiredChoiceKinds"]]:
            defects.append(f"shape {shape_id!r} (R13 rule 1, no growth): link {link['linkId']!r} "
                           f"requires a `recruit` choice against its antagonist")
    return defects


def validate_arc_shapes(shapes: Mapping[str, Mapping[str, Any]], *,
                        host_kinds: "Mapping[str, Mapping[str, Any]] | None" = None,
                        patterns: "Sequence[Mapping[str, Any]] | None" = None,
                        role_tags: "Mapping[str, Any] | None" = None,
                        role_ids: "set[str] | None" = None,
                        bounds: "tuple[int, int] | None" = None) -> "list[str]":
    """Rules 1–6 plus the description/negative clause, over `shapes`. Returns defect strings; empty means
    clean. The joins default to the committed registries, so a test overrides only what it crafts."""
    host_kinds = host_kinds if host_kinds is not None else storylet_vocab.load_host_kinds()
    # `load_host_kinds` returns rows; a caller may hand either the list or an id-keyed mapping.
    if not isinstance(host_kinds, Mapping):
        host_kinds = {str(row["id"]): row for row in host_kinds}
    patterns = patterns if patterns is not None else storylet_vocab.load_choice_patterns()
    role_tags = role_tags if role_tags is not None else storylet_vocab.load_role_tags()
    role_ids = (role_ids if role_ids is not None
                else {str(role["id"]) for role in character_vocab.load_roles()})
    bounds = bounds if bounds is not None else load_link_count_bounds()

    defects: "list[str]" = []
    for shape_id, row in shapes.items():
        for key in ("description", "negative"):
            if not str(row.get(key) or "").strip():
                defects.append(f"shape {shape_id!r} has no {key}")
        defects.extend(_rule_1_link_count_and_ids(shape_id, row, bounds))
        defects.extend(_rule_2_hosts_and_kinds(shape_id, row, host_kinds))
        defects.extend(_rule_3_choice_kinds_allocatable(shape_id, row, patterns))
        defects.extend(_rule_4_flags_read_are_set_earlier(shape_id, row))
        defects.extend(_rule_5_roles_close(shape_id, row, role_tags, role_ids))
        defects.extend(_rule_6_r13(shape_id, row))
    return defects


def all_defects() -> "list[str]":
    """Every rule over the COMMITTED files — the reader a report or a test can call."""
    return (validate_arc_shapes(load_arc_shapes())
            + validate_spine_frame(load_spine_frame()))


def shape(shape_id: str, path: "Path | str | None" = None) -> dict:
    """One shape by id. Refuses an unknown id rather than returning None."""
    shapes = load_arc_shapes(path)
    if shape_id not in shapes:
        raise _refuse(f"{REGISTRY_REL}: no shape {shape_id!r} — the v1 ids are {list(SHAPE_IDS)}")
    return shapes[shape_id]


def links_in_order(shape_id: str, path: "Path | str | None" = None) -> "tuple[dict, ...]":
    """A shape's links in play order — the registry's array order is the order, never a sort key."""
    return tuple(shape(shape_id, path)["links"])


# --- the spine frame (spec §5) ----------------------------------------------------------------------

_SPINE_KEYS = frozenset({"schemaVersion", "registryVersion", "afterLast", "fragments", "chapters"})
_CHAPTER_KEYS = frozenset({"chapterId", "pieceId", "after", "description", "negative", "cast",
                           "scenes"})
_SCENE_KEYS = frozenset({"sceneSlot", "beats", "speakers", "teaches"})
_FRAGMENT_KEYS = frozenset({"fragmentId", "afterChapter", "after", "description", "negative"})


def load_spine_frame(path: "Path | str | None" = None) -> dict:
    """Load and validate the frame's SHAPE (not its rules — `validate_spine_frame` owns those)."""
    frame_path = _path(SPINE_FRAME_REL, path)
    if not frame_path.exists():
        raise _refuse(f"the spine frame does not exist: {frame_path}")
    document = json.loads(frame_path.read_text(encoding="utf-8"))
    label = str(frame_path)
    if not isinstance(document, dict):
        raise _refuse(f"{label}: the frame must be a JSON object")
    for keys, label_ in ((_SPINE_KEYS, label),):
        unknown = sorted(set(document) - keys)
        if unknown:
            raise _refuse(f"{label_}: unknown key(s) {unknown} — allowed: {sorted(keys)}")
        missing = sorted(keys - set(document))
        if missing:
            raise _refuse(f"{label_}: missing required key(s) {missing}")
    if document["schemaVersion"] != 1:
        raise _refuse(f"{label}: schemaVersion must be 1")
    for key, allowed in (("chapters", _CHAPTER_KEYS), ("fragments", _FRAGMENT_KEYS)):
        if not isinstance(document[key], list):
            raise _refuse(f"{label}: {key} must be a list")
        for row in document[key]:
            if not isinstance(row, dict):
                raise _refuse(f"{label}: every {key} row must be an object")
            unknown = sorted(set(row) - allowed)
            if unknown:
                raise _refuse(f"{label}: {key} row has unknown key(s) {unknown} — allowed: "
                              f"{sorted(allowed)}")
            missing = sorted(allowed - set(row))
            if missing:
                raise _refuse(f"{label}: {key} row is missing required key(s) {missing}")
    for chapter in document["chapters"]:
        if not isinstance(chapter["cast"], list) or not isinstance(chapter["scenes"], list):
            raise _refuse(f"{label}: chapter {chapter['chapterId']!r} cast and scenes must be lists")
        for scene in chapter["scenes"]:
            if not isinstance(scene, dict):
                raise _refuse(f"{label}: every scene must be an object")
            unknown = sorted(set(scene) - _SCENE_KEYS)
            if unknown:
                raise _refuse(f"{label}: scene has unknown key(s) {unknown}")
            missing = sorted(_SCENE_KEYS - set(scene))
            if missing:
                raise _refuse(f"{label}: scene is missing required key(s) {missing}")
    return document


def scene_beats_cap(path: "Path | str | None" = None) -> int:
    """`scene.maxBeatsPerScene` from the story-scene tuning file — the player's own authored-content
    bound, read rather than copied."""
    tuning_path = _path(SCENE_TUNING_REL, path, core_root)
    document = json.loads(tuning_path.read_text(encoding="utf-8"))
    value = (document.get("scene") or {}).get("maxBeatsPerScene")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _refuse(f"{tuning_path}: scene.maxBeatsPerScene must be a positive integer, got {value!r}")
    return value


def _chain(rows: "Sequence[Mapping[str, Any]]", id_key: str, after_key: str, label: str
           ) -> "tuple[list[str], list[str]]":
    """`(order, defects)` — one root, no cycle, no gap, and every `after` naming a row of the set."""
    defects: "list[str]" = []
    ids = [str(row[id_key]) for row in rows]
    seen_ids: "set[str]" = set()
    for row_id in ids:
        if row_id in seen_ids:
            defects.append(f"{label}: duplicate id {row_id!r}")
        seen_ids.add(row_id)
    by_after: "dict[str, str]" = {}
    for row in rows:
        after = str(row[after_key])
        if after != "none" and after not in seen_ids:
            defects.append(f"{label}: {row[id_key]!r} follows {after!r}, which is no row of the set")
        if after != "none" and after in by_after:
            defects.append(f"{label}: {by_after[after]!r} and {row[id_key]!r} both follow {after!r}")
        by_after[after] = str(row[id_key])
    roots = [str(row[id_key]) for row in rows if str(row[after_key]) == "none"]
    if len(roots) != 1:
        defects.append(f"{label}: {len(roots)} row(s) have after 'none'; exactly one root is required")
    # A cycle anywhere — including one the root cannot reach — is a cycle. Walk each row's parent chain.
    parent = {str(row[id_key]): str(row[after_key]) for row in rows}
    for row_id in parent:
        seen_here: "list[str]" = []
        node = row_id
        while node != "none" and node in parent:
            if node in seen_here:
                defects.append(f"{label}: the after chain revisits {node!r} (a cycle)")
                break
            seen_here.append(node)
            node = parent[node]
    order: "list[str]" = []
    visited: "set[str]" = set()
    current = "none"
    while True:
        following = by_after.get(current)
        if following is None:
            break
        if following in visited:
            defects.append(f"{label}: the after chain revisits {following!r} (a cycle)")
            break
        visited.add(following)
        order.append(following)
        current = following
    for row_id in ids:
        if row_id not in visited:
            defects.append(f"{label}: {row_id!r} is not reachable from the chain root (a gap)")
    return order, defects


def _teaching_defects(order: "Sequence[str]", by_id: "Mapping[str, Mapping[str, Any]]",
                      spine_values: "Mapping[str, int]") -> "list[str]":
    """Owner ruling 2026-09-20: every scene `teaches` a spine-carried value or `none`, no value twice,
    and along the `after` chain the first teaching of each value follows the registry's own order."""
    defects: "list[str]" = []
    first_at: "dict[str, int]" = {}
    position = 0
    for chapter_id in order:
        for scene in by_id[chapter_id]["scenes"]:
            value = str(scene["teaches"])
            if value == "none":
                continue
            if value not in spine_values:
                defects.append(f"chapter {chapter_id!r}: scene teaches {value!r}, which is no "
                               f"teaches.v1.json value carried by the spine")
            elif value in first_at:
                defects.append(f"chapter {chapter_id!r}: value {value!r} is taught by two scenes")
            else:
                first_at[value] = position
            position += 1
    taught = sorted(first_at.items(), key=lambda item: item[1])
    indexes = [spine_values[value] for value, _at in taught if value in spine_values]
    if indexes != sorted(indexes):
        defects.append(f"the after chain teaches out of order: first teachings {[v for v, _ in taught]} "
                       f"follow registry order {indexes}, which is not ascending")
    return defects


def validate_spine_frame(frame: Mapping[str, Any], *, teaches: "Sequence[Mapping[str, Any]] | None" = None,
                         max_beats: "int | None" = None) -> "list[str]":
    """Every §5 rule. Returns defect strings; empty means clean.

    The antagonist-speaks rule (R2) applies from the first scene onward: a chapter row with no scenes
    plans nothing (its scenes are authored structure, filled before the spine pipeline runs), so the
    committed frame's empty rows could never satisfy a speaker rule. A fixture frame with scenes and no
    `lead_antagonist` among the speakers fails.
    """
    teaches = teaches if teaches is not None else storylet_vocab.load_teaches()
    max_beats = max_beats if max_beats is not None else scene_beats_cap()
    spine_values = {str(row["value"]): int(row["teachingOrder"]) for row in teaches
                    if "spine" in [str(carrier) for carrier in row["carriers"]]}

    defects: "list[str]" = []
    if frame["afterLast"] != AFTER_LAST:
        defects.append(f"afterLast is {frame['afterLast']!r}; it is fixed to {AFTER_LAST!r} (R3)")

    order, chain_defects = _chain(frame["chapters"], "chapterId", "after", "the chapter chain")
    defects.extend(chain_defects)
    # A frame may carry no fragments at all; an empty history is not a broken one.
    if frame["fragments"]:
        _fragment_order, fragment_defects = _chain(frame["fragments"], "fragmentId", "after",
                                                   "the fragment history")
        defects.extend(fragment_defects)

    chapter_ids = {str(chapter["chapterId"]) for chapter in frame["chapters"]}
    by_id = {str(chapter["chapterId"]): chapter for chapter in frame["chapters"]}
    piece_ids: "set[str]" = set()
    for chapter in frame["chapters"]:
        chapter_id = str(chapter["chapterId"])
        if str(chapter["pieceId"]) in piece_ids:
            defects.append(f"chapter {chapter_id!r}: piece id {chapter['pieceId']!r} is used twice")
        piece_ids.add(str(chapter["pieceId"]))
        for key in ("description", "negative"):
            if not str(chapter.get(key) or "").strip():
                defects.append(f"chapter {chapter_id!r} has no {key}")
    for fragment in frame["fragments"]:
        fragment_id = str(fragment["fragmentId"])
        if str(fragment["afterChapter"]) not in chapter_ids:
            defects.append(f"fragment {fragment_id!r} follows chapter {fragment['afterChapter']!r}, "
                           f"which is no chapter of the frame")
        for key in ("description", "negative"):
            if not str(fragment.get(key) or "").strip():
                defects.append(f"fragment {fragment_id!r} has no {key}")

    speakers: "set[str]" = set()
    for chapter_id in order:
        chapter = by_id[chapter_id]
        cast = [str(token) for token in chapter["cast"]]
        for scene in chapter["scenes"]:
            beats = scene["beats"]
            if not isinstance(beats, int) or isinstance(beats, bool) or beats < 1:
                defects.append(f"chapter {chapter_id!r}: scene {scene['sceneSlot']!r} has {beats!r} "
                               f"beats; at least one is required")
            elif beats > max_beats:
                defects.append(f"chapter {chapter_id!r}: scene {scene['sceneSlot']!r} has {beats} beats, "
                               f"over scene.maxBeatsPerScene={max_beats}")
            if not scene["speakers"]:
                defects.append(f"chapter {chapter_id!r}: scene {scene['sceneSlot']!r} names no speaker")
            for speaker in scene["speakers"]:
                speakers.add(str(speaker))
                if str(speaker) != "none" and str(speaker) not in cast:
                    defects.append(f"chapter {chapter_id!r}: scene {scene['sceneSlot']!r} speaker "
                                   f"{speaker!r} is not in the chapter's cast")
    if speakers and "lead_antagonist" not in speakers:
        defects.append("the frame has scenes, so the antagonist must speak (R2): lead_antagonist is in "
                       "no scene's speakers")

    defects.extend(_teaching_defects(order, by_id, spine_values))
    return defects


def spine_chain(path: "Path | str | None" = None) -> "tuple[str, ...]":
    """The chapter ids in `after` order — the order the spine runs in, never a numeric index."""
    frame = load_spine_frame(path)
    order, defects = _chain(frame["chapters"], "chapterId", "after", "the chapter chain")
    if defects:
        raise _refuse(f"{SPINE_FRAME_REL}: the chapter chain does not close: {defects[0]}")
    return tuple(order)
