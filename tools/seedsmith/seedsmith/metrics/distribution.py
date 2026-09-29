"""seedsmith.metrics.distribution — Distribution/CellDeviation, /Evenness, /Inequality
(spec-analytics.md §1; S6, tasks/seedsmith-todo.md).

`ctx.budget` is a `list[budget.BudgetRow]`. A conflicted row (no provenance entry marked
authoritative) blocks its OWN distribution check and reports the conflict instead of a deviation
— spec-budget.md §2: "a target nobody has adjudicated is not a target, and measuring against it
produces confident nonsense." All three metrics here ship `gates=False` for the whole of W1
(spec-numerics.md's calibration discipline, spec-metrics.md §4): nobody can name a correct Pielou
value in advance.
"""
from __future__ import annotations

import math

from .model import Ctx, Finding, Loop, Metric, Severity


def _observed_count(corpus, dimension: str) -> int:
    if dimension.startswith("kind:"):
        kind = dimension.split(":", 1)[1]
        return len(corpus.by_kind(kind))
    if dimension.startswith("role:") and dimension.endswith(":base-type"):
        role = dimension.split(":")[1]
        return sum(1 for e in corpus.by_kind("base-type") if e.get("role") == role)
    raise ValueError(f"do not know how to count observed content for dimension {dimension!r}")


class CellDeviation(Metric):
    """Per-cell deviation — *where* is it wrong (spec-analytics.md §1.1). O(n), actionable, and
    it names the row to fix."""

    id = "Distribution/CellDeviation"
    family = "Distribution"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"corpus", "budget"})
    covers: tuple[str, ...] = ("appendix-a:14",)

    def run(self, ctx: Ctx) -> list[Finding]:
        findings = []
        for row in ctx.budget:
            if row.conflict:
                findings.append(Finding(
                    metric=self.id, severity=Severity.NOTE, subject=row.dimension,
                    message=f"'{row.dimension}' has no authoritative source among "
                            f"{[p.value for p in row.provenance]} — refusing to measure "
                            f"against an unadjudicated target",
                    evidence={"code": "BudgetConflict",
                             "provenance": [p.value for p in row.provenance]}))
                continue

            observed = _observed_count(ctx.corpus, row.dimension)
            if row.target == 0:
                if observed > 0:
                    findings.append(Finding(
                        metric=self.id, severity=Severity.NOTE, subject=row.dimension,
                        message=f"'{row.dimension}' has {observed} entries but no budgeted "
                                f"target — unbudgeted content, not an infinite ratio",
                        evidence={"code": "UnbudgetedCell", "observed": observed}))
                continue

            if not row.tolerance.contains(observed, row.target):
                relative = (observed - row.target) / row.target
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=row.dimension,
                    message=f"'{row.dimension}': observed {observed}, target {row.target} "
                            f"(tolerance -{row.tolerance.under}/+{row.tolerance.over}) — "
                            f"{relative:+.1%}",
                    evidence={"observed": observed, "target": row.target,
                             "derivation": row.derivation.value,
                             "toleranceUnder": row.tolerance.under,
                             "toleranceOver": row.tolerance.over}))
        return findings


def _diversity(counts: "list[int]") -> dict:
    total = sum(counts)
    occupied = [c for c in counts if c > 0]
    richness = len(occupied)

    if total == 0 or richness == 0:
        return {"shannon": None, "pielou": None, "simpson": None, "richness": 0}
    if richness == 1:
        # ln(1) = 0 -> Pielou's J = H/ln(S) is 0/0. One occupied cell is total dominance, so
        # J is defined as 0.0 here rather than raised as a division error.
        return {"shannon": 0.0, "pielou": 0.0, "simpson": 1.0, "richness": 1}

    proportions = [c / total for c in occupied]
    shannon = -sum(p * math.log(p) for p in proportions)
    pielou = shannon / math.log(richness)
    simpson = sum(p * p for p in proportions)
    return {"shannon": shannon, "pielou": pielou, "simpson": simpson, "richness": richness}


class Evenness(Metric):
    """Is the spread healthy at all — Shannon/Pielou/Simpson/richness over one dimension's cell
    counts (spec-analytics.md §1.2). Measure-only for the whole of W1: nobody can name a correct
    Pielou value in advance (spec-budget.md §5)."""

    id = "Distribution/Evenness"
    family = "Distribution"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"corpus", "budget"})
    covers: tuple[str, ...] = ("appendix-a:14",)

    def run(self, ctx: Ctx) -> list[Finding]:
        by_family: "dict[str, list]" = {}
        for row in ctx.budget:
            if row.conflict:
                continue
            family = row.dimension.rsplit(":", 1)[-1] if ":" in row.dimension else row.dimension
            by_family.setdefault(family, []).append(row)

        findings = []
        for family, rows in by_family.items():
            if len(rows) < 2:
                continue  # a "distribution" of one cell has nothing to be even or uneven about
            counts = [_observed_count(ctx.corpus, r.dimension) for r in rows]
            stats = _diversity(counts)
            findings.append(Finding(
                metric=self.id, severity=Severity.NOTE, subject=family,
                message=f"'{family}': Pielou J={stats['pielou']:.3f}, richness="
                        f"{stats['richness']}/{len(rows)} "
                        f"(measure-only — no gating threshold set yet)"
                        if stats["pielou"] is not None else
                        f"'{family}': no content in any of {len(rows)} cells",
                evidence={**stats, "cellCount": len(rows)}))
        return findings


def _gini(counts: "list[int]") -> "float | None":
    n = len(counts)
    total = sum(counts)
    if n == 0 or total == 0:
        return None
    ordered = sorted(counts)
    weighted = sum((2 * i - n - 1) * x for i, x in enumerate(ordered, start=1))
    return weighted / (n * total)


class Inequality(Metric):
    """How concentrated — Gini coefficient over the sorted count vector (spec-analytics.md §1.3).
    Gini and Pielou disagree usefully: Gini reacts to how skewed the TAIL is, Pielou to the
    NUMBER of occupied cells."""

    id = "Distribution/Inequality"
    family = "Distribution"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"corpus", "budget"})
    covers: tuple[str, ...] = ()

    def run(self, ctx: Ctx) -> list[Finding]:
        by_family: "dict[str, list]" = {}
        for row in ctx.budget:
            if row.conflict:
                continue
            family = row.dimension.rsplit(":", 1)[-1] if ":" in row.dimension else row.dimension
            by_family.setdefault(family, []).append(row)

        findings = []
        for family, rows in by_family.items():
            if len(rows) < 2:
                continue
            counts = [_observed_count(ctx.corpus, r.dimension) for r in rows]
            gini = _gini(counts)
            if gini is None:
                continue
            findings.append(Finding(
                metric=self.id, severity=Severity.NOTE, subject=family,
                message=f"'{family}': Gini={gini:.3f} over {len(rows)} cells "
                        f"(measure-only — no gating threshold set yet)",
                evidence={"gini": gini, "cellCount": len(rows)}))
        return findings
