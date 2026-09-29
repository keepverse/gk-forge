"""seedsmith.adapters.actions.signature_propose.derive --- A-P3's own candidate assembly: per-
sample bounded self-heal (F9's adapted contract) and majority-vote resolution over TWO fields --
`atomFamilies` AND `differentiator` (spec-signature-propose.md SS2 "Which fields are voted": "Two
voted fields this time"). Reuses `creatures.anchor.vote.resolve_vote` and
`pipeline.llm_caller.call_with_self_heal` directly, never reimplemented (this whole program's own
reuse discipline) -- exactly as `family_propose/derive.py` and `general_propose/derive.py` do.

**Why TWO voted fields, and why `differentiator` is the one that matters most.** `atomFamilies` is
voted for the same reason it always is: it is the mechanical identity, and tier-1 dedup hashes it.
`differentiator` is voted ONLY here, and the argument is specific rather than inherited (spec SS2):
this is the one judgement the whole pipeline exists to make. If it is wrong, the species' signature
action is a family action with a different name -- invisible to every deterministic gate downstream,
because tiers 1/2 hash mechanics and tier 3 is advisory. A 1-1-1 split on EITHER field writes
`confidence: 'unresolved'` for the WHOLE candidate (spec SS2) -- never just the one field that split.

**`motifsExpressed` is deliberately NOT voted** (spec SS2, same reasoning as A-P2's own identical
rule): it is a self-report feeding the tier-3 review queue only, and tier 3 is advisory by design --
voting it would add cost for a field that never rejects anything. It is taken straight from sample 0
(the same "primary" sample that already supplies `name`/`flavor`/`rationale`, none of which are
voted either) -- stated once here rather than re-decided per field.

**Not a copy of `validate_heal.derive`.** A-S4 (`validate_heal`) is a LATER, separate stage that
gates and votes over whatever a generation pipeline hands it, against ITS OWN fixture schemas. This
module is the real A-P3: it owns its OWN schema (`prompts.SIGNATURE_ACTION_SCHEMA`), and it never
grades itself (spec SS3) -- so the vote/heal machinery here exists ONLY to turn three raw model
samples into one candidate row, never to decide final acceptance. `confidence` on that row is read
straight off each field's own `VoteResult`, never invented (binding constraint 4).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from ....pipeline.llm_caller import LlmCallerConfig, call_with_self_heal
from ....pipeline.model import BLOCKED_FIELD
from ...creatures.anchor.vote import SetVoteResult, VoteResult, resolve_set_vote, resolve_vote
from ..coverage_assignment.derive import splice_payoff_enablers
from .prompts import (
    SYSTEM_PROMPT,
    atom_families_are_allowed,
    atom_families_differ_from_family,
    atom_families_not_forbidden,
    build_brief,
    build_context,
    differentiator_is_known,
    entry_for,
    motifs_expressed_are_known,
    motifs_expressed_exclude_anti_motifs,
    schema_for_call,
)

__all__ = [
    "SAMPLE_COUNT", "MAX_HEAL", "VOTED_FIELDS", "canonical_family_key", "build_verify_fn",
    "default_for_none", "sample_draft", "Candidate", "finalize_candidate",
    "propose_signature_action", "candidate_row", "canonical_dump", "candidate_set_hash",
]

#: Spec SS2: three permuted samples, always. Never a config knob -- changing this changes the
#: vote's own arithmetic (a 1-1-1 split has no meaning over any other count).
SAMPLE_COUNT = 3

#: Acceptance #11: "Repairs are bounded at two ... passed explicitly -- the config default is 3."
MAX_HEAL = 2

#: The two fields voted over three permuted samples (spec SS2) -- pinned as a tuple so a third
#: field needs a deliberate code change, matching `adapters/creatures/anchor/vote.py`'s own
#: `VOTED_FIELDS` frozenset discipline for this stage's own local pair.
VOTED_FIELDS: "tuple[str, ...]" = ("atomFamilies", "differentiator")

#: A sample whose own self-heal was exhausted (F9: `default_for_none` returns `None` for the
#: still-failing key) contributes NO usable `atomFamilies` pick. It must still cast a VOTE --
#: silently dropping it from the count would let two real samples out-vote a total of two instead
#: of three, changing what "1-1-1" and "2-1" mean. This sentinel can never collide with a real
#: pick (canonical keys are `|`-joined atom-family ids, none of which is this literal string), so
#: it always counts as its own, distinct, losing vote. Identical convention to
#: `family_propose/derive.py`'s own sentinel, kept local (self-containment, see that module's own
#: docstring for why sibling propose stages never import each other's private constants).
_UNRESOLVED_ATOM_SENTINEL = "\x00signature-propose:unresolved-atom-sample\x00"

#: The SAME sentinel discipline, for `differentiator` -- a sample whose own value is missing or not
#: a string still casts its own distinct, losing vote rather than being silently dropped. Can never
#: collide with a real differentiator value (the closed six-value vocabulary, none of which is this
#: literal string).
_UNRESOLVED_DIFFERENTIATOR_SENTINEL = "\x00signature-propose:unresolved-differentiator-sample\x00"


def canonical_family_key(values: Sequence[str]) -> str:
    """Sorted + deduped + joined, so `["b","a"]` and `["a","b"]` vote as agreement rather than a
    2-1 split created by ordering alone. Independently defined here rather than imported from
    `general_propose.derive.canonical_family_key` or `family_propose.derive.canonical_family_key`
    -- the identical one-line convention, kept local so this module stays pure and self-contained
    (spec SS3: "one brief in, one candidate out"; sibling propose stages are peers, not shared
    dependencies of each other)."""
    return "|".join(sorted(set(values)))


def build_verify_fn(context: Mapping[str, Any]) -> Callable[[Mapping[str, Any], Mapping[str, Any]], "tuple[dict, dict]"]:
    """`call_with_self_heal`'s own `verify_fn(items, out) -> (hard, soft)`, closed over ONE
    rendered brief context. A declared block (`blocked` non-empty) short-circuits every other
    check -- an honest decline is an answer, never a defect to heal (the same discipline
    `family_propose/derive.py:build_verify_fn` states for the sibling stage). `atomFamilies` is
    checked against BOTH `family_propose`'s two shared rules AND this stage's own hard "must
    differ from every family action" rule (`atom_families_differ_from_family`) -- a draft that
    reuses a family action's atom-family set is rejected here, at generation time, and the
    re-prompt names the colliding action (spec's own most novel rule for this stage).
    `motifsExpressed` is checked for both an unknown motif and a species anti-motif expression.
    `differentiator` is checked against this brief's own closed, permuted enum."""

    def verify_fn(items: Mapping[str, Any], out: Mapping[str, Any]) -> "tuple[dict, dict]":
        hard: "dict[str, str]" = {}
        soft: "dict[str, str]" = {}
        if not isinstance(out, dict):
            hard["_draft"] = "response is not an object"
            return hard, soft
        if out.get(BLOCKED_FIELD):
            return hard, soft

        for key in ("name", "flavor", "atomFamilies", "motifsExpressed", "differentiator",
                   "rationale", BLOCKED_FIELD):
            if key not in out:
                hard[key] = "required key missing"

        if "atomFamilies" in out:
            reasons = (atom_families_are_allowed(out, context)
                      + atom_families_not_forbidden(out, context)
                      + atom_families_differ_from_family(out, context))
            if reasons:
                hard["atomFamilies"] = "; ".join(reasons)

        if "motifsExpressed" in out:
            reasons = (motifs_expressed_are_known(out, context)
                      + motifs_expressed_exclude_anti_motifs(out, context))
            if reasons:
                hard["motifsExpressed"] = "; ".join(reasons)

        if "differentiator" in out:
            reasons = differentiator_is_known(out, context)
            if reasons:
                hard["differentiator"] = "; ".join(reasons)

        return hard, soft

    return verify_fn


def default_for_none(key: str, original: object) -> None:
    """F9's own required override, restated for this pipeline (acceptance #11): NEVER
    `call_with_self_heal`'s shipped default (`lambda key, original: original`), which for a
    GENERATION stage would hand back a BRIEF-CONTEXT field as though the model had answered it.
    `None` is the only honest fallback -- the same shape `VoteResult.value` already uses for
    `confidence == 'unresolved'`."""
    return None


#: See `general_propose.derive._NULLISH_BLOCKED_TOKENS`'s own docstring for the real-call evidence
#: (`"false"` and `"none"`, measured on the general-propose and family-propose siblings). Kept
#: local, same closed set, same self-containment reason this module's own functions state
#: elsewhere.
_NULLISH_BLOCKED_TOKENS = frozenset({"false", "none", "null", "n/a", "na"})


def _normalize_blocked(out: Mapping[str, Any]) -> dict:
    """**Real-call finding, 2026-09-04 (first real smoke batch)** -- identical fix to the
    general-propose sibling module. See `general_propose.derive._normalize_blocked`'s docstring for
    the full real-call evidence: the hardened description alone did not stop a real local model
    from substituting a null-ish word for the empty string this field asks for; any member of
    `_NULLISH_BLOCKED_TOKENS` is folded back to the empty string here, once, at the model boundary.
    `"true"` is deliberately left alone."""
    if isinstance(out, Mapping) and str(out.get(BLOCKED_FIELD, "")).strip().lower() in _NULLISH_BLOCKED_TOKENS:
        return {**out, BLOCKED_FIELD: ""}
    return dict(out) if isinstance(out, Mapping) else out


def sample_draft(brief: Mapping[str, Any], *, sample_index: int,
                 pairing_table: "Mapping[str, Sequence[str]] | None" = None,
                 family_glossary: "Mapping[str, str] | None" = None,
                 usage_weights: "Mapping[str, int] | None" = None,
                 config: "LlmCallerConfig | None" = None) -> "tuple[dict, dict]":
    """The ONE function in this module that calls a model -- one of `SAMPLE_COUNT` samples for one
    brief. `max_heal=MAX_HEAL` is passed EXPLICITLY (acceptance #11). Returns `(out, soft)`; `soft`
    carries a `FAILED:<reason>` entry for any key `default_for_none` fell back on.

    `family_glossary` (SMOKE BATCH criterion-2 fix, 2026-09-05): threaded straight to
    `build_context`, optional and defaulted to `None`.

    `usage_weights` (roster-balance FC3, 2026-09-06): threaded straight to `build_context`,
    optional, defaults to `None`, identical contract to the sibling propose modules."""
    context = build_context(brief, sample_index=sample_index, pairing_table=pairing_table,
                            family_glossary=family_glossary, usage_weights=usage_weights)
    brief_text = build_brief(context)
    out, soft = call_with_self_heal(
        dict(context), SYSTEM_PROMPT, lambda _items: brief_text, build_verify_fn(context),
        config=config or LlmCallerConfig(), max_heal=MAX_HEAL, default_for=default_for_none,
        schema=schema_for_call(context["allowedAtomFamilies"], context["motifsExpressedEnum"],
                               context["differentiatorEnum"]),
    )
    return _normalize_blocked(out), soft


@dataclass(frozen=True)
class Candidate:
    brief_id: str
    outcome: str                              # "accepted" | "blocked" | "unresolved"
    entry: "dict[str, Any] | None"
    votes: "dict[str, Any] | None"             # {"atomFamilies": SetVoteResult, "differentiator": VoteResult}
    provenance: "dict[str, Any]"


def _is_unresolved(vote: VoteResult, sentinel: str) -> bool:
    """A vote is unresolved either the ordinary way (a genuine 1-1-1 split, `resolve_vote`'s own
    `confidence == 'unresolved'`) or because its WINNING value is the "no sample produced a usable
    answer" sentinel -- a 2-1 or 3-0 majority for "nobody answered" is not a real answer either."""
    return vote.confidence == "unresolved" or vote.value == sentinel


def finalize_candidate(brief: Mapping[str, Any], drafts: Sequence[Mapping[str, Any]], *,
                       candidate_id: str, provenance: "Mapping[str, Any] | None" = None,
                       pairing_table: "Mapping[str, Sequence[str]] | None" = None) -> Candidate:
    """Pure -- zero model calls, so this is what `--dry-run` and the recorded-transcript replay
    test both exercise. Takes exactly `SAMPLE_COUNT` already-produced draft dicts (live-called-
    and-healed, or a recorded transcript replayed verbatim) and resolves ONE candidate:

    1. A declared block on sample 0 short-circuits straight to `outcome='blocked'`. `name`/
       `flavor`/`rationale`/`motifsExpressed` are never voted (spec SS2) -- sample 0 is therefore
       this candidate's own single, deterministic source for all four throughout, stated once
       here rather than re-decided per field.
    2. Otherwise, majority vote over BOTH `atomFamilies` (canonical set key) and `differentiator`
       (raw value) INDEPENDENTLY (`resolve_vote`, reused, never reimplemented). A 1-1-1 split on
       EITHER field -- or a vote whose WINNING value is that field's own "sample never produced a
       usable answer" sentinel -- writes `outcome='unresolved'` for the WHOLE candidate,
       `entry=None`, and the split field's own `vote.value is None`: **never sample 0's raw pick
       for either field** (binding constraint 4, asserted explicitly by this module's own tests).
    3. On two resolved votes, the final `atomFamilies` is the VOTE's own resolved set, split back
       into a sorted list, and the final `differentiator` is the VOTE's own resolved value --
       never any one sample's raw draft value for either. `motifsExpressed` is NEVER touched by
       either vote -- it stays exactly sample 0's own value, whatever the other two samples wrote.
    """
    if len(drafts) != SAMPLE_COUNT:
        raise ValueError(f"finalize_candidate needs exactly {SAMPLE_COUNT} drafts, got {len(drafts)}")

    brief_id = brief.get("briefId") or brief.get("id")
    prov = dict(provenance or {})

    primary = drafts[0]
    if isinstance(primary, Mapping) and primary.get(BLOCKED_FIELD):
        return Candidate(brief_id=brief_id, outcome="blocked", entry=None, votes=None, provenance=prov)

    atom_samples: "list[list[str] | None]" = []
    differentiator_values: "list[str]" = []
    for draft in drafts:
        families = draft.get("atomFamilies") if isinstance(draft, Mapping) else None
        atom_samples.append(sorted(set(families)) if isinstance(families, list) and families else None)

        differentiator = draft.get("differentiator") if isinstance(draft, Mapping) else None
        differentiator_values.append(differentiator if isinstance(differentiator, str) and differentiator
                                     else _UNRESOLVED_DIFFERENTIATOR_SENTINEL)

    # `atomFamilies` is set-valued -> per-member majority. `differentiator` is a genuine SCALAR and
    # keeps `resolve_vote` unchanged (changed 2026-09-05; see `general_propose.derive` for why the
    # set field needed a different aggregation).
    atom_vote = resolve_set_vote(atom_samples, sample_count=SAMPLE_COUNT)
    differentiator_vote = resolve_vote(differentiator_values)
    votes = {"atomFamilies": atom_vote, "differentiator": differentiator_vote}
    prov["samplePicks"] = atom_samples

    if (atom_vote.confidence == "unresolved"
            or _is_unresolved(differentiator_vote, _UNRESOLVED_DIFFERENTIATOR_SENTINEL)):
        return Candidate(brief_id=brief_id, outcome="unresolved", entry=None, votes=votes, provenance=prov)

    # A-S7 `coverage-assignment` splice (spec-coverage-assignment.md SS6): unions in the brief's
    # own required family, ONLY on an accepted candidate -- deterministic, zero extra model calls,
    # omitted `requiredFamilies` is byte-identical to before this existed.
    atom_families = sorted(set(atom_vote.values) | set(brief.get("requiredFamilies") or ()))
    if pairing_table:
        atom_families = splice_payoff_enablers(
            atom_families, pairing_table=pairing_table,
            allowed_atom_families=brief.get("pool", {}).get("allowedAtomFamilies", ()))
    entry = entry_for(
        {**primary, "atomFamilies": atom_families, "differentiator": differentiator_vote.value},
        candidate_id=candidate_id, brief_id=brief_id, provenance=prov,
    )
    return Candidate(brief_id=brief_id, outcome="accepted", entry=entry, votes=votes, provenance=prov)


def propose_signature_action(brief: Mapping[str, Any], *, candidate_id: str,
                             pairing_table: "Mapping[str, Sequence[str]] | None" = None,
                             family_glossary: "Mapping[str, str] | None" = None,
                             usage_weights: "Mapping[str, int] | None" = None,
                             config: "LlmCallerConfig | None" = None,
                             provenance: "Mapping[str, Any] | None" = None) -> Candidate:
    """The live, one-brief-in-one-candidate-out entry point (spec SS3: "Never carry state between
    calls"). Calls a real model up to `SAMPLE_COUNT * (MAX_HEAL + 1)` times. Never exercised
    directly by this module's own test suite (binding constraint 8) -- every test instead drives
    `sample_draft`'s pure ingredients (`build_context`/`build_brief`) and `finalize_candidate`
    (which makes zero calls) separately.

    `family_glossary` (SMOKE BATCH criterion-2 fix, 2026-09-05): threaded straight to
    `sample_draft` for every one of the `SAMPLE_COUNT` samples -- optional, defaults to `None`.

    `usage_weights` (roster-balance FC3, 2026-09-06): threaded straight to `sample_draft` for
    every sample -- the identical weight table each time, optional, defaults to `None`."""
    drafts: "list[dict]" = []
    heal_notes: "list[dict]" = []
    for sample_index in range(SAMPLE_COUNT):
        draft, soft = sample_draft(brief, sample_index=sample_index, pairing_table=pairing_table,
                                   family_glossary=family_glossary, usage_weights=usage_weights,
                                   config=config)
        drafts.append(draft)
        heal_notes.append(soft)

    prov = dict(provenance or {})
    prov["healNotes"] = heal_notes
    return finalize_candidate(brief, drafts, candidate_id=candidate_id, provenance=prov,
                              pairing_table=pairing_table)


def candidate_row(candidate: Candidate, *, pipeline_id: str = "A-P3", scope: str = "species") -> "dict[str, Any]":
    """The row shape this module WRITES to disk -- deliberately close to
    `family_propose.derive.candidate_row`'s own shape (`candidateId`/`briefId`/`pipelineId`/
    `scope`/`draft`), so a future wiring of A-S4 onto this module's real output is a straight read,
    not a reshape. `scope` defaults to `"species"`, NOT the pipeline's own name -- it must match
    the real `vocab.SCOPES` vocabulary (`{"general","family","species"}`, `ActionEnums.cs`-sourced)
    exactly the way `general_propose`'s own default is `"general"` and `family_propose`'s is
    `"family"`: each pipeline's candidate row tags the SAME scope as the brief it answers, never
    its own pipeline label. A-P3 answers a species-scope brief (A-S2's `p3-briefs.json`, itself
    A-S1's species-scope plan entries plus `familyActions`, byte-identical otherwise) -- found as a
    real defect 2026-09-04 (`mint_action_id` refusing `scope: "signature"` as not real vocabulary,
    the first time A-P3 output ever reached `candidate_assembly` for real); fixed here and in this
    module's own `entry_for` (`prompts.py`). The one real difference from the general/family shape:
    `confidence`/`voteMinority` are each a SMALL DICT keyed
    by field name (`\"atomFamilies\"`/`\"differentiator\"`), never a single scalar -- this stage
    votes TWO fields, and collapsing them into one value would silently throw one away. Both are
    read straight off each field's own `VoteResult`, never invented (binding constraint 4) -- the
    whole dict is `None` exactly when no vote was resolved (a `blocked` candidate makes none)."""
    votes = candidate.votes or {}
    return {
        "candidateId": candidate.entry["candidateId"] if candidate.entry else None,
        "briefId": candidate.brief_id,
        "pipelineId": pipeline_id,
        "scope": scope,
        "outcome": candidate.outcome,
        "confidence": {name: vote.confidence for name, vote in votes.items()} if votes else None,
        "voteMinority": {name: vote.minority for name, vote in votes.items()} if votes else None,
        "draft": candidate.entry,
        "_provenance": candidate.provenance,
    }


def canonical_dump(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"


def candidate_set_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    """A stable digest over a whole round's own candidate rows, ordered by `candidateId` /
    `briefId` (never dict/filesystem iteration order) -- mirrors
    `family_propose.derive.candidate_set_hash`'s identical convention, kept local for the same
    self-containment reason `canonical_family_key` states above."""
    ordered = sorted(rows, key=lambda r: (r.get("candidateId") or "", r.get("briefId") or ""))
    blob = json.dumps(ordered, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
