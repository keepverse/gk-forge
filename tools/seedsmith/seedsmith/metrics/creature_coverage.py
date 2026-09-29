"""seedsmith.metrics.creature_coverage — Coverage/CreatureUncovered (spec-creature-metrics.md §2.1, A5).

Lives in `metrics/`, not `adapters/creatures/`, on purpose (spec §4): per-entity coverage is a generic
property — items will want it too — and the adapter supplies the strata (which entries exist, how
they reference each other via `reference_fields`), the metric does the counting. This is the same
split `provenance-supersede` was moved to core backlog to preserve.

**Fully generic, no creature-specific hardcoding beyond the default `subject_kind`.** Coverage is
computed by scanning every OTHER kind's entries for ANY field value equal to a subject's id — the
same "does this string look like a reference" question `Corpus.discover_edges` already answers,
applied per-subject instead of corpus-wide. A subject with zero referencing entries anywhere is
`GAP`-uncovered (audit A5's own fix: family coverage is a different, and insufficient, question —
"a handful of multi-family creatures can satisfy every partition while most of the roster gets no
content, and coverage reports green"). A subject with ANY referencing entry is fully covered and produces NO finding at all — silence is
healthy, the same convention `Coverage/EmptyPartition` already uses (owner, 2026-08-31: "any
generated artifact counts"; the stricter "every eligible kind must be present" reading was
explicitly rejected as noise on a small roster). "Report per-kind breakdown" (the other half of
that decision) lives inside the ONE finding a zero-content subject produces: its evidence names
every kind that was checked and found absent, which is the actionable detail a bare "uncovered"
would not give a reader deciding what to generate next.
"""
from __future__ import annotations

from .model import Ctx, Finding, Loop, Metric, Severity


def _string_leaves(value) -> "list[str]":
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: "list[str]" = []
        for v in value.values():
            out.extend(_string_leaves(v))
        return out
    if isinstance(value, list):
        out = []
        for v in value:
            out.extend(_string_leaves(v))
        return out
    return []


class CreatureUncoveredMetric(Metric):
    id = "Coverage/CreatureUncovered"
    family = "Coverage"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"corpus", "adapter"})
    covers: "tuple[str, ...]" = ()

    #: Overridable per-instance so a future non-creature consumer (items, say) can reuse this class
    #: verbatim rather than the module needing a second near-duplicate (spec §4's own stated goal).
    subject_kind: str = "creature"

    def run(self, ctx: Ctx) -> "list[Finding]":
        subjects = ctx.corpus.by_kind(self.subject_kind)
        if not subjects:
            return []

        subject_ids = {e.id for e in subjects}
        content_kind_ids = sorted(
            k.kind for k in ctx.adapter.kinds() if k.kind != self.subject_kind
        )

        covered_by: "dict[str, set[str]]" = {}
        for kind_id in content_kind_ids:
            for entry in ctx.corpus.by_kind(kind_id):
                for value in _string_leaves(entry.data):
                    if value in subject_ids:
                        covered_by.setdefault(value, set()).add(kind_id)

        findings: "list[Finding]" = []
        for subject in sorted(subjects, key=lambda e: e.id):
            if subject.id in covered_by:
                continue  # covered by SOMETHING — silence, matching EmptyPartitionMetric's own convention
            findings.append(Finding(
                metric=self.id, severity=Severity.GAP, subject=subject.id,
                message=f"{self.subject_kind} {subject.id!r} has NO generated content "
                        f"(checked {content_kind_ids})",
                evidence={"presentKinds": [], "absentKinds": content_kind_ids},
                assertion=f"any entry of another kind references {subject.id!r}",
                remedy="planner: schedule generation for this entity",
            ))
        return findings
