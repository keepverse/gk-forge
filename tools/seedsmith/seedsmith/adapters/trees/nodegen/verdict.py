"""seedsmith.adapters.trees.nodegen.verdict — `GATING_METRICS` dict + `missing_thresholds()`
(task H1, spec-tree-language.md §7.1, §7 gate 23).

**Not a second `GATING_METRICS`.** Task A2's `adapters.trees.targets` already carries the mapping
this module's own spec section names — `GATING_METRICS: {metric -> PassiveTreeTargets attribute}`
for the six threshold-shaped gates, plus `missing_thresholds`. Re-exported here (via `tuning.py`,
this package's own re-export of A2) so a caller reaches both from `nodegen.verdict` without needing
to know they were first written for a different task.

**What this module adds on top:** the `RunReport`/`Verdict` resolution logic `items/setgen/verdict
.py` ships and A2's targets module does not — "pass only when every gating metric both ran and
cleared", FAIL beating NOT_MEASURED, a held partition alone denying a PASS (§7 gate 23's own three
clauses, quoted in this module's docstrings below). The 8 real `PassiveTree/*` metrics that FEED a
`RunReport` are H4's (`metrics/passive_tree.py`) — this module only owns what a report of their
outcomes resolves to, same split A2/H4 already draw for the threshold table itself.

§7.1's own promotion rule — **exactly one metric is `gates=True`, and it is
`PassiveTree/UnresolvedCount`** — is enforced at METRIC REGISTRATION (`metrics/registry.py:17-21`'s
`MetricRegistry.register`, "an OPEN-loop metric may never gate (P3)"), not by this module: `verdict
.py` consumes outcomes a registry already refused to accept in the wrong shape, it does not itself
re-check which registered metric carries the flag.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from ..targets import GATING_METRICS, PassiveTreeTargets, missing_thresholds

if TYPE_CHECKING:
    from ....metrics.registry import MetricRegistry

__all__ = [
    "GATING_METRICS", "missing_thresholds", "missing_thresholds_report", "Verdict",
    "MetricOutcome", "RunReport", "UNRESOLVED_COUNT_METRIC", "hard_gate_ids",
    "assert_exactly_one_hard_gate",
]

#: §7.1: "exactly one gate is promoted to hard-fail first" — named here as a constant so a test can
#: assert `UNRESOLVED_COUNT_METRIC in GATING_METRICS` without spelling the string twice.
UNRESOLVED_COUNT_METRIC = "PassiveTree/UnresolvedCount"


class Verdict(Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_MEASURED = "not_measured"


@dataclass
class MetricOutcome:
    metric: str
    ran: bool
    cleared: bool
    detail: str = ""

    @property
    def verdict(self) -> Verdict:
        if not self.ran:
            return Verdict.NOT_MEASURED
        return Verdict.PASS if self.cleared else Verdict.FAIL


@dataclass
class RunReport:
    """§7 gate 23 (`RunReport.verdict`, `setgen/verdict.py:83-96`'s own precedent): `FAIL` beats
    `NOT_MEASURED`; a held partition alone denies a `PASS`."""

    outcomes: "list[MetricOutcome]" = field(default_factory=list)
    held_partitions: "list[str]" = field(default_factory=list)

    def record(self, metric: str, *, ran: bool, cleared: bool, detail: str = "") -> None:
        self.outcomes.append(MetricOutcome(metric, ran, cleared, detail))

    @property
    def verdict(self) -> Verdict:
        gating = [o for o in self.outcomes if o.metric in GATING_METRICS
                 or o.metric == UNRESOLVED_COUNT_METRIC]
        if any(o.verdict is Verdict.FAIL for o in gating):
            return Verdict.FAIL
        if self.held_partitions or not gating or any(
                o.verdict is Verdict.NOT_MEASURED for o in gating):
            return Verdict.NOT_MEASURED
        return Verdict.PASS

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "heldPartitions": list(self.held_partitions),
            "metrics": [
                {"metric": o.metric, "ran": o.ran, "cleared": o.cleared,
                 "verdict": o.verdict.value, "detail": o.detail}
                for o in self.outcomes
            ],
        }


def missing_thresholds_report(targets: PassiveTreeTargets) -> "list[str]":
    """§7 gate 5's own dry-run print ("`gatesMissingAThreshold`... before the run spends anything")
    — a thin alias so callers reaching this module for the run report can also print the gap list
    without a second import of `adapters.trees.targets`."""
    return missing_thresholds(targets)


# ---------------------------------------------------------------------------------------------
# task H2 — §7.1's promotion rule, read off a REAL metric registry rather than off `GATING_METRICS`.
#
# ⚠ **A naming collision resolved here, stated plainly.** The todo's own H2 acceptance wording is
# `"GATING_METRICS has exactly one entry"`. That cannot mean `adapters.trees.targets.GATING_METRICS`
# (the constant re-exported two lines up): A2 built it with SIX entries — one per threshold-shaped
# gate (§7 gates 15-18, 20, 22) — and `test_nodegen_verdict.py::GatingMetricsReexportTests`/
# `RunReportVerdictTests` already exercise all six of them; shrinking that dict to one entry would
# break H1's own already-green tests over a name the spec never asked to change.
#
# What §7.1 actually promotes to "exactly one" is a DIFFERENT thing with a similar name: of every
# metric REGISTERED under one family in `metrics.registry.MetricRegistry` (`metrics/registry.py`),
# exactly one may carry `gates=True` — "every other gate starts False and is promoted... as a
# deliberate, later, separate act." `CreatureRoster/UnresolvedCount` is the one place this already
# holds in the shipped registry today (`metrics/creature_roster.py:369`); `PassiveTree/UnresolvedCount`
# is the metric H4 (not yet built) promotes the same way — this module cannot make that literally
# true in the registry ahead of H4 without doing H4's own job, so what it ships instead is the
# INVARIANT itself, enforced against whatever registry a caller hands it, proven here against
# today's real `CreatureRoster` (already exactly one) and against a synthetic fixture standing in for
# PassiveTree's own end state (`test_nodegen_verdict.py`'s own test for this function).
# ---------------------------------------------------------------------------------------------

def hard_gate_ids(registry: "MetricRegistry", family: str) -> "list[str]":
    """The metric ids under `family` currently registered with `gates=True`, read off the real
    registry — never off `GATING_METRICS` (that dict answers "does this gate have a threshold",
    not "is this gate promoted to hard-fail the run")."""
    return sorted(m.id for m in registry.all() if m.family == family and m.gates)


def assert_exactly_one_hard_gate(registry: "MetricRegistry", family: str) -> None:
    """§7.1: "exactly one gate is promoted to hard-fail first." Raises, naming every offending id,
    if `family` carries zero or more than one `gates=True` metric in `registry` — zero means a run
    can PASS with nothing actually gated (a checkmark nobody earned); more than one means two
    thresholds can each independently outrank the other's own promotion decision."""
    ids = hard_gate_ids(registry, family)
    if len(ids) != 1:
        raise ValueError(
            f"{family}: expected exactly one gates=True metric (§7.1), found {len(ids)}: {ids}")
