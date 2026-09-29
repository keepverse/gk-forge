"""seedsmith.metrics.cell_occupancy — `Distribution/CellOccupancy` (item module 13, set-charm-gen).

⭐ **The distinctness gate is the cell, not the capability.** `Distribution/Evenness` and
`Distribution/Inequality` measure spread over *one* dimension's cells; this measures occupancy of a
**composite** cell, which is the right shape for the question "can a player tell these two sets
apart?" — so it is a new metric, not an existing one pointed at a new column.

> Cell key = `(capability, sorted multiset of the stat families granted at every threshold above the
> lowest)`. **Median occupancy ≤ 2**; max and singleton share reported beside it.

Derived, not invented (`docs/research/game-design/03-roster-scale.md` §1): Summoners War 832 units at
1.02/cell (median 1), Honkai Star Rail ~95 at 1.7–1.8 (median 2), Arknights 425 at 1.97 (median 2).
Fire Emblem Heroes — *"the worst documented in the genre"* — is 1,410 at 15.3, median 7, max 129.

⚠ **`gates = False`, deliberately, and this is the honest reading rather than a softening.** The
threshold is defined over the **generated species-set population** (~904), which does not exist yet:
today's corpus holds **30 legacy sets**, a different population, and promoting the gate now would
gate CI on the wrong denominator. The finding is still `GAP` severity, so a plain `seedsmith check`
reports it and the module-13 **run verdict** treats it as a real gate
(`adapters/items/setgen/verdict.py`'s `GATING_METRICS`). Promotion belongs with the generation run
that creates the population it measures — the same "measure first, then promote" sequence
spec-metrics.md §4 states, with the trigger written down instead of left to memory.

Measured against the live 30-set corpus 2026-09-04: **28 cells, median 1, max 2, 26 singletons.**
"""
from __future__ import annotations

from ..adapters.items.setgen.cells import cell_report
from ..adapters.items.setgen.tuning import SetCharmTuningError
from ..adapters.items.setgen.tuning import load as load_tuning
from .model import Ctx, Finding, Loop, Metric, Severity

#: What must become true before `gates` may flip to True. Written down rather than remembered.
PROMOTION_TRIGGER = (
    "the generated species-set population exists (module 13's generation run) — the threshold is "
    "defined over ~904 generated sets, not over the 30 legacy sets shipped today"
)


class CellOccupancy(Metric):
    id = "Distribution/CellOccupancy"
    family = "Distribution"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"corpus"})
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        entries = [e.data for e in ctx.corpus.by_kind("set")]
        if not entries:
            return [Finding(
                metric=self.id, severity=Severity.NOT_MEASURED, subject="(suite)",
                message="no `set` entries in this corpus — an empty population is NOT a passing "
                        "distinctness result",
                evidence={"code": "EmptyPopulation"})]
        try:
            tuning = load_tuning()
        except (FileNotFoundError, SetCharmTuningError) as exc:
            return [Finding(
                metric=self.id, severity=Severity.NOT_MEASURED, subject="(suite)",
                message=f"set-charm-gen tuning unreadable ({exc}) — refusing to measure against an "
                        f"assumed threshold",
                evidence={"code": "ThresholdUnavailable"})]

        report = cell_report(entries)
        ceiling = tuning.median_cell_occupancy_max
        severity = Severity.NOTE if report.within(ceiling) else Severity.GAP
        findings = [Finding(
            metric=self.id, severity=severity, subject="set:capability+higher-thresholds",
            message=(f"{report.population} sets over {report.cells} cells: median "
                     f"{report.median:g} (threshold <= {ceiling}), max {report.maximum}, "
                     f"singletons {report.singletons}/{report.cells} "
                     f"({report.singleton_share_permille}permille)"),
            evidence={"cells": report.cells, "population": report.population,
                      "median": report.median, "max": report.maximum,
                      "singletons": report.singletons,
                      "singletonSharePermille": report.singleton_share_permille,
                      "medianMax": ceiling, "promotionTrigger": PROMOTION_TRIGGER},
            assertion=(f"median cell occupancy over (capability, higher-threshold family multiset) "
                       f"is at most {ceiling}"),
            remedy="items generate --kind set (module 13) — vary the higher thresholds, not the "
                   "capability; the capability is the coarse axis and was never doing the "
                   "distinctness work",
        )]

        # The diagnostic that shows a picker collapsing onto the three or four most flattering
        # capabilities. Reported, never gating — passing it proves nothing about distinctness.
        used = len(report.capability_usage)
        top = ", ".join(f"{fam} x{n}" for fam, n in report.capability_usage[:3])
        findings.append(Finding(
            metric=self.id, severity=Severity.NOTE, subject="set:capability-usage",
            message=f"{used} distinct capabilities used over {report.population} sets "
                    f"(report-only, never a gate; most used: {top})",
            evidence={"capabilitiesUsed": used,
                      "usage": [list(pair) for pair in report.capability_usage]},
        ))
        return findings
