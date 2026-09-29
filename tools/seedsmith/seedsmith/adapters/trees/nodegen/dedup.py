"""seedsmith.adapters.trees.nodegen.dedup — local exact Jaccard over TIER SIBLINGS (task H1,
spec-tree-language.md §6.1, §7 gate 20).

⛔ **Never the shared MinHash.** `items/setgen/dedup.py`'s own measured table stands: the shared
`SemanticDedup/NearDuplicate` metric estimates Jaccard from a 32-hash signature that over-reports by
up to 7x on names this short (`'Tier Duration'` / `'Husk of the Murmuration'`: true 0.120, MinHash
0.844). §7 gate 20 names this exact defect for the SAME reason `items/setgen/dedup.py` does: gating
the near-duplicate RATE on a signal that over-reports by 7x fails every run for the wrong reason.
`shingles` is imported from the shared metric module so tokenisation cannot drift between the two —
only the comparison differs here, same as there.

**Two uses, one function.** §6.1's `avoid_neighbour_k` (the brief's "already written in this tier —
do not repeat" list, `brief.SiblingSummary`) and §7 gate 20's corpus-level `NearDuplicate` metric
both reduce to "which of these strings is closest to this one, by exact Jaccard" — this module is
the one place that comparison lives; H4's `metrics/passive_tree.py` calls it corpus-wide, this
module's own `nearest` calls it per-tier for the brief.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from ....metrics.dedup import shingles

__all__ = ["exact_jaccard_permille", "NearestMatch", "nearest", "TierDedupReport", "tier_report"]


def exact_jaccard_permille(a: str, b: str) -> int:
    """Same arithmetic as `items/setgen/dedup.exact_jaccard_permille` — multiply before divide,
    exactly once, integer per-mille throughout."""
    sa, sb = shingles(a), shingles(b)
    union = sa | sb
    if not union:
        return 0
    return (len(sa & sb) * 1000) // len(union)


@dataclass(frozen=True)
class NearestMatch:
    node_id: str
    name: str
    jaccard_permille: int


def nearest(candidate_name: str, siblings: "Mapping[str, str]", k: int) -> "list[NearestMatch]":
    """The `k` nearest of `siblings` (`{nodeId: name}`) to `candidate_name`, by exact Jaccard,
    highest first, ties broken by `nodeId` so the result is a total function of its inputs rather
    than of dict iteration order. This is `accepted_neighbours`/`avoid_neighbour_k`'s own primitive
    (`distribution_planner/derive.py:516-522,576`), spelled out for tree names specifically."""
    if k < 0:
        raise ValueError("nearest: k must be non-negative")
    scored = sorted(
        (NearestMatch(node_id=nid, name=name,
                      jaccard_permille=exact_jaccard_permille(candidate_name, name))
         for nid, name in siblings.items()),
        key=lambda m: (-m.jaccard_permille, m.node_id),
    )
    return scored[:k]


@dataclass(frozen=True)
class TierDedupReport:
    population: int
    exact_duplicates: "tuple[tuple[str, str], ...]"
    near_duplicates: "tuple[tuple[str, str, int], ...]"  # (nodeIdA, nodeIdB, jaccardPermille)

    @property
    def rate_permille(self) -> int:
        if self.population == 0:
            return 0
        return (len(self.near_duplicates) * 1000) // self.population


def tier_report(names: "Mapping[str, str]", *, threshold_permille: int = 600) -> TierDedupReport:
    """`{nodeId: name}` -> the exact report for ONE tier's siblings. `O(n^2)` over a tier's own
    width (2-8 nodes per §3.1's archetype widths), which is trivial — the shared metric needs LSH
    because it compares the WHOLE corpus; this compares one tier."""
    ids = sorted(names)
    by_lower: "dict[str, list[str]]" = {}
    for node_id in ids:
        by_lower.setdefault(names[node_id].strip().lower(), []).append(node_id)
    exact = tuple(
        (group[i], group[j])
        for group in by_lower.values() if len(group) > 1
        for i in range(len(group)) for j in range(i + 1, len(group))
    )

    near: "list[tuple[str, str, int]]" = []
    for i, left in enumerate(ids):
        for right in ids[i + 1:]:
            if names[left].strip().lower() == names[right].strip().lower():
                continue
            score = exact_jaccard_permille(names[left], names[right])
            if score >= threshold_permille:
                near.append((left, right, score))
    return TierDedupReport(population=len(ids), exact_duplicates=exact, near_duplicates=tuple(near))
