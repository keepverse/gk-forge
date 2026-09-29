"""seedsmith.adapters.trees.plan.ladder — the tier ladder and the budget column
(spec-tree-plan.md §2-3, task B1).

`req(t)` gates on APTITUDE POINTS (R1/R-G0), never skill points — a different currency from
`tree-state`'s unlock cost. `W(T)` is the cumulative tree power at tier `T`, linear per tier (D20's
pairing rule). Every value here is an exact integer: `t(t+1)` is a product of consecutive integers
and therefore always even, so `k*t(t+1)//2` has no remainder for any integer `k` — no rounding ever
enters the aptitude ladder.

The budget column and the per-node split DO round (per-mille of one branch budget cannot divide
evenly in general) — both use the same "round half up, residual to the LAST slot" rule, verified
digit-for-digit against spec-tree-plan.md §3's own worked tables for all three shipped archetypes
before this module was written (never assume a derivation matches worked examples — check it).
"""
from __future__ import annotations

from dataclasses import dataclass


class LadderError(ValueError):
    """A ladder or budget computation was asked for an input it cannot answer safely."""


def req(t: int, k: int) -> int:
    """D26's tier-gate threshold, in aptitude points. `t(t+1)` is always even, so this is exact —
    never a source of rounding drift."""
    if t < 1:
        raise LadderError(f"tier must be >= 1, got {t}")
    return k * t * (t + 1) // 2


def cumulative_power(big_t: int, b: int) -> int:
    """`W(T) = b * T(T+1)/2` — cumulative tree power at tier `T`, per D20's linear-per-tier
    pairing rule. `b` is the per-tier power constant; both this and `req` share `t(t+1)/2`, which is
    why `W(T)/req(T) = b/k` exactly (the shared factor cancels — spec-tree-plan.md §2)."""
    if big_t < 1:
        raise LadderError(f"tier must be >= 1, got {big_t}")
    return b * big_t * (big_t + 1) // 2


def _round_half_up(numerator: int, denominator: int) -> int:
    """Exact integer round-half-up via the `(2n + d) // (2d)` identity — no float anywhere, per
    docs/architecture/numeric-types.md's numeric-overflow rule (a per-mille magnitude is exactly the kind of value that must
    never touch a float)."""
    if denominator <= 0:
        raise LadderError(f"denominator must be positive, got {denominator}")
    return (2 * numerator + denominator) // (2 * denominator)


def tier_budget_milli(tier_count: int) -> "tuple[int, ...]":
    """`tierBudget[t] = B_b * t / T_tri` in per-mille of one branch budget `B_b`
    (spec-tree-plan.md §3). Each tier's exact share is rounded half up independently; the residual
    (1000 minus the sum of the rounded values) is folded entirely into the DEEPEST tier — verified
    to be 0 at tierCount=10 (the shipped topology), and stated as still binding for any other count
    because two correct-looking round-half-up implementations can disagree in the last per-mille.

    `Σ_t t == T_tri` by definition, so the archetype's own width vector never enters this sum at
    all — every archetype spends exactly `B_b` per branch by construction, not by normalisation.
    """
    if tier_count < 1:
        raise LadderError(f"tier_count must be >= 1, got {tier_count}")
    t_tri = tier_count * (tier_count + 1) // 2
    shares = [_round_half_up(t * 1000, t_tri) for t in range(1, tier_count + 1)]
    residual = 1000 - sum(shares)
    shares[-1] += residual
    return tuple(shares)


def node_budget_milli(tier_share_milli: int, width: int) -> "tuple[int, ...]":
    """Split one tier's per-mille budget share across `width` nodes: `base = tier_share // width`
    (floor), the first `width - 1` nodes each get `base`, and the LAST node in the tier absorbs the
    entire remainder (`tier_share - base*width`). Not "round half up per node" — verified against
    every cell of all three shipped archetypes' worked tables in spec-tree-plan.md §3 (e.g. tier 3,
    width 2, share 55 -> [27, 28], never [28, 27] or [28, 28])."""
    if width < 1:
        raise LadderError(f"width must be >= 1, got {width}")
    base = tier_share_milli // width
    remainder = tier_share_milli - base * width
    return tuple([base] * (width - 1) + [base + remainder])


@dataclass(frozen=True)
class TierLadder:
    tier_count: int
    req_scale_points: int
    b: int

    @property
    def req_by_tier(self) -> "tuple[int, ...]":
        return tuple(req(t, self.req_scale_points) for t in range(1, self.tier_count + 1))

    @property
    def cumulative_power_by_tier(self) -> "tuple[int, ...]":
        return tuple(cumulative_power(t, self.b) for t in range(1, self.tier_count + 1))

    def reward_per_point(self, t: int) -> "tuple[int, int]":
        """`(numerator, denominator)` of `W(t)/req(t)` in lowest terms over `b` — i.e. returns
        `(1, k)` meaning `b/k`, since `b` itself cancels (spec-tree-plan.md §2). Exact rational,
        never a float."""
        w = cumulative_power(t, 1)  # b=1 so the result IS the b-coefficient
        r = req(t, self.req_scale_points)
        from math import gcd
        g = gcd(w, r)
        return (w // g, r // g)
