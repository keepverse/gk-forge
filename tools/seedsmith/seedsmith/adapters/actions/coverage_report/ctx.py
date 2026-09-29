"""seedsmith.adapters.actions.coverage_report.ctx — `ActionCoverageCtx`, the bundle the thirteen
action-coverage metrics (`seedsmith/metrics/action_coverage.py`) read from `Ctx.action_coverage`
(A-S5, spec-coverage-report.md §2).

Lives beside `derive.py` rather than inside `metrics/`, same split `adapters/creatures/dump_ctx.py`'s
own docstring states: loading and composing action-specific JSON is adapter knowledge, not
something the generic `metrics` package should know how to do. This module holds only the plain
data bundle — no I/O. The real-file loader lives in the sibling entrypoint
`../generate_coverage_report.py` (`build_ctx_from_real_files`), matching every other module in this
adapter family: `derive.py`/`ctx.py` are pure, the entrypoint is the one place that touches disk.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass(frozen=True)
class RosterCounts:
    """The live roster, measured from the creature seed folder. `family_count` is every family id
    with at least one assigned member; `family_assigned_count` is the sum of member counts across
    those families (a species may belong to more than one family, so this can exceed
    `species_count`'s own share that has a family at all — the same distinction
    `generate_distribution_planner.py`'s own `familyAssignedSpeciesCount` summary field draws)."""
    species_count: int
    family_count: int
    family_assigned_count: int


@dataclass(frozen=True)
class ActionCoverageCtx:
    """Everything the thirteen metrics in `metrics/action_coverage.py` read. Built once per report
    run (real or synthetic) and handed to every metric via `Ctx.action_coverage` — the same
    "load once, hand to every metric" shape `CreatureDumpCtx` already established for T1.10.

    `accepted_rows`: the corpus this report measures — A-S3's survivors plus whatever is already
    committed under `gk-data/packs/fusion/data/seed/actions/` (A-C1's own load). A partial smoke corpus is legal while
    the model stages are being proven — every metric below must degrade to an honest,
    non-alarming empty report rather than a spurious wall of GAP findings, and the coverage-report
    algorithm's own quota-vs-zero handling (mirroring `metrics/distribution.py:CellDeviation`'s
    "target == 0" branch) is what keeps that true.

    `quota_by_scope_category` / `subject_category_counts`: both re-derived by THIS module (spec §3
    step 2 — "recompute the quota independently"), never read from a stored A-S1 answer.
    `subject_category_counts` keeps the PER-SUBJECT breakdown (`(scope, scopeKeyOrGeneral) ->
    {category: count}`) that `quota_by_scope_category` alone loses by summing across subjects —
    the per-subject numbers are what next-round target derivation (spec §3 step 5) needs to name
    which subject is short, not just which scope/category is.

    `family_ids`: the live authored atom-family namespace (`vocab.load_family_ids`), read fresh.
    `pairing_table`: `pairings.json`, read-only, never rewritten by this module (spec §4). `None`
    means the file was not available this run — `enablerPayoffCoverage`/`pairingReach` report
    NOT_MEASURED rather than a false "zero reach" (`metrics/model.py:34`'s own discipline: a metric
    whose needs are unmet is never silently a pass, and never a false GAP either).
    `review_rows`: A-S3's tier-3 `review-queue.json` entries, if a round wrote one — feeds
    `semanticNeighbour` (OPEN). Empty by default: no round has run A-S3 for real yet.
    """
    accepted_rows: "tuple[Mapping[str, object], ...]"
    quota_by_scope_category: "Mapping[tuple[str, str], int]"
    subject_category_counts: "Mapping[tuple[str, str], Mapping[str, int]]"
    family_ids: "frozenset[str]"
    pairing_table: "Mapping[str, tuple[str, ...]] | None"
    roster: RosterCounts
    scope_windows: "Mapping[str, tuple[int, int]]"    # ST3: the loaded per-scope rung windows --
                                                      # `build_cell_groups`/`next_round_targets` read
                                                      # these, never a code literal. The entrypoint
                                                      # loads them once (`load_scope_windows`).
    review_rows: "tuple[Mapping[str, object], ...]" = field(default_factory=tuple)
    round_no: int = 1
    mode: str = "smoke"
    tuning_version: int = 1               # action-corpus-run.v1.json's own `version` — acceptance
                                          # #8's "provenance recording... the tuning version"
    per_species_count: int = 3            # compatibility default for pure synthetic fixtures
