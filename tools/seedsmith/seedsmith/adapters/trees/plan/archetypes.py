"""seedsmith.adapters.trees.plan.archetypes — the three shape archetypes, the mechanism/magnitude
ramp, and R-A1's reward-spread refusal (spec-tree-plan.md §3.1, §4, task B1).

Structural constants (spec-tree-plan.md "Structural, in code" table) — changing any of these
re-mints every node id, which is a migration under D24, not a balance pass. They stay `const`-shaped
Python module constants, never tunables.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import gcd

from .ladder import (  # noqa: F401 (re-exported for archetypes' own math)
    LadderError,
    _round_half_up,
    node_budget_milli,
    tier_budget_milli,
)

TIER_COUNT = 10
BRANCH_COUNT = 2
NODES_PER_BRANCH = 20
PAIRING_RULE = "power-linear-in-tier"  # D20: one legal value


@dataclass(frozen=True)
class Archetype:
    id: str
    widths: "tuple[int, ...]"  # per-tier node count, one branch, len == TIER_COUNT, sum == NODES_PER_BRANCH

    def __post_init__(self) -> None:
        if len(self.widths) != TIER_COUNT:
            raise LadderError(f"{self.id}: widths has {len(self.widths)} entries, need {TIER_COUNT}")
        if sum(self.widths) != NODES_PER_BRANCH:
            raise LadderError(f"{self.id}: widths sum to {sum(self.widths)}, need {NODES_PER_BRANCH}")


# The shipped three, verified digit-for-digit against spec-tree-plan.md §3's worked node-budget
# tables before this module was written (see tests/test_tree_plan_ladder.py).
BROAD_AND_FLAT = Archetype("broad-and-flat", (2, 2, 2, 2, 2, 2, 2, 2, 2, 2))
GATED_DEEP = Archetype("gated-deep", (3, 3, 3, 2, 2, 2, 2, 1, 1, 1))
LATE_CROWN = Archetype("late-crown", (1, 1, 2, 2, 2, 2, 2, 2, 3, 3))

SHIPPED_ARCHETYPES: "tuple[Archetype, ...]" = (BROAD_AND_FLAT, GATED_DEEP, LATE_CROWN)


def assign_archetype(tree_ordinal: int, archetypes: "tuple[Archetype, ...]" = SHIPPED_ARCHETYPES) -> Archetype:
    """Deterministic and append-safe: `archetype(tree) = archetypes[ordinal(tree) mod len(archetypes)]`
    (spec-tree-plan.md §3.1). Roster ordinals are append-only, so this never reassigns an existing
    tree's archetype when the roster grows."""
    if not archetypes:
        raise LadderError("at least one archetype is required")
    return archetypes[tree_ordinal % len(archetypes)]


def mechanism_share_milli(t: int, tier_count: int, ramp_start_milli: int, ramp_end_milli: int) -> int:
    """`mechShareMilli[t] = rampStartMilli + (rampEndMilli - rampStartMilli)*(t-1)/(tierCount-1)`
    (spec-tree-plan.md §4), rounded half up. Pinned: at `t == tierCount` this equals
    `rampEndMilli` exactly (division by `tierCount-1` gives `t-1 == tierCount-1`)."""
    if tier_count < 2:
        raise LadderError("mechanism ramp needs tierCount >= 2 (a single tier has no ramp to walk)")
    if not (1 <= t <= tier_count):
        raise LadderError(f"tier {t} out of range 1..{tier_count}")
    span = ramp_end_milli - ramp_start_milli
    return ramp_start_milli + _round_half_up(span * (t - 1), tier_count - 1)


def mechanism_nodes(archetype: Archetype, tier_count: int, ramp_start_milli: int, ramp_end_milli: int) -> "tuple[int, ...]":
    """Per-tier COUNT of mechanism-class nodes for one archetype (spec-tree-plan.md §4) — an exact
    count, never a threshold. `mechNodes[tierCount] == widths[tierCount-1]` is `R-M1`: the deepest
    tier is 100% mechanism by construction, since `mechanism_share_milli` returns exactly
    `ramp_end_milli` there."""
    return tuple(
        _round_half_up(archetype.widths[t - 1] * mechanism_share_milli(t, tier_count, ramp_start_milli, ramp_end_milli), 1000)
        for t in range(1, tier_count + 1)
    )


class RewardSpreadRefusal(LadderError):
    """R-A1: the reward-per-skill-point spread across archetypes at one tier exceeds the configured
    bound. Names the tier and the two archetypes at the extremes, never silently accepted."""


def reward_per_skill_point(archetype: Archetype, t: int, unlock_first: int, unlock_step: int) -> "tuple[int, int]":
    """`r_a(t) = W(t) / cost(N_a(t))` as an exact `(numerator, denominator)` fraction over `b`
    (spec-tree-plan.md §3.1). `N_a(t) = 2 * sum(widths[:t])` (both branches); `cost(N) = N(N+4)` at
    `first=5, step=2` generalises to `cost(N) = N*(N-1)*step/2 + N*first` for any `(first, step)`."""
    if not (1 <= t <= TIER_COUNT):
        raise LadderError(f"tier {t} out of range 1..{TIER_COUNT}")
    n = 2 * sum(archetype.widths[:t])
    cost = n * (n - 1) * unlock_step // 2 + n * unlock_first
    w = t * (t + 1) // 2  # b=1; b cancels across archetypes at the same tier
    if cost == 0:
        raise LadderError(f"{archetype.id} at tier {t}: N={n} gives cost 0 — cannot form a reward ratio")
    g = gcd(w, cost)
    return (w // g, cost // g)


def check_reward_spread(archetypes: "tuple[Archetype, ...]", tier_count: int,
                        unlock_first: int, unlock_step: int, max_ratio_milli: int) -> None:
    """R-A1, walked at EVERY tier (not only `t == tierCount`, which is the one point the historical
    defect could not appear at — spec-tree-plan.md §3.1's own account of why the missing check went
    unnoticed). Raises naming the tier and the two archetypes at the extremes."""
    for t in range(1, tier_count + 1):
        ratios = [(a.id, *reward_per_skill_point(a, t, unlock_first, unlock_step)) for a in archetypes]

        # Find the max and min ratio by cross-multiplication — never divide to a float.
        def frac_ge(a, b):
            (_, an, ad), (_, bn, bd) = a, b
            return an * bd >= bn * ad
        hi = ratios[0]
        lo = ratios[0]
        for r in ratios[1:]:
            if frac_ge(r, hi):
                hi = r
            if frac_ge(lo, r):
                lo = r
        hi_id, hi_n, hi_d = hi
        lo_id, lo_n, lo_d = lo
        # spread = (hi_n/hi_d) / (lo_n/lo_d) = (hi_n*lo_d) / (hi_d*lo_n), compared to max_ratio_milli/1000
        if hi_n * lo_d * 1000 > max_ratio_milli * hi_d * lo_n:
            raise RewardSpreadRefusal(
                f"tier {t}: reward-per-skill-point spread {hi_id}({hi_n}/{hi_d}) vs "
                f"{lo_id}({lo_n}/{lo_d}) exceeds archetype.rewardSpreadMaxRatioMilli={max_ratio_milli}")


def reward_per_point_milli_by_tier(archetype: Archetype, unlock_first: int, unlock_step: int) -> "tuple[int, ...]":
    """`archetypes[].rewardPerPointMilli[]` (spec-tree-plan.md's frozen schema table): the §3.1
    pacing gradient, emitted per tier so a diff between two archetypes shows it directly.

    Every value here is `r_a(t) / r_a(tierCount)`, in per-mille, as an exact integer ratio — `b`
    cancels top and bottom (same reasoning as `reward_per_skill_point`'s own docstring), so this
    needs no external power constant and is `1000` at `t == tierCount` BY CONSTRUCTION (numerator
    and denominator become the same fraction there). This is the concrete milli encoding C1 task
    resolved for the schema's `rewardPerPointMilli[]` field — the spec names the field and the
    property it must show (the tier-2 gradient) but not its exact units, so self-normalizing
    against the archetype's own completion value is the stated default: it needs no `b`, is
    dimensionless, and reproduces the spec's own worked spread (§3.1's 6.0x at tier 2, 1.00x at
    completion) once compared across archetypes.
    """
    w_t_over_cost_t = [reward_per_skill_point(archetype, t, unlock_first, unlock_step) for t in range(1, TIER_COUNT + 1)]
    complete_n, complete_d = w_t_over_cost_t[-1]
    result = []
    for (n, d) in w_t_over_cost_t:
        # r_a(t)/r_a(T) = (n/d) / (complete_n/complete_d) = (n*complete_d) / (d*complete_n)
        numerator = n * complete_d * 1000
        denominator = d * complete_n
        result.append(_round_half_up(numerator, denominator))
    return tuple(result)


def max_node_milli(archetype: Archetype, tier_count: int) -> int:
    """`archetypes[].maxNodeMilli` (spec-tree-plan.md's frozen schema table): the archetype's own
    single largest node, ‰ of one branch — what `archetype_shapes_actually_differ` (C1's inverse
    guard, task C1) compares across the archetype set. Recomputes from the same `tier_budget_milli`
    / `node_budget_milli` pair `build_plan` uses, never a second formula."""
    shares = tier_budget_milli(tier_count)
    return max(
        max(node_budget_milli(shares[t - 1], archetype.widths[t - 1]))
        for t in range(1, tier_count + 1)
    )
