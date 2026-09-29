"""seedsmith.adapters.creatures.commander_effect — the first real per-creature generator (G4).

A commander effect is a DOCTRINE: how this creature's squad behaves in battle. The per-kind
expression rule comes from `adapter-creatures`' own `KindSpec.motif_expression`, inlined literally
into the brief and never cited (audit A1: five generators handed the same motifs without expression
rules produce a thesaurus, with every check passing).

⛔ **Depends on G1 having landed.** Generating from the pre-filter motifs (`一类` = "armour-class
one", `伤害` from a stat row) would bake stat vocabulary into committed, append-only content. That
is a **Never** in spec-commander-effect.md §7, not a preference.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...workflow.validators import (
    anti_motif_violation,
    field_echo,
    language_consistency,
    motif_coverage,
    non_empty,
    name_collision,
    subject_name_echo,
)
from .kinds import COMMANDER_EFFECT

__all__ = [
    "COMMANDER_EFFECT_SCHEMA", "SYSTEM_PROMPT", "ID_PREFIX",
    "build_brief", "build_context", "load_subjects", "VALIDATORS", "entry_for",
]

#: ⛔ Required, not cosmetic. `Corpus.add` raises on a duplicate id ACROSS ALL KINDS — `entries` is
#: one global dict and only `by_kind` is partitioned. An effect keyed `wallnut` would collide with
#: the creature `wallnut` and fail corpus load outright.
ID_PREFIX = "commander-effect."

#: No numeric field anywhere: `audit_schema` rejects one mechanically, and `channels()` is empty for
#: creatures so there is no numeric path to misuse (audit A4).
COMMANDER_EFFECT_SCHEMA: "dict[str, Any]" = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "doctrine": {"type": "string"},
    },
    "required": ["name", "doctrine"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You design commander effects for creatures in a Plants-vs-Zombies-derived RPG. "
    "A commander effect is a DOCTRINE: how this creature's squad behaves in battle. "
    "Return the value only — never repeat a field name as a label inside its own value. "
    "Write the doctrine in the SAME LANGUAGE as the motifs you are given - if they are "
    "Chinese, the whole doctrine must be Chinese, never English prose with Chinese words "
    "spliced in. "
    "Give the effect its OWN distinct name - never simply repeat the creature's name. "
    "Never invent lore the provided motifs do not support."
)

VALIDATORS = (motif_coverage, anti_motif_violation, field_echo, non_empty,
              language_consistency, subject_name_echo,
              name_collision)


def build_context(subject: "Mapping[str, Any]") -> "dict[str, Any]":
    """Read-only inputs a node needs. `requiredFields` drives `non_empty`."""
    return {
        "motifs": list(subject.get("motifs") or []),
        "antiMotifs": list(subject.get("antiMotifs") or []),
        "requiredFields": ["name", "doctrine"],
        "expressionRule": COMMANDER_EFFECT.motif_expression,
        "displayName": subject.get("displayName") or subject.get("speciesId", ""),
        "speciesId": subject.get("speciesId", ""),
    }


def build_brief(context: "Mapping[str, Any]") -> str:
    """Inlines motifs, anti-motifs and the expression rule LITERALLY. Cites nothing — a brief that
    says \"motifs come from motifs.v1.json\" invites invention (51 invented tags, historically)."""
    lines = [
        f"Creature: {context['displayName']} ({context['speciesId']})",
        f"How a motif is expressed for this kind: {context['expressionRule']}",
        "",
        "Motifs (use at least one, verbatim): " + ", ".join(context["motifs"]),
    ]
    anti = context.get("antiMotifs") or []
    if anti:
        lines.append("Anti-motifs (these words must NOT appear): " + ", ".join(anti))
    lines += ["", "Design ONE commander effect - a doctrine for how this creature's squad behaves."]
    return "\n".join(lines)


def entry_for(species_id: str, draft: "Mapping[str, Any]", *, basis: str,
              provenance: "Mapping[str, Any] | None" = None,
              motifs: "Sequence[str] | None" = None) -> "dict[str, Any]":
    """The committed corpus entry. `creatureId` is the declared `reference_field`, so
    `planner.ordering` derives generation order structurally.

    `_provenance.motifs` records the exact motifs this entry was generated FROM. Without it,
    "is this entry stale?" is unanswerable and the only options are regenerate-everything (which
    discards good stochastic output) or nothing. This is the same lesson `themes.v1.json` taught on
    2026-09-01: an artifact derived from another must record enough to detect drift."""
    entry = {
        "id": f"{ID_PREFIX}{species_id}",
        "nameKey": f"commanderEffect.{species_id}",
        "name": draft["name"],
        "creatureId": species_id,
        "doctrine": draft["doctrine"],
        "basis": basis,
    }
    if provenance or motifs is not None:
        prov = dict(provenance or {})
        if motifs is not None:
            prov["motifs"] = list(motifs)
        entry["_provenance"] = prov
    return entry


def stale_ids(entries: "Sequence[Mapping[str, Any]]",
              subjects: "Sequence[Mapping[str, Any]]") -> "list[str]":
    """Creatures whose committed effect was generated from motifs that have since changed.

    An entry with no recorded motifs predates provenance tracking and is reported stale — it cannot
    be proven current, and silently assuming it is current is how the theme registry rotted."""
    current = {s["speciesId"]: list(s["motifs"]) for s in subjects}
    out: "list[str]" = []
    for e in entries:
        sid = e.get("creatureId")
        if sid not in current:
            continue
        recorded = (e.get("_provenance") or {}).get("motifs")
        if recorded is None or list(recorded) != current[sid]:
            out.append(sid)
    return sorted(out)


def load_subjects(creatures_root: Path) -> "list[dict[str, Any]]":
    """One subject per creature that HAS motifs. A creature whose motifs are blocked produces nothing —
    an answer, not a failure (spec-commander-effect.md §2.6)."""
    gen = creatures_root / "_generated"
    motifs = json.loads((gen / "motif-assignments.json").read_text(encoding="utf-8"))
    names: "dict[str, str]" = {}
    for path in sorted((creatures_root / "creature").rglob("*.json")):
        for row in json.loads(path.read_text(encoding="utf-8")).get("entries", []):
            names[row["id"]] = row.get("name") or row["id"]

    subjects: "list[dict[str, Any]]" = []
    for sid in sorted(motifs):
        rec = motifs[sid]
        if rec.get("basis") == "blocked" or not rec.get("motifs"):
            continue
        subjects.append({
            "speciesId": sid,
            "displayName": names.get(sid, sid),
            "motifs": rec.get("motifs") or [],
            "antiMotifs": rec.get("antiMotifs") or [],
            "basis": rec.get("basis", "text"),
        })
    return subjects
