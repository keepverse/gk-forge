"""seedsmith.metrics.registry — registration and the runner (spec-metrics.md §6).

Registration is the second place `Loop.OPEN + gates=True` is rejected (the first is
`Metric.__init_subclass__`) — this is the one the S1 acceptance criterion names directly, since
"raises at registration" describes the act of adding a metric to an active suite, not merely
defining its class.
"""
from __future__ import annotations

from .model import Ctx, Finding, Loop, Metric, Severity


class MetricRegistry:
    def __init__(self) -> None:
        self._metrics: dict[str, Metric] = {}

    def register(self, metric: Metric) -> None:
        if metric.loop is Loop.OPEN and metric.gates:
            raise ValueError(
                f"{metric.id}: an OPEN-loop metric may never gate (P3) — refusing to register"
            )
        if metric.id in self._metrics:
            raise ValueError(f"duplicate metric id {metric.id!r}")
        self._metrics[metric.id] = metric

    def all(self) -> list[Metric]:
        return list(self._metrics.values())

    def get(self, metric_id: str) -> Metric | None:
        return self._metrics.get(metric_id)


def run_all(registry: MetricRegistry, ctx: Ctx,
           metric_ids: "list[str] | None" = None) -> list[Finding]:
    """Run every registered metric (or only `metric_ids`, if given) against `ctx`.

    A metric whose `needs` are not satisfied by `ctx` never runs — it emits a NOT_MEASURED
    finding instead, so an absent check is never indistinguishable from a healthy pass.
    """
    findings: list[Finding] = []
    metrics = registry.all() if metric_ids is None else [
        m for m in (registry.get(mid) for mid in metric_ids) if m is not None
    ]
    for metric in metrics:
        missing = sorted(n for n in metric.needs if not ctx.has(n))
        if missing:
            findings.append(Finding(
                metric=metric.id, severity=Severity.NOT_MEASURED, subject="(suite)",
                message=f"{metric.id} needs {missing}, not available in this run",
                evidence={"missing": missing},
            ))
            continue
        findings.extend(metric.run(ctx))
    return findings
