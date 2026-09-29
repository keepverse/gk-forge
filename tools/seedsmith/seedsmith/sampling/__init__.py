"""seedsmith.sampling — stratified sampling for open-loop review (spec-analytics.md §8).

Simple random sampling is the wrong tool: with many small strata, a random N over-represents
whichever stratum is largest and can miss a whole band entirely. This guarantees at least one
sample per non-empty stratum (when `n` allows), then distributes the remainder proportionally via
largest-remainder apportionment (reused from `numerics`, not re-implemented) — a corpus fails in
its neglected corners, and "even the smallest band gets looked at" is the property that matters.

Seeded from `metric id + corpus revision` (never wall-clock or `random` module state, which this
workflow's runtime disallows anyway) so the same sample is reproducible: a reviewer can re-read
exactly what they read last week and diff their own judgement against it.
"""
from __future__ import annotations

import hashlib

from ..numerics.apportion import largest_remainder_apportion


def corpus_revision(corpus) -> str:
    """A stable content hash, not a git hash — changes exactly when the corpus does, and works
    the same whether or not the working tree matches HEAD."""
    ids = sorted(corpus.entries)
    return hashlib.sha256("|".join(ids).encode("utf-8")).hexdigest()[:16]


def _seeded_shuffle_order(items: "list[str]", seed_key: str) -> "list[str]":
    """A deterministic permutation of `items` — stdlib `random.Random` seeded from a stable
    string-derived integer (never the unseeded global `random` state)."""
    import random
    seed_int = int(hashlib.sha256(seed_key.encode("utf-8")).hexdigest(), 16)
    rng = random.Random(seed_int)
    ordered = list(items)
    rng.shuffle(ordered)
    return ordered


def stratified_sample(items_by_stratum: "dict[str, list]", n: int, *, metric_id: str,
                      revision: str) -> "dict[str, list]":
    """Returns `{stratum: [sampled items]}`. `n` is the TOTAL sample size across all strata.

    Every non-empty stratum gets at least one sample (bounded by its own size and by `n` overall);
    the remainder is split across strata proportional to stratum size via largest-remainder.
    """
    non_empty = {k: v for k, v in items_by_stratum.items() if v}
    if not non_empty or n <= 0:
        return {}

    seed_key = f"{metric_id}:{revision}"
    guaranteed = min(1, n)
    base_allocation = {k: min(guaranteed, len(v)) for k, v in non_empty.items()}
    remaining = n - sum(base_allocation.values())

    if remaining > 0:
        weights = {k: len(v) for k, v in non_empty.items()}
        extra = largest_remainder_apportion(remaining, weights)
        for k in base_allocation:
            base_allocation[k] = min(base_allocation[k] + extra.get(k, 0), len(non_empty[k]))

    result = {}
    for stratum, items in non_empty.items():
        count = base_allocation[stratum]
        if count <= 0:
            continue
        ordered = _seeded_shuffle_order([str(i) for i in range(len(items))],
                                        f"{seed_key}:{stratum}")
        picked_indices = sorted(int(i) for i in ordered[:count])
        result[stratum] = [items[i] for i in picked_indices]
    return result
