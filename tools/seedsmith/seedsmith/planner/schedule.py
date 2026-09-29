"""List scheduling and the work-order document (spec-planner.md §5-§6, plan P4).

Three rules, all deliberately dumb:

- **Layer by layer**, never crossing a dependency edge — the layers come from `ordering`, so this
  module never decides what depends on what.
- **Longest-job-first within a layer** — classic list scheduling. Partitions with more entries take
  longer, and starting them first shortens the makespan.
- **Model tier by a rule table, not an optimiser.** A table is auditable; an optimiser is a second
  thing to debug when the plan looks wrong, and "why did it pick that model" is not a question
  anyone should have to answer by reading a search.

**Every job names the findings it closes.** That link is what makes a work order gradeable: after
execution the metrics re-run, and a job that ran without clearing its finding is a **pipeline**
defect rather than a content one. Without it, a failed generation is indistinguishable from content
nobody attempted.

⛔ **A spec conflict resolved here, deliberately and with evidence.** `spec-planner.md` §7 says the
planner *"must place the four base-type partitions in the base-type layer"*. The plan and todo say
the opposite — they are **excluded**, because S2 found their `_meta.partition` string is wrong while
the entries' own `role`/`frame` fields are intact. They hold real content and need a **relabel**,
not generation. The newer, evidence-backed reading wins; generating into them would author
duplicates of content that already exists. `EXCLUDED_REASON_MISLABELED` carries that decision to
anyone reading the output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from .ordering import KindOrder

__all__ = [
    "Job",
    "Layer",
    "Partition",
    "WorkOrder",
    "Excluded",
    "EXCLUDED_REASON_MISLABELED",
    "DEFAULT_MODEL_TIERS",
    "schedule",
]

#: Why a partition that *looks* empty is not a generation job. Surfaced in the work order rather
#: than dropped silently: a partition that vanishes without explanation reads as a planner bug.
EXCLUDED_REASON_MISLABELED = "mislabeled-partition-needs-relabel-not-generation"


@dataclass(frozen=True)
class ModelTiers:
    """Which kinds get the stronger model, and what the two tiers are called.

    A table, not a heuristic. `invents_identity` is the whole rule: a kind that mints new names and
    new ids needs the stronger model; a kind that assembles from a closed vocabulary does not.
    """

    strong: str = "opus"
    cheap: str = "sonnet"
    invents_identity: frozenset[str] = frozenset({
        # `combination` is item module 21's rename of `socket-word` (D20, ruled 2026-09-04:
        # "regenerate, do not retain"). The retired `socket-word` spelling was dropped 2026-09-21
        # (ISG7-follow-up) once SSH2.6's retirement was complete for real — the legacy seed file is
        # gone and the kind is gone from both ports' tables (`adapters/items/kinds.py`,
        # `gk-forge/tools/ItemSeedValidator/Registries/KindCatalog.cs`) — so no partition can name it, and a
        # dead spelling here is residue, not a safety net. A combination invents a name and an id
        # exactly as a socket-word did.
        "base-type", "unique", "set", "charm", "combination", "consumable",
        "gem", "material",
    })

    def for_kind(self, kind: str) -> str:
        return self.strong if kind in self.invents_identity else self.cheap


DEFAULT_MODEL_TIERS = ModelTiers()


@dataclass(frozen=True)
class Partition:
    """One unit of work the planner might dispatch.

    `entries` is the job size for longest-job-first. `closes` are `(metric_id, subject)` pairs —
    the spec's own "by metric id + subject", kept as a pair rather than a formatted string so a
    grader can match them without parsing prose.
    """

    id: str
    kind: str
    entries: int
    constraints: Mapping[str, str] = field(default_factory=dict)
    closes: tuple[tuple[str, str], ...] = ()
    excluded_reason: str | None = None


@dataclass(frozen=True)
class Excluded:
    partition: str
    kind: str
    reason: str

    def to_dict(self) -> dict:
        return {"partition": self.partition, "kind": self.kind, "reason": self.reason}


@dataclass(frozen=True)
class Job:
    partition: str
    kind: str
    entries: int
    brief: str
    model: str
    constraints: Mapping[str, str]
    closes: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "partition": self.partition,
            "kind": self.kind,
            "entries": self.entries,
            "brief": self.brief,
            "model": self.model,
            "constraints": dict(self.constraints),
            "closes": list(self.closes),
        }


@dataclass(frozen=True)
class Layer:
    layer: int
    parallel: bool
    jobs: tuple[Job, ...]

    def to_dict(self) -> dict:
        return {"layer": self.layer, "parallel": self.parallel,
                "jobs": [j.to_dict() for j in self.jobs]}


@dataclass(frozen=True)
class WorkOrder:
    budget_version: int
    corpus_revision: str
    layers: tuple[Layer, ...]
    feasible: bool = True
    refusals: tuple[str, ...] = ()
    excluded: tuple[Excluded, ...] = ()
    concurrency: int = 1

    def to_dict(self) -> dict:
        """Exactly spec-planner.md §6's shape. `excluded` and `concurrency` are additive — §6's
        keys are all present and unchanged, so an existing reader is unaffected."""
        return {
            "budgetVersion": self.budget_version,
            "corpusRevision": self.corpus_revision,
            "layers": [layer.to_dict() for layer in self.layers],
            "feasible": self.feasible,
            "refusals": list(self.refusals),
            "excluded": [e.to_dict() for e in self.excluded],
            "concurrency": self.concurrency,
        }

    @property
    def jobs(self) -> tuple[Job, ...]:
        return tuple(job for layer in self.layers for job in layer.jobs)

    def layer_of(self, partition: str) -> int:
        for layer in self.layers:
            for job in layer.jobs:
                if job.partition == partition:
                    return layer.layer
        raise KeyError(f"partition {partition!r} is not scheduled (excluded, or never offered)")

    def waves(self, layer: int) -> tuple[tuple[str, ...], ...]:
        """How the concurrency cap chunks one layer, longest-first.

        Exposed as a derived view rather than baked into `layers`, because `layer` means *dependency
        stage* — collapsing the cap into it would conflate "cannot run yet" with "no worker free",
        and those have different fixes.
        """
        jobs = next(l.jobs for l in self.layers if l.layer == layer)
        cap = max(1, self.concurrency)
        return tuple(
            tuple(j.partition for j in jobs[i:i + cap])
            for i in range(0, len(jobs), cap)
        )


def schedule(
    partitions: Sequence[Partition],
    order: KindOrder,
    *,
    budget_version: int,
    corpus_revision: str,
    concurrency: int = 4,
    brief_dir: str = "briefs",
    tiers: ModelTiers = DEFAULT_MODEL_TIERS,
) -> WorkOrder:
    """Place every offered partition into its kind's dependency layer.

    An excluded partition never becomes a job but **is** reported, so the output distinguishes
    "nothing to do here" from "the planner dropped it".

    A partition whose kind is not in the derived order is a refusal, not a crash and not a silent
    drop: it means the adapter offered work for a kind the graph does not know, which is a real
    inconsistency worth naming in the artifact rather than in a stack trace.
    """
    if not order.ok:
        return WorkOrder(
            budget_version=budget_version,
            corpus_revision=corpus_revision,
            layers=(),
            feasible=False,
            refusals=tuple(c.explain() for c in order.cycles),
            concurrency=concurrency,
        )

    excluded = tuple(
        Excluded(p.id, p.kind, p.excluded_reason)
        for p in partitions
        if p.excluded_reason is not None
    )
    offered = [p for p in partitions if p.excluded_reason is None]

    refusals: list[str] = []
    by_layer: dict[int, list[Partition]] = {}
    for p in offered:
        try:
            stage = order.stage_of(p.kind)
        except KeyError:
            refusals.append(
                f"partition {p.id!r} names kind {p.kind!r}, which the derived order does not contain"
            )
            continue
        by_layer.setdefault(stage, []).append(p)

    layers: list[Layer] = []
    for stage in sorted(by_layer):
        # Longest-job-first; partition id breaks ties so the plan is reproducible. A schedule that
        # reorders between runs cannot be diffed against the one a human would write, which is
        # exactly how spec-planner.md §7 says to judge this module.
        ranked = sorted(by_layer[stage], key=lambda p: (-p.entries, p.id))
        jobs = tuple(
            Job(
                partition=p.id,
                kind=p.kind,
                entries=p.entries,
                brief=f"{brief_dir}/{p.id.replace('/', '_')}.md",
                model=tiers.for_kind(p.kind),
                constraints=dict(p.constraints),
                closes=tuple(f"{metric}:{subject}" if subject else metric
                             for metric, subject in p.closes),
            )
            for p in ranked
        )
        layers.append(Layer(layer=len(layers) + 1, parallel=len(jobs) > 1, jobs=jobs))

    return WorkOrder(
        budget_version=budget_version,
        corpus_revision=corpus_revision,
        layers=tuple(layers),
        feasible=True,
        refusals=tuple(refusals),
        excluded=excluded,
        concurrency=concurrency,
    )
