"""`anchor-emit` (creature-seed module 8, spec-anchor-emit.md) — writes classified anchors to
`gk-data/packs/fusion/data/seed/creatures/species/**.json` as seed files (item/seed-contract.md's law): the seed is
generator input, never rows a runtime reads.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from .provenance import AnchorProvenance
from .schema import DERIVED_FIELDS

#: DERIVED fields are written as a convenience echo, never authored — marked so a reader is never
#: confused about who owns them (spec §1 consequence 1).
_DERIVED_MARKER_KEY = "_derived"


def entry_for(species_id: str, anchor_fields: Mapping[str, Any], *, provenance: AnchorProvenance) -> "dict[str, Any]":
    """The committed anchor entry: the 21 anchor keys plus `_derived` and `_provenance`. Every
    unresolved voted field is written explicitly as the string `"unresolved"` — never omitted
    (spec's own testing-strategy rule: a missing key must not mean 'unsure')."""
    entry: "dict[str, Any]" = dict(anchor_fields)
    entry[_DERIVED_MARKER_KEY] = sorted(DERIVED_FIELDS)
    entry["_provenance"] = provenance.to_dict()
    return entry


def assert_no_magnitude(entry: Mapping[str, Any]) -> "list[str]":
    """Mechanical check for the seed-contract rule: no field but `gameTypeId` may be a bare
    number. Walks only the top-level anchor keys — `_derived`/`_provenance` are metadata, not
    anchor content, and are excluded on purpose."""
    offenders = []
    for key, value in entry.items():
        if key.startswith("_"):
            continue
        if key == "gameTypeId":
            continue
        if isinstance(value, bool):
            continue  # bool is not a magnitude (e.g. `pure`)
        if isinstance(value, (int, float)):
            offenders.append(key)
    return offenders


def stale_ids(
    entries: Sequence[Mapping[str, Any]],
    *, current_dump_hash: str, current_prompt_versions: Mapping[str, int],
) -> "list[str]":
    """An entry is stale when what it was derived from has changed, compared by RECORDED value —
    never by mtime (same shape as `commander_effect.stale_ids`, built because that generator once
    rewrote all 84 entries stochastically every run). An entry with no `_provenance` at all
    predates tracking and is reported stale — it cannot be proven current."""
    out: "list[str]" = []
    for e in entries:
        species_id = e.get("speciesId")
        prov = e.get("_provenance")
        if prov is None:
            out.append(species_id)
            continue
        if prov.get("dumpHash") != current_dump_hash:
            out.append(species_id)
            continue
        recorded_versions = prov.get("promptVersions") or {}
        if dict(recorded_versions) != dict(current_prompt_versions):
            out.append(species_id)
    return sorted(v for v in out if v)


def stale_fields(entry: Mapping[str, Any], *, current_prompt_versions: Mapping[str, int]) -> "list[str]":
    """Field-level granularity (spec's own `changed_prompt_version_marks_only_that_pipelines_fields`
    rule): only the fields owned by pipelines whose recorded version differs from current."""
    from .prompts import PIPELINES

    prov = entry.get("_provenance") or {}
    recorded = prov.get("promptVersions") or {}
    affected: "list[str]" = []
    for pid, spec in PIPELINES.items():
        if recorded.get(pid) != current_prompt_versions.get(pid):
            affected.extend(spec.attributes)
    return sorted(set(affected))


# --- canonical serialisation, corpus-dump's rules (spec §2) -----------------------------------

def render_family_file(entries: Sequence[Mapping[str, Any]]) -> bytes:
    """Sorted by `speciesId` ordinal, keys sorted (via `sort_keys=True`), two-space indent, `\\n`
    endings, CJK unescaped, explicit nulls (`json.dumps` never omits a `None`-valued key) — the
    same canonical rules `corpus-dump` uses, because these files are hashed too."""
    sorted_entries = sorted(entries, key=lambda e: e.get("speciesId", ""))
    text = json.dumps(sorted_entries, indent=2, sort_keys=True, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def write_family_file(path: Path, entries: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_family_file(entries))


def build_index(entries_by_family_file: Mapping[str, Sequence[Mapping[str, Any]]]) -> "dict[str, str]":
    """`speciesId -> relative file path` — O(1) single-species lookup so `run-control` can resume
    without loading the whole tree (spec §2)."""
    index: "dict[str, str]" = {}
    for rel_path, entries in entries_by_family_file.items():
        for e in entries:
            sid = e.get("speciesId")
            if sid:
                index[sid] = rel_path
    return index


def render_index(index: Mapping[str, str]) -> bytes:
    text = json.dumps(dict(sorted(index.items())), indent=2, sort_keys=True, ensure_ascii=False)
    return (text + "\n").encode("utf-8")
