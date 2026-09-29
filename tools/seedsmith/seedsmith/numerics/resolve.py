"""seedsmith.numerics.resolve — `resolve()` and `explain()`, with every guardrail from
spec-numerics.md §3.3 asserted on every call, not left to the caller to remember.
"""
from __future__ import annotations

from dataclasses import dataclass

from .formulas import band, primary_channel_m1, tier_ladder
from .model import REFERENCE_LEVEL, TIER_COUNT, OpWeight, ProgressionModel, ProgressionPoint, TierBands


class UnsharedChannelError(ValueError):
    """A channel with no authored `channelWeight` — the registry's own instruction: "a generator
    with no authored share for a channel must reject at import, not guess one." """

    def __init__(self, channel: str) -> None:
        super().__init__(f"channel {channel!r} has no authored channelWeight in this TierBands "
                         f"version — refusing to guess one")
        self.channel = channel


class CalibrationLevelError(ValueError):
    """`referenceLevel` (20) is a CALIBRATION anchor, never an evaluation point
    (spec-numerics.md §6.3) — resolving shipping content at the literal calibration level is the
    single easiest misreading of this spec, and this guardrail is what catches it."""

    def __init__(self, level: int) -> None:
        super().__init__(
            f"resolve() was called at level {level}, the calibration anchor — pass "
            f"allow_calibration_level=True if this is genuinely the calibration case, not a "
            f"shipping resolve")


@dataclass(frozen=True)
class ResolvedMagnitude:
    channel: str
    op: OpWeight
    tier: int
    share_permille: int
    reference_base: int
    m1: int
    ladder: "tuple[int, ...]"
    lo: int
    hi: int

    @property
    def value(self) -> int:
        return self.ladder[self.tier - 1]


def _assert_guardrails(ladder: "list[int]", bands: "list[tuple[int, int]]") -> None:
    for i in range(1, len(ladder)):
        if not ladder[i - 1] < ladder[i]:
            raise AssertionError(
                f"monotonicity violated: tier {i} magnitude {ladder[i - 1]} is not < "
                f"tier {i + 1} magnitude {ladder[i]}")
    for m_t, (lo, hi) in zip(ladder, bands):
        if not (lo <= m_t <= hi):
            raise AssertionError(f"band containment violated: {lo} <= {m_t} <= {hi} is false")
    for i in range(len(bands) - 1):
        hi_t = bands[i][1]
        lo_next = bands[i + 1][0]
        # OD4: overlap is REQUIRED, not forbidden — hi_t >= lo_(t+1). An earlier draft of this
        # spec asserted the opposite (hi_t < lo_(t+1)) and would have raised on every resolve;
        # `<` here (not `<=`) is deliberate so a TIE (hi_1 == lo_2, e.g. might's hi_1=lo_2=5) is
        # accepted, exactly as bands.v1.json's own registry text requires.
        if hi_t < lo_next:
            raise AssertionError(
                f"OD4 overlap violated: tier {i + 1}'s hi ({hi_t}) must be >= tier {i + 2}'s "
                f"lo ({lo_next}) — a well-rolled lower rung must be able to beat a "
                f"badly-rolled higher one")


def resolve(channel: str, op: OpWeight, tier: int, tuning: TierBands,
           progression: ProgressionModel, point: ProgressionPoint, *,
           allow_calibration_level: bool = False) -> ResolvedMagnitude:
    if point.level == REFERENCE_LEVEL and not allow_calibration_level:
        raise CalibrationLevelError(point.level)
    if not (1 <= tier <= TIER_COUNT):
        raise ValueError(f"tier must be in 1..{TIER_COUNT}, got {tier}")

    share = tuning.share_permille(channel, op)          # raises UnsharedChannelError
    reference_base = progression.reference_base(channel, point)
    m1 = primary_channel_m1(share, reference_base)
    ladder = tier_ladder(m1, TIER_COUNT)
    bands = [band(m_t) for m_t in ladder]

    _assert_guardrails(ladder, bands)

    lo, hi = bands[tier - 1]
    return ResolvedMagnitude(
        channel=channel, op=op, tier=tier, share_permille=share, reference_base=reference_base,
        m1=m1, ladder=tuple(ladder), lo=lo, hi=hi,
    )


def explain(channel: str, op: OpWeight, tier: int, tuning: TierBands,
           progression: ProgressionModel, point: ProgressionPoint, *,
           allow_calibration_level: bool = False) -> str:
    """The derivation chain for one entry — share, reference base, tier, ratio, rounding — so a
    balance disagreement lands on a specific line of a specific formula (spec-numerics.md §3.4)
    rather than two people asserting numbers at each other."""
    r = resolve(channel, op, tier, tuning, progression, point,
               allow_calibration_level=allow_calibration_level)
    return (
        f"channel={channel} op={op.value} tier={r.tier}/{5}\n"
        f"  sharePermille = {r.share_permille} (base_share x channelWeight x opWeight)\n"
        f"  referenceBase({progression.axis()}={point.level}) = {r.reference_base}\n"
        f"  m1 = round_legible({r.share_permille} x {r.reference_base} / 1000) = {r.m1}\n"
        f"  ladder (r=1.75 per tier) = {list(r.ladder)}\n"
        f"  m_{r.tier} = {r.value}, band = [{r.lo}, {r.hi}] (-33%/+33%)"
    )
