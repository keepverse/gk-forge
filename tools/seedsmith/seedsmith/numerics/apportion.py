"""seedsmith.numerics.apportion — largest-remainder (Hamilton) apportionment
(spec-numerics.md §3.3 "Apportionment closure", spec-analytics.md §9.2).

Naive `round(total * weight)` per bucket does not sum back to `total` — rounding drift — so a
budget silently gains or loses points and every downstream check inherits the error. Largest
remainder is exact by construction: floor everything, then hand the remaining units to the
largest fractional remainders.

The Alabama paradox (increasing `total` can decrease an individual share) is real and irrelevant
here, because `total` is a fixed per-mille budget (1000), never something that grows — noted so
the next reader does not re-litigate it (spec-analytics §9.2).
"""
from __future__ import annotations


def largest_remainder_apportion(total: int, weights: "dict[str, int]") -> "dict[str, int]":
    """Split `total` integer units across `weights` (proportional, any positive integers),
    returning integer shares that sum EXACTLY to `total`."""
    weight_sum = sum(weights.values())
    if weight_sum <= 0:
        raise ValueError("apportionment weights must sum to a positive number")

    exact = {key: total * w / weight_sum for key, w in weights.items()}
    floors = {key: int(v) for key, v in exact.items()}
    remainders = {key: exact[key] - floors[key] for key in weights}

    shortfall = total - sum(floors.values())
    # Largest remainder first; ties broken by key for determinism (never by insertion order,
    # which is not a property callers should be able to depend on).
    ranked = sorted(remainders, key=lambda k: (-remainders[k], k))
    result = dict(floors)
    for key in ranked[:shortfall]:
        result[key] += 1
    return result
