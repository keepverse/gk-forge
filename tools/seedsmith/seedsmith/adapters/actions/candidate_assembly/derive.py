"""seedsmith.adapters.actions.candidate_assembly.derive — the merge this package's own
`__init__.py` describes, plus deterministic id minting. Pure derivation; the sibling entrypoint
`../generate_candidate_assembly.py` owns the one disk read/write, matching every `derive.py` in
this adapter family.

**Two things this module deliberately does NOT do**, both real, considered calls rather than
oversights:

1. **It never widens `kinds.py`'s `ACTION_SEED_REQUIRED`/`ACTION_SEED_OPTIONAL`.** A real draft
   carries `flavor`/`rationale` (A-P1/A-P2/A-P3) and `differentiator` (A-P3 only) -- none of the
   three is a field of the committed `action-seed` schema (`kinds.py` measured directly, 2026-09-04:
   neither set names any of them), and `load.py`'s own loader never reads them either. They did
   their job informing the model's OWN choice of `atomFamilies`/`motifsUsed` and, for `rationale`,
   feeding A-S3's tier-3 semantic-similarity review (`dedup_select.derive.default_similarity` reads
   `rationale` off the SURVIVING candidate row directly -- never off the committed seed) --
   `differentiator` fed A-P3's OWN g2 conformance check (`validate_heal/gates.py`'s
   `atomFamilies`-equals-a-family-action's-set rule) and A-S4's advisory reporting
   (`differentiator_is_none`). Once a candidate is accepted and deduped, nothing downstream reads
   any of the three again -- `name` is the one identity field the committed schema DOES keep
   (`ACTION_SEED_OPTIONAL`), so this module keeps that one and drops the rest. A future spec that
   wants player-facing flavour text on the committed corpus (mirroring `items/kinds.py`'s own
   `flavor`/`flavorKey` split) is a real, separate, reviewed schema change to `kinds.py` -- not
   something to smuggle in here.
2. **It never re-derives `structureAxes` for the committed row.** `brief.slot.structureAxes` is the
   rung-table CEILING BUDGET the candidate was allowed to claim from (`distribution_planner.derive.
   structure_axes_for`) -- not what the candidate actually uses. No real pipeline (A-P1/A-P2/A-P3)
   asks the model which axes it claims (`validate_heal/schemas.py`'s own 2026-09-04 fix), so there
   is no real signal for the committed row's OPTIONAL `structureAxes` field today. Copying the
   ceiling budget in as though it were the candidate's own claim would silently misreport what the
   action actually does -- left absent instead, honestly, the same "we don't have this yet"
   discipline `distribution_planner.derive`'s own module docstring already uses for `slot.kind`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping, Sequence

from ..kinds import KINDS
from ..validate_heal.derive import CandidateVerdict, validate_candidate
from ..validate_heal.gates import BriefContext
from ..vocab import PAIRING_ROLES, SCOPES

__all__ = [
    "SCOPE_RANK", "ANSWER_FIELDS_BY_PIPELINE", "answer_only", "ACTION_SEED_ID_PATTERN",
    "mint_action_id", "build_brief_context", "gate_candidate_row", "assemble_seed_row",
    "AssemblyReject", "AssemblyResult", "anchor_key", "assemble_round",
    "build_envelope", "canonical_dump",
]

# spec-dedup-select.md's own total-ordering rank, reused here rather than reinvented --
# `dedup_select.derive.SCOPE_RANK`'s identical value, kept local so this module stays
# self-contained the same way `general_propose.derive.canonical_family_key` states a reason for
# not importing its own near-duplicate from `validate_heal.derive`.
SCOPE_RANK: "dict[str, int]" = {"general": 0, "family": 1, "species": 2}
assert set(SCOPE_RANK) == SCOPES, "every real scope needs a rank"


# ---------------------------------------------------------------------------------------------
# The answer-only projection A-S4's real schemas (`validate_heal/schemas.py`, fixed 2026-09-04)
# actually gate -- strips the wrapper fields (`candidateId`/`briefId`/`scope`/`_provenance`) each
# pipeline's own `entry_for` adds AFTER the model answers, so gating a real, on-disk candidate
# never trips g1's "extra key" check on its own infrastructure fields.
# ---------------------------------------------------------------------------------------------

ANSWER_FIELDS_BY_PIPELINE: "dict[str, tuple[str, ...]]" = {
    "A-P1": ("name", "flavor", "atomFamilies", "rationale"),
    "A-P2": ("name", "flavor", "atomFamilies", "motifsExpressed", "rationale"),
    "A-P3": ("name", "flavor", "atomFamilies", "motifsExpressed", "differentiator", "rationale"),
}


def answer_only(draft: Mapping[str, object], pipeline_id: str) -> "dict[str, object]":
    """Only the keys THIS pipeline's own real schema actually asks the model for -- a key present
    on `draft` but not in this pipeline's own answer set (e.g. `candidateId`) is silently dropped
    here, never carried into the gate (it is the caller's job, not g1's, to know the envelope)."""
    if pipeline_id not in ANSWER_FIELDS_BY_PIPELINE:
        raise ValueError(f"answer_only: unknown pipeline id {pipeline_id!r}")
    fields = ANSWER_FIELDS_BY_PIPELINE[pipeline_id]
    return {k: draft[k] for k in fields if k in draft}


# ---------------------------------------------------------------------------------------------
# Id minting -- follows `distribution_planner.derive.plan_subject`'s own `briefId` precedent
# (`f"brief.{scope}.{id_key}.{ordinal:03d}"`) but reads the REAL `action-seed` id_pattern straight
# off `kinds.py` (never a second, hand-copied regex) and respects its one real asymmetry: general
# uses a 4-digit ordinal with NO scope-key segment at all; family/species use a 3-digit ordinal
# WITH one (`kinds.py:50`, verified against the live pattern below, not assumed).
# ---------------------------------------------------------------------------------------------

ACTION_SEED_ID_PATTERN = next(k.id_pattern for k in KINDS if k.kind == "action-seed")
assert ACTION_SEED_ID_PATTERN is not None, "action-seed must carry a real id_pattern"


def mint_action_id(scope: str, scope_key: "str | None", ordinal: int) -> str:
    """Pure -- the caller (`assemble_round`) owns deciding what `ordinal` is (subject-local,
    starting at `existing_count + 1`, mirroring `plan_subject`'s own "ordinals are always
    subject-local, starting at 1"). Asserts the result against the REAL regex before returning it
    -- a malformed mint must never reach `dedup_select.derive.parse_candidate` silently."""
    if scope not in SCOPES:
        raise ValueError(f"mint_action_id: scope {scope!r} is not real vocabulary {sorted(SCOPES)}")
    if ordinal < 1:
        raise ValueError(f"mint_action_id: ordinal must be >= 1, got {ordinal}")

    if scope == "general":
        action_id = f"action.general.{ordinal:04d}"
    else:
        if not scope_key or not isinstance(scope_key, str):
            raise ValueError(
                f"mint_action_id: scope {scope!r} needs a real string scope_key, got {scope_key!r}")
        action_id = f"action.{scope}.{scope_key}.{ordinal:03d}"

    if not ACTION_SEED_ID_PATTERN.match(action_id):
        raise ValueError(
            f"mint_action_id: minted id {action_id!r} does not match the real action-seed "
            f"id_pattern {ACTION_SEED_ID_PATTERN.pattern!r} -- refused before it could reach A-S3")
    return action_id


# ---------------------------------------------------------------------------------------------
# A-S4 gating, called against a real brief -- `BriefContext` construction reads only what a real
# A-S1/A-S2 brief already carries (`anchor`/`pool`/`slot`). `forbidden_anchor_tokens` (A-P1's own
# g2 rule) and `family_action_atom_sets` (A-P3's own) have no real source wired yet -- neither is
# invented here; a caller that has them passes them in, everyone else gets the honest empty default
# (g2 already treats an empty tuple as "nothing to check", never a false pass dressed up as a real
# one -- `gates.py`'s own `if ctx.forbidden_anchor_tokens:`/`if ... and ctx.family_action_atom_sets`
# guards).
# ---------------------------------------------------------------------------------------------

def build_brief_context(brief: Mapping[str, object], *, pipeline_id: str,
                        forbidden_anchor_tokens: Sequence[str] = (),
                        family_action_atom_sets: Sequence["frozenset[str]"] = ()) -> BriefContext:
    pool = brief.get("pool") or {}
    anchor = brief.get("anchor") or {}
    scope = brief.get("scope")
    # family-scope anchors carry `familyMotifs`/`familyAntiMotifs`; general/species carry
    # `motifs`/`antiMotifs` directly (`distribution_planner.derive.brief_anchor`'s own three
    # branches) -- read the one this brief's own scope actually populates, never both blindly.
    if scope == "family":
        motifs = frozenset(anchor.get("familyMotifs") or ())
        anti_motifs = frozenset(anchor.get("familyAntiMotifs") or ())
    else:
        motifs = frozenset(anchor.get("motifs") or ())
        anti_motifs = frozenset(anchor.get("antiMotifs") or ())

    return BriefContext(
        brief_id=brief.get("briefId") or brief.get("id") or "",
        pipeline_id=pipeline_id,
        allowed_atom_families=frozenset(pool.get("allowedAtomFamilies") or ()),
        forbidden_atom_families=frozenset(pool.get("forbiddenAtomFamilies") or ()),
        motifs=motifs, anti_motifs=anti_motifs,
        # the brief's own ceiling budget -- g2 checks a CLAIMED axis against this row, never
        # confused with what this module itself carries into the committed seed (module docstring
        # point 2: the committed row never gets a copy of this).
        structure_budget_ceiling=tuple((brief.get("slot") or {}).get("structureAxes") or ()),
        family_action_atom_sets=tuple(family_action_atom_sets),
        forbidden_anchor_tokens=tuple(forbidden_anchor_tokens),
    )


def gate_candidate_row(candidate_row: Mapping[str, object], brief: Mapping[str, object], *,
                       names_already_in_round: Sequence[str] = (),
                       motif_or_role_terms: Sequence[str] = (),
                       forbidden_anchor_tokens: Sequence[str] = (),
                       family_action_atom_sets: Sequence["frozenset[str]"] = ()) -> CandidateVerdict:
    """One accepted round-row, gated against A-S4's real per-pipeline schema
    (`validate_heal.schemas.SCHEMAS_BY_PIPELINE`, resolved internally by `validate_candidate`) --
    zero re-voting (`vote_samples`/`vote_options` are never supplied: this candidate's own vote
    already resolved inside A-P1/A-P2/A-P3 itself, `general_propose.derive.finalize_candidate`'s own
    job, never repeated here)."""
    pipeline_id = candidate_row["pipelineId"]
    draft = candidate_row.get("draft") or {}
    ctx = build_brief_context(brief, pipeline_id=pipeline_id,
                              forbidden_anchor_tokens=forbidden_anchor_tokens,
                              family_action_atom_sets=family_action_atom_sets)
    return validate_candidate(
        candidate_id=candidate_row.get("candidateId") or "",
        brief_id=candidate_row.get("briefId") or "",
        pipeline_id=pipeline_id,
        scope=candidate_row.get("scope"),
        draft=answer_only(draft, pipeline_id),
        ctx=ctx,
        motif_or_role_terms=tuple(motif_or_role_terms),
        names_already_in_round=tuple(names_already_in_round),
    )


# ---------------------------------------------------------------------------------------------
# The merge -- draft's own answer fields + brief's own planner-owned mechanical fields ->
# `kinds.py`'s real `action-seed` shape.
# ---------------------------------------------------------------------------------------------

def assemble_seed_row(candidate_row: Mapping[str, object], brief: Mapping[str, object], *,
                      action_id: str) -> dict:
    """Pure merge, no minting (the caller already decided `action_id`) -- so a test can assert this
    function's own output against a known id without also depending on ordinal bookkeeping."""
    draft = candidate_row.get("draft") or {}
    scope = candidate_row.get("scope") or brief.get("scope")
    if scope not in SCOPES:
        raise ValueError(f"assemble_seed_row: scope {scope!r} is not real vocabulary {sorted(SCOPES)}")

    slot = brief.get("slot")
    if not isinstance(slot, Mapping):
        raise ValueError(f"assemble_seed_row: brief {brief.get('briefId')!r} is missing its 'slot' object")

    pairing = brief.get("pairing") or {}
    pairing_role = pairing.get("role")
    if pairing_role not in PAIRING_ROLES:
        raise ValueError(
            f"assemble_seed_row: brief {brief.get('briefId')!r} pairing.role {pairing_role!r} is "
            f"not real vocabulary {sorted(PAIRING_ROLES)}")

    atom_families = draft.get("atomFamilies")
    if not isinstance(atom_families, list) or not atom_families:
        raise ValueError(
            f"assemble_seed_row: candidate {candidate_row.get('candidateId')!r} draft carries no "
            f"non-empty atomFamilies -- an accepted candidate must always have one")

    row: "dict[str, object]" = {
        "id": action_id,
        "scope": scope,
        # explicit, always present -- `None` for general, a real key for family/species, matching
        # the brief's OWN envelope convention (`distribution_planner.derive.plan_subject`'s own
        # `"scopeKey": scope_key` line, always present regardless of scope).
        "scopeKey": brief.get("scopeKey"),
        "category": slot.get("category"),
        "rungBand": list(slot.get("rungBand") or ()),
        "targetMode": slot.get("targetMode"),
        # explicit key always present -- `dedup_select.derive.parse_candidate`'s own hard
        # requirement: a real shape when targetMode == "area", JSON null otherwise, never omitted.
        "areaShape": slot.get("areaShape"),
        "relation": slot.get("relation"),
        "atomFamilies": list(atom_families),
        "pairingRole": pairing_role,
        "pairedPayoffFamily": pairing.get("pairedPayoffFamily"),
        "name": draft.get("name"),
    }
    motifs = draft.get("motifsExpressed")
    if isinstance(motifs, list):
        row["motifsUsed"] = list(motifs)
    return row


# ---------------------------------------------------------------------------------------------
# Round orchestration -- gate (optional), order, mint, assemble. Deterministic: byte-wise scope
# rank, then briefId, then candidateId -- never dict/filesystem iteration order, matching every
# `order_candidates`/`sorted(..., key=...)` in this adapter family.
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class AssemblyReject:
    candidate_id: str
    brief_id: str
    outcome: str                          # the CandidateVerdict outcome that stopped assembly
    gate_defects: "dict[str, str]"


@dataclass(frozen=True)
class AssemblyResult:
    assembled_rows: "list[dict]"
    verdicts: "dict[str, CandidateVerdict]"   # candidateId -> verdict, gated rows only
    gate_rejects: "list[AssemblyReject]"
    skipped_unaccepted: "list[str]"           # candidateId (or briefId when none) of every round
                                              # row whose OWN outcome was never "accepted" -- never
                                              # assembled, never gated a second time


def anchor_key(scope: "str | None", scope_key: "str | None") -> "tuple[str, str]":
    return (scope or "", scope_key or "")


def assemble_round(candidate_rows: Sequence[Mapping[str, object]],
                   briefs_by_id: Mapping[str, Mapping[str, object]], *,
                   gate: bool = True, existing_counts: "Mapping[tuple[str, str], int] | None" = None,
                   forbidden_anchor_tokens_by_pipeline: "Mapping[str, Sequence[str]] | None" = None,
                   family_action_atom_sets_by_anchor:
                       "Mapping[tuple[str, str], Sequence[frozenset[str]]] | None" = None,
                   ) -> AssemblyResult:
    """One round's own accepted candidates -> assembled `action-seed` rows. `existing_counts`
    seeds the per-anchor ordinal counter from the ALREADY-committed corpus (`(scope, scopeKey) ->
    count`) -- omitted (or empty), every anchor starts at ordinal 1, matching `plan_subject`'s own
    "ordinals are always subject-local, starting at 1" for a fresh corpus.

    Only `outcome == "accepted"` rows are considered (binding constraint from this program's own
    acceptance discipline: `confidence in {"high","split"}` and a real `candidateId` both follow
    from `outcome == "accepted"` by construction -- `general_propose.derive.finalize_candidate`
    only ever sets it alongside a resolved vote and a non-null entry, never independently)."""
    existing_counts = dict(existing_counts or {})
    forbidden_anchor_tokens_by_pipeline = dict(forbidden_anchor_tokens_by_pipeline or {})
    family_action_atom_sets_by_anchor = dict(family_action_atom_sets_by_anchor or {})

    accepted: "list[Mapping[str, object]]" = []
    skipped: "list[str]" = []
    for row in candidate_rows:
        if row.get("outcome") == "accepted" and row.get("candidateId"):
            accepted.append(row)
        else:
            skipped.append(str(row.get("candidateId") or row.get("briefId") or "?"))

    ordered = sorted(accepted, key=lambda r: (
        SCOPE_RANK.get(r.get("scope"), len(SCOPE_RANK)), r.get("briefId") or "", r["candidateId"],
    ))

    verdicts: "dict[str, CandidateVerdict]" = {}
    gate_rejects: "list[AssemblyReject]" = []
    assembled: "list[dict]" = []
    names_by_anchor: "dict[tuple[str, str], list[str]]" = {}

    for row in ordered:
        cid = row["candidateId"]
        brief_id = row.get("briefId")
        brief = briefs_by_id.get(brief_id)
        if brief is None:
            raise ValueError(
                f"{cid}: no brief found for briefId {brief_id!r} -- assembly cannot merge a "
                f"candidate against a brief it does not have")

        scope = row.get("scope") or brief.get("scope")
        scope_key = brief.get("scopeKey")
        anchor = anchor_key(scope, scope_key)

        if gate:
            pipeline_id = row["pipelineId"]
            verdict = gate_candidate_row(
                row, brief, names_already_in_round=tuple(names_by_anchor.get(anchor, ())),
                forbidden_anchor_tokens=forbidden_anchor_tokens_by_pipeline.get(pipeline_id, ()),
                family_action_atom_sets=family_action_atom_sets_by_anchor.get(anchor, ()),
            )
            verdicts[cid] = verdict
            if verdict.outcome != "accepted":
                gate_rejects.append(AssemblyReject(cid, brief_id, verdict.outcome, dict(verdict.gate_defects)))
                continue
            names_by_anchor.setdefault(anchor, []).append(str((verdict.entry or {}).get("name") or ""))

        ordinal = existing_counts.get(anchor, 0) + 1
        existing_counts[anchor] = ordinal
        action_id = mint_action_id(scope, scope_key, ordinal)
        assembled.append(assemble_seed_row(row, brief, action_id=action_id))

    return AssemblyResult(assembled_rows=assembled, verdicts=verdicts, gate_rejects=gate_rejects,
                          skipped_unaccepted=skipped)


# ---------------------------------------------------------------------------------------------
# Envelope assembly + write -- identical discipline to every sibling `derive.py`'s own
# `build_envelope`/`canonical_dump` (sorted keys, fixed indent, trailing `\n`, CJK unescaped).
# ---------------------------------------------------------------------------------------------

def build_envelope(kind: str, entries: "list[dict]", meta: dict) -> dict:
    return {"schemaVersion": 1, "kind": kind, "_meta": meta, "entries": entries}


def canonical_dump(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
