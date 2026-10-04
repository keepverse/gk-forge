"""seedsmith.adapters.items.recipegen.migrate_legacy_shards — the fix for the "real, already-tracked"
finding `run.py`'s own module docstring names (2026-09-07): seven pre-existing, hand-authored cost
lines in the real recipes corpus (`recipe.009`/`010`/`011`/`017`/`018`/`025`/`029`) name a legacy,
retired shard band id (`shard.common`/`rare`/`epic`/`legendary`). `MaterialCatalog.IsLegacyShardId`
is `true` for these, so `MaterialRecipeCatalog.Load` refuses all seven at real C# import time
(`MaterialUnissuableRule`) — these recipes can never be paid.

`materialgen.vocab.require_issuable` already refuses a legacy id at GENERATION time, so `recipegen`
itself can never reproduce this defect — but it also can never repair it, since it only mints NEW
recipes (`recipe.031`/`032`), never re-authors the 30 pre-existing hand-authored ones. This module is
the missing other half: detect legacy cost lines in an existing corpus, and rewrite them in place.

Mapping mirrors `LegacyCreatureRarityIds.ForwardMap` (`gk-core/src/FusionRpg.Core/Creatures/CreatureRarity.cs:94-99`)
exactly, verified live against source, never re-derived: each legacy band maps to its LOWEST new-
ladder rung (spec-rarity-migration.md §4 point 4), so no player gains value on migration.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import run as run_mod

#: LegacyCreatureRarityIds.ForwardMap, mirrored exactly — one-way, legacy -> new ladder. Never the
#: reverse; new content is never authored in legacy ids (materialgen.vocab.require_issuable already
#: refuses that at generation time).
LEGACY_SHARD_FORWARD_MAP: "dict[str, str]" = {
    "common": "chaff",
    "rare": "cultivated",
    "epic": "heirloom",
    "legendary": "sunwoven",
}

_AMENDMENT_BATCH = "recipegen/legacy-shard-migration-1"


@dataclass(frozen=True)
class LegacyShardCostLine:
    """One cost line in one recipe entry naming a legacy shard id."""

    entry_id: str
    cost_line_index: int
    legacy_material: str      # e.g. "shard.rare"
    migrated_material: str    # e.g. "shard.cultivated"


def find_legacy_shard_cost_lines(doc: dict) -> "list[LegacyShardCostLine]":
    """Detect. Walks every entry's `costLines`, in file order; empty on an already-migrated (or
    never-affected) corpus."""
    findings: "list[LegacyShardCostLine]" = []
    for entry in doc.get("entries", []):
        entry_id = entry.get("id")
        for i, cost_line in enumerate(entry.get("costLines", [])):
            material = cost_line.get("material")
            if not isinstance(material, str) or not material.startswith("shard."):
                continue
            band = material[len("shard."):]
            new_rung = LEGACY_SHARD_FORWARD_MAP.get(band)
            if new_rung is not None:
                findings.append(LegacyShardCostLine(
                    entry_id=entry_id, cost_line_index=i, legacy_material=material,
                    migrated_material=f"shard.{new_rung}"))
    return findings


def migrate_legacy_shard_ids(doc: dict) -> "tuple[dict, list[LegacyShardCostLine]]":
    """Fix, pure. Returns a NEW doc (entries with no legacy cost line are kept BY IDENTITY, never
    copied) with every legacy shard cost line rewritten to its mapped new-ladder id, plus the list
    of changes made — an empty list means a no-op, safe to call on an already-clean corpus. Never
    mutates `doc` itself."""
    findings = find_legacy_shard_cost_lines(doc)
    if not findings:
        return doc, findings

    by_entry: "dict[str, list[LegacyShardCostLine]]" = {}
    for f in findings:
        by_entry.setdefault(f.entry_id, []).append(f)

    new_entries = []
    for entry in doc.get("entries", []):
        entry_findings = by_entry.get(entry.get("id"))
        if not entry_findings:
            new_entries.append(entry)
            continue
        new_cost_lines = list(entry.get("costLines", []))
        for f in entry_findings:
            new_cost_lines[f.cost_line_index] = {
                **new_cost_lines[f.cost_line_index], "material": f.migrated_material,
            }
        new_entries.append({**entry, "costLines": new_cost_lines})

    return {**doc, "entries": new_entries}, findings


def apply_to_real_corpus(
    path: "Path | None" = None, *, authored_utc: str = "",
) -> "list[LegacyShardCostLine]":
    """Read, migrate, and — only if anything changed — write back, appending one `_meta.amendments`
    entry documenting the fix (this corpus's own established convention, e.g. the real
    `recipegen/trial-1` amendment already there). A clean corpus is left byte-for-byte untouched:
    no amendment is appended and the file is not rewritten at all.
    """
    p = path or run_mod.RECIPES_CORPUS_PATH
    doc: "dict[str, Any]" = json.loads(p.read_text(encoding="utf-8"))
    new_doc, findings = migrate_legacy_shard_ids(doc)
    if not findings:
        return findings

    amendment = {
        "batch": _AMENDMENT_BATCH,
        "note": (
            "Seven pre-existing cost lines named a retired legacy shard band id "
            "(shard.common/rare/epic/legendary), refused at real C# import time "
            "(MaterialCatalog.IsLegacyShardId / MaterialUnissuableRule via MaterialRecipeCatalog.Load "
            "-- these recipes could never be paid). Migrated via "
            "seedsmith.adapters.items.recipegen.migrate_legacy_shards, mirroring "
            "LegacyCreatureRarityIds.ForwardMap exactly (each legacy band maps to its lowest new-ladder "
            "rung, spec-rarity-migration.md sec4 point 4): common->chaff, rare->cultivated, "
            "epic->heirloom, legendary->sunwoven. No live model call -- a mechanical id rewrite, no "
            "prompt involved, same 'hand-authored, no model' precedent recipegen's own trial-1 "
            "amendment used for its hand-authored name/flavor."
        ),
        "promptVersion": "n/a-mechanical-migration",
        "model": _AMENDMENT_BATCH,
        "authoredUtc": authored_utc,
        "sourceRef": "docs/architecture/creature-seed/spec-rarity-migration.md#4",
        "entries": sorted({f.entry_id for f in findings}),
    }
    new_meta = {**new_doc["_meta"],
                "amendments": [*new_doc["_meta"].get("amendments", []), amendment]}
    new_doc = {**new_doc, "_meta": new_meta}

    p.write_text(json.dumps(new_doc, ensure_ascii=False, sort_keys=False, indent=2) + "\n",
                 encoding="utf-8", newline="\n")
    return findings


def main(argv=None) -> int:
    """`python -m seedsmith.adapters.items.recipegen.migrate_legacy_shards [--check]`.

    Default: apply the fix to the real shipped corpus. `--check`: report only, exit 1 if any legacy
    cost line is found, 0 if the corpus is already clean — for CI/pre-flight use.
    """
    import argparse
    import sys
    from datetime import datetime, timezone

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report findings only; do not write; exit 1 if any are found")
    args = parser.parse_args(argv)

    if args.check:
        doc = json.loads(run_mod.RECIPES_CORPUS_PATH.read_text(encoding="utf-8"))
        findings = find_legacy_shard_cost_lines(doc)
        if not findings:
            print("clean — no legacy shard cost lines found")
            return 0
        for f in findings:
            print(f"{f.entry_id}[{f.cost_line_index}]: {f.legacy_material} -> {f.migrated_material}")
        print(f"{len(findings)} legacy cost line(s) found across "
              f"{len({f.entry_id for f in findings})} recipe(s)")
        return 1

    authored_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    findings = apply_to_real_corpus(authored_utc=authored_utc)
    if not findings:
        print("clean — no legacy shard cost lines found, nothing written")
        return 0
    for f in findings:
        print(f"fixed {f.entry_id}[{f.cost_line_index}]: {f.legacy_material} -> {f.migrated_material}")
    print(f"wrote {len({f.entry_id for f in findings})} recipe(s) to {run_mod.RECIPES_CORPUS_PATH}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
