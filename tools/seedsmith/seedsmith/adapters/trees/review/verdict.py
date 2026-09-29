"""seedsmith.adapters.trees.review.verdict — the tier-2 acceptance numbers, computed not tabled
(task J2, spec-tree-review.md §3.1, §6.3).

`gk-core/data/tuning/passive-tree-targets.v2.json`'s own `sampling.acceptanceLadder` already carries the
four `rejectsIn60 -> upperBoundPermille95` rows a human reads — this module is what makes "computed
not tabled" literally true rather than aspirational: `clopper_pearson_upper_bound_permille` is the
real exact one-sided Clopper-Pearson bound (verified against every value in the spec's own §3.1/§6.3
tables), used both to PROVE the committed ladder's four rows agree with the formula (a hand-typed
table can drift; a test that recomputes it cannot) and to resolve the "Hold. Draw 30 more" branch
(§6.3 row 3), whose real n=90 draw has no row of its own in the 60-row ladder at all.

No `scipy` (or any other numeric dependency) — this repo's own `pyproject.toml` already records the
exact debt an undeclared import creates ("D2.3... DECLARED NOWHERE until now — a fresh clone failed
... ModuleNotFoundError"), and scipy is a far heavier, compiled dependency than `jieba` was. The exact
Clopper-Pearson upper bound is instead the smallest `p` solving `BinomialCDF(k; n, p) = alpha` — found
by bisection over `math.comb`'s own exact integer binomial coefficients, pure stdlib, no approximation
beyond ordinary floating-point bisection (200 iterations converges to well under a part-per-billion,
verified against every spec value to 1e-2 already).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..targets import AcceptanceRung, PassiveTreeTargets


def _binomial_cdf(k: int, n: int, p: float) -> float:
    """`P(X <= k)` for `X ~ Binomial(n, p)`, via `math.comb`'s exact integer coefficients — never
    `scipy`, never a normal approximation (wrong exactly where this module is used: small n, tail
    probabilities)."""
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if k >= n else 0.0
    return sum(math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i)) for i in range(k + 1))


def clopper_pearson_upper_bound_permille(n: int, k: int, alpha: float = 0.05) -> int:
    """The exact one-sided (1-alpha) Clopper-Pearson upper bound on a true defect rate, given `k`
    rejects observed in `n` trials — rounded to the nearest per-mille integer, matching
    `AcceptanceRung.upper_bound_permille_95`'s own unit. `k >= n` returns 1000 (100%): no evidence
    at all bounds nothing.

    The bound is the smallest `p` for which `BinomialCDF(k; n, p) = alpha` — `BinomialCDF(k; n, p)`
    is strictly decreasing in `p` for fixed `n, k < n`, so a plain bisection converges to it.
    """
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    if k < 0:
        raise ValueError(f"k must be >= 0, got {k}")
    if k >= n:
        return 1000

    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if _binomial_cdf(k, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2 * 1000)


@dataclass(frozen=True)
class Tier2Verdict:
    """One tier-2 draw's outcome (§6.3's own four-row ladder, plus the n=90 hold-redraw case it
    points to but does not tabulate). `matched_rung` is the COMMITTED ladder row this resolved
    against, when one exists at this exact `(n, k)` — `None` for the n=90 hold-redraw case, which is
    resolved purely from the formula since no committed row covers it."""

    n: int
    k: int
    upper_bound_permille: int
    verdict: str
    matched_rung: "AcceptanceRung | None"


def resolve_tier2_verdict(rejects: int, targets: PassiveTreeTargets, *,
                          sample_size: "int | None" = None) -> Tier2Verdict:
    """§6.3's own ladder, resolved for a real draw. `sample_size` defaults to
    `targets.tier2_sample_size` (60) for the FIRST draw; the caller passes
    `targets.tier2_sample_size + targets.tier3_additional_sample_size` (90) for the "Hold, draw 30
    more" branch's own second draw (§6.3 row 3's own worked example: "2 in 90 -> <= 6.83%").

    Every number is computed fresh via `clopper_pearson_upper_bound_permille`, never read off the
    ladder directly — the ladder is consulted only to find which COMMITTED row (if any) names this
    exact `(n, k)`, for its `verdict` label and as the cross-check that the committed table has not
    drifted from the formula (`AcceptanceLadderAgreesWithTheFormulaTests` in the test file proves this
    for the four rows that exist).
    """
    n = sample_size if sample_size is not None else targets.tier2_sample_size
    bound = clopper_pearson_upper_bound_permille(n, rejects)

    matched = next(
        (rung for rung in targets.acceptance_ladder
         if rung.rejects_in_60 == rejects and n == targets.tier2_sample_size),
        None)

    if matched is not None:
        verdict = matched.verdict
    elif rejects > max((r.rejects_in_60 for r in targets.acceptance_ladder), default=-1):
        # Beyond the ladder's own worst-named row (>= 3 rejects in 60, or the equivalent share at a
        # different n) -- §6.3's own rung 4, "more than one tree in ten is bad; fix the prompt."
        verdict = "batch-reject"
    else:
        # A real n (e.g. 90, the hold-redraw draw) with no committed row at all -- resolved purely
        # from the formula, named honestly as "not one of the tabled rows" rather than guessing
        # which label it should inherit.
        verdict = "computed-not-tabled"

    return Tier2Verdict(n=n, k=rejects, upper_bound_permille=bound, verdict=verdict,
                        matched_rung=matched)
