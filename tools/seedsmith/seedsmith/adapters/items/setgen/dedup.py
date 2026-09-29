"""seedsmith.adapters.items.setgen.dedup — the name-distinctness gate, measured EXACTLY.

⛔ **Why this exists instead of reading `SemanticDedup/NearDuplicate`'s output directly.** That
metric estimates Jaccard from a 32-hash MinHash signature, and on names this short the estimate is
badly biased upward. Measured against the live corpus 2026-09-04:

| pair | true Jaccard | MinHash estimate |
|---|---|---|
| `'Tier Duration'` / `'Husk of the Murmuration'` | **0.120** | 0.844 |
| `'Spiralled Bead'` / `'Spiralled Intercom'` | **0.333** | 0.906 |
| `'Root of the Foundation'` / `'Signet of the Foundation'` | 0.652 | 0.719 |

The first two are not near-duplicates by any reading, and both are reported as such today. This
module's spec makes the near-duplicate **rate** a gate, so gating on a signal that over-reports by
7× would fail every run for the wrong reason.

The fix is the standard MinHash+LSH pattern rather than a new idea: **LSH is a candidate generator;
the exact check is the filter.** `shingles` is imported from the shared metric so the tokenisation
cannot drift between the two — only the comparison differs, and only here.

⚠ **The shared metric is deliberately NOT changed from this module.** It is registered for every
adapter and its finding count is another stream's baseline; moving it mid-session would be a
silent regression somewhere else. Filed as a defect in module 13's own todo entry, with this table
as the evidence.
"""
from __future__ import annotations

from dataclasses import dataclass

from ....metrics.dedup import shingles


@dataclass(frozen=True)
class NearDuplicatePair:
    a: str
    b: str
    jaccard_permille: int


@dataclass(frozen=True)
class DedupReport:
    population: int
    exact_duplicates: "tuple[tuple[str, str], ...]"
    near_duplicates: "tuple[NearDuplicatePair, ...]"

    @property
    def rate_permille(self) -> int:
        """Near-duplicate PAIRS per thousand entries. Integer per-mille — the multiply happens
        before the divide, exactly once."""
        if self.population == 0:
            return 0
        return (len(self.near_duplicates) * 1000) // self.population

    def within(self, ceiling_permille: int, exact_max: int) -> bool:
        return self.rate_permille <= ceiling_permille and len(self.exact_duplicates) <= exact_max


def exact_jaccard_permille(a: str, b: str) -> int:
    sa, sb = shingles(a), shingles(b)
    union = sa | sb
    if not union:
        return 0
    return (len(sa & sb) * 1000) // len(union)


def dedup_report(names: "dict[str, str]", *, threshold_permille: int = 600) -> DedupReport:
    """`{entry_id: name}` -> the exact report.

    O(n²) on purpose and stated as such: this runs over one generated population (~1,844 at the
    full roster), not over the whole corpus, and 1,844² comparisons of two short frozensets is
    under a second. The shared metric needs LSH because it compares the WHOLE corpus; this does
    not, and buying an approximation for a cost we are not paying would be the wrong trade.
    """
    ids = sorted(names)
    by_lower: "dict[str, list[str]]" = {}
    for entry_id in ids:
        by_lower.setdefault(names[entry_id].strip().lower(), []).append(entry_id)
    exact = tuple(
        (group[i], group[j])
        for group in by_lower.values() if len(group) > 1
        for i in range(len(group)) for j in range(i + 1, len(group))
    )

    near: "list[NearDuplicatePair]" = []
    shingled = {entry_id: shingles(names[entry_id]) for entry_id in ids}
    for i, left in enumerate(ids):
        for right in ids[i + 1:]:
            sa, sb = shingled[left], shingled[right]
            union = sa | sb
            if not union:
                continue
            score = (len(sa & sb) * 1000) // len(union)
            if score >= threshold_permille and names[left].strip().lower() != names[right].strip().lower():
                near.append(NearDuplicatePair(a=left, b=right, jaccard_permille=score))
    return DedupReport(population=len(ids), exact_duplicates=exact,
                       near_duplicates=tuple(near))
