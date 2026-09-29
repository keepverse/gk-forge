"""seedsmith.metrics.appendix_a — the Appendix-A defect table from
`docs/architecture/seedsmith-map.md` (§ "20 defects"), as data.

Rows 1-6 are owned by the C# validator and out of seedsmith's scope entirely. Row 8 (Feasibility)
and row 19 (dependency order) are `planner`'s job — W2, gated on W1 being green. Rows 17-18
(Quality, open-loop) are S8's job. `seedsmith metrics --coverage` uses `in_scope_w1` to tell a
genuinely-missing row from a row that was never meant to be claimed yet — spec-metrics.md §5's
whole discipline is that the distinction must be visible, not silently the same "not covered".
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppendixARow:
    number: int
    description: str
    family: str
    in_scope_w1: bool


ROWS: "tuple[AppendixARow, ...]" = (
    AppendixARow(1, "Partition id / id template transcribed wrong", "Identity (C#)", False),
    AppendixARow(2, "Invented vocabulary outside the closed set", "Vocabulary (C#)", False),
    AppendixARow(3, "Name collisions, possessives, rarity words in names", "Naming (C#)", False),
    AppendixARow(4, "Reference derived from a pattern instead of looked up", "Referential (C#)", False),
    AppendixARow(5, "Reference invisible to the resolver (snake_case vs kebab)", "Referential (C#)", False),
    AppendixARow(6, "Tracking id vs runtime id confused, four times", "Referential (C#)", False),
    AppendixARow(7, "A rule that lives only in a lane document until violated", "Constraint", True),
    AppendixARow(8, "An allocation that is arithmetically unsatisfiable", "Feasibility", False),  # planner, W2
    AppendixARow(9, "An exemplar propagating a wrong shape, three times", "ExemplarConformance", True),
    AppendixARow(10, "Content that ships unreachable — no drop path, no recipe", "Linkage", True),
    AppendixARow(11, "A set nothing can complete — members by role, never pinned", "Linkage", True),
    AppendixARow(12, "A whole feature unbound — milestones, no granting base type", "Linkage", True),
    AppendixARow(13, "Allocated partition with zero entries — nine, eight accidental", "Coverage", True),
    AppendixARow(14, "Distribution skew — humanoid uniques half of plant", "Distribution", True),
    AppendixARow(15, "Rarity ladder not monotonic — band-90 flatter than band-50", "Balance", True),
    AppendixARow(16, "Two entries rendering identically for different mechanics", "SemanticDedup", True),
    AppendixARow(17, "Flavour absent — 60 consumables, 30 of 70 charms", "Quality (open-loop)", False),  # S8
    AppendixARow(18, "Names legally distinct but all saying one idea", "Quality (open-loop)", False),  # S8
    AppendixARow(19, "Same-stage / wrong-order references between kinds", "Dependency order", False),  # planner, W2
    AppendixARow(20, "A material that drops and nothing consumes", "Linkage (note)", True),
)


def coverage_report(registered_metrics) -> "dict":
    covered: "dict[int, list[str]]" = {}
    for metric in registered_metrics:
        for tag in metric.covers:
            if tag.startswith("appendix-a:"):
                covered.setdefault(int(tag.split(":")[1]), []).append(metric.id)

    claimed, known_gap, unclaimed = [], [], []
    for row in ROWS:
        metric_ids = covered.get(row.number, [])
        if metric_ids:
            claimed.append((row, metric_ids))
        elif not row.in_scope_w1:
            known_gap.append(row)
        else:
            unclaimed.append(row)
    return {"claimed": claimed, "known_gap": known_gap, "unclaimed": unclaimed}
