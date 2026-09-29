"""seedsmith.numerics.model — locked shape constants, `ProgressionModel`, `TierBands`.

Locked constants below are transcribed from `gk-data/packs/fusion/data/seed/items/_registry/bands.v1.json`'s
`powerBand.tierScaling` block (read fresh 2026-08-23) — code, not data, per spec-numerics.md §3.1's
own layering ("Shape — the formulas — code, versioned with the module — changes when a locked
registry constant changes, rare, needs a registry bump"). `numerics` never opens that file at
runtime; this is the one place the values are copied, with citation, so drift is auditable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol


class OpWeight(Enum):
    FLAT = "Flat"
    INCREASED = "Increased"
    MORE = "More"


# bands.v1.json powerBand.tierScaling — referenceLevel, magnitudeRatioPerMille,
# durationRatioPerMille, bandFloorPerMille, bandCeilingPerMille.
REFERENCE_LEVEL = 20
MAGNITUDE_RATIO_PERMILLE = 1750         # r = 1.75, t1->t5 spans ~9.4x
DURATION_RATIO_PERMILLE = 1400          # r = 1.4, MANDATORY for a status.apply duration ladder
BAND_FLOOR_PERMILLE = 670               # -33% around a tier midpoint
BAND_CEILING_PERMILLE = 1330            # +33% around a tier midpoint
TIER_COUNT = 5

DEFAULT_OP_WEIGHTS: dict[OpWeight, int] = {
    OpWeight.FLAT: 1000,
    OpWeight.INCREASED: 1000,
    OpWeight.MORE: 550,        # ~1/1.8: multiplicative compounds where Increased dilutes
}


@dataclass(frozen=True)
class ProgressionPoint:
    """What a magnitude resolves against. `level` is `BattleRulesetProgression`'s one axis today;
    a future progression model may add map/run — spec-numerics.md §6.2 keeps that swap possible
    by putting the whole thing behind `ProgressionModel`, not by growing this dataclass in
    advance of the design that would justify it.
    """

    level: int


class ProgressionModel(Protocol):
    def reference_base(self, channel: str, point: ProgressionPoint) -> int: ...
    def axis(self) -> str: ...
    def content_ladder(self) -> "list | None": ...


@dataclass(frozen=True)
class BattleRulesetProgression:
    """Implements `ProgressionModel` by reading the adapter's own `Channel.reference_base`
    callables (spec-foundation §7.1: numerics gets reference bases from `adapter.channels()`,
    never from `gk-data/packs/fusion/data/seed/items/` directly). `content_ladder()` returns `None` — progression is a
    stub (spec-numerics.md §6.2) — so `Balance/LadderInversion` must report `NOT_MEASURED`, never
    a pass, for as long as this is the active model.
    """

    channels_by_id: "dict[str, object]"  # channel id -> Channel (has .reference_base(level))

    @classmethod
    def from_adapter(cls, adapter) -> "BattleRulesetProgression":
        return cls(channels_by_id={c.id: c for c in adapter.channels()})

    def reference_base(self, channel: str, point: ProgressionPoint) -> int:
        return self.channels_by_id[channel].reference_base(point.level)

    def axis(self) -> str:
        return "level"

    def content_ladder(self):
        return None


@dataclass(frozen=True)
class NumericsContext:
    """What `Ctx.numerics` holds — `resolve()` needs both a `TierBands` and a `ProgressionModel`,
    and `Ctx` has one generic `numerics` slot, so this bundles them rather than growing `Ctx`
    itself with numerics-specific fields."""

    tuning: "TierBands"
    progression: ProgressionModel


@dataclass(frozen=True)
class TierBands:
    """The one genuinely tunable surface (spec-numerics.md §2, §3.1). `channel_weight` has no
    default: a channel absent from it is an unshared channel, and `resolve()` must raise rather
    than guess (spec-numerics.md §3.3, "no silent defaults" — the registry's own instruction).
    """

    version: int
    base_share_permille: int
    channel_weight_permille: "dict[str, int]"   # e.g. {"vitality": 1000} for weight 1.0
    op_weight_permille: "dict[OpWeight, int]" = field(
        default_factory=lambda: dict(DEFAULT_OP_WEIGHTS))

    @classmethod
    def load(cls, version: "int | str" = "latest") -> "TierBands":
        from . import tier_bands_io
        return tier_bands_io.load(version)

    def share_permille(self, channel: str, op: OpWeight) -> int:
        if channel not in self.channel_weight_permille:
            from .resolve import UnsharedChannelError
            raise UnsharedChannelError(channel)
        weight = self.channel_weight_permille[channel]
        op_w = self.op_weight_permille.get(op, 1000)
        return round(self.base_share_permille * weight * op_w / 1_000_000)

    def adjust(self, overrides: "dict[str, float]") -> "TierBands":
        """Returns a NEW TierBands with `overrides` applied — never mutates. Keys are
        `"channelWeight.<id>"` or `"baseShare"`; values are plain ratio multipliers (e.g. `0.85`
        for 85%), exactly matching spec-numerics.md §3.2's worked example
        (`{"channelWeight.might": 0.85}`) — stored internally as per-mille integers."""
        base_share = self.base_share_permille
        weights = dict(self.channel_weight_permille)
        prefix = "channelWeight."
        for key, ratio in overrides.items():
            if key == "baseShare":
                base_share = round(ratio * 1000)
            elif key.startswith(prefix):
                weights[key[len(prefix):]] = round(ratio * 1000)
        return TierBands(version=self.version, base_share_permille=base_share,
                         channel_weight_permille=weights,
                         op_weight_permille=dict(self.op_weight_permille))
