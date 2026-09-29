"""seedsmith.adapters.actions.characteristic_pool.pool — the six closed groups
`characteristic-pool.json` ships (spec §2's inlined table, **not**
`action-corpus-ideal.md` §12 — that table is stale in two places the spec's own §2 documents:
group E's `pairingRole` gains `none` in place of `neutral`, and group B drops `threatBand`
entirely. The spec's inlined table is the only authoritative one).

One entry per group (A-F) — never one per species; `characteristic-pool.json` is the closed
CONTRACT every later brief reads its fields from, not per-species content. Where a group's field
draws from a genuinely closed, already-loaded vocabulary, `closedValues` states it (read fresh
from the same sources `adapters/actions/vocab.py` already loads — never re-typed); where a
field's vocabulary is open, per-round, or owned by a later module (group D's `structureAxes`
union across rungs is closed and included; group F's `antiMotifs`/`avoidNeighbours` are
round-relative and genuinely have nothing closed to list), `closedValues` is simply absent for
that field — an omission, not a placeholder, matching this module's "never invent" rule.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from ..vocab import (
    ACTION_KINDS, AREA_SHAPES, CATEGORIES, PAIRING_ROLES, RELATIONS, SCOPES, TARGET_MODES,
    load_family_ids, load_pairing_keys,
)
from .catalog import RARITY_LADDER

__all__ = ["build_pool_entries", "RUNGS_PATH"]

REPO_ROOT = Path(__file__).resolve().parents[6]
RUNGS_PATH = REPO_ROOT / "data" / "tuning" / "action-rungs.v4.json"

# 6 elements — ActorElementTypes.cs:3-11 (re-verified live, see derive.py's own citation note).
_ELEMENTS: "tuple[str, ...]" = ("fire", "ice", "air", "earth", "light", "dark")


def _load_rung_structure_axes(path: Path) -> "list[str]":
    """The union of every rung row's `structureBudget`, in first-appearance order — read fresh
    from `gk-core/data/tuning/action-rungs.v4.json`, never re-typed (constraint 4: the same set every
    tier, until the three C1 family-access gates land)."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    axes: "list[str]" = []
    for row in doc.get("rows", []):
        for axis in row.get("structureBudget", []):
            if axis not in axes:
                axes.append(axis)
    return axes


def _load_rung_numbers(path: Path) -> "list[int]":
    doc = json.loads(path.read_text(encoding="utf-8"))
    return sorted(row["rung"] for row in doc.get("rows", []))


def build_pool_entries(*, rungs_path: Path = RUNGS_PATH) -> "list[dict]":
    structure_axes = _load_rung_structure_axes(rungs_path)
    rung_numbers = _load_rung_numbers(rungs_path)
    family_ids = sorted(load_family_ids())
    pairing_keys = sorted(load_pairing_keys())

    groups: "list[dict]" = [
        {
            "id": "pool.a-scope-anchor",
            "group": "A", "name": "Scope + anchor",
            "fields": ["scope", "scopeKey"],
            "sourceVocabulary": "spec-eligibility-axis.md §3.1",
            "whoPicks": "planner",
            "closedValues": {"scope": sorted(SCOPES)},
        },
        {
            "id": "pool.b-identity-context",
            "group": "B", "name": "Identity context",
            "fields": ["family", "motifs", "antiMotifs", "element", "themeKey", "rarity"],
            "sourceVocabulary": "catalog + motif-assignments.json + family-assignments.json + "
                                "themes.v1.json; 6 elements ActorElementTypes.cs:3-11; 10 rarity "
                                "rungs CreatureRarity.cs:16-27",
            "whoPicks": "read from the seed",
            "closedValues": {"element": list(_ELEMENTS), "rarity": list(RARITY_LADDER)},
        },
        {
            "id": "pool.c-mechanical-slot",
            "group": "C", "name": "Mechanical slot",
            "fields": ["category", "targetMode", "areaShape", "relation", "kind", "rungBand"],
            "sourceVocabulary": "ActionEnums.cs, ActionTargetSpec.cs, "
                                "data/tuning/action-rungs.v4.json",
            "whoPicks": "planner",
            "closedValues": {
                "category": sorted(CATEGORIES), "targetMode": sorted(TARGET_MODES),
                "areaShape": sorted(AREA_SHAPES), "relation": sorted(RELATIONS),
                "kind": sorted(ACTION_KINDS), "rungBand": rung_numbers,
            },
        },
        {
            "id": "pool.d-pool-constraints",
            "group": "D", "name": "Pool constraints",
            "fields": ["allowedAtomFamilies", "forbiddenAtomFamilies", "structureAxes"],
            "sourceVocabulary": "the 98 authored affix families "
                                "(data/seed/items/affix-families/*.json); RungRow.StructureBudget",
            "whoPicks": "planner",
            "closedValues": {
                # Constraint 4 — the SAME set every tier, until the three C1 gates land. Read
                # fresh, never re-typed (same loader `adapters/actions/vocab.py` already uses).
                "allowedAtomFamilies": family_ids, "structureAxes": structure_axes,
            },
        },
        {
            "id": "pool.e-pairing-role",
            "group": "E", "name": "Pairing role",
            "fields": ["pairingRole", "pairedPayoffFamily"],
            "sourceVocabulary": "data/seed/actions/pairings.json via EnablerPayoffPairings",
            "whoPicks": "planner",
            "closedValues": {"pairingRole": sorted(PAIRING_ROLES), "pairedPayoffFamily": pairing_keys},
        },
        {
            "id": "pool.f-negative-constraints",
            "group": "F", "name": "Negative constraints",
            "fields": ["antiMotifs", "avoidNeighbours"],
            "sourceVocabulary": "derived (spec-dedup-select.md §2's fingerprint; "
                                "spec-distribution-planner.md §3 step 8)",
            "whoPicks": "planner",
            # No `closedValues`: both fields are round-relative — nothing closed to list without
            # inventing content this module has no business authoring.
        },
    ]
    return groups
