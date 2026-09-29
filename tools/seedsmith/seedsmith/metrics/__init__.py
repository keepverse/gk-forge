"""seedsmith.metrics — the check catalogue (spec-metrics.md).

Metrics are pure: `(corpus, budget, numerics, adapter) -> list[Finding]`. No I/O, no mutation, no
ordering dependence.
"""
from __future__ import annotations

from .model import Ctx, Finding, Loop, Metric, Severity
from .registry import MetricRegistry, run_all

__all__ = ["Ctx", "Finding", "Loop", "Metric", "MetricRegistry", "Severity", "run_all"]
