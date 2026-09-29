"""Dungeon anchor provenance (D1.11, spec-dungeon-seed-contract.md §6). Every entry's
`_provenance` records `{planHash, briefHash, promptVersions, registryVersions, motifSubsetHash,
attempts, confidence, minorityValues}` — the staleness key is `briefHash + promptVersions +
registryVersions + motifSubsetHash`, NEVER `planHash` alone and never mtime: "a plan that adds a
cell must not stale untouched entries."
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class DungeonProvenance:
    plan_hash: str
    brief_hash: str
    prompt_versions: "Mapping[str, int]" = field(default_factory=dict)
    registry_versions: "Mapping[str, int]" = field(default_factory=dict)
    motif_subset_hash: str = ""
    attempts: "Mapping[str, int]" = field(default_factory=dict)
    confidence: "Mapping[str, str]" = field(default_factory=dict)
    minority_values: "Mapping[str, Any]" = field(default_factory=dict)

    def to_dict(self) -> "dict[str, Any]":
        return {
            "planHash": self.plan_hash,
            "briefHash": self.brief_hash,
            "promptVersions": dict(self.prompt_versions),
            "registryVersions": dict(self.registry_versions),
            "motifSubsetHash": self.motif_subset_hash,
            "attempts": dict(self.attempts),
            "confidence": dict(self.confidence),
            "minorityValues": dict(self.minority_values),
        }


def staleness_key(provenance: Mapping[str, Any]) -> tuple:
    """The four fields that decide staleness — deliberately excluding `planHash`, which is
    recorded for audit but must never itself stale an untouched entry (§6, and why the planner's
    motif-slot allocation is sized to the FULL target up front: a plan that only adds a cell must
    change no existing entry's brief)."""
    return (
        provenance.get("briefHash"),
        tuple(sorted((provenance.get("promptVersions") or {}).items())),
        tuple(sorted((provenance.get("registryVersions") or {}).items())),
        provenance.get("motifSubsetHash"),
    )


def stale_ids(entries: "Sequence[Mapping[str, Any]]", *, id_field: str, current: Mapping[str, Any]) -> "list[str]":
    """An entry is stale when its RECORDED staleness key differs from the CURRENT one — never by
    mtime. An entry with no `_provenance` predates tracking and is reported stale (cannot be
    proven current). `current` is a provenance-shaped dict with the same four keys `staleness_key`
    reads, representing what a fresh run would produce right now."""
    current_key = staleness_key(current)
    out: "list[str]" = []
    for e in entries:
        entry_id = e.get(id_field)
        prov = e.get("_provenance")
        if prov is None:
            out.append(entry_id)
            continue
        if staleness_key(prov) != current_key:
            out.append(entry_id)
    return sorted(v for v in out if v)
