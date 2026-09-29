"""seedsmith.adapters.actions.validate_heal.derive --- Stages 2/3 (vote, bounded self-heal) plus
the round orchestration that ties Stage 0's schema audit, Stage 1's gates (`gates.py`), Stage 2's
vote resolution and Stage 3's heal together into one per-candidate verdict and one per-round report
(spec-validate-heal.md SS2). Pure derivation except `run_self_heal`, the one function in this whole
module that makes a model call --- every other function here, including `validate_candidate` and
`validate_round`, is zero-model-call and is what `--dry-run` (acceptance #9) exercises.

**Two independent entry points, converging on the same `CandidateVerdict` shape** (deliberate, see
this module's own build report for the full reasoning): `run_self_heal` is the LIVE path --- one
brief in, a model called up to three times, a gated-or-`unresolved` draft out. `validate_candidate`
is the RECORDED path --- a draft (already healed, or hand-planted for a test) gated against g1/g2/g3
plus already-supplied vote samples, zero calls. A real run composes them (heal, then hand the
result to `validate_candidate`); every test in spec SS4 that is not specifically about the heal
loop's own call count uses `validate_candidate` directly, against the raising stub, per SS4's own
"tests never call a model" rule.

**Why `escalated` means what it means here, not what `PipelineResult`/`run_pipeline` mean by it.**
The generic `pipeline.run.run_pipeline` (Wave 3) already uses `escalated` for "heal budget
exhausted, defect still present" --- but F9 (spec SS2 Stage 3) explicitly REASSIGNS that exact
outcome to `unresolved` for a GENERATION stage, because `run_pipeline`'s own `default_for` would
hand back a brief field as though the model had answered it, which this module refuses to do. So
this module's own `escalated` is reserved for something `run_pipeline` has no name for: a genuinely
unexpected exception during one candidate's processing (a permutation-reproduction mismatch --- SS2
Stage 2's F8-corrected replacement raises rather than returning a soft verdict --- or any other bug
this module has no named path for), caught at the ROUND level and reported rather than aborting the
whole round. This is the SAME convention `workflow/runner.py`'s own `run_many` already uses for a
fan-out subject that raised (`"outcome": "escalated"`, `runner.py:66`) --- reused deliberately,
not reinvented, and given a real reason here because it is easy to misread as sharing
`run_pipeline`'s meaning when it does not.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from ....pipeline.llm_caller import LlmCallerConfig, call_with_self_heal
from ....pipeline.model import BLOCKED_FIELD
from ...creatures.anchor.permute import order_for
from ...creatures.anchor.vote import (SetVoteResult, VoteRecord, VoteResult, disagreement_rate,
                                   resolve_set_vote, resolve_vote)
from .gates import BriefContext, run_g1, run_g2, run_g3
from .schemas import SCHEMAS_BY_PIPELINE, VOTED_FIELDS_BY_PIPELINE

__all__ = [
    "canonical_set_key", "VoteSample", "verify_permutation", "resolve_vote_field",
    "resolve_set_vote_field",
    "build_verify_fn", "default_for_none", "build_heal_user", "run_self_heal",
    "CandidateVerdict", "validate_candidate", "validate_round", "RoundReport",
    "build_envelope", "canonical_dump", "candidate_set_hash",
]


# ---------------------------------------------------------------------------------------------
# Stage 2 --- vote resolution (SS2 Stage 2, F8's corrected permutation replacement).
# ---------------------------------------------------------------------------------------------

def canonical_set_key(values: Sequence[str]) -> str:
    """A multi-member field (`atomFamilies`) votes over a CANONICAL key for the whole set, the same
    "canonicalise before voting" discipline `adapters/effects/affix/derive.py`'s own
    `canonical_bundle_key` already uses for its own multi-ref bundle vote --- a local equivalent
    rather than a cross-program import, since the two programs' bundle shapes are otherwise
    unrelated. Sorted + deduped + joined so `["b","a"]` and `["a","b"]` vote as agreement, never as
    a 2-1 split created by ordering alone."""
    return "|".join(sorted(set(values)))


@dataclass(frozen=True)
class VoteSample:
    """One of the three permuted samples for one voted field on one candidate. `rendered_order` is
    the option order the sample was actually PRESENTED under --- carried alongside `chosen_value`
    so this module can verify it was reproduced from the claimed seed, never trusted blindly."""

    sample_index: int                    # 0, 1, 2
    rendered_order: "tuple[str, ...]"
    chosen_value: str                    # the model's pick for this sample -- a canonical set key
                                          # for a multi-member field, a scalar for a single one


def verify_permutation(brief_id: str, field_name: str, options: Sequence[str],
                       sample: VoteSample) -> None:
    """SS2 Stage 2's F8-corrected replacement, part 1: recompute `order_for` and assert the
    recorded sample's rendered order equals it BYTE FOR BYTE. Never a soft defect --- a mismatch
    means the sample was rendered from a different seed than the one claimed, which is deterministic
    and therefore never a false positive; the caller (`validate_round`) is what turns this raise
    into a per-candidate `escalated` verdict rather than aborting the whole run."""
    expected = tuple(order_for(brief_id, field_name, sample.sample_index, options))
    if tuple(sample.rendered_order) != expected:
        raise ValueError(
            f"{brief_id}/{field_name} sample {sample.sample_index}: rendered order "
            f"{sample.rendered_order!r} does not reproduce order_for(...) = {expected!r} -- the "
            f"sample was rendered from a different seed than the one claimed"
        )


def resolve_vote_field(brief_id: str, field_name: str, options: Sequence[str],
                       samples: Sequence[VoteSample]) -> VoteResult:
    """Verifies all three samples' permutations (part 1), then resolves the vote over their
    `chosen_value`s (`resolve_vote`, reused from `creatures.anchor.vote` --- never reimplemented).
    `confidence` and `value` come ONLY from this call, never read from a model field (binding
    constraint 4)."""
    if len(samples) != 3:
        raise ValueError(f"{brief_id}/{field_name}: expected exactly 3 vote samples, got {len(samples)}")
    for s in samples:
        verify_permutation(brief_id, field_name, options, s)
    return resolve_vote([s.chosen_value for s in samples])


def resolve_set_vote_field(brief_id: str, field_name: str, options: Sequence[str],
                           samples: Sequence[VoteSample]) -> SetVoteResult:
    """The SET-valued twin of `resolve_vote_field`, for `atomFamilies` (added 2026-09-05).

    Same permutation verification, same "three samples exactly" rule — only the aggregation
    differs, and it has to. `chosen_value` here is a `canonical_set_key`, i.e. a whole SET flattened
    to one `|`-joined string, so voting it with the scalar `resolve_vote` scored `{a,b}`/`{a,c}`/
    `{a,d}` as a 1-1-1 split and discarded a unanimous 3/3 agreement on `a`. That is the identical
    defect measured and fixed on the three propose stages the same day, where it was holding the
    real unresolved rate at 40-55%; A-S4 votes the same field the same wrong way, so it gets the
    same correction rather than being left as a known-bad path behind a passing gate.

    An empty `chosen_value` means the sample produced no usable pick; it is passed as `None` and
    still counts against the majority threshold, exactly as on the propose side."""
    if len(samples) != 3:
        raise ValueError(f"{brief_id}/{field_name}: expected exactly 3 vote samples, got {len(samples)}")
    for s in samples:
        verify_permutation(brief_id, field_name, options, s)
    picks = [(s.chosen_value.split("|") if s.chosen_value else None) for s in samples]
    return resolve_set_vote(picks)


# ---------------------------------------------------------------------------------------------
# Stage 3 --- bounded self-heal, F9's adapted generation-stage contract.
# ---------------------------------------------------------------------------------------------

def build_verify_fn(*, pipeline_id: str, ctx: BriefContext) -> Callable:
    """`call_with_self_heal`'s own `verify_fn(items, out) -> (hard, soft)`, closed over the one
    brief this heal round answers. `items` is the brief itself (F9's own reading of the helper's
    generalisation) and is not read here beyond what `ctx` already carries; `out` is the model's
    single draft. A declared, well-formed block short-circuits BOTH g1 and g2 --- "a declared block
    is an answer, not a design to gate" (the same discipline `pipeline.run.run_pipeline`'s own
    `verify` already uses for its per-key blocks, SS3: never let the model's honest decline be
    treated as a defect)."""
    schema = SCHEMAS_BY_PIPELINE[pipeline_id]

    def verify_fn(items: Mapping[str, object], out: Mapping[str, object]):
        hard: "dict[str, str]" = {}
        soft: "dict[str, str]" = {}
        if not isinstance(out, dict):
            hard["_draft"] = "response is not an object"
            return hard, soft

        if out.get(BLOCKED_FIELD):
            reason = out.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                hard[BLOCKED_FIELD] = "blocked=true but 'reason' is empty -- a genuine decline names why"
            return hard, soft

        hard.update(run_g1(out, schema))
        g2_hard, _restriction_claimed = run_g2(out, ctx)
        hard.update(g2_hard)
        return hard, soft

    return verify_fn


def default_for_none(key: str, original: object) -> None:
    """F9's own required override: NEVER `call_with_self_heal`'s shipped default
    (`lambda key, original: original`), which for a GENERATION stage would hand back a brief FIELD
    as though the model had answered it. `None` is the only honest fallback, and it is the exact
    shape `VoteResult.value` already uses for the same meaning (`confidence == 'unresolved'`)."""
    return None


def build_heal_user(brief: Mapping[str, object], out: Mapping[str, object],
                    hard: Mapping[str, str]) -> str:
    """Names the exact defect per key, never a bare retry (SS2 Stage 3, acceptance #7). Mirrors
    `llm_caller._default_heal_user`'s own shape (defect list + the source the model needs to fix
    against) but supplies the BRIEF as the source, since a generation stage's "source" is what it
    was asked to build from, never the model's own prior (wrong) draft repeated back to it."""
    defects = "\n".join(f"- {k}: {r}" for k, r in hard.items())
    return (
        f"Your draft had these problems:\n{defects}\n\n"
        f"Fix ONLY the named field(s). Return the COMPLETE corrected JSON object (every key this "
        f"schema requires).\n\nThe brief you are answering:\n"
        f"{json.dumps(dict(brief), ensure_ascii=False)}"
    )


def run_self_heal(*, brief: Mapping[str, object], pipeline_id: str, ctx: BriefContext,
                  system: str, build_user: Callable[[Mapping[str, object]], str],
                  config: LlmCallerConfig) -> "tuple[dict, dict, int]":
    """The one function in this module that calls a model. `max_heal=2` is passed EXPLICITLY
    (`llm_caller`'s own config default is 3) --- three attempts total: one generation, two repairs
    (SS2 Stage 3, acceptance #6). Returns `(out, soft, heal_count)`.

    `heal_count` is tracked by counting `build_heal_user` invocations, with one adjustment.
    `call_with_self_heal`'s own `range(heal_budget + 1)` loop calls `build_heal_user` after EVERY
    failed attempt, including the LAST one in the budget --- whose resulting prompt is then thrown
    away, since there is no further `call_model` round left to send it in (`llm_caller.py`'s own
    loop does not special-case "this was the final attempt"). So on the FULLY-EXHAUSTED path,
    `build_heal_user` is called `max_heal + 1` times (3 for `max_heal=2`) even though only
    `max_heal` (2) repairs were genuinely SENT to the model. The helper's own return value already
    distinguishes the two cases unambiguously: exhaustion is exactly when its `soft` dict carries a
    `FAILED:`-prefixed entry (F9's own verdict rule) --- so this function subtracts one from the
    raw `build_heal_user` count in that case, and not otherwise, giving 0 for a first-try success, 1
    for a success on the first repair, and exactly `max_heal` (2) when every attempt fails (SS2
    Stage 3's F9 note: "its `_provenance` carries the heal count, exactly 2 on this path")."""
    raw_heal_user_calls = 0

    def counting_build_heal_user(items, out, hard):
        nonlocal raw_heal_user_calls
        raw_heal_user_calls += 1
        return build_heal_user(brief, out, hard)

    out, soft = call_with_self_heal(
        dict(brief), system, build_user, build_verify_fn(pipeline_id=pipeline_id, ctx=ctx),
        config=config, max_heal=2,
        build_heal_user=counting_build_heal_user,
        default_for=default_for_none,
    )
    exhausted = any(isinstance(v, str) and v.startswith("FAILED:") for v in soft.values())
    heal_count = raw_heal_user_calls - (1 if exhausted else 0)
    return out, soft, heal_count


# ---------------------------------------------------------------------------------------------
# Round-report/candidate assembly --- SS2 "What it emits". Zero model calls; this is the whole of
# what `--dry-run` exercises.
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class CandidateVerdict:
    candidate_id: str
    brief_id: str
    pipeline_id: str
    scope: str
    outcome: str                          # "accepted" | "blocked" | "unresolved" | "escalated"
    gate_defects: "dict[str, str]"        # g1+g2, keyed by field
    quality_notes: "tuple[str, ...]"      # g3, advisory -- never affects `outcome`
    differentiator_is_none: bool          # A-P3 only, recorded never penalised
    structure_axes_unchecked: bool        # 'restriction' claimed -- passed, reported unverified
    vote_results: "dict[str, VoteResult]"
    heal_count: int
    entry: "dict[str, object] | None"     # the final action-brief-shaped row, only when accepted
    provenance: "dict[str, object]"


def _finalize_atom_families(vote_results: Mapping[str, VoteResult]) -> "list[str] | None":
    """`atomFamilies` is voted for every pipeline (SS2 Stage 2) --- the CANDIDATE's own final value
    is the vote's resolved canonical key, split back into a list, never the model's raw single-shot
    draft value (binding constraint 4: confidence/value come only from the vote). Returns `None`
    when the vote was `unresolved` (1-1-1) -- the caller reads that as `value is None`."""
    result = vote_results.get("atomFamilies")
    if result is None or result.value is None:
        return None
    return sorted(result.value.split("|")) if result.value else []


def validate_candidate(*, candidate_id: str, brief_id: str, pipeline_id: str, scope: str,
                       draft: Mapping[str, object], ctx: BriefContext,
                       heal_count: int = 0, heal_defects: "Mapping[str, str] | None" = None,
                       vote_samples: "Mapping[str, Sequence[VoteSample]] | None" = None,
                       vote_options: "Mapping[str, Sequence[str]] | None" = None,
                       motif_or_role_terms: Sequence[str] = (),
                       names_already_in_round: Sequence[str] = (),
                       provenance: "Mapping[str, object] | None" = None) -> CandidateVerdict:
    """The zero-model-call path (`--dry-run`, and every gate/vote test in spec SS4 not specifically
    about the heal loop's own call count). `heal_defects` --- when given and non-empty --- is Stage
    3's own `FAILED:`-derived defect set for an already-attempted-and-exhausted heal round; when
    non-empty this function short-circuits straight to `unresolved` WITHOUT reading `draft` as an
    answer for those keys (F9: "nothing else is read from `out` for such a key").

    **A g1/g2 hard defect found HERE (not via `heal_defects`) also reports `unresolved`, deliberately
    --- a scope decision this module's own build made, not something spec-validate-heal.md states in
    so many words.** In a live run a g1/g2 defect is Stage 3's own job to heal BEFORE a candidate
    ever reaches this function; finding one here means either a test is exercising the gates
    directly against a planted violation (which reads `gate_defects`, not `outcome`), or `--dry-run`
    is gating a candidate that was never healed at all (zero calls, by definition, so there is no
    live repair to attempt) --- in both cases `unresolved` is the more honest label than inventing a
    fifth outcome the spec's own four-way vocabulary does not name, and it puts the candidate in the
    same review queue a heal-exhausted one lands in, which is exactly where a human should look.
    """
    heal_defects = dict(heal_defects or {})
    vote_samples = dict(vote_samples or {})
    vote_options = dict(vote_options or {})
    prov = dict(provenance or {})
    prov["healCount"] = heal_count

    if heal_defects:
        return CandidateVerdict(
            candidate_id=candidate_id, brief_id=brief_id, pipeline_id=pipeline_id, scope=scope,
            outcome="unresolved", gate_defects=dict(heal_defects), quality_notes=(),
            differentiator_is_none=False, structure_axes_unchecked=False, vote_results={},
            heal_count=heal_count, entry=None, provenance=prov,
        )

    if draft.get(BLOCKED_FIELD):
        return CandidateVerdict(
            candidate_id=candidate_id, brief_id=brief_id, pipeline_id=pipeline_id, scope=scope,
            outcome="blocked", gate_defects={}, quality_notes=(), differentiator_is_none=False,
            structure_axes_unchecked=False, vote_results={}, heal_count=heal_count, entry=None,
            provenance=prov,
        )

    schema = SCHEMAS_BY_PIPELINE[pipeline_id]
    gate_defects: "dict[str, str]" = {}
    gate_defects.update(run_g1(draft, schema))
    g2_defects, restriction_claimed = run_g2(draft, ctx)
    gate_defects.update(g2_defects)

    vote_results: "dict[str, VoteResult]" = {}
    for field_name in VOTED_FIELDS_BY_PIPELINE[pipeline_id]:
        samples = vote_samples.get(field_name)
        options = vote_options.get(field_name)
        if samples is None or options is None:
            continue                       # no sample supplied -- gate defects alone decide
        # `atomFamilies` is set-valued -> per-member majority; every other voted field is a
        # genuine scalar and keeps the unchanged scalar path.
        result = (resolve_set_vote_field(brief_id, field_name, options, samples)
                  if field_name == "atomFamilies"
                  else resolve_vote_field(brief_id, field_name, options, samples))
        vote_results[field_name] = result
        if result.confidence == "unresolved":
            gate_defects[field_name] = "1-1-1 vote -- unresolved, value is None"

    if gate_defects:
        return CandidateVerdict(
            candidate_id=candidate_id, brief_id=brief_id, pipeline_id=pipeline_id, scope=scope,
            outcome="unresolved", gate_defects=gate_defects, quality_notes=(),
            differentiator_is_none=False, structure_axes_unchecked=restriction_claimed,
            vote_results=vote_results, heal_count=heal_count, entry=None, provenance=prov,
        )

    atom_families = _finalize_atom_families(vote_results) \
        if "atomFamilies" in vote_results else draft.get("atomFamilies")
    differentiator = vote_results["differentiator"].value if "differentiator" in vote_results \
        else draft.get("differentiator")
    differentiator_is_none = differentiator == "none"

    entry = dict(draft)
    entry["atomFamilies"] = atom_families
    if "differentiator" in draft or pipeline_id == "A-P3":
        entry["differentiator"] = differentiator
    entry["structureEnforced"] = not restriction_claimed

    notes = run_g3(draft, motif_or_role_terms=motif_or_role_terms,
                   names_already_in_round=names_already_in_round)

    return CandidateVerdict(
        candidate_id=candidate_id, brief_id=brief_id, pipeline_id=pipeline_id, scope=scope,
        outcome="accepted", gate_defects={}, quality_notes=tuple(notes),
        differentiator_is_none=differentiator_is_none,
        structure_axes_unchecked=restriction_claimed, vote_results=vote_results,
        heal_count=heal_count, entry=entry, provenance=prov,
    )


# ---------------------------------------------------------------------------------------------
# Round orchestration --- catches any exception a single candidate raises (a permutation mismatch,
# or anything else) and reports it as `escalated` rather than aborting the round
# (`workflow/runner.py`'s own `run_many` precedent, reused --- see module docstring).
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class RoundReport:
    verdicts: "tuple[CandidateVerdict, ...]"
    disagreement_rate: "dict[str, dict[str, float]]"
    differentiator_none_rate: "float | None"
    restriction_unchecked_count: int
    candidate_set_hash: str


def validate_round(candidates: Sequence[Mapping[str, object]], *,
                   contexts: Mapping[str, BriefContext],
                   candidate_kwargs: "Mapping[str, Mapping[str, object]] | None" = None) -> RoundReport:
    """`candidates`: one dict per candidate, each carrying at least `candidateId`/`briefId`/
    `pipelineId`/`scope`/`draft` -- `contexts` keys on `briefId`. `candidate_kwargs`, keyed by
    `candidateId`, supplies the rest of `validate_candidate`'s own keyword arguments (heal results,
    vote samples/options, motif/role terms) -- kept OUT of the candidate row itself so the round's
    own hashed `candidate_set_hash` (below) is over the candidate's OWN content, never over
    per-call plumbing.

    Candidates are processed in the caller's given order but the round's own g3 "name uniqueness"
    check needs every PRIOR candidate's name, in a total order -- so this function sorts by
    `candidateId` first (byte-wise, matching every `order_candidates` in this adapter family) and
    walks that order, exactly like `dedup_select.derive.select_round`'s own single hash-set walk.

    **Real-call finding, 2026-09-04 (first real smoke batch)**: `candidateId` is `None` on every
    real A-P1/A-P2/A-P3 row whose OWN vote came back `unresolved` or `blocked`
    (`general_propose.derive.candidate_row`: `"candidateId": ... if candidate.entry else None`) --
    the overwhelming common case in practice (measured: 13/17 real rows across this batch's P1+P2
    output). A bare `sorted(..., key=lambda c: c["candidateId"])` raises `TypeError` comparing
    `None` to `str` the moment more than one such row is in the same round, aborting the WHOLE
    round rather than reaching the per-candidate `try/except` below that exists for exactly this
    kind of per-row problem. `briefId` is a stable, always-present tie-break for the `None` group --
    every real brief has exactly one candidate row per round, so this never changes ordering among
    rows that already carry a real, distinct `candidateId`.
    """
    ordered = sorted(candidates, key=lambda c: (c["candidateId"] is None, c["candidateId"] or "",
                                                c.get("briefId") or ""))
    candidate_kwargs = candidate_kwargs or {}

    verdicts: "list[CandidateVerdict]" = []
    names_seen: "list[str]" = []
    vote_records: "list[VoteRecord]" = []
    restriction_unchecked = 0
    differentiator_flags: "list[bool]" = []

    for row in ordered:
        cid = row["candidateId"]
        brief_id = row["briefId"]
        pipeline_id = row["pipelineId"]
        scope = row["scope"]
        draft = row["draft"]
        ctx = contexts[brief_id]
        kwargs = dict(candidate_kwargs.get(cid) or {})
        try:
            verdict = validate_candidate(
                candidate_id=cid, brief_id=brief_id, pipeline_id=pipeline_id, scope=scope,
                draft=draft, ctx=ctx, names_already_in_round=tuple(names_seen), **kwargs,
            )
        except Exception as e:            # a single candidate's defect must never abort the round
            verdict = CandidateVerdict(
                candidate_id=cid, brief_id=brief_id, pipeline_id=pipeline_id, scope=scope,
                outcome="escalated", gate_defects={"_error": str(e)}, quality_notes=(),
                differentiator_is_none=False, structure_axes_unchecked=False, vote_results={},
                heal_count=int((kwargs or {}).get("heal_count", 0)), entry=None,
                provenance={"error": str(e)},
            )
        verdicts.append(verdict)
        if verdict.outcome == "accepted" and verdict.entry and verdict.entry.get("name"):
            names_seen.append(str(verdict.entry["name"]))
        if verdict.structure_axes_unchecked:
            restriction_unchecked += 1
        if verdict.differentiator_is_none:
            differentiator_flags.append(True)
        elif verdict.pipeline_id == "A-P3" and verdict.outcome == "accepted":
            differentiator_flags.append(False)
        for field_name, result in verdict.vote_results.items():
            vote_records.append(VoteRecord(species_id=cid, side=scope, field=field_name, result=result))

    none_rate = (sum(differentiator_flags) / len(differentiator_flags)) if differentiator_flags else None

    return RoundReport(
        verdicts=tuple(verdicts),
        disagreement_rate=disagreement_rate(vote_records),
        differentiator_none_rate=none_rate,
        restriction_unchecked_count=restriction_unchecked,
        candidate_set_hash=candidate_set_hash(ordered),
    )


def candidate_set_hash(candidates: Sequence[Mapping[str, object]]) -> str:
    """Same `None`-candidateId real-call finding as `validate_round`'s own docstring -- this
    function is called independently of that one (e.g. `dedup_select.derive`'s own round hashing)
    and needs the identical tie-break, not just a caller that happens to pre-sort first."""
    ordered = sorted(candidates, key=lambda c: (c["candidateId"] is None, c["candidateId"] or "",
                                                c.get("briefId") or ""))
    blob = json.dumps(ordered, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_envelope(kind: str, entries: "list[dict]", meta: dict) -> dict:
    return {"schemaVersion": 1, "kind": kind, "_meta": meta, "entries": entries}


def canonical_dump(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
