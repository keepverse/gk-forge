"""Open-loop generation: write content, mark it for review, and never grade your own homework (G3).

An **open-loop** metric is one with no machine answer — "is this writing any good" is the standing
example. `Quality/FlavourGeneric` already handles that for *existing* text: it samples stratified by
kind and emits `needsReview` notes, never a pass or a fail.

G3's whole point is that **generated** content enters the same queue on the same terms. Two rules
make that real rather than aspirational:

1. **An open-loop pipeline's schema may not contain a pass/fail field.** Enforced by
   `audit_open_loop_schema`, not by review — a schema with a `quality` boolean is a model being
   invited to mark its own homework, and it will always pass itself.
2. **Generated rows are marked `needsReview` and sampled like any other**, so the finding stays
   open. A pipeline that could close its own open-loop finding would make the queue look empty
   precisely when it had just added the most work to it.

The sampling is `seedsmith.sampling` — **reused, not reimplemented**. Its stratification guarantee
(every non-empty stratum gets at least one sample) is the reason a corpus's neglected corners get
looked at, and a second sampler here would drift from it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from ..metrics.model import Finding, Loop, Severity
from ..sampling import stratified_sample
from .model import BLOCKED_FIELD, SchemaDefect
from .provenance import PROVENANCE_FIELD

__all__ = [
    "NEEDS_REVIEW_FIELD",
    "VERDICT_FIELD_NAMES",
    "audit_open_loop_schema",
    "mark_for_review",
    "sample_for_review",
]

#: Marks a generated row as awaiting human judgement. Present on every open-loop output.
NEEDS_REVIEW_FIELD = "needsReview"

#: Field names that would let a model grade itself. Matched case-insensitively on the whole name,
#: because `qualityOk` and `is_valid` are the same mistake wearing different spellings.
VERDICT_FIELD_NAMES = frozenset({
    "pass", "passed", "fail", "failed", "ok", "valid", "isvalid", "approved", "accepted",
    "quality", "qualityok", "score", "rating", "grade", "verdict", "good", "correct",
})


def _is_verdict(name: str) -> bool:
    normalized = name.replace("_", "").replace("-", "").lower()
    return normalized in VERDICT_FIELD_NAMES


def audit_open_loop_schema(schema: Mapping[str, Any], *, path: str = "$") -> list[SchemaDefect]:
    """Reject any field that lets an open-loop pipeline grade its own output.

    Recurses for the same reason `audit_schema` does: a `verdict` nested inside an array of
    objects grades just as effectively as a top-level one, and is harder to spot.

    `blocked` is explicitly **not** a verdict. Declining to do the work is not a judgement about
    the work's quality — conflating them would remove the model's only honest way out.
    """
    defects: list[SchemaDefect] = []

    for name, sub in (schema.get("properties") or {}).items():
        if name != BLOCKED_FIELD and _is_verdict(name):
            defects.append(SchemaDefect(
                f"{path}.{name}",
                f"open-loop schemas may not carry a verdict field — {name!r} lets the pipeline "
                f"mark its own homework, and it will always pass itself",
            ))
        if isinstance(sub, dict):
            defects.extend(audit_open_loop_schema(sub, path=f"{path}.{name}"))

    items = schema.get("items")
    if isinstance(items, dict):
        defects.extend(audit_open_loop_schema(items, path=f"{path}[]"))

    for keyword in ("anyOf", "oneOf", "allOf"):
        for i, sub in enumerate(schema.get(keyword) or ()):
            if isinstance(sub, dict):
                defects.extend(audit_open_loop_schema(sub, path=f"{path}.{keyword}[{i}]"))

    return defects


def mark_for_review(entry: Mapping[str, Any]) -> dict:
    """Stamp a generated row as awaiting human judgement. A copy, never in place."""
    return {**entry, NEEDS_REVIEW_FIELD: True}


@dataclass(frozen=True)
class ReviewCandidate:
    """One generated row queued for human review."""

    id: str
    stratum: str
    data: Mapping[str, Any]

    @property
    def generated(self) -> bool:
        return PROVENANCE_FIELD in self.data


def sample_for_review(
    candidates: Sequence[ReviewCandidate],
    *,
    metric_id: str,
    revision: str,
    sample_size: int = 12,
) -> list[Finding]:
    """Sample generated rows into the same review queue existing content uses.

    Every finding is `NOTE` + `needsReview`, never `GAP` and never a pass. An open-loop metric that
    emitted a pass would be answering a question it has already said has no machine answer.

    Strata are sorted before iteration: Python randomises string hashing per process, so a dict
    built from a set iterates differently across runs even when the sampled *set* is identical.
    `FlavourGeneric` hit exactly that and fixed it the same way — "reproducible" has to mean
    byte-identical output, not merely set-equal.
    """
    by_stratum: dict[str, list[ReviewCandidate]] = {}
    for candidate in candidates:
        by_stratum.setdefault(candidate.stratum, []).append(candidate)

    sampled = stratified_sample(by_stratum, sample_size,
                                metric_id=metric_id, revision=revision)

    findings: list[Finding] = []
    for stratum in sorted(sampled):
        for candidate in sampled[stratum]:
            findings.append(Finding(
                metric=metric_id,
                severity=Severity.NOTE,
                subject=candidate.id,
                message=(
                    f"'{candidate.id}' ({stratum}) sampled for review — "
                    f"{'generated' if candidate.generated else 'existing'} content"
                ),
                evidence={
                    NEEDS_REVIEW_FIELD: True,
                    "stratum": stratum,
                    "revision": revision,
                    "generated": candidate.generated,
                },
            ))
    return findings


def is_open_loop(metric: object) -> bool:
    return getattr(metric, "loop", None) is Loop.OPEN
