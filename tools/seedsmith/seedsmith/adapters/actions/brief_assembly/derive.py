"""seedsmith.adapters.actions.brief_assembly.derive — spec-brief-assembly.md §3's whole contract.
Pure derivation; the one file that touches disk is the sibling entrypoint
`../generate_brief_assembly.py`, matching every `derive.py` in this adapter family.

**What this module is, stated plainly (spec §1).** A-S1 builds every P1/P2 brief from static
inputs, in a token-free phase, before any model has run. A-P3's brief is different — it carries
`familyActions`, the accepted, deduped, id-assigned output of its own family's A-P2 round, which by
construction cannot exist at the moment A-S1 runs. Nobody owned assembling THAT brief; this module
is the named owner (`spec-signature-propose.md` §6, "⛔ DECIDED 2026-09-03").

**Reuse, never a second implementation (spec §3.2's own instruction).** `fingerprint` is A-S3's own
value, not a fresh one: every accepted action row is parsed through `dedup_select.derive.
parse_candidate` — the SAME validator A-S3 used to decide the row survived — and rendered through
`distribution_planner.fingerprint.render_fingerprint_string`, the one canonical joined-string
renderer every other brief-shaped field in this program already uses (`distribution_planner.
derive.plan_subject`'s own `avoidNeighbours` entries). Reusing `parse_candidate` also closes the
"never assemble from unaccepted output" rule (spec §4) as a side effect: a reject/review row is a
completely different shape (no `category`/`targetMode`/`atomFamilies`), so it fails inside
`parse_candidate` before this module ever considers including it — the mechanism is the SAME
closed-vocabulary parser that gated the row into `gk-data/packs/fusion/data/seed/actions/` in the first place, not a
second, independently-written acceptance check.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping, Sequence

from ..dedup_select.derive import parse_candidate
from ..distribution_planner.fingerprint import render_fingerprint_string

__all__ = [
    "FamilyAction", "parse_accepted_family_action", "index_accepted_family_actions",
    "assemble_brief", "assemble_briefs", "require_family_actions",
    "build_envelope", "canonical_dump",
]


# ---------------------------------------------------------------------------------------------
# One entry of a brief's `familyActions` list — spec §3.2's own JSON shape:
# `{actionId, name, atomFamilies (sorted), fingerprint}`, matching `spec-signature-propose.md`
# §2's inlining rule verbatim: "its family's accepted actions, each as name + sorted atomFamilies
# + fingerprint".
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class FamilyAction:
    action_id: str
    name: str
    atom_families: "tuple[str, ...]"          # sorted, per spec-signature-propose.md §2
    fingerprint: str

    def to_dict(self) -> dict:
        return {"actionId": self.action_id, "name": self.name,
                "atomFamilies": list(self.atom_families), "fingerprint": self.fingerprint}


def parse_accepted_family_action(row: Mapping[str, object],
                                 family_ids: "frozenset[str]") -> "tuple[str, str | None, FamilyAction]":
    """Validates one accepted-round row through A-S3's own candidate parser and renders its
    fingerprint through the ONE canonical joined-string renderer this program has — never a second
    definition of either. Returns `(scope, scopeKey, FamilyAction)`; the caller decides which
    `scope` values matter (only `"family"` ever feeds a brief's `familyActions`, spec §3.1: P3
    differs from its family's shipped siblings, never from a general or another species' own
    signature action).

    A row that is not a real, accepted, vocabulary-valid `action-seed` entry — a reject row
    (`{id, candidateId, tier, reason, collidedWith}`), a review row, or anything missing
    `category`/`targetMode`/`atomFamilies`/etc. — raises HERE, inside `parse_candidate`, before
    this module ever decides whether to include it. `actionId` is `candidate.id` verbatim: this
    module never invents one (spec §4), it only reads what the accepted round already assigned.
    """
    candidate = parse_candidate(row, family_ids)
    fingerprint = render_fingerprint_string(candidate.fp)
    action = FamilyAction(
        action_id=candidate.id, name=candidate.name,
        atom_families=tuple(sorted(candidate.fp.atom_families)), fingerprint=fingerprint,
    )
    return candidate.scope, candidate.scope_key, action


def index_accepted_family_actions(accepted_rows: Sequence[Mapping[str, object]],
                                  family_ids: "frozenset[str]") -> "dict[str, list[FamilyAction]]":
    """Groups the accepted round's FAMILY-scoped actions by family id (`scopeKey`), each family's
    list **sorted ordinally by `actionId`** (spec §3.2: "an unsorted list makes the run
    order-dependent and replay undefinable"). Pure and total: same `accepted_rows` in, same
    grouping and order out, every call — no clock, no random seed, no I/O (§5 test 3, asserted
    across two runs by the caller)."""
    by_family: "dict[str, list[FamilyAction]]" = {}
    for row in accepted_rows:
        scope, scope_key, action = parse_accepted_family_action(row, family_ids)
        if scope != "family":
            continue                          # general- and species-scoped rows never feed familyActions
        if not scope_key:
            raise ValueError(f"accepted family-scoped action {action.action_id!r} carries no "
                             f"scopeKey -- a family action with no family id is a data defect")
        by_family.setdefault(scope_key, []).append(action)
    for actions in by_family.values():
        actions.sort(key=lambda a: a.action_id)
    return by_family


# ---------------------------------------------------------------------------------------------
# One P3 brief -- A-S1's own species-scope entry, byte-identical, plus `familyActions`.
# ---------------------------------------------------------------------------------------------

def assemble_brief(plan_entry: Mapping[str, object],
                   family_actions_by_family: Mapping[str, Sequence[FamilyAction]]) -> dict:
    """Never re-derives anything A-S1 already decided (spec §4) — every key already on
    `plan_entry` (`id`, `briefId`, `scope`, `scopeKey`, `anchor`, `slot`, `pool`, `pairing`,
    `avoidNeighbours`, `_provenance`) is carried through untouched; `familyActions` is the only
    key this module adds. A family-less species (`anchor.family` is `None` or the key is absent)
    gets the key present and EMPTY, never omitted (spec §3.3 — the common case for species without
    family membership)."""
    if plan_entry.get("scope") != "species":
        raise ValueError(
            f"assemble_brief: expected a species-scope (signature) brief, got scope="
            f"{plan_entry.get('scope')!r} (id={plan_entry.get('id')!r}) -- only signature briefs "
            f"carry familyActions (spec-brief-assembly.md §3.2)")
    family = (plan_entry.get("anchor") or {}).get("family")
    actions = family_actions_by_family.get(family, ()) if family else ()
    brief = dict(plan_entry)
    brief["familyActions"] = [a.to_dict() for a in actions]
    return brief


def assemble_briefs(plan_entries: Sequence[Mapping[str, object]],
                    accepted_rows: Sequence[Mapping[str, object]],
                    family_ids: "frozenset[str]") -> "list[dict]":
    """§3 end to end: every species-scope (signature) entry in A-S1's plan gets exactly one P3
    brief, **never skipped** (spec §3.3), walked in the plan's own order (A-S1 already ordered the
    live species catalog once; this module does not re-sort it). `general`/`family`-scope plan
    entries are not signature briefs and are not emitted here — A-P3 has no use for them."""
    by_family = index_accepted_family_actions(accepted_rows, family_ids)
    return [assemble_brief(e, by_family) for e in plan_entries if e.get("scope") == "species"]


# ---------------------------------------------------------------------------------------------
# The absence-vs-empty contract A-P3 raises on (spec §3.2, §5 test 6). A-P3 does not exist yet
# (`spec-signature-propose.md` is DRAFTED, not built) — this is a stand-alone check of the same
# CONTRACT its own consumer will apply, proven here rather than left unexercised until A-P3 ships.
# ---------------------------------------------------------------------------------------------

def require_family_actions(brief: Mapping[str, object]) -> "list[dict]":
    """The absence-vs-empty rule `spec-signature-propose.md` §3 states for its own consumer: a
    brief whose `familyActions` key is **absent** raises; a brief whose `familyActions` is an
    **empty list** is legal. Never collapse the two — collapsing them is exactly how A-P3 could
    silently run early against a brief this module never finished assembling."""
    if "familyActions" not in brief:
        raise ValueError(
            f"brief {brief.get('id', '?')!r} is missing the required 'familyActions' key -- "
            f"a downstream consumer following spec-signature-propose.md §3 raises on absence; "
            f"[] is legal and means 'no family'")
    return brief["familyActions"]


# ---------------------------------------------------------------------------------------------
# Canonical envelope assembly + write -- same discipline every `_canonical_dump` in this adapter
# family already uses: sorted keys, fixed indent, trailing `\n`, CJK unescaped.
# ---------------------------------------------------------------------------------------------

def build_envelope(entries: "list[dict]", meta: dict) -> dict:
    return {"schemaVersion": 1, "kind": "action-brief", "_meta": meta, "entries": entries}


def canonical_dump(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
