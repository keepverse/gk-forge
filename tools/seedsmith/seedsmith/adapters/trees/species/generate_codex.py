"""seedsmith.adapters.trees.species.generate_codex — the codex-summary STAGE's own resolution
function (task J8, spec-species-tree.md §6, §7.1). Its sibling stage,
`species.generate_favour_fit` (§3.1 step 3), is the SAME shape in a separate file — one file per
stage, matching `adapters.effects.affix`'s own one-file-per-pipeline convention. Pure
result-producing, no persistence: matching
`species/plan.py`'s own scope discipline (a DETERMINISTIC half exists with no file writer of its
own), this module is the MODEL-CALLING half with the identical property — it returns results in
memory and never decides where a committed per-species seed file lives, because that file does not
exist yet. `gk-data/packs/fusion/data/seed/passive-tree/species/<speciesId>.json` (spec's own Project structure table:
"THE SEED — enums + prose + codexSummary") is written ALONGSIDE a species tree's own generated
nodes, by the still-unbuilt full orchestration this task (J8) also owns — building a throwaway
output path for this stage alone, ahead of that real writer, would just be work to redo.

3-way voted via similarity-clustered resolution (`resolve_codex_vote` below) — the `vote` module's
own shape, with the clustering rung `nodegen.dedup` already calibrates at corpus scale. It replaced
EXACT-MATCH `resolve_vote` after a real 2-species run (2026-09-21) measured that resolving **0 of 2**;
the samples' own Jaccard figures are recorded in `resolve_codex_vote`'s docstring. Whether three
independently-generated sentences converge often enough in practice was exactly the kind of thing
the real run (J9) was to measure — it has now measured it. Never assumed here either way.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from ....pipeline.llm_caller import LlmCallerConfig
from ....workflow.runner import MAX_WORKERS
from .plan import FavourCell
from .roster import SpeciesAnchor

SAMPLES_PER_SPECIES = 3

#: Reused verbatim from `nodegen.dedup`'s own calibrated rung (the same threshold the tree
#: near-duplicate metric already gates on at corpus scale), never a second number invented for this
#: stage -- this program's own "reuse the shared primitive, never fork it" rule.
CODEX_VOTE_SIMILARITY_PERMILLE = 600

#: The batch driver's own default bound on codex-vote draws per species (task J9-B2, 2026-09-21).
#: One draw is a 3-sample vote; the vote resolves STOCHASTICALLY -- BCU2.12's bounded re-proof
#: measured roughly one resolve per draw over two species and four draws (evidence
#: `tasks/reports/BCU2.12-proof-20260921.json`), and the resume pass inverted the two species exactly.
#: A roster therefore needs more than one draw to converge, and an unbounded loop would hide a bad
#: prompt behind retries rather than reporting it.
#:
#: With `r` the per-draw resolve probability, the expected number of 3-sample draws per species is
#: `(1 - r**A) / (1 - r)`: at r~=0.5 that is 1.75 draws at A=3, 1.94 at A=5, 1.97 at A=6, 2.0 as A
#: grows. So draws past ~3 buy tail coverage almost for free, while the WORST case stays bounded at
#: `A` draws (`3A` calls, against the 120 node calls one species already costs). 6 is the smallest
#: round bound here that leaves under ~2 % of a roster unresolved at r~=0.5; the driver exposes it as
#: `--codex-attempts`, so it is a stated policy, never a hidden constant.
DEFAULT_CODEX_VOTE_ATTEMPTS = 6


def _clusters(values: "Sequence[str]", *, threshold_permille: int) -> "list[list[int]]":
    """Single-linkage clusters of sample INDICES, two samples joined when their exact Jaccard is at
    least `threshold_permille`. Deterministic: the result depends only on the sample texts."""
    from ..nodegen.dedup import exact_jaccard_permille

    clusters: "list[list[int]]" = []
    for index in range(len(values)):
        for cluster in clusters:
            if any(exact_jaccard_permille(values[index], values[other]) >= threshold_permille
                   for other in cluster):
                cluster.append(index)
                break
        else:
            clusters.append([index])
    return clusters


def resolve_codex_vote(values: "Sequence[str]", *,
                       threshold_permille: int = CODEX_VOTE_SIMILARITY_PERMILLE,
                       ) -> "tuple[str | None, str, str | None]":
    """`(value, confidence, minority)` for one species' three codex sentences.

    **Why not the plain exact-match `resolve_vote` (measured 2026-09-21, J9-B1(a), a real bounded run
    of two species against `google/gemma-4-26b-a4b-qat`):** three independent generations of a free
    sentence essentially never coincide byte-for-byte, so the exact-match vote resolved **0 of 2**
    species and every species metadata file (`species/<speciesId>.json`, J8's own deliverable) would
    have been withheld from the whole 840-species run. The samples' own exact-Jaccard pairs:
    `AbyssSwordStar` 717/601/**858**‰ ("relentless, seeking blades... paralyzed with dread" vs
    "...stumbling in a daze" vs "...stumbling in a daze" without "relentless,"), `AcientSunNut`
    287/**489**/369‰. This is the SAME machinery mismatch `resolve_set_vote`'s own docstring already
    records being fixed for a different multi-member field ("~90% unresolved" on a real run).

    So resolution is single-linkage clustering at `nodegen.dedup`'s own 600‰ rung: the largest cluster
    of two or more wins, its FIRST sample (in sample order) is returned **verbatim** -- never a
    synthesized sentence, the same contract `resolve_vote` holds -- and a sample outside the winning
    cluster is recorded as `minority`. A genuine three-way disagreement (AcientSunNut's best pair is
    489‰, below the rung) stays honestly `unresolved`; the threshold is not lowered to force it.
    """
    clusters = _clusters(list(values), threshold_permille=threshold_permille)
    largest = max(clusters, key=len)
    if len(largest) < 2:
        return None, "unresolved", None
    minority = next((values[i] for i in range(len(values)) if i not in largest), None)
    return values[largest[0]], ("high" if len(largest) == len(values) else "split"), minority


def resolve_codex_summaries(
    species: "Sequence[tuple[str, SpeciesAnchor, FavourCell]]", *,
    provenance_base: "Mapping[str, Any]",
    call: "Callable[..., str] | None" = None,
    config: LlmCallerConfig | None = None,
    workers: int = MAX_WORKERS,
) -> "tuple[dict[str, dict], dict[str, dict], dict[str, dict]]":
    """`species` is `(speciesId, anchor, favourCell)` triples — the caller's own already-resolved
    roster+favour-lock join, never re-derived here (this module owns the model call, not the
    upstream data). Returns `(fresh, unresolved, results)`:

    * `fresh` — `{speciesId: {"codexSummary": str, "_provenance": {...}}}`, one entry per species
      whose vote resolved (3-0 or 2-1). A resolved value can never itself carry a content defect:
      `codex_summary_content_is_clean` (`workflow/graphs/species_codex.py`) already gates every
      SAMPLE that reaches `persisted` on the identical `codex_summary_defects` check this module
      would otherwise repeat post-vote, and the vote only ever returns one of the samples it
      was given verbatim — never a synthesized value — so a validator-clean input set makes a
      dirty RESOLVED value a logical impossibility, not merely an untested case. (Caught while
      writing this module's own tests: an earlier draft re-checked the resolved value anyway and
      the "content defect survives the vote" test could not be made to fail without disabling the
      validator, proving the branch it was testing was dead code, not an untested one — removed.)
    * `unresolved` — `{speciesId: {"reason": ..., ...}}`: `"vote_unresolved"` (1-1-1) or
      `"insufficient_valid_samples"` (fewer than `SAMPLES_PER_SPECIES` samples ever validated —
      this is where a persistently numeric/jargon-laden brief shows up, since the validator repairs
      or drops those samples before they ever reach a vote).
    * `results` — the per-sample-state graph outcome, keyed by the sample's own subject id.
    """
    from ....workflow.graphs.species_codex import build_species_codex_graph, state_for_species_codex
    from ....workflow.runner import run_many

    persisted: "dict[str, dict]" = {}
    app = build_species_codex_graph(
        on_persist=lambda k, v: persisted.__setitem__(k, v), config=config, call=call)

    species_samples: "dict[str, list[str]]" = {}
    states: "list[dict]" = []
    for species_id, anchor, favour in species:
        sample_ids: "list[str]" = []
        for sample_index in range(SAMPLES_PER_SPECIES):
            # A permuted seed per sample, seeded on speciesId|sample_index -- consistent with
            # every other voted stage in this program, even though this brief has no OPTION LIST
            # to permute; `order_for` is not called here for exactly that reason (nothing to
            # shuffle), and the vote's own three independent samples are what "votes", not a
            # permutation of a fixed option order.
            subject_id = f"{species_id}-codex-sample-{sample_index}"
            state = state_for_species_codex(subject_id, anchor, favour)
            states.append(state)
            sample_ids.append(subject_id)
        species_samples[species_id] = sample_ids

    results = run_many(app, states, max_workers=workers)

    fresh: "dict[str, dict]" = {}
    unresolved: "dict[str, dict]" = {}
    for species_id, sample_ids in species_samples.items():
        samples = [
            persisted[sid] for sid in sample_ids
            if sid in persisted and isinstance(persisted[sid], dict) and "codexSummary" in persisted[sid]
        ]
        if len(samples) != SAMPLES_PER_SPECIES:
            unresolved[species_id] = {
                "reason": "insufficient_valid_samples",
                "validSamples": len(samples), "samplesExpected": SAMPLES_PER_SPECIES,
            }
            continue

        vote_value, vote_confidence, vote_minority = resolve_codex_vote(
            [s.get("codexSummary", "") for s in samples])
        if vote_value is None:
            unresolved[species_id] = {"reason": "vote_unresolved", "confidence": vote_confidence}
            continue

        provenance = dict(provenance_base)
        provenance["voteConfidence"] = vote_confidence
        if vote_minority:
            provenance["voteMinority"] = vote_minority
        fresh[species_id] = {"codexSummary": vote_value, "_provenance": provenance}

    return fresh, unresolved, results
