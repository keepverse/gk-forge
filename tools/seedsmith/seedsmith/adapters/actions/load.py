"""seedsmith.adapters.actions.load — the load algorithm (spec-corpus-loader.md §3).

Deterministic, total, and pure: no network, no database, no mutation of anything under
`gk-data/packs/fusion/data/seed/actions/` itself. Built entirely on `Corpus.load` / `Corpus.add` / `Corpus.discover_edges`
(`corpus/model.py`) — this module never reimplements or forks those primitives. The one place it
comes close (`_load_committed_corpus`'s scratch copy, below) is explained at the point it happens,
with the specific reason `Corpus.load`'s own signature cannot express what step 2b/2c need.

"Total" over "raises on the first problem": a lost envelope, an undeclared file, an undeclared
prefix, an unknown enum, a wrong-cased wire string, an unknown atom family, and an unknown family
`scopeKey` are all `Finding`s — collected, never silently dropped, never a reason to stop reading
the rest of the tree. Only what `Corpus.load`/`Corpus.add` already raise on (unparseable JSON, a
real duplicate id) still raises `CorpusLoadError`, matching "the tool could not run" rather than
"the content has a defect" (`corpus/model.py:24-35`).
"""
from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .kinds import ACTION_SEED_REQUIRED, KINDS
from .vocab import (
    AREA_SHAPES, CATEGORIES, ACTION_KINDS, PAIRING_ROLES, RELATIONS, SCOPES, TAGS, TARGET_MODES,
    load_accepted_family_ids, load_family_map_keys, load_pairing_keys,
)
from ...corpus import Corpus, CorpusLoadError, Edge, Entry

MANIFEST_NAME = "_manifest.json"

# `_exemplars/` is Corpus.load's OWN convention (`corpus/model.py:188`), not this program's — it is
# never listed in `_manifest.json` and never flagged as an undeclared prefix (§3 step 2c: "is not
# in this table and is not this module's").
EXEMPLARS_PREFIX = "_exemplars"


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    message: str
    entry_id: "str | None" = None


@dataclass
class LoadResult:
    corpus: Corpus
    edges: "list[Edge]" = field(default_factory=list)
    findings: "list[Finding]" = field(default_factory=list)


# ---------------------------------------------------------------------------------------------
# §3 step 2 / 2c — the manifest: declared config files, and the disposition of every underscore
# prefix (`_rounds/` exclude; `_generated/`, `_briefs/`, `_reports/` load).
# ---------------------------------------------------------------------------------------------

def _read_manifest(actions_root: Path) -> dict:
    path = actions_root / MANIFEST_NAME
    if not path.is_file():
        # No manifest at all means nothing is declared — every config file and every underscore
        # prefix found will report as undeclared, which is the honest (if noisy) reading rather
        # than a hard refusal to run: a missing manifest is a content gap, not a parse failure.
        return {"schemaVersion": 1, "kind": "action-config", "entries": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise CorpusLoadError(Path(MANIFEST_NAME), f"invalid JSON: {e}") from e


def _parse_manifest(manifest: dict) -> "tuple[frozenset[str], dict[str, str]]":
    """Returns (declared config-file repo-relative ids, {prefix -> disposition})."""
    config_files: "set[str]" = set()
    dispositions: "dict[str, str]" = {}
    for row in manifest.get("entries", []):
        if not isinstance(row, dict):
            continue
        row_type = row.get("type")
        if row_type == "config-file" and row.get("id"):
            config_files.add(row["id"])
        elif row_type == "prefix" and row.get("id") and row.get("disposition"):
            dispositions[row["id"]] = row["disposition"]
    return frozenset(config_files), dispositions


# ---------------------------------------------------------------------------------------------
# §3 step 2c — prefix-level classification: a fifth underscore prefix with no manifest row is a
# finding, not a silent load.
# ---------------------------------------------------------------------------------------------

def _classify_prefixes(actions_root: Path, dispositions: "dict[str, str]") -> "list[Finding]":
    findings: "list[Finding]" = []
    for child in sorted(actions_root.iterdir()):
        if not child.is_dir() or not child.name.startswith("_"):
            continue
        if child.name == EXEMPLARS_PREFIX:
            continue
        if (child.name + "/") not in dispositions:
            findings.append(Finding(
                code="undeclared-prefix", path=child.name + "/",
                message=f"{child.name}/: underscore prefix with no disposition row in "
                        f"{MANIFEST_NAME} — undeclared",
            ))
    return findings


# ---------------------------------------------------------------------------------------------
# §3 step 2 — file-level classification: envelope (loaded elsewhere) / declared config (skipped,
# with a reason) / undeclared (a finding). Skips files under an EXCLUDED or UNDECLARED prefix —
# those are already covered by the prefix-level finding (or are legitimately out of this module's
# concern, for `_rounds/`) rather than double-reported file by file.
# ---------------------------------------------------------------------------------------------

def _classify_files(actions_root: Path, config_files: "frozenset[str]",
                    dispositions: "dict[str, str]") -> "list[Finding]":
    findings: "list[Finding]" = []
    for path in sorted(actions_root.rglob("*.json")):
        rel = path.relative_to(actions_root)
        rel_posix = rel.as_posix()
        if rel_posix == MANIFEST_NAME:
            continue

        top = rel.parts[0] if len(rel.parts) > 1 else None
        if top and top.startswith("_") and top != EXEMPLARS_PREFIX:
            if dispositions.get(top + "/") != "load":
                continue  # excluded (`_rounds/`) or undeclared — not this pass's concern

        if rel_posix in config_files:
            continue

        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise CorpusLoadError(rel, f"invalid JSON: {e}") from e

        if isinstance(doc, dict) and doc.get("kind") and isinstance(doc.get("entries"), list):
            continue  # envelope — real corpus content, loaded by `_load_committed_corpus`

        findings.append(Finding(
            code="undeclared", path=rel_posix,
            message=f"{rel_posix}: not an envelope (no kind+entries) and not declared in "
                    f"{MANIFEST_NAME} — undeclared file",
        ))
    return findings


# ---------------------------------------------------------------------------------------------
# §3 steps 1, 2b, 3 — the committed-corpus graph itself, via ONE real `Corpus.load` call over a
# scratch copy of `actions_root` with excluded/undeclared prefixes removed first.
# ---------------------------------------------------------------------------------------------

def _load_committed_corpus(actions_root: Path, dispositions: "dict[str, str]") -> Corpus:
    """Why a copy, not N separate `Corpus.load(child)` calls (one per included subdirectory):

    `Corpus.load`'s exemplar handling keys off `rel.parts[0] == "_exemplars"`, relative to
    whatever root THAT CALL was given (`corpus/model.py:188`). Calling `Corpus.load` once per
    child directory would make `_exemplars/` a call's own root instead of a top-level child of it,
    silently breaking `is_exemplar` for anything inside it.

    Why not one `Corpus.load(actions_root)` call with post-hoc filtering: `Corpus.add`'s
    duplicate-id check (`corpus/model.py:96-101`) fires DURING the walk, the moment the second
    colliding id is added — by the time `Corpus.load` could return control to a caller for
    filtering, a real `_rounds/` vs. committed-corpus collision (§3 step 2b, review F14) has
    already raised. Filtering the result of a call that has already raised cannot work.

    So: copy `actions_root` into a scratch directory first, with `_rounds/` (and any undeclared
    prefix — safer to exclude than to guess) removed, keeping every directory in the SAME relative
    position it holds in the real tree, then make the one real `Corpus.load` call over the copy.
    Read-only with respect to the real tree; the copy is a throwaway `tempfile` directory, removed
    before this function returns.
    """
    with tempfile.TemporaryDirectory(prefix="action-corpus-load-") as tmp:
        tmp_root = Path(tmp)
        for child in sorted(actions_root.iterdir()):
            if child.name == MANIFEST_NAME:
                continue
            if child.is_dir() and child.name.startswith("_") and child.name != EXEMPLARS_PREFIX:
                if dispositions.get(child.name + "/") != "load":
                    continue  # declared exclude, or undeclared — never enters the committed graph
            dest = tmp_root / child.name
            if child.is_dir():
                shutil.copytree(child, dest)
            else:
                shutil.copy2(child, dest)
        return Corpus.load(tmp_root)


# ---------------------------------------------------------------------------------------------
# §3 step 4/5 — per-entry schema + closed-vocabulary validation for `action-seed` entries. Every
# other kind is untouched (owned by its own writer — see `kinds.py`'s module docstring): entries
# stay in the corpus either way (discovery over declaration — an invalid entry is still real
# content, and its id may still be a legitimate edge target from elsewhere), and violations surface
# as `Finding`s rather than excluding the row, matching this module's "total" contract above.
# ---------------------------------------------------------------------------------------------

def _validate_entry(entry: Entry, family_ids: "frozenset[str]", pairing_keys: "frozenset[str]",
                    family_map_keys: "frozenset[str]") -> "list[Finding]":
    if entry.kind != "action-seed":
        return []

    findings: "list[Finding]" = []
    data = entry.data

    def refuse(code: str, field_name: str, value: object) -> None:
        findings.append(Finding(
            code=code, path=entry.path, entry_id=entry.id,
            message=f"{entry.id}: field {field_name!r} refused — unknown value {value!r}",
        ))

    missing = ACTION_SEED_REQUIRED - data.keys()
    for field_name in sorted(missing):
        findings.append(Finding(
            code="missing-required-field", path=entry.path, entry_id=entry.id,
            message=f"{entry.id}: missing required field {field_name!r}",
        ))

    category = data.get("category")
    if category is not None and category not in CATEGORIES:
        refuse("unknown-enum", "category", category)

    for tag in data.get("tags") or []:
        if tag not in TAGS:
            refuse("unknown-enum", "tags", tag)

    kind_hint = data.get("kindHint")
    if kind_hint is not None and kind_hint not in ACTION_KINDS:
        refuse("unknown-enum", "kindHint", kind_hint)

    target_mode = data.get("targetMode")
    if target_mode is not None and target_mode not in TARGET_MODES:
        refuse("unknown-enum", "targetMode", target_mode)

    area_shape = data.get("areaShape")
    if area_shape is not None and area_shape not in AREA_SHAPES:
        refuse("unknown-enum", "areaShape", area_shape)

    relation = data.get("relation")
    if relation is not None and relation not in RELATIONS:
        refuse("unknown-enum", "relation", relation)

    scope = data.get("scope")
    if scope is not None and scope not in SCOPES:
        refuse("unknown-enum", "scope", scope)

    pairing_role = data.get("pairingRole")
    if pairing_role is not None and pairing_role not in PAIRING_ROLES:
        refuse("unknown-enum", "pairingRole", pairing_role)

    for family in data.get("atomFamilies") or []:
        if family not in family_ids:
            refuse("unknown-family", "atomFamilies", family)

    paired = data.get("pairedPayoffFamily")
    if paired is not None and paired not in pairing_keys:
        refuse("unknown-pairing-family", "pairedPayoffFamily", paired)

    if scope == "family":
        scope_key = data.get("scopeKey")
        if scope_key is not None and scope_key not in family_map_keys:
            refuse("unknown-family-scope-key", "scopeKey", scope_key)

    return findings


# ---------------------------------------------------------------------------------------------
# The entry point — §3's six steps (+2b/2c) in order.
# ---------------------------------------------------------------------------------------------

def load_committed(actions_root: Path) -> LoadResult:
    """Load `gk-data/packs/fusion/data/seed/actions/` (or any tree shaped like it) as the committed action corpus.

    Excludes `_rounds/` (§3 step 2b/2c); loads `_generated/`, `_briefs/`, `_reports/` and
    `_exemplars/` into the same graph as the root-level committed content, so a cross-prefix
    reference (a brief naming an `action.*` id, say) resolves as one edge rather than two
    never-connected graphs. Calls `Corpus.discover_edges` once per kind with that kind's OWN
    `id_pattern` (§2's ten-row table) — never one shared pattern for the whole adapter.
    """
    manifest = _read_manifest(actions_root)
    config_files, dispositions = _parse_manifest(manifest)

    findings: "list[Finding]" = []
    findings.extend(_classify_prefixes(actions_root, dispositions))
    findings.extend(_classify_files(actions_root, config_files, dispositions))

    corpus = _load_committed_corpus(actions_root, dispositions)

    family_ids = load_accepted_family_ids()
    pairing_keys = load_pairing_keys()
    family_map_keys = load_family_map_keys()
    for entry in corpus.by_kind("action-seed"):
        findings.extend(_validate_entry(entry, family_ids, pairing_keys, family_map_keys))

    edges: "list[Edge]" = []
    for kind_spec in KINDS:
        if kind_spec.id_pattern is None:
            continue
        edges.extend(corpus.discover_edges(kind_spec.id_pattern, skip_fields=frozenset({"name"})))

    return LoadResult(corpus=corpus, edges=edges, findings=findings)
