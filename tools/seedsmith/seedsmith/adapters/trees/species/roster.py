"""seedsmith.adapters.trees.species.roster — the species roster reader (task J5,
spec-species-tree.md §2.1, §4).

**The blind spot this must not inherit, stated with the real file that proves it exists today.**
`gk-forge/tools/CreatureQualityReport/Program.cs:77` skips any file beginning with `_`, so it never sees
`data/seed/creatures/species/zombie/_needs-review.json` — which, checked directly against the real
committed corpus while writing this module (2026-09-07), STILL holds a live conflict: `SnorkleZombie`
is indexed at `zombie/undead.json` (the current, corrected copy — `aptitudePrimary: "Onslaught"`) but
`_needs-review.json` ALSO defines a `SnorkleZombie` entry (a stale draft, `confidence.
aptitudePrimary: "unresolved"`), parked, never resolved, invisible to any tool applying the `_` skip.
This is not a hypothetical: `load_roster()` below raises on the real repo state for exactly this
reason, and the raise is correct — the parked entry is a genuine unresolved duplicate, not a false
positive to special-case away.

Two rules from §2.1, both load-bearing:

1. The roster is read from `_index.json` (a flat `{speciesId: relativeFilePath}` map — checked
   directly against the real file: 904 keys today, not the spec's own 2026-09-05 count of 840; the
   count is NEVER hardcoded here, only ever `len(index)`), and every `.json` file under the species
   root is walked WITHOUT the `_`-prefix skip. A species id present on disk but not indexed, indexed
   under a path other than where it is actually defined, or defined in more than one file, HALTS the
   run naming every conflicting path — never "pick the first one."
2. `_index.json` itself is excluded from the walk by NAME (it is the manifest, not a species content
   file), never by the underscore convention — so a future `_index-v2.json` or similar would still be
   walked as content rather than silently assumed to be another manifest.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[6]
SPECIES_ROOT = REPO_ROOT / "data" / "seed" / "creatures" / "species"
INDEX_FILENAME = "_index.json"


class RosterError(ValueError):
    """The species roster is inconsistent — raised before any downstream planning reads it, naming
    every conflicting path rather than silently choosing one (spec-species-tree.md §2.1 rule 1)."""


@dataclass(frozen=True)
class SpeciesAnchor:
    """The five fields §4's decoupling table names as *"what this creature is"* — inputs to the
    favour-lock brief, never the lock itself (§4's own rule, enforced by the planner, not here)."""

    species_id: str
    element_primary: str
    aptitude_primary: str
    posture: str
    traits: "tuple[str, ...]"
    reason: str
    source_path: str


@dataclass(frozen=True)
class Roster:
    #: `_index.json`'s own key order — deterministic (dict insertion order, preserved by `json.loads`)
    #: and never re-sorted here, so a planner seeding off position as well as id stays reproducible.
    species_ids: "tuple[str, ...]"
    anchors: "Mapping[str, SpeciesAnchor]"


def _iter_species_files(root: Path):
    for path in sorted(root.rglob("*.json")):
        if path.parent == root and path.name == INDEX_FILENAME:
            continue
        yield path


def _anchor_from_entry(entry: Mapping, *, source_path: str) -> SpeciesAnchor:
    species_id = entry.get("speciesId")
    if not species_id:
        raise RosterError(f"{source_path}: an anchor entry has no speciesId")
    return SpeciesAnchor(
        species_id=species_id,
        element_primary=str(entry.get("elementPrimary", "")),
        aptitude_primary=str(entry.get("aptitudePrimary", "")),
        posture=str(entry.get("posture", "")),
        traits=tuple(entry.get("traits", ())),
        reason=str(entry.get("reason", "")),
        source_path=source_path,
    )


def load_roster(root: "Path | None" = None) -> Roster:
    """Read `_index.json`, walk every real anchor file without the `_` skip, and cross-check them
    against each other before returning anything — see the module docstring for why this order
    (index first, then a full disk walk, then reconciliation) is what makes rule 1 real rather than
    aspirational."""
    root = root or SPECIES_ROOT
    index_path = root / INDEX_FILENAME
    if not index_path.is_file():
        raise RosterError(f"{index_path} does not exist — the species roster has no index to read")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(index, dict):
        raise RosterError(f"{index_path} must hold a JSON object of speciesId -> relative file path")

    anchors_by_location: "dict[str, dict[str, SpeciesAnchor]]" = {}
    found_at: "dict[str, list[str]]" = {}
    for path in _iter_species_files(root):
        rel = path.relative_to(root).as_posix()
        doc = json.loads(path.read_text(encoding="utf-8"))
        entries = doc if isinstance(doc, list) else [doc]
        by_id: "dict[str, SpeciesAnchor]" = {}
        for entry in entries:
            anchor = _anchor_from_entry(entry, source_path=rel)
            by_id[anchor.species_id] = anchor
            found_at.setdefault(anchor.species_id, []).append(rel)
        anchors_by_location[rel] = by_id

    problems: "list[str]" = []
    for species_id, paths in sorted(found_at.items()):
        indexed_path = index.get(species_id)
        if indexed_path is None:
            problems.append(f"{species_id!r} is on disk at {paths!r} but not in {INDEX_FILENAME!r}")
        elif any(p != indexed_path for p in paths):
            other = sorted(set(paths) - {indexed_path})
            problems.append(
                f"{species_id!r} is indexed at {indexed_path!r} but ALSO defined at {other!r} — "
                f"indexed twice, never picked silently")
    for species_id, indexed_path in sorted(index.items()):
        if not isinstance(indexed_path, str):
            problems.append(f"{species_id!r} in {INDEX_FILENAME!r} does not name a string path")
        elif indexed_path not in anchors_by_location:
            problems.append(
                f"{species_id!r} is indexed at {indexed_path!r} but that file does not exist on disk")
        elif species_id not in anchors_by_location[indexed_path]:
            problems.append(
                f"{species_id!r} is indexed at {indexed_path!r} but that file does not define it")
    if problems:
        raise RosterError(
            f"species roster is inconsistent ({len(problems)} problem(s)): " + "; ".join(problems))

    species_ids = tuple(index.keys())
    anchors = {sid: anchors_by_location[index[sid]][sid] for sid in species_ids}
    return Roster(species_ids=species_ids, anchors=anchors)
