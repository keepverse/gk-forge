"""seedsmith.numerics.pava — pool-adjacent-violators isotonic regression
(spec-analytics.md §5).

A correlation says a power ladder is *mostly* right; it never says *which rung* is wrong. PAVA
fits the closest monotone non-decreasing sequence to the observed one, and the points it had to
pool into the same block **are** the inversions, by construction — that is the finding, not a
correlation coefficient nobody can act on.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PoolBlock:
    fitted_value: float
    start: int
    end: int          # inclusive; end > start means this block pooled >=2 raw points

    @property
    def pooled(self) -> bool:
        return self.end > self.start


def pava(values: "list[float]") -> "list[PoolBlock]":
    """O(n) pool-adjacent-violators for a non-decreasing fit. Returns the blocks in order; a
    block with `pooled=True` is exactly the run of original points PAVA had to merge because they
    violated monotonicity against their neighbours."""
    blocks: "list[list]" = []  # each: [sum, weight, start, end]
    for i, v in enumerate(values):
        blocks.append([v, 1, i, i])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            b2 = blocks.pop()
            b1 = blocks.pop()
            blocks.append([b1[0] + b2[0], b1[1] + b2[1], b1[2], b2[3]])
    return [PoolBlock(fitted_value=total / weight, start=start, end=end)
           for total, weight, start, end in blocks]
