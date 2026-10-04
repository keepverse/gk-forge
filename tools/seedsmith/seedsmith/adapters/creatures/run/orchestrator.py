"""Ties `machine.py`/`selectors.py` to the eight `classify-pipelines` graphs into one
species-at-a-time run (creature-seed module 9, spec-run-control.md §1-2), permuting every
enum-bearing pipeline and majority-voting the five load-bearing fields
(spec-option-permutation.md — module 6, Q8/Q25).

**Pause is checked only BETWEEN species, never mid-species** (§2's explicit warning: "a species
half-classified across eight pipelines is not a resumable unit... an anchor with four fields from
before the pause and four from after, with two different prompt versions in one entry").

Found live (2026-09-02, a real 3-species proof run): `permute.py`/`vote.py` existed, fully tested,
with ZERO real callers anywhere in the codebase — every classification was a single unpermuted
sample, exactly the label/position-bias failure mode module 6 exists to prevent. This module is
now that caller.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from ..anchor.prompts import PIPELINES, SpeciesLore
from ..anchor.permute import order_for
from ..anchor.schema import APTITUDES, ATTACK_TEMPO, DEPLOY_MODE, ELEMENTS, RARITY, THREAT_BAND
from ..anchor.vote import VOTED_FIELDS, resolve_vote
from ....pipeline.llm_caller import LlmCallerConfig
from ....workflow.graphs.creature_anchor import build_pipeline_graph, state_for_pipeline

#: The one field, and its vocabulary, that each pipeline's `build_brief` can render in a shuffled
#: order via `context["order"]` — established by reading every brief function in `prompts.py`
#: (only these actually consume that key). `kit-shape` has none: it asks for FOUR independent
#: fields at once with no single dominant enum listing, and none of its four is in `VOTED_FIELDS`.
_PERMUTABLE_FIELD: "dict[str, tuple[str, tuple[str, ...]]]" = {
    "element-primary": ("elementPrimary", ELEMENTS),
    "element-secondary": ("elementSecondary", ELEMENTS),
    "aptitude-primary": ("aptitudePrimary", APTITUDES),
    "aptitude-secondary": ("aptitudeSecondary", APTITUDES),
    "identity": ("rarity", RARITY),
    "deployment": ("deployMode", DEPLOY_MODE),
    # creature-corpus-self-heal C1 (2026-09-04): kit-shape decides FOUR attributes
    # (attackTempo/reach/targetPreference/resourceProfile) but only attackTempo gets voted here —
    # the one the real 833-species audit actually found collapsed (entropy 0.00, 1/5 values used).
    # reach/targetPreference/resourceProfile stay sample-0-only, same as identity's own
    # traits/variants/family — a deliberate, named scope call (plan's own risk table), not a
    # silent omission.
    "kit-shape": ("attackTempo", ATTACK_TEMPO),
}


def _permutable_field(pipeline_id: str, basis: str) -> "tuple[str, tuple[str, ...]] | None":
    """`threat-audit` is basis-conditional: for `observed`/`stated` the rung is a deterministic
    computed value the model AUDITS (never chooses — Q16, "number wins"), so there is nothing to
    permute or vote on; only the `inferred`/`blocked` variant genuinely picks a rung from lore."""
    if pipeline_id == "threat-audit":
        return ("threatBand", THREAT_BAND) if basis in ("inferred", "blocked") else None
    return _PERMUTABLE_FIELD.get(pipeline_id)


#: What a declared attribute the model never answered is written as. One honest spelling of "no
#: answer came back" — the same string the vote path already writes for a split it could not resolve
#: (`draft[field_name] = vote.value ... else "unresolved"`), and the same one
#: `anchor/emit.py` documents as the rule ("a missing key must not mean 'unsure'").
#:
#: Measured 2026-10-04 against the real corpus: 280 entries were missing an attribute its own
#: pipeline had RUN — 84 `aptitudeSecondary`, 88 `elementSecondary`, and 54 each of `reach` and
#: `targetPreference`, every one of them on an entry whose `_provenance.attempts` recorded the
#: owning pipeline at the current prompt version. Nothing dropped them: the merge loop below folds in
#: whatever keys the draft happens to carry, so a reply that omitted a `required` key produced an
#: entry with the key simply ABSENT. Two of those fields (`reach`, `targetPreference`) are required
#: by the C# anchor reader, so the absence is not cosmetic — the whole C# tool exits 1 on the first
#: such entry and abandons the load.
#:
#: Before this, an omission was invisible in the only place anyone would have looked: `_provenance`
#: recorded `attempts: 1` and a `confidence` entry, both of which read like a completed judgement.
NO_ANSWER = "unresolved"


def _fill_unanswered(draft: "dict[str, Any]", attributes: "tuple[str, ...]") -> "dict[str, Any]":
    """Every declared attribute the draft omitted becomes an explicit `NO_ANSWER`.

    The keys it adds are the pipeline's OWN declared `attributes`, read from the same `PipelineSpec`
    whose per-call JSON Schema marks them `required` — so this cannot invent a field, and it cannot
    drift from the spec: rename an attribute and this follows. `blocked` is untouched (the merge loop
    drops it), as is any attribute the draft did answer.
    """
    for attribute in attributes:
        if attribute not in draft:
            draft[attribute] = NO_ANSWER
    return draft


def _invoke(
    pipeline_id: str, lore: SpeciesLore, *, basis: str, context: "dict[str, Any]",
    field_order: "tuple[str, ...] | None", call: "Callable[..., str] | None", config: LlmCallerConfig,
) -> "dict[str, Any]":
    ctx = dict(context)
    if field_order is not None:
        ctx["order"] = list(field_order)
    graph = build_pipeline_graph(pipeline_id, basis=basis, call=call, config=config)
    state = state_for_pipeline(pipeline_id, lore, context=ctx, basis=basis)
    return graph.invoke(state)


def run_one_species(
    species_id: str, lore: SpeciesLore, *, basis: str,
    threat_rung: "tuple[str, int] | None" = None,
    call: "Callable[..., str] | None" = None,
    config: LlmCallerConfig | None = None,
    pipelines: "Sequence[str] | None" = None,
    initial_context: "dict[str, Any] | None" = None,
) -> "dict[str, Any]":
    """Runs all eight pipelines for one species, sequentially — each pipeline's decided fields
    feed forward into the next's `context` (posture-resource/element-distinct need the
    already-decided upstream values). Returns the merged field dict plus per-pipeline outcomes.

    Every pipeline with a permutable field (`_PERMUTABLE_FIELD` / basis-conditional threat-audit)
    gets a deterministic per-(species, field, sample) shuffled option order (spec-option-
    permutation.md §3) — never the schema's declaration order twice in a row for the same field.
    The five `VOTED_FIELDS` additionally run THREE samples and take the majority
    (`vote.resolve_vote`) — a 3-0 is `confidence: high`, a 2-1 is `split` with the minority
    recorded, and a 1-1-1 resolves to `"unresolved"`, never silently the first sample. The
    pipeline's OTHER (non-voted) attributes, and its recorded outcome, come from sample 0 — the
    three vote samples ARE the pipeline's calls for that species, not three calls on top of one
    (spec §6's own budget: 8 base calls/species + 2 EXTRA per voted field, not 3 extra).

    `threat_rung` is `(rung_id, rung_ordinal)` from `threat-band.classify()` — required when
    `basis` is `observed`/`stated` (the `threat-audit` pipeline shows a rung name, never a
    number, per spec-classify-pipelines.md §3) and irrelevant when `basis` is `inferred`/
    `blocked` (that variant chooses the rung from lore instead and needs no computed input).

    `pipelines` (creature-corpus-self-heal B1, 2026-09-04): when given, runs only THIS subset instead
    of all eight — the mechanism a fixed prompt redeploys through without paying for a full
    8-pipeline reclassification of species that already have 7 perfectly good judgments.
    `initial_context` MUST be supplied whenever `pipelines` narrows the set below "everything from
    the start" — a validator downstream of an omitted pipeline still needs its real decided value
    (e.g. `kit-shape`'s own `posture_resource` validator reads `context["aptitudePrimary"]`, which
    only a full run's own earlier `aptitude-primary` pipeline would otherwise have set). Seeding it
    from the species' EXISTING anchor is the caller's job (`runner.py`), not this function's — this
    module has no notion of "existing anchor," only of what one classification pass computes.
    """
    context: "dict[str, Any]" = dict(initial_context or {})
    if basis in ("observed", "stated"):
        if threat_rung is None:
            raise ValueError(
                f"species {species_id!r} has basis={basis!r} but no threat_rung was supplied — "
                f"threat-audit needs the rung threat-band already computed")
        context["rungId"], context["rungOrdinal"] = threat_rung

    merged: "dict[str, Any]" = {}
    outcomes: "dict[str, str]" = {}
    votes: "dict[str, Any]" = {}
    pipeline_attempts: "dict[str, int]" = {}
    calls_made = 0
    for pipeline_id in (pipelines if pipelines is not None else PIPELINES):
        perm = _permutable_field(pipeline_id, basis)
        voted_field = perm[0] if perm and perm[0] in VOTED_FIELDS else None

        if voted_field is None:
            field_order = order_for(species_id, perm[0], 0, list(perm[1])) if perm else None
            result = _invoke(pipeline_id, lore, basis=basis, context=context,
                             field_order=field_order, call=call, config=config)
            outcomes[pipeline_id] = result.get("outcome", "escalated")
            pipeline_attempts[pipeline_id] = int(result.get("attempts", 1))
            calls_made += pipeline_attempts[pipeline_id]  # repair rounds are real calls too
            draft = _fill_unanswered(
                dict(result.get("draft") or {}), PIPELINES[pipeline_id].attributes)
        else:
            field_name, vocab = perm
            samples: "list[str]" = []
            primary_draft: "dict[str, Any] | None" = None
            primary_outcome = "escalated"
            primary_attempts = 1
            for sample_index in range(3):
                field_order = order_for(species_id, field_name, sample_index, list(vocab))
                result = _invoke(pipeline_id, lore, basis=basis, context=context,
                                 field_order=field_order, call=call, config=config)
                draft = result.get("draft") or {}
                samples.append(draft.get(field_name) or "")
                calls_made += int(result.get("attempts", 1))
                if sample_index == 0:
                    primary_draft = dict(draft)
                    primary_outcome = result.get("outcome", "escalated")
                    primary_attempts = int(result.get("attempts", 1))
            outcomes[pipeline_id] = primary_outcome
            pipeline_attempts[pipeline_id] = primary_attempts  # sample 0's — matches its outcome/draft
            vote = resolve_vote(samples)
            votes[field_name] = vote
            draft = _fill_unanswered(
                dict(primary_draft or {}), PIPELINES[pipeline_id].attributes)
            draft[field_name] = vote.value if vote.value is not None else NO_ANSWER

        for key, value in draft.items():
            if key == "blocked":
                continue
            merged[key] = value
            context[key] = value

    merged["_pipelineOutcomes"] = outcomes
    merged["_pipelineAttempts"] = pipeline_attempts
    merged["_votes"] = {
        field: {"confidence": v.confidence, "minority": v.minority} for field, v in votes.items()
    }
    merged["_callsMade"] = calls_made
    return merged


def run_selection(
    species_ids: "list[str]",
    lore_by_id: "Mapping[str, SpeciesLore]",
    basis_by_id: "Mapping[str, str]",
    *,
    threat_rungs_by_id: "Mapping[str, tuple[str, int]] | None" = None,
    call: "Callable[..., str] | None" = None,
    config: LlmCallerConfig | None = None,
    should_pause: "Callable[[], bool]" = lambda: False,
) -> "dict[str, Any]":
    """Iterates `species_ids` IN ORDER. `should_pause()` is polled only between species — a
    species that has already started its eight pipelines always finishes them before the run can
    stop. Resuming a paused run is simply calling this again with the remaining ids (the ones not
    already in a prior call's `completed` list) — the already-finished species are never
    re-touched, so a pause-then-resume cycle makes zero additional calls for work already done."""
    threat_rungs = threat_rungs_by_id or {}
    completed: "list[str]" = []
    results: "dict[str, dict]" = {}
    for species_id in species_ids:
        if should_pause():
            return {"completed": completed, "results": results, "paused": True}
        results[species_id] = run_one_species(
            species_id, lore_by_id[species_id], basis=basis_by_id.get(species_id, "blocked"),
            threat_rung=threat_rungs.get(species_id), call=call, config=config)
        completed.append(species_id)
    return {"completed": completed, "results": results, "paused": False}
