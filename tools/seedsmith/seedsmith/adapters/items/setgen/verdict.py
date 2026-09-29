"""seedsmith.adapters.items.setgen.verdict — the run verdict, and the thing it may never launder.

⛔ **A partition that did not run reports `NOT_MEASURED`, never a pass.** `Severity.NOT_MEASURED`
already exists and the tool already states the discipline: *"a metric whose needs are unmet reports
NOT_MEASURED, never a pass, and never a false GAP."*

> **The run verdict is `pass` only when every gating metric both ran and cleared** — an empty
> species partition, an absent `budget` context, or a held `basis = "name"` population each make the
> verdict `not_measured`, which is the honest answer.

⚠ **Every metric gets a threshold, and this module is where that is enforced as a fact rather than
an intention.** `GATING_METRICS` names each gate with the tuning key its threshold is read from.
`missing_thresholds()` returns the gates whose threshold is not resolvable — a command with no
threshold is something you run and then argue about, and the meta-test asserts that list is empty.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .tuning import SetCharmGenTuning


class Verdict(Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_MEASURED = "not_measured"


#: metric id -> the `SetCharmGenTuning` attribute holding its threshold. Every gate this module's
#: spec names appears here; a gate with no entry is exactly the "command without a threshold" the
#: spec refuses.
GATING_METRICS: "dict[str, str]" = {
    "Distribution/CellOccupancy": "median_cell_occupancy_max",
    "SemanticDedup/ExactDuplicateName": "exact_duplicate_names_max",
    "SemanticDedup/NearDuplicate": "near_duplicate_rate_max_permille",
    "Distribution/Inequality:charm-axis": "charm_axis_gini_max_permille",
    "Linkage/SetCompletability": "_zero_findings",
}

#: Report-only by their own metric discipline: no prior exists, and inventing one is the mistake the
#: discipline names. They must still appear in the run report — a metric that runs and is never read
#: is the same as one that never ran.
REPORT_ONLY_METRICS: "tuple[str, ...]" = (
    "Distribution/Inequality:set-capability",
    "Distribution/Evenness:set-capability",
)


def missing_thresholds(tuning: SetCharmGenTuning) -> "list[str]":
    missing: "list[str]" = []
    for metric, key in GATING_METRICS.items():
        if key == "_zero_findings":
            continue                     # its threshold IS zero findings; there is nothing to tune
        if getattr(tuning, key, None) is None:
            missing.append(metric)
    return missing


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
    outcomes: "list[MetricOutcome]" = field(default_factory=list)
    held_partitions: "list[str]" = field(default_factory=list)

    def record(self, metric: str, *, ran: bool, cleared: bool, detail: str = "") -> None:
        self.outcomes.append(MetricOutcome(metric, ran, cleared, detail))

    @property
    def verdict(self) -> Verdict:
        """`pass` only when every gating metric both ran and cleared.

        Order matters and is deliberate: a FAIL beats a NOT_MEASURED, because "we measured it and it
        is wrong" is more actionable than "part of it did not run". But a held partition alone is
        enough to deny a pass, which is the whole point.
        """
        gating = [o for o in self.outcomes if o.metric in GATING_METRICS]
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
            "reportOnly": list(REPORT_ONLY_METRICS),
        }
