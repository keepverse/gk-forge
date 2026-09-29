"""The threat-audit review queue (creature-seed module 7, pipeline 5 `threat-audit`,
spec-classify-pipelines.md §3). A `too-low`/`too-high` verdict never overrides the computed rung
(Q16: "number wins") — it only enters this queue, which `roster-metrics` (module 14) reports and a
human (or a retune of `creature-threat.v1.json`) resolves. seedsmith's own open-loop rule: a metric
that cannot verify its own fix produces a queue, never a silent pass.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ThreatAuditReviewEntry:
    species_id: str
    side: str
    computed_rung_id: str
    verdict: str          # "too-low" | "too-high" (never "agree" — those never enter the queue)
    reason: str


def build_review_queue(entries) -> "list[ThreatAuditReviewEntry]":
    """Filters to only the disagreements — an `agree` verdict never occupies a queue slot."""
    return [e for e in entries if e.verdict != "agree"]


def write_review_queue(entries: "list[ThreatAuditReviewEntry]", path: Path) -> None:
    """Sorted by `(side, species_id)` ordinal — deterministic, diffable, same discipline as
    `corpus-dump`'s own canonical serialisation."""
    rows = sorted(entries, key=lambda e: (e.side, e.species_id))
    path.write_text(
        json.dumps([asdict(e) for e in rows], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")


def read_review_queue(path: Path) -> "list[ThreatAuditReviewEntry]":
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [ThreatAuditReviewEntry(**row) for row in raw]
