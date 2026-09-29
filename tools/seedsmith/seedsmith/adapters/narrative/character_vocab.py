"""The character vocabulary registries and their readers (spec-character-vocab.md §3-§6, NS23).

Four closed lists a character seed is built from — roles, voices, line contexts and the required
(context, band) pairs — plus the rules that make them a vocabulary:

- **Roles are the runtime's own nine**, pinned with the reason that a change is reviewed in both programs;
  `warlord` is the one antagonist role (R13 rule 1: an antagonist never grows from meeting the player).
- **Bands come from the disposition file** (`gk-data/packs/fusion/data/seed/dungeon/_registry/disposition.v1.json`) — there is
  no second ladder.
- **R13 rule 3**: an antagonist's pairs are relation and world-fact only, so no personal-history context
  (`thanks`, `refused`, `spared`, `betrayed`, `joins`) may appear on one; `joins` is never an antagonist
  pair.
- **The three lead tokens are a declaration** (R11): `lead_summoner`, `lead_companion`, `lead_antagonist`.

Every value carries its own `description` and `negative`, and every list carries `none` where a model
chooses from it (a character must have a role, a voice and a context, so `none` is a refusal, never a
silent default).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...workspace_roots import content_root

__all__ = [
    "REGISTRY_DIR", "ROLE_IDS", "VOICE_IDS", "CONTEXT_IDS", "CONTEXT_BUCKETS", "DISPOSITION_REL",
    "LEAD_TOKENS", "PERSONAL_HISTORY_CONTEXTS", "load_roles", "load_voices", "load_line_contexts",
    "load_line_pairs", "disposition_bands", "required_pairs", "validate_roles", "validate_voices",
    "validate_line_contexts", "validate_line_pairs", "all_defects",
    "VOICE_REGISTERS", "VOICES_DIR_REL", "BUDGET_REL", "exemplar_line_bounds", "load_voice_exemplar",
    "validate_voice_exemplars", "avoid_terms",
]

REGISTRY_DIR = "data/seed/narrative/_registry"
ROLES_REL = f"{REGISTRY_DIR}/roles.v1.json"
VOICES_REL = f"{REGISTRY_DIR}/voices.v1.json"
LINE_CONTEXTS_REL = f"{REGISTRY_DIR}/line-contexts.v1.json"
LINE_PAIRS_REL = f"{REGISTRY_DIR}/line-pairs.v1.json"
DISPOSITION_REL = "data/seed/dungeon/_registry/disposition.v1.json"

#: The runtime's closed role list (`npc-story-events-ideal.md` §6.3) plus the model-facing `none`.
ROLE_IDS: "tuple[str, ...]" = ("wanderer", "trader", "hermit", "chronicler", "clan-elder", "warlord",
                               "captive", "envoy", "companion", "none")
VOICE_IDS: "tuple[str, ...]" = ("formal", "blunt", "playful", "grim", "sly", "gentle", "none")
CONTEXT_IDS: "tuple[str, ...]" = ("greet", "farewell", "thanks", "refused", "spared", "betrayed", "joins",
                                  "taunt", "rumor", "doctrine", "return-won", "return-wiped",
                                  "return-lost", "return-quiet", "none")
CONTEXT_BUCKETS: "tuple[str, ...]" = ("relation", "personal-history", "world-fact", "outing", "none")
#: R13 rule 3's forbidden set: a personal-history line is knowledge of a past the antagonist never had.
PERSONAL_HISTORY_CONTEXTS: "tuple[str, ...]" = ("thanks", "refused", "spared", "betrayed", "joins")
#: R11: the three lead tokens, a declaration.
LEAD_TOKENS: "tuple[str, ...]" = ("lead_summoner", "lead_companion", "lead_antagonist")
ALLEGIANCES: "tuple[str, ...]" = ("independent", "ally", "antagonist", "player", "none")

_ROLE_KEYS = frozenset({"id", "allegiance", "description", "negative"})
_VOICE_KEYS = frozenset({"id", "description", "negative"})
_CONTEXT_KEYS = frozenset({"id", "bucket", "description", "negative"})
_PAIR_KEYS = frozenset({"id", "pairs", "description", "negative"})


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
        unknown = sorted(set(row) - allowed)
        if unknown:
            raise ValueError(f"{rel}: row {row.get('id')!r} has unknown key(s) {unknown} — allowed: "
                             f"{sorted(allowed)}")
        missing = sorted(allowed - set(row))
        if missing:
            raise ValueError(f"{rel}: row {row.get('id')!r} is missing required key(s) {missing}")
    return rows


def load_roles(path: "Path | str | None" = None) -> "list[dict]":
    return _read(ROLES_REL, "roles", _ROLE_KEYS, path)


def load_voices(path: "Path | str | None" = None) -> "list[dict]":
    return _read(VOICES_REL, "voices", _VOICE_KEYS, path)


def load_line_contexts(path: "Path | str | None" = None) -> "list[dict]":
    return _read(LINE_CONTEXTS_REL, "lineContexts", _CONTEXT_KEYS, path)


def load_line_pairs(path: "Path | str | None" = None) -> dict:
    document = json.loads(_path(LINE_PAIRS_REL, path).read_text(encoding="utf-8"))
    for key in ("bandsFrom", "leads", "linePairs"):
        if key not in document:
            raise ValueError(f"{LINE_PAIRS_REL}: missing {key!r}")
    for row in document["linePairs"]:
        unknown = sorted(set(row) - _PAIR_KEYS)
        if unknown:
            raise ValueError(f"{LINE_PAIRS_REL}: row {row.get('id')!r} has unknown key(s) {unknown}")
    return document


def disposition_bands(path: "Path | str | None" = None) -> "tuple[str, ...]":
    document = json.loads(_path(DISPOSITION_REL, path).read_text(encoding="utf-8"))
    bands = document.get("disposition")
    if isinstance(bands, dict) and bands:          # a mapping of band -> its own facts
        return tuple(str(name) for name in bands)
    if isinstance(bands, list) and bands:          # a plain ordered member list (today's shape)
        return tuple(str(name) for name in bands)
    raise ValueError(f"{DISPOSITION_REL}: `disposition` must be a non-empty list or object")


def required_pairs(document: "Mapping[str, Any]", allegiance: str) -> "frozenset[tuple[str, str]]":
    """The required `(context, band)` set for one allegiance — a PURE function of the document and the
    allegiance: the same input always yields the same set (order comes from the file, never a set walk)."""
    for row in document["linePairs"]:
        if str(row["id"]) == allegiance:
            return frozenset((str(pair["context"]), str(band))
                             for pair in row["pairs"] for band in pair["bands"])
    raise ValueError(f"{allegiance!r} is no allegiance row of {LINE_PAIRS_REL}")


def _prose(rows: "Sequence[Mapping[str, Any]]", label: str) -> "list[str]":
    defects = []
    for row in rows:
        for key in ("description", "negative"):
            if not str(row.get(key) or "").strip():
                defects.append(f"{label} {row.get('id')!r} has no {key}")
    return defects


def validate_roles(rows: "Sequence[Mapping[str, Any]]") -> "list[str]":
    defects = _prose(rows, "role")
    ids = [str(row["id"]) for row in rows]
    if ids != list(ROLE_IDS):
        defects.append(f"roles must be the runtime's nine plus `none`, in this order: {list(ROLE_IDS)}; "
                       f"got {ids}")
    for row in rows:
        if str(row["allegiance"]) not in ALLEGIANCES:
            defects.append(f"role {row['id']!r}: allegiance {row['allegiance']!r} is outside "
                           f"{list(ALLEGIANCES)}")
    antagonists = [row["id"] for row in rows if row["allegiance"] == "antagonist"]
    if antagonists != ["warlord"]:
        defects.append(f"`warlord` is the one antagonist role (R13 rule 1), found {antagonists}")
    return defects


def validate_voices(rows: "Sequence[Mapping[str, Any]]") -> "list[str]":
    defects = _prose(rows, "voice")
    if [str(row["id"]) for row in rows] != list(VOICE_IDS):
        defects.append(f"voices must be {list(VOICE_IDS)}, got {[row['id'] for row in rows]}")
    return defects


def validate_line_contexts(rows: "Sequence[Mapping[str, Any]]") -> "list[str]":
    defects = _prose(rows, "line context")
    if [str(row["id"]) for row in rows] != list(CONTEXT_IDS):
        defects.append(f"line contexts must be {list(CONTEXT_IDS)}, got {[row['id'] for row in rows]}")
    for row in rows:
        if str(row["bucket"]) not in CONTEXT_BUCKETS:
            defects.append(f"line context {row['id']!r}: bucket {row['bucket']!r} is outside "
                           f"{list(CONTEXT_BUCKETS)}")
        if row["bucket"] == "personal-history" and str(row["id"]) not in PERSONAL_HISTORY_CONTEXTS:
            defects.append(f"line context {row['id']!r} is personal-history but not in R13 rule 3's set")
    return defects


def validate_line_pairs(document: "Mapping[str, Any]", contexts: "Sequence[Mapping[str, Any]]",
                        bands: "Sequence[str]") -> "list[str]":
    defects = _prose(document["linePairs"], "line pair")
    known = {str(row["id"]) for row in contexts if str(row["id"]) != "none"}
    if list(document["leads"]) != list(LEAD_TOKENS):
        defects.append(f"the leads block must be exactly {list(LEAD_TOKENS)} (R11), got {document['leads']}")
    for row in document["linePairs"]:
        allegiance = str(row["id"])
        if allegiance not in ALLEGIANCES:
            defects.append(f"line pair row {allegiance!r}: allegiance is outside {list(ALLEGIANCES)}")
        for pair in row["pairs"]:
            context = str(pair["context"])
            if context not in known:
                defects.append(f"{allegiance}: context {context!r} is no known line context")
            for band in pair["bands"]:
                if str(band) not in bands:
                    defects.append(f"{allegiance}: band {band!r} is not a disposition band {list(bands)}")
            if allegiance == "antagonist":
                if context in PERSONAL_HISTORY_CONTEXTS:
                    defects.append(f"antagonist pair {context!r} is personal history — R13 rule 3 forbids it")
                if context == "joins":
                    defects.append("`joins` is never an antagonist pair (R13)")
        if allegiance == "player" and row["pairs"]:
            defects.append("the player row carries no pairs: the summoner speaks only in spine scenes")
    return defects


def all_defects() -> "list[str]":
    """Every rule over the COMMITTED files — the reader a report or a test can call."""
    return (validate_roles(load_roles())
            + validate_voices(load_voices())
            + validate_line_contexts(load_line_contexts())
            + validate_line_pairs(load_line_pairs(), load_line_contexts(), disposition_bands())
            + validate_voice_exemplars())   # NS24: the authored exemplars themselves


# ---------------------------------------------------------------------------------------------
# NS24 — voice exemplars (spec-character-vocab.md §4)
# ---------------------------------------------------------------------------------------------

#: The six registers that carry an exemplar file (`none` is a refusal, not a register).
VOICE_REGISTERS: "tuple[str, ...]" = ("formal", "blunt", "playful", "grim", "sly", "gentle")
VOICES_DIR_REL = "data/seed/narrative/_exemplars/voices"
BUDGET_REL = "data/seed/narrative/_plan/budget.v1.json"

_AVOID_HELPER = "load_avoid_terms"


def exemplar_line_bounds(path: "Path | str | None" = None) -> "tuple[int, int]":
    """The `character.exemplarLines` bounds from the narrative budget — a bound no code owns."""
    document = json.loads(_path(BUDGET_REL, path).read_text(encoding="utf-8"))
    block = (document.get("character") or {}).get("exemplarLines")
    if not isinstance(block, dict) or "min" not in block or "max" not in block:
        raise ValueError(f"{BUDGET_REL}: missing the character.exemplarLines block with min and max")
    return int(block["min"]), int(block["max"])


def load_voice_exemplar(register: str, path: "Path | str | None" = None) -> dict:
    """One register's authored exemplar file, read fresh and checked for unknown keys."""
    rel = f"{VOICES_DIR_REL}/{register}.en.json"
    document = json.loads(_path(rel, path).read_text(encoding="utf-8"))
    unknown = sorted(set(document) - {"schemaVersion", "locale", "register", "lines", "lexicon", "note"})
    if unknown:
        raise ValueError(f"{rel}: unknown key(s) {unknown}")
    if document.get("register") != register:
        raise ValueError(f"{rel}: register {document.get('register')!r} is not {register!r}")
    return document


def validate_voice_exemplars(registers: "Sequence[str]" = VOICE_REGISTERS,
                             bounds: "tuple[int, int] | None" = None) -> "list[str]":
    """Every register has an exemplar that loads, within the budget's line bounds, in Latin script,
    digit-free and brace-free (a brace would mean an unfilled template reached the file)."""
    from ...workflow.validators.scripts import ScriptClass, script_of

    low, high = bounds if bounds is not None else exemplar_line_bounds()
    allowed = {ScriptClass.LATIN, ScriptClass.COMMON}
    defects: "list[str]" = []
    for register in registers:
        try:
            document = load_voice_exemplar(register)
        except (OSError, ValueError) as exc:
            defects.append(f"voice exemplar {register!r} does not load: {exc}")
            continue
        lines = document.get("lines")
        if not isinstance(lines, list) or not lines:
            defects.append(f"voice exemplar {register!r} carries no lines")
            continue
        if not low <= len(lines) <= high:
            defects.append(f"voice exemplar {register!r}: {len(lines)} lines, outside the budget's "
                           f"{low}-{high}")
        lexicon = document.get("lexicon") or {}
        for key in ("signature", "forbidden"):
            if not list(lexicon.get(key) or []):
                defects.append(f"voice exemplar {register!r}: lexicon.{key} is empty")
        for line in lines:
            text = str(line)
            if any(ch.isdigit() for ch in text):
                defects.append(f"voice exemplar {register!r}: a line carries a digit: {text!r}")
            if "{" in text or "}" in text:
                defects.append(f"voice exemplar {register!r}: a line carries a brace: {text!r}")
            outsiders = sorted({ch for ch in text if script_of(ch) not in allowed})
            if outsiders:
                defects.append(f"voice exemplar {register!r}: a line leaves Latin script: {outsiders}")
    return defects


def avoid_terms() -> "tuple[str, ...]":
    """`ip-censor`'s shared avoid-list, when the helper and its registry are present. Absent means an
    empty tuple — IC-3: the scan is a release gate, and this module never keeps a private IP list."""
    try:
        from ....ip_censor import avoid_list  # type: ignore[attr-defined]
        terms = getattr(avoid_list, _AVOID_HELPER, None)
        if terms is None:
            return ()
        return tuple(terms() or ())
    except Exception:                      # noqa: BLE001 — an absent helper is the documented case
        return ()
