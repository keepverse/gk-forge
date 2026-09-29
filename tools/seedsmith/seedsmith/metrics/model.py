"""seedsmith.metrics.model — Metric, Finding, Loop, Severity, Ctx (spec-metrics.md §1-2).

Four fields on `Metric` carry rules rather than data (spec-metrics.md §1):

- `loop`: a CLOSED metric can verify its own fix; an OPEN one cannot and so may never gate —
  enforced here, not by convention, because "Loop.OPEN with gates=True raises" is itself an
  acceptance criterion (tasks/seedsmith-todo.md, S1).
- `gates`: starts False for every new metric; promotion is a deliberate, later, separate act
  (spec-metrics.md §4).
- `needs`: declared so the runner can skip cleanly — a metric needing `budget` when none exists
  reports NOT_MEASURED, never a pass; silence and success must stay distinguishable.
- `covers`: which Appendix-A defect ids this metric claims (spec-metrics.md §5) — not enforced
  structurally in S1 (there is no Appendix-A binding yet for the stub feature), but the field
  exists from the start so no later module has to retrofit it onto every existing metric.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar

FINDING_SCHEMA_VERSION = 1


class Loop(Enum):
    CLOSED = "closed"
    OPEN = "open"


class Severity(Enum):
    GAP = "gap"
    NOTE = "note"
    NOT_MEASURED = "not_measured"


VALID_NEEDS = frozenset({
    "corpus", "adapter", "budget", "numerics", "creature_dump", "creature_anchors", "action_coverage",
    "passive_tree_plan",
})


@dataclass(frozen=True)
class Finding:
    metric: str
    severity: Severity
    subject: str
    message: str
    evidence: dict = field(default_factory=dict)
    assertion: "str | None" = None    # CLOSED only: what must become true
    remedy: "str | None" = None       # machine-readable hint: which pipeline could close it
    schema_version: int = FINDING_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "severity": self.severity.value,
            "subject": self.subject,
            "message": self.message,
            "evidence": self.evidence,
            "assertion": self.assertion,
            "remedy": self.remedy,
            "schemaVersion": self.schema_version,
        }


@dataclass
class Ctx:
    """What a metric may read. `adapter` is typed loosely (not `SeedAdapter` directly) so the
    stub — which implements the protocol structurally, not by inheritance — satisfies it without
    friction."""

    corpus: object                 # seedsmith.corpus.Corpus
    adapter: object                # seedsmith.adapters.SeedAdapter
    budget: object = None
    numerics: object = None
    creature_dump: object = None      # seedsmith.adapters.creatures.dump_ctx.CreatureDumpCtx — T1.10
    creature_anchors: object = None   # list[dict] of classified anchor entries — T2.10
    action_coverage: object = None  # seedsmith.adapters.actions.coverage_report.ctx.ActionCoverageCtx — A-S5
    passive_tree_plan: object = None  # PassiveTreePlanCtx (adapters.trees.plan.metrics_ctx) — task C1

    def has(self, need: str) -> bool:
        return getattr(self, need, None) is not None


class Metric(ABC):
    id: ClassVar[str]
    family: ClassVar[str]
    loop: ClassVar[Loop]
    gates: ClassVar[bool] = False
    needs: ClassVar[frozenset[str]] = frozenset({"corpus", "adapter"})
    covers: ClassVar[tuple[str, ...]] = ()

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        # The OPEN+gates=True contradiction is deliberately NOT checked here: catching it at
        # class-definition time would make it impossible to even construct an instance to hand
        # to a test verifying MetricRegistry.register()'s own guard (tasks/seedsmith-todo.md, S1
        # names registration specifically). One enforcement point for that rule, not two.
        unknown = cls.needs - VALID_NEEDS
        if unknown:
            raise ValueError(f"{cls.__name__}: unknown needs {sorted(unknown)}")

    @abstractmethod
    def run(self, ctx: Ctx) -> list[Finding]: ...
