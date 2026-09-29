"""seedsmith.adapters.trees.species.generate_favour_fit — the favour-fit STAGE's own resolution
function (task J8, spec-species-tree.md §3.1 step 3). §3.1's own four steps, restated against this
function's real inputs: step 1 (`species.plan.assign_favour_cells`'s quota) and step 2 (the same
call's per-species cell + alternates) already happened before this function is ever called; THIS
function is step 3 — "the call receives ONE cell, its alternates, and the species' own lore, and
answers ONE question: does this favour fit, and if not, which of these alternates does?"

**One graph PER SPECIES, not one shared graph** — a real, structural difference from
`generate_codex.resolve_codex_summaries`'s own shared-graph shape. The codex-summary schema is
IDENTICAL for every species (free text, same max length); the favour-fit schema's own `enum` is
built FRESH per species from THAT species' own alternates (`schemas.favour_fit_schema`, gate 8's
own per-call discipline) — two species never share an enum, so they can never share a graph either.
3-way voted via `resolve_vote` over the small `choice` enum (`"offered"` / an alternate key /
`"none"`) — the SAME machinery every other voted scalar field in this program already uses.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from ....pipeline.llm_caller import LlmCallerConfig
from ....workflow.runner import MAX_WORKERS
from .plan import FavourCell
from .roster import SpeciesAnchor

SAMPLES_PER_SPECIES = 3


def resolve_favour_fit(
    species: "Sequence[tuple[str, SpeciesAnchor, FavourCell, Sequence[FavourCell]]]", *,
    provenance_base: "Mapping[str, Any]",
    call: "Callable[..., str] | None" = None,
    config: LlmCallerConfig | None = None,
    workers: int = MAX_WORKERS,
) -> "tuple[dict[str, dict], dict[str, dict], dict[str, dict]]":
    """`species` is `(speciesId, anchor, offeredCell, alternates)` tuples — the caller's own
    already-resolved roster + `assign_favour_cells` join, never re-derived here.

    Returns `(fresh, unresolved, results)`:

    * `fresh` — `{speciesId: {"cell": FavourCell, "choice": str, "_provenance": {...}}}`. `cell` is
      the RESOLVED `FavourCell` object (the offered one, or the winning alternate) — never a bare
      string a caller would have to re-look-up, since the caller already handed this function the
      exact `FavourCell` instances it is choosing among.
    * `unresolved` — `{speciesId: {"reason": ..., ...}}`: `"vote_unresolved"` (1-1-1),
      `"insufficient_valid_samples"` (fewer than `SAMPLES_PER_SPECIES` samples ever validated), or
      `"none_of_the_offered_favours_fit"` — the vote resolved to the literal `"none"` answer, which
      §3.1 step 3 names as a LEGITIMATE outcome, never a failure: this species' favour lock could
      not be assigned from its own offered options and belongs in the review queue as `unresolved`
      (spec-species-tree.md §3.1/§4's own success criterion — the SAME `unresolved` concept
      `UnresolvedCountMetric`'s own `mechanicalFavour` subject, task J5, already gates on).
    * `results` — the per-sample-state graph outcome, keyed by the sample's own subject id, pooled
      across every species this call resolved (never just the last one).
    """
    from ....workflow.graphs.species_favour_fit import (
        build_species_favour_fit_graph,
        state_for_species_favour_fit,
    )
    from ....workflow.runner import run_many
    from ...creatures.anchor.vote import resolve_vote

    fresh: "dict[str, dict]" = {}
    unresolved: "dict[str, dict]" = {}
    all_results: "dict[str, dict]" = {}

    for species_id, anchor, offered, alternates in species:
        alternates = list(alternates)
        alt_keys = [a.key() for a in alternates]
        cell_by_key = {offered.key(): offered, **{a.key(): a for a in alternates}}

        persisted: "dict[str, dict]" = {}
        app = build_species_favour_fit_graph(
            alternate_keys=alt_keys, on_persist=lambda k, v: persisted.__setitem__(k, v),
            config=config, call=call)

        sample_ids: "list[str]" = []
        states: "list[dict]" = []
        for sample_index in range(SAMPLES_PER_SPECIES):
            subject_id = f"{species_id}-favour-sample-{sample_index}"
            states.append(state_for_species_favour_fit(subject_id, anchor, offered, alternates))
            sample_ids.append(subject_id)

        results = run_many(app, states, max_workers=workers)
        all_results.update(results)

        samples = [
            persisted[sid] for sid in sample_ids
            if sid in persisted and isinstance(persisted[sid], dict) and "choice" in persisted[sid]
        ]
        if len(samples) != SAMPLES_PER_SPECIES:
            unresolved[species_id] = {
                "reason": "insufficient_valid_samples",
                "validSamples": len(samples), "samplesExpected": SAMPLES_PER_SPECIES,
            }
            continue

        vote = resolve_vote([s.get("choice", "") for s in samples])
        if vote.value is None:
            unresolved[species_id] = {"reason": "vote_unresolved", "confidence": vote.confidence}
            continue

        if vote.value == "none":
            unresolved[species_id] = {
                "reason": "none_of_the_offered_favours_fit", "confidence": vote.confidence}
            continue

        resolved_key = offered.key() if vote.value == "offered" else vote.value
        if resolved_key not in cell_by_key:
            # Structurally unreachable given the schema's own enum -- never trusted silently.
            unresolved[species_id] = {"reason": "resolved_choice_not_a_real_cell", "choice": vote.value}
            continue

        provenance = dict(provenance_base)
        provenance["voteConfidence"] = vote.confidence
        if vote.minority:
            provenance["voteMinority"] = vote.minority
        fresh[species_id] = {
            "cell": cell_by_key[resolved_key], "choice": vote.value, "_provenance": provenance}

    return fresh, unresolved, all_results
