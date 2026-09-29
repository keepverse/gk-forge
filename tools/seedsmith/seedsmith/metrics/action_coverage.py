"""seedsmith.metrics.action_coverage — the thirteen action-corpus coverage metrics (module A-S5,
spec-coverage-report.md §2's register, plus G3 `speciesCoverage` added 2026-09-12). Each metric
reads `ctx.action_coverage`
(`ActionCoverageCtx`, built by the `actions` adapter's own `coverage_report` package) — loading and
composing action-specific JSON is adapter knowledge, not something this generic package should know
how to do, the same split `corpus_coverage.py`'s own docstring states for `creature_dump`.

Every metric class here is a thin wrapper: the real computation lives in
`seedsmith.adapters.actions.coverage_report.derive`, one function per metric, because this
module's algorithm (cell partitioning, quota recomputation, next-round targets, the verdict) is
substantial shared infrastructure several of these metrics need at once — the same reason
`distribution_planner`/`dedup_select` keep their own large `derive.py` rather than inlining
everything into a thinner call site.

Eleven CLOSED, `gates=False` (promotion is a deliberate, later, separate act — `metrics/model.py:8-9`,
`:85`). Two OPEN (`FlavourQualityMetric`, `SemanticNeighbourMetric`) — `gates=False` FOREVER, and
`MetricRegistry.register` raises on `Loop.OPEN` + `gates=True` (`metrics/registry.py:18-21`), so
these two can never be promoted by accident even if someone tries.
"""
from __future__ import annotations

from ..adapters.actions.coverage_report import derive as cr
from .model import Ctx, Finding, Loop, Metric, Severity

_NEEDS = frozenset({"action_coverage"})


class CellOccupancyMetric(Metric):
    id = "action.corpus.cellOccupancy"
    family = "ActionCoverage"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS

    def run(self, ctx: Ctx) -> "list[Finding]":
        return cr.cell_occupancy_findings(self.id, ctx.action_coverage)


class ThinCellMetric(Metric):
    id = "action.corpus.thinCell"
    family = "ActionCoverage"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS

    def run(self, ctx: Ctx) -> "list[Finding]":
        return cr.thin_cell_findings(self.id, ctx.action_coverage)


class QuotaDriftMetric(Metric):
    id = "action.corpus.quotaDrift"
    family = "ActionCoverage"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS

    def run(self, ctx: Ctx) -> "list[Finding]":
        return cr.quota_drift_findings(self.id, ctx.action_coverage)


class EnablerPayoffCoverageMetric(Metric):
    id = "action.corpus.enablerPayoffCoverage"
    family = "ActionCoverage"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS

    def run(self, ctx: Ctx) -> "list[Finding]":
        return cr.enabler_payoff_coverage_findings(self.id, ctx.action_coverage)


class PairingReachMetric(Metric):
    id = "action.corpus.pairingReach"
    family = "ActionCoverage"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS

    def run(self, ctx: Ctx) -> "list[Finding]":
        return cr.pairing_reach_findings(self.id, ctx.action_coverage)


class AtomFamilyNamespaceMetric(Metric):
    id = "action.corpus.atomFamilyNamespace"
    family = "ActionCoverage"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS

    def run(self, ctx: Ctx) -> "list[Finding]":
        return cr.atom_family_namespace_findings(self.id, ctx.action_coverage)


class SpeciesCollisionMetric(Metric):
    id = "action.corpus.speciesCollision"
    family = "ActionCoverage"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS

    def run(self, ctx: Ctx) -> "list[Finding]":
        return cr.species_collision_findings(self.id, ctx.action_coverage)


class SpeciesCoverageMetric(Metric):
    """G3 (2026-09-12): the per-SUBJECT coverage gate the scope-aggregate cells are blind to. A
    scope cell (`cell.species.attack.1-10`) can pass while hundreds of species hold nothing; this
    metric asserts every planned species subject has at least one accepted row."""
    id = "action.corpus.speciesCoverage"
    family = "ActionCoverage"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS

    def run(self, ctx: Ctx) -> "list[Finding]":
        return cr.species_coverage_findings(self.id, ctx.action_coverage)


class SingletonShareMetric(Metric):
    id = "action.corpus.singletonShare"
    family = "ActionCoverage"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS

    def run(self, ctx: Ctx) -> "list[Finding]":
        return cr.singleton_share_findings(self.id, ctx.action_coverage)


class StructureEnforceabilityMetric(Metric):
    id = "action.corpus.structureEnforceability"
    family = "ActionCoverage"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS

    def run(self, ctx: Ctx) -> "list[Finding]":
        return cr.structure_enforceability_findings(self.id, ctx.action_coverage)


class RosterReconciliationMetric(Metric):
    id = "action.corpus.rosterReconciliation"
    family = "ActionCoverage"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS

    def run(self, ctx: Ctx) -> "list[Finding]":
        cov = ctx.action_coverage
        return cr.roster_reconciliation_findings(
            self.id, cov.roster, len(cov.accepted_rows), cov.per_species_count)


class FlavourQualityMetric(Metric):
    id = "action.corpus.flavourQuality"
    family = "ActionCoverage"
    loop = Loop.OPEN
    gates = False
    needs = _NEEDS

    def run(self, ctx: Ctx) -> "list[Finding]":
        return cr.flavour_quality_findings(self.id, ctx.action_coverage)


class SemanticNeighbourMetric(Metric):
    id = "action.corpus.semanticNeighbour"
    family = "ActionCoverage"
    loop = Loop.OPEN
    gates = False
    needs = _NEEDS

    def run(self, ctx: Ctx) -> "list[Finding]":
        return cr.semantic_neighbour_findings(self.id, ctx.action_coverage)


# CLOSED first, then OPEN — matches spec §2's register table order. `generate_coverage_report.py`
# runs the CLOSED eleven through the normal registry/verdict path and the OPEN two into a
# review-queue-only pass (spec §3 step 4) — never through the same "did this gate" computation.
ALL_ACTION_COVERAGE_CLOSED_METRICS: "tuple[type[Metric], ...]" = (
    CellOccupancyMetric, ThinCellMetric, QuotaDriftMetric, EnablerPayoffCoverageMetric,
    PairingReachMetric, AtomFamilyNamespaceMetric, SpeciesCollisionMetric, SpeciesCoverageMetric,
    SingletonShareMetric, StructureEnforceabilityMetric, RosterReconciliationMetric,
)
ALL_ACTION_COVERAGE_OPEN_METRICS: "tuple[type[Metric], ...]" = (
    FlavourQualityMetric, SemanticNeighbourMetric,
)
ALL_ACTION_COVERAGE_METRICS: "tuple[type[Metric], ...]" = (
    ALL_ACTION_COVERAGE_CLOSED_METRICS + ALL_ACTION_COVERAGE_OPEN_METRICS
)
