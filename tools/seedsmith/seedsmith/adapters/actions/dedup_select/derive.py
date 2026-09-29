"""seedsmith.adapters.actions.dedup_select.derive — spec-dedup-select.md §3's six steps. Pure
derivation; the one file that touches disk is the sibling entrypoint
`../generate_dedup_select.py`, matching every `derive.py` in this adapter family.

**Real input gap, same shape every prior module in this session has documented rather than
papered over.** This module's real input -- A-S4's accepted candidate set -- does not exist yet
(A-S4, `validate-heal`, is a later, unbuilt module; map's own build-order note lists A-S3 as
buildable before A-S5 despite the data-flow dependency). Everything below is proven against
synthetic, in-memory candidate-set fixtures (`tests/test_dedup_select.py`), the same discipline
A-S1 used against A-S3's own not-yet-existing `action-dedup.v1.json` and A-G1 used against A-S5's
not-yet-existing quality gate.

**A genuine shape gap this module had to close, flagged rather than hidden.** Spec §3 step 1's
total-ordering key is `(scopeRank, scopeKey ordinal, briefId ordinal, candidateId ordinal)`, but
`briefId` is not a field of the shipped `action-seed` KindSpec (`kinds.py`'s `ACTION_SEED_REQUIRED`
/ `ACTION_SEED_OPTIONAL` -- neither lists it), and no A-S4 spec exists to say whether a candidate
carries one. `parse_candidate` below reads `briefId` if present (`row.get("briefId")`) and falls
back to `""` if absent, so the ordering key is always well-formed and total either way -- a
candidate's own `id` already breaks every remaining tie uniquely (the id is the entry's identity,
so no two candidates can share one). Similarly, tier 3's `name`/`rationale` fields are read the
same permissive way (`row.get(...) or ""`): `rationale` is not in `ACTION_SEED_OPTIONAL` either,
but nothing in `kinds.py`'s loader forbids EXTRA fields on an envelope row, and spec §1 names
`rationale` explicitly as one of tier 3's two inputs.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from ..characteristic_pool.derive import CATEGORIES
from ..distribution_planner.derive import validate_atom_family_namespace
from ..distribution_planner.fingerprint import FingerprintComponents, render_fingerprint
from ..distribution_planner.tuning import FINGERPRINT_COMPONENT_COUNT
from ..type_weights.tuning import AREA_SHAPES, TARGET_MODES
from ..vocab import PAIRING_ROLES, RELATIONS, SCOPES, load_family_ids
from .similarity import jaccard_milli, token_set

__all__ = [
    "Candidate", "parse_candidate", "order_candidates", "SCOPE_RANK",
    "Reject", "run_tier1", "run_tier2", "run_tier3", "default_similarity",
    "RoundResult", "select_round", "build_envelope", "canonical_dump",
]

# spec §3 step 1: general < family < species, an ordinal for byte-wise (Ordinal) sort -- never a
# dict/filesystem iteration order.
SCOPE_RANK: "dict[str, int]" = {"general": 0, "family": 1, "species": 2}
assert set(SCOPE_RANK) == SCOPES, "every real scope needs a rank"


# ---------------------------------------------------------------------------------------------
# §3 step 1 (parse + total ordering) -- a candidate row, validated and rendered into the one
# canonical fingerprint (`distribution_planner.fingerprint`, reused rather than re-implemented per
# this module's own build instructions).
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    id: str
    scope: str
    scope_key: "str | None"
    brief_id: str                        # "" when the row carries none -- see module docstring
    fp: FingerprintComponents
    name: str
    rationale: str
    raw: Mapping[str, object]            # the original row, written back verbatim on survival


def parse_candidate(row: Mapping[str, object], family_ids: "frozenset[str]") -> Candidate:
    """Validates every wire-string field against its closed vocabulary BEFORE anything is hashed
    (spec §5 'Casing': a `"Area"`/`"Row"`/`"Enemy"` planted violation is refused here, never
    silently hashed as though it were real vocabulary)."""
    cid = row.get("id")
    if not cid or not isinstance(cid, str):
        raise ValueError(f"candidate row missing a real string 'id' -- got {cid!r}")

    scope = row.get("scope")
    if scope not in SCOPES:
        raise ValueError(f"{cid}: scope {scope!r} is not real vocabulary {sorted(SCOPES)} -- refused")

    category = row.get("category")
    if category not in CATEGORIES:
        raise ValueError(f"{cid}: category {category!r} is not real vocabulary -- refused")

    target_mode = row.get("targetMode")
    if target_mode not in TARGET_MODES:
        raise ValueError(f"{cid}: targetMode {target_mode!r} is not real vocabulary -- refused")

    relation = row.get("relation")
    if relation not in RELATIONS:
        raise ValueError(f"{cid}: relation {relation!r} is not real vocabulary -- refused")

    pairing_role = row.get("pairingRole")
    if pairing_role not in PAIRING_ROLES:
        raise ValueError(f"{cid}: pairingRole {pairing_role!r} is not real vocabulary -- refused")

    # spec §2: "areaShape is the literal `none` when targetMode != area -- a missing KEY is a
    # defect, `none` is a value." The row itself must carry the KEY (a real shape when
    # targetMode == "area", JSON null otherwise) -- omitting it outright is refused here; the
    # fingerprint then renders that null as the literal string "none"
    # (`distribution_planner.fingerprint.render_fingerprint`'s own `NONE_AREA_SHAPE`).
    if "areaShape" not in row:
        raise ValueError(f"{cid}: missing required key 'areaShape' -- present (a real shape or "
                         f"JSON null) is required, omission is refused")
    raw_area_shape = row["areaShape"]
    if target_mode == "area":
        if raw_area_shape not in AREA_SHAPES:
            raise ValueError(f"{cid}: targetMode 'area' requires a real areaShape -- got "
                             f"{raw_area_shape!r}")
        area_shape = raw_area_shape
    else:
        if raw_area_shape is not None:
            raise ValueError(f"{cid}: targetMode {target_mode!r} != 'area' must carry "
                             f"areaShape: null -- got {raw_area_shape!r}")
        area_shape = None

    atom_families = tuple(row.get("atomFamilies") or ())
    if not atom_families:
        raise ValueError(f"{cid}: atomFamilies must be non-empty")
    validate_atom_family_namespace(atom_families, family_ids)

    structure_axes = tuple(row.get("structureAxes") or ())

    scope_key = row.get("scopeKey")
    brief_id = row.get("briefId") or ""
    name = row.get("name") or ""
    rationale = row.get("rationale") or ""

    fp = FingerprintComponents(
        atom_families=atom_families, category=category, target_mode=target_mode,
        area_shape=area_shape, relation=relation, structure_axes=structure_axes,
        pairing_role=pairing_role,
    )
    return Candidate(id=cid, scope=scope, scope_key=scope_key, brief_id=brief_id, fp=fp,
                     name=name, rationale=rationale, raw=dict(row))


def _sort_key(c: Candidate) -> "tuple[int, str, str, str]":
    return (SCOPE_RANK[c.scope], c.scope_key or "", c.brief_id, c.id)


def order_candidates(candidates: Sequence[Candidate]) -> "list[Candidate]":
    """The total order spec §3 step 1 mandates. Every later step walks THIS order -- input order
    (shuffled or not) never reaches any later step directly."""
    return sorted(candidates, key=_sort_key)


# ---------------------------------------------------------------------------------------------
# §3 step 2 -- tier 1, exact fingerprint match, a hash set over the whole round + accepted corpus.
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Reject:
    candidate_id: str
    tier: int
    reason: str
    collided_with: str


def run_tier1(ordered: Sequence[Candidate],
             accepted_fp_to_id: Mapping["tuple[str, ...]", str]) -> "tuple[list[Candidate], list[Reject]]":
    """`accepted_fp_to_id` seeds the hash set (the already-accepted corpus); it grows as
    candidates survive, so a later duplicate WITHIN this round collides against an earlier
    survivor too -- "the first candidate in the fixed order wins" (spec §3 step 2) falls out of
    walking `ordered` and inserting only on survival, never re-checking the caller's own mapping."""
    fp_to_id: "dict[tuple[str, ...], str]" = dict(accepted_fp_to_id)
    survivors: "list[Candidate]" = []
    rejects: "list[Reject]" = []
    for c in ordered:
        fp = render_fingerprint(c.fp)
        collided_with = fp_to_id.get(fp)
        if collided_with is not None:
            rejects.append(Reject(c.id, 1, "identical fingerprint", collided_with))
            continue
        fp_to_id[fp] = c.id
        survivors.append(c)
    return survivors, rejects


# ---------------------------------------------------------------------------------------------
# §3 step 3 -- tier 2, near-duplicate (exactly one field apart), hard reject, but ONLY within an
# anchor. A hash set per field-masked projection, per anchor -- O(7) lookups per candidate, never
# an O(n^2) pairwise scan (constraint 2/spec §3 step 3's own requirement).
# ---------------------------------------------------------------------------------------------

def _masked(t: "tuple[str, ...]", i: int) -> "tuple[str, ...]":
    return t[:i] + t[i + 1:]


def run_tier2(ordered_tier1_survivors: Sequence[Candidate],
             accepted_by_anchor: Mapping["tuple[str, str]", Sequence["tuple[tuple[str, ...], str]"]],
             ) -> "tuple[list[Candidate], list[Reject]]":
    """`accepted_by_anchor`: `(scope, scopeKey)` -> `[(renderedFingerprint, id), ...]` for the
    already-accepted corpus. Buckets are built lazily per anchor and grow as this round's own
    candidates survive, exactly like tier 1's single hash set -- so two candidates in the SAME
    anchor that are each other's only one-field-apart neighbour still correctly reject the later
    one. A different anchor never shares a bucket (cross-anchor near-duplicates are allowed by
    design, spec §3 step 3 -- "a fire species and an ice species may both have 'burst damage down
    a row', and should")."""
    # buckets[anchor][field_index][masked_projection] -> {value_at_field_index: candidate_id}
    buckets: "dict[tuple[str, str], list[dict[tuple[str, ...], dict[str, str]]]]" = {}

    def anchor_buckets(anchor: "tuple[str, str]") -> "list[dict]":
        existing = buckets.get(anchor)
        if existing is not None:
            return existing
        per_field: "list[dict[tuple[str, ...], dict[str, str]]]" = [
            {} for _ in range(FINGERPRINT_COMPONENT_COUNT)
        ]
        for fp, cid in accepted_by_anchor.get(anchor, ()):
            for i in range(FINGERPRINT_COMPONENT_COUNT):
                per_field[i].setdefault(_masked(fp, i), {})[fp[i]] = cid
        buckets[anchor] = per_field
        return per_field

    survivors: "list[Candidate]" = []
    rejects: "list[Reject]" = []
    for c in ordered_tier1_survivors:
        anchor = (c.scope, c.scope_key or "")
        per_field = anchor_buckets(anchor)
        fp = render_fingerprint(c.fp)

        collided_with: "str | None" = None
        for i in range(FINGERPRINT_COMPONENT_COUNT):
            bucket = per_field[i].get(_masked(fp, i))
            if not bucket:
                continue
            for value, cid in bucket.items():
                if value != fp[i]:               # same other-6-fields projection, this one field differs
                    collided_with = cid
                    break
            if collided_with is not None:
                break

        if collided_with is not None:
            rejects.append(Reject(
                c.id, 2, "near-duplicate -- exactly one field apart within the same anchor",
                collided_with))
            continue

        for i in range(FINGERPRINT_COMPONENT_COUNT):
            per_field[i].setdefault(_masked(fp, i), {})[fp[i]] = c.id
        survivors.append(c)

    return survivors, rejects


# ---------------------------------------------------------------------------------------------
# §3 step 4 -- tier 3, semantic, advisory only. The token-overlap heuristic is the DEFAULT
# `similarity_fn`; the seam itself accepts anything shaped `(Candidate, Candidate) -> int`, which
# is what lets a test inject a fixed/stubbed function (spec §5 'Offline guarantee').
# ---------------------------------------------------------------------------------------------

SimilarityFn = Callable[[Candidate, Candidate], int]


def default_similarity(a: Candidate, b: Candidate) -> int:
    return jaccard_milli(token_set(a.name, a.rationale), token_set(b.name, b.rationale))


def run_tier3(ordered_tier2_survivors: Sequence[Candidate], similarity_fn: SimilarityFn,
             threshold_milli: int) -> "list[dict]":
    """All pairs among THIS round's own final survivors (never against the accepted corpus, and
    never rejects -- spec §3 step 4: "over this round's own candidates"). O(n^2) pairs, unlike
    tier 2's masked hash sets: unlike a whole-corpus lexical scan (`metrics.dedup.SemanticDedup`'s
    own LSH banding, built for 1,400+ names), one round is bounded by constraint 3 to roughly the
    size of the whole expected corpus (~850) or, in the smoke batch that actually exists today,
    far smaller -- a plain double loop is the simplest correct thing, not a shortcut that will
    need revisiting at the shipped scale. Iterates `ordered_tier2_survivors` (already the total
    order from step 1) in a fixed `i < j` walk, so the result never depends on input order."""
    rows: "list[dict]" = []
    n = len(ordered_tier2_survivors)
    for i in range(n):
        a = ordered_tier2_survivors[i]
        for j in range(i + 1, n):
            b = ordered_tier2_survivors[j]
            sim = similarity_fn(a, b)
            if sim >= threshold_milli:
                rows.append({"candidateA": a.id, "candidateB": b.id, "similarityMilli": sim})
    return rows


# ---------------------------------------------------------------------------------------------
# Provenance hashing -- sorted by id (the total order's own last tiebreak) before hashing, so the
# hash is invariant to the CALLER's input order (spec §5 'Determinism').
# ---------------------------------------------------------------------------------------------

def _hash_rows(rows: Sequence[Mapping[str, object]]) -> str:
    blob = json.dumps(list(rows), ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------------------------
# Orchestration -- spec §3 steps 1-5 over one round.
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class RoundResult:
    survivor_entries: "list[dict]"
    reject_entries: "list[dict]"
    review_entries: "list[dict]"
    corpus_hash: str
    candidate_set_hash: str
    semantic_ran: bool


def select_round(*, candidate_rows: Sequence[Mapping[str, object]],
                 accepted_rows: Sequence[Mapping[str, object]], round_no: int,
                 similarity_threshold_milli: int, run_semantic: bool = True,
                 similarity_fn: "SimilarityFn | None" = None,
                 family_ids: "frozenset[str] | None" = None) -> RoundResult:
    """Pure: no clock, no random seed, no I/O, no network. `run_semantic=False` is the
    `--no-semantic` mode (spec §3's own "first-class mode, not a debug flag") -- it must produce
    byte-identical `survivor_entries`/`reject_entries` to a `run_semantic=True` call over the same
    inputs (acceptance #6), which holds here by construction: tier 3 runs strictly AFTER tiers 1
    and 2 have already decided every survivor, and never removes one (acceptance #5)."""
    fam_ids = family_ids if family_ids is not None else load_family_ids()

    candidates = [parse_candidate(r, fam_ids) for r in candidate_rows]
    accepted = [parse_candidate(r, fam_ids) for r in accepted_rows]

    ordered = order_candidates(candidates)
    ordered_accepted = order_candidates(accepted)

    candidate_set_hash = _hash_rows([c.raw for c in ordered])
    corpus_hash = _hash_rows([c.raw for c in ordered_accepted])

    accepted_fp_to_id = {render_fingerprint(c.fp): c.id for c in ordered_accepted}
    tier1_survivors, tier1_rejects = run_tier1(ordered, accepted_fp_to_id)

    accepted_by_anchor: "dict[tuple[str, str], list[tuple[tuple[str, ...], str]]]" = {}
    for c in ordered_accepted:
        anchor = (c.scope, c.scope_key or "")
        accepted_by_anchor.setdefault(anchor, []).append((render_fingerprint(c.fp), c.id))

    tier2_survivors, tier2_rejects = run_tier2(tier1_survivors, accepted_by_anchor)

    review_rows: "list[dict]" = []
    if run_semantic:
        fn = similarity_fn or default_similarity
        review_rows = run_tier3(tier2_survivors, fn, similarity_threshold_milli)

    all_rejects = sorted(tier1_rejects + tier2_rejects, key=lambda r: r.candidate_id)
    reject_entries = [
        {"id": f"reject.round-{round_no}.{i:04d}", "candidateId": r.candidate_id, "tier": r.tier,
         "reason": r.reason, "collidedWith": r.collided_with}
        for i, r in enumerate(all_rejects, start=1)
    ]

    review_sorted = sorted(review_rows, key=lambda r: (r["candidateA"], r["candidateB"]))
    review_entries = [
        {"id": f"review.round-{round_no}.{i:04d}", **row}
        for i, row in enumerate(review_sorted, start=1)
    ]

    survivor_entries = [dict(c.raw) for c in sorted(tier2_survivors, key=lambda c: c.id)]

    return RoundResult(
        survivor_entries=survivor_entries, reject_entries=reject_entries,
        review_entries=review_entries, corpus_hash=corpus_hash,
        candidate_set_hash=candidate_set_hash, semantic_ran=run_semantic,
    )


# ---------------------------------------------------------------------------------------------
# §3 step 6 -- canonical envelope assembly + write. Sorted keys, fixed indent, trailing `\n`,
# explicit nulls, CJK unescaped -- the same discipline every `_canonical_dump` in this adapter
# family already uses (`generate_distribution_planner.py`'s own, not shared -- see this module's
# sibling `../generate_dedup_select.py`, which owns the actual file write).
# ---------------------------------------------------------------------------------------------

def build_envelope(kind: str, entries: "list[dict]", meta: dict) -> dict:
    return {"schemaVersion": 1, "kind": kind, "_meta": meta, "entries": entries}


def canonical_dump(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
