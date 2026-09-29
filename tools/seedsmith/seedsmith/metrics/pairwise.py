"""seedsmith.metrics.pairwise — Coverage/PairwiseHole (spec-analytics.md §2.2).

Content lives in a cross-product of dimensions; full cartesian coverage is neither achievable nor
desirable, so the target is pairwise (2-way) coverage: every legal pair of values from every pair
of dimensions should co-occur at least once. `legal_combinations()` is what keeps this from
flooding with false holes for pairs that are simply impossible — `ward-array` under a hybrid frame
is not missing content, it is content that cannot exist (adapters.items.registries).

Only checked for a dimension pair when at least one kind carries BOTH fields on the same entry —
a dimension pair with no common kind (rarity only lives on `unique`, element only on
`gem`/`material`/`consumable`) has nothing to co-occur, and is silently skipped rather than
reported as 100% missing, which would be noise, not a finding.
"""
from __future__ import annotations

from itertools import combinations

from .model import Ctx, Finding, Loop, Metric, Severity


class PairwiseHole(Metric):
    id = "Coverage/PairwiseHole"
    family = "Coverage"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"corpus", "adapter"})
    covers: tuple[str, ...] = ()

    def run(self, ctx: Ctx) -> list[Finding]:
        dimensions = ctx.adapter.dimensions()
        legal = ctx.adapter.legal_combinations()
        findings: list[Finding] = []

        for dim_a, dim_b in combinations(dimensions, 2):
            common_kinds = dim_a.applies_to & dim_b.applies_to
            if not common_kinds:
                continue

            required = {(va, vb) for va in dim_a.values for vb in dim_b.values
                       if legal(dim_a.id, va, dim_b.id, vb)}
            if not required:
                continue

            seen: set[tuple[str, str]] = set()
            for kind in common_kinds:
                for entry in ctx.corpus.by_kind(kind):
                    va, vb = entry.get(dim_a.field), entry.get(dim_b.field)
                    if va is not None and vb is not None:
                        seen.add((va, vb))

            missing = sorted(required - seen)
            if not missing:
                continue
            sample = ", ".join(f"({a},{b})" for a, b in missing[:6])
            more = f", +{len(missing) - 6} more" if len(missing) > 6 else ""
            findings.append(Finding(
                metric=self.id, severity=Severity.GAP,
                subject=f"{dim_a.id}×{dim_b.id}",
                message=f"{len(missing)} of {len(required)} legal ({dim_a.id}, {dim_b.id}) pairs "
                        f"never co-occur in {sorted(common_kinds)} content ({sample}{more})",
                evidence={"dimensionA": dim_a.id, "dimensionB": dim_b.id,
                         "seen": len(seen), "required": len(required),
                         "missingSample": missing[:20]},
            ))
        return findings
