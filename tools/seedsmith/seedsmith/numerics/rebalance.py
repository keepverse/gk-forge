"""seedsmith.numerics.rebalance — `rebalance()` (a diff, never a mutation) and
`solve_base_share()` (spec-numerics.md §3.2, §6.1).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .model import TIER_COUNT, MAGNITUDE_RATIO_PERMILLE, OpWeight, ProgressionModel, ProgressionPoint, TierBands
from .resolve import resolve


@dataclass(frozen=True)
class Move:
    channel: str
    op: OpWeight
    tier: int
    before: int
    after: int

    @property
    def delta(self) -> int:
        return self.after - self.before


@dataclass(frozen=True)
class RebalanceReport:
    moves: "tuple[Move, ...]"

    def largest_movers(self, n: int = 10) -> "list[Move]":
        return sorted(self.moves, key=lambda m: -abs(m.delta))[:n]

    def is_noop(self) -> bool:
        return all(m.delta == 0 for m in self.moves)

    def publish(self, tuning: TierBands, version: int) -> TierBands:
        """Returns a NEW TierBands stamped with `version` — writing it to
        `data/seed/items/_tuning/tier-bands.v{version}.json` is the CLI's job
        (`seedsmith numerics rebalance --publish`), not this module's; `rebalance()` itself never
        touches disk, matching spec-numerics.md §3.2 ("nothing until publish")."""
        return TierBands(version=version, base_share_permille=tuning.base_share_permille,
                         channel_weight_permille=dict(tuning.channel_weight_permille),
                         op_weight_permille=dict(tuning.op_weight_permille))


def all_channel_op_tier_triples(tuning: TierBands) -> "list[tuple[str, OpWeight, int]]":
    return [(channel, op, tier)
           for channel in sorted(tuning.channel_weight_permille)
           for op in OpWeight
           for tier in range(1, TIER_COUNT + 1)]


def rebalance(before: TierBands, after: TierBands, progression: ProgressionModel,
             point: ProgressionPoint, *, triples=None,
             allow_calibration_level: bool = False) -> RebalanceReport:
    """What would move, and by how much — every magnitude resolvable under BOTH tunings,
    grouped so the caller can sort by largest movers. `triples` defaults to every
    (channel, op, tier) `before` has an authored share for; pass an explicit list to scope a
    diff to specific channels without needing corpus-wide affix->channel mining, which is a
    separate, unverified piece of domain knowledge this function does not depend on."""
    triples = triples if triples is not None else all_channel_op_tier_triples(before)
    moves = []
    for channel, op, tier in triples:
        b = resolve(channel, op, tier, before, progression, point,
                   allow_calibration_level=allow_calibration_level)
        a = resolve(channel, op, tier, after, progression, point,
                   allow_calibration_level=allow_calibration_level)
        moves.append(Move(channel=channel, op=op, tier=tier, before=b.value, after=a.value))
    return RebalanceReport(moves=tuple(moves))


def solve_base_share(target_level_delta: int, reference_level: int, *,
                     affixes_per_item: float, mean_tier: float, effective_channels: float = 5.0,
                     slots: int = 15, ratio_permille: int = MAGNITUDE_RATIO_PERMILLE,
                     base_curve=lambda level: 80 + 30 * level) -> float:
    """Solve `baseShare` (permille) from a level-invariant target: "full gear is worth fighting
    `target_level_delta` levels above you" (spec-numerics.md §6.1's correction — a raw multiplier
    is not level-invariant when both sides share BattleRuleset's linear curve, a level delta is).

    Linear algebra, not iterative: `gain_per_channel = (slots * affixes_per_item /
    effective_channels) * baseShare/1000 * ratio^(mean_tier-1)` is linear in `baseShare`, so this
    solves in closed form once the target multiplier is known.

    `base_curve` defaults to `BattleRuleset.BaseHp` (`80 + 30*level`, `BattleModels.cs:61`) as the
    anchor curve for the level-delta -> multiplier conversion — the worked table in
    spec-numerics.md §6.1 tracks a survivability-style multiplier, and HP is what "naked vs
    geared" most naturally anchors to; pass a different `base_curve` to anchor against another
    channel's reference base instead.

    `affixes_per_item` and `mean_tier` are REQUIRED, not defaulted: spec-numerics.md gives no
    stated default for either (only "effectiveChannels ~ 5" is offered as an approximation), and
    guessing values that were never written down would silently fabricate a design input.
    """
    multiplier = base_curve(reference_level + target_level_delta) / base_curve(reference_level)
    ratio_factor = (ratio_permille / 1000) ** (mean_tier - 1)
    per_share_gain = (slots * affixes_per_item / effective_channels) * ratio_factor / 1000
    return (multiplier - 1) / per_share_gain
