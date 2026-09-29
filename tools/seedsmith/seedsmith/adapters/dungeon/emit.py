"""Canonical dungeon anchor serialisation and emission (D1.11, spec-dungeon-seed-contract.md §6).
**One object per file** — unlike the creatures anchor's per-family list — so `gk-data/packs/fusion/data/seed/dungeon/
<directory>/<id>.json` holds exactly one entry, plus one `_index.json` per directory
(`id -> filename`) for O(1) lookup without a full-tree load.

`write_entry`/`write_corpus` now accept an optional provenance mapping (`seedsmith-content-
standard` Task 12) — the real, precise fix for the wiring gap `spec-content-completeness-
dungeon.md` §2 names: this writer previously had no way to attach `_provenance` at all, which is
WHY no committed dungeon content ever carried the field despite `provenance.py`'s own
`DungeonProvenance`/`stale_ids` existing as real code (that module's own staleness-key SHAPE is
kept as documentation of dungeon's richer audit fields; the staleness KEY itself is computed via
`build_provenance` below, reusing `pipeline/staleness.py`'s shared `staleness_key` — the one thing
`content-completeness-core` says every domain must agree on, not re-derive). Optional and additive:
every existing call (the idempotency test's own real usage) that passes no provenance is byte-for-
byte unaffected.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence


def render_entry(entry: Mapping[str, Any]) -> bytes:
    """Sorted keys, two-space indent, `\\n` line ending, CJK unescaped, explicit nulls — the
    creatures/anchor/emit.py `render_family_file` rules, applied per single object here."""
    text = json.dumps(dict(entry), indent=2, sort_keys=True, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def build_provenance(*, brief_hash: str, prompt_version: str, schema_version: str,
                     model_id: str) -> "dict[str, Any]":
    """Composes the `_provenance` shape this domain stamps going forward. The staleness KEY itself
    is `pipeline.staleness.staleness_key` (`content-completeness-core` Task 2) — imported here
    rather than re-derived, per that module's own boundary ("never invent a domain-specific...
    stale definition inside core itself" applies just as much in reverse: a domain must not
    re-derive core's own key either). `stalenessKey` is the exact field name
    `pipeline.staleness.is_stale` reads (`recorded.get("stalenessKey")`), so a dungeon entry stamped
    here is directly readable by `Content/FieldStale` with no adapter-specific glue."""
    from ...pipeline.staleness import staleness_key as _staleness_key
    key = _staleness_key(brief_hash=brief_hash, prompt_version=prompt_version,
                         schema_version=schema_version, model_id=model_id)
    return {
        "briefHash": brief_hash, "promptVersion": prompt_version,
        "schemaVersion": schema_version, "modelId": model_id, "stalenessKey": key,
    }


def write_entry(directory: Path, entry_id: str, entry: Mapping[str, Any], *,
                provenance: "Mapping[str, Any] | None" = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{entry_id}.json"
    payload = dict(entry)
    if provenance is not None:
        payload["_provenance"] = dict(provenance)
    path.write_bytes(render_entry(payload))
    return path


def render_index(ids: "Sequence[str]") -> bytes:
    index = {entry_id: f"{entry_id}.json" for entry_id in sorted(ids)}
    text = json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def write_index(directory: Path, ids: "Sequence[str]") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "_index.json"
    path.write_bytes(render_index(ids))
    return path


def write_corpus(directory: Path, entries_by_id: "Mapping[str, Mapping[str, Any]]", *,
                 provenance_by_id: "Mapping[str, Mapping[str, Any]] | None" = None) -> "list[Path]":
    """Writes every entry plus the directory's `_index.json`. A second call over unchanged input
    writes byte-identical content (the rerun test hashes every file, not just checks existence).
    `provenance_by_id` is optional and additive (default `None` — every existing call is
    unaffected); a future orchestrator that generates entries via `pipelines.py` passes one entry's
    worth of `build_provenance(...)` output per id here to get `_provenance` stamped for free."""
    provenance_by_id = provenance_by_id or {}
    written = [write_entry(directory, entry_id, entry, provenance=provenance_by_id.get(entry_id))
              for entry_id, entry in entries_by_id.items()]
    written.append(write_index(directory, list(entries_by_id)))
    return written
