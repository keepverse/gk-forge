"""seedsmith.adapters.creatures.family.consolidate — candidate labels -> the family vocabulary
(spec-family-consolidate.md).

Runs over `family-extract`'s COMMITTED output only, never live extraction (§2.0/§7 boundaries) —
the input to this module is a fixed, already-recorded set of candidates, which is what makes
"same inputs -> byte-identical vocabulary, forever" (§2.1) a provable claim rather than a hope.

Merging reads `label` (English) only; `nativeLabel` is carried into the family record for display
and `lore-enrich`, and never participates in grouping (§2.0, resolving audit S7).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

__all__ = [
    "FamilyCandidateInput",
    "ConsolidatedFamilies",
    "normalize",
    "head_noun",
    "canonical_key",
    "consolidate",
    "load_synonyms",
]

SYNONYMS_PATH = Path(__file__).resolve().parent / "synonyms.json"

# §2.1 rule 2 — a documented suffix set. A token here means "this word describes the SHAPE of the
# label, not what the thing IS" — stripping it is what makes `nut-type` reduce to the same head as
# `wall-nut`.
#
# Expanded 2026-08-31 after the FIRST REAL model run exposed the original 5-word set as too narrow.
# `google/gemma-4-26b-a4b-qat`, unprompted, produced labels like `fire-based`, `light-based`,
# `chomper-kin`, `nut-kin`, `pea-kin`, `ice-attackers`, `bucket-users`, `sun-producers` — every one
# a "<theme>-<generic relational noun>" shape the original 5 words did not cover. Left unfixed, this
# produced BOTH failure directions at once on the same 53-candidate batch: semantically IDENTICAL
# groups split apart (`ice-attackers` and `ice-family` became two separate families instead of one),
# and semantically UNRELATED groups incorrectly merged (`fire-based`+`light-based` -> one false
# "based" family; `chomper-kin`+`nut-kin`+`pea-kin` -> one false "kin" family). The false-merge
# direction is the more dangerous of the two — it silently combines things that are not kin, which
# is exactly what audit A6 named this module to prevent.
_GENERIC_SUFFIXES = frozenset({
    "type", "class", "kind", "kins", "kin", "variant", "family", "families", "themed", "theme",
    "based", "users", "user", "attacker", "attackers", "producer", "producers", "vessel", "vessels",
    "shooter", "shooters", "related", "affiliated", "linked", "associated", "group", "style",
})

_PUNCT = re.compile(r"[^a-z0-9]+")


def normalize(label: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace, kebab-case (§2.1 rule 1)."""
    return _PUNCT.sub("-", label.strip().lower()).strip("-")


def head_noun(normalized_label: str) -> str:
    """The last token that is not a generic suffix (§2.1 rule 2) — `wall-nut`, `defensive-nut` and
    `nut-type` all reduce to `nut`. If every token is a generic suffix, the last token is used
    anyway rather than returning an empty head."""
    tokens = [t for t in normalized_label.split("-") if t]
    if not tokens:
        return normalized_label
    for token in reversed(tokens):
        if token not in _GENERIC_SUFFIXES:
            return token
    return tokens[-1]


def load_synonyms(path: Path = SYNONYMS_PATH) -> "dict[str, str]":
    """Read fresh, never transcribed — a human edits this file, the algorithm only reads it."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    return dict(doc.get("aliases") or {})


def canonical_key(label: str, synonyms: Mapping[str, str]) -> str:
    """§2.1 rules 2-3, composed: an exact synonym match wins over head-noun merging (it exists
    precisely for the labels head-noun merging cannot reach), otherwise fall back to the head."""
    norm = normalize(label)
    if norm in synonyms:
        return normalize(synonyms[norm])
    return head_noun(norm)


@dataclass(frozen=True)
class FamilyCandidateInput:
    species_id: str
    label: str
    native_label: str
    basis: str  # "text" | "name" — a `blocked` creature contributes no candidate at all


@dataclass(frozen=True)
class ConsolidatedFamilies:
    # familyId -> {nativeLabels: [...], basis-per-nativeLabel is not tracked here; a family is a
    # merged vocabulary entry, not a per-candidate ledger}
    families: "dict[str, dict]"
    # speciesId -> [familyId], sorted, deduplicated — multi-membership (§2.4)
    assignments: "dict[str, list[str]]"


def consolidate(
    candidates: Sequence[FamilyCandidateInput],
    *,
    synonyms: "Mapping[str, str] | None" = None,
    existing_registry: "Mapping[str, dict] | None" = None,
) -> ConsolidatedFamilies:
    """Mechanical merge: normalize -> head-noun/synonym -> canonical key -> family id.

    `existing_registry` is `families.v1.json`'s own content from a PRIOR run, if any — append-only
    (§2.3): every id already in it keeps its exact identity and position; only a canonical key with
    no prior id gets a new one, appended in order of first appearance across `candidates` sorted by
    `speciesId` (§2.1 rule 4). Passing `None` means "first run ever", not "ignore history".
    """
    syn = dict(synonyms) if synonyms is not None else load_synonyms()
    ordered = sorted(candidates, key=lambda c: c.species_id)

    key_to_id: "dict[str, str]" = {}
    order: "list[str]" = []
    if existing_registry:
        for family_id, record in existing_registry.items():
            key_to_id[record.get("canonicalKey", family_id)] = family_id
            order.append(family_id)

    families: "dict[str, dict]" = (
        {fid: dict(rec) for fid, rec in existing_registry.items()} if existing_registry else {}
    )
    assignments: "dict[str, set[str]]" = {}

    for c in ordered:
        key = canonical_key(c.label, syn)
        family_id = key_to_id.get(key)
        if family_id is None:
            # A canonical key with no matching id in the existing registry is a NEW family — its
            # id IS the canonical key text (§2.1: the head/synonym target, kebab already).
            family_id = key
            key_to_id[key] = family_id
            order.append(family_id)
            families[family_id] = {"canonicalKey": key, "nativeLabels": []}
        native_labels = families[family_id].setdefault("nativeLabels", [])
        if c.native_label not in native_labels:
            native_labels.append(c.native_label)
        assignments.setdefault(c.species_id, set()).add(family_id)

    # Append-only ordering preserved: rebuild `families` in `order`'s sequence so the emitted file
    # never silently reorders an id that was already present.
    ordered_families = {fid: families[fid] for fid in order}
    ordered_assignments = {sid: sorted(fams) for sid, fams in sorted(assignments.items())}

    return ConsolidatedFamilies(families=ordered_families, assignments=ordered_assignments)
