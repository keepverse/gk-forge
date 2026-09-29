"""seedsmith.adapters.items.channels — the 14 primaryChannel families from
`gk-data/packs/fusion/data/seed/items/_registry/bands.v1.json`'s `powerBand.channelFamilyGroups.primaryChannel`,
each wired to a `reference_base` that mirrors
`gk-core/src/FusionRpg.Core/Battle/BattleModels.cs`'s `BattleRuleset` formulas (transcribed with citation
below — there is no JSON export of that C# class to read instead).

The 14→3-formula grouping (which channel points at which of BattleRuleset's three baselines) is a
plain semantic read of each channel's own name, not a numeric or balance judgment: no number here
was chosen by this module, every one is copied verbatim from `BattleRuleset`. Which formula a
channel's magnitude should ultimately resolve against is real balance work and stays `numerics`'
job (S5) once `docs/architecture/power/ssot-power-scale.md`'s `ProgressionPoint` exists — this
module only proves `channels()` returns real, citable baselines rather than an empty placeholder.
"""
from __future__ import annotations

from ..base import Channel, Unit

# BattleRuleset.BaseHp/BaseAtk/RoundDurationMs, gk-core/src/FusionRpg.Core/Battle/BattleModels.cs:57-63.
# Transcribed, not read from JSON: BattleRuleset is C#, and no registry mirrors it.
HP_SHAPED = frozenset({
    "vitality", "fortitude", "bulwark", "warding", "resilience", "plating", "carapace", "mending",
})
ATK_SHAPED = frozenset({"might", "ferocity", "savagery"})
INTERVAL_SHAPED = frozenset({"quickening", "flourishing", "swiftness"})

PRIMARY_CHANNEL_IDS = HP_SHAPED | ATK_SHAPED | INTERVAL_SHAPED


def _battle_ruleset_base_hp(level: int) -> int:
    return 80 + 30 * level


def _battle_ruleset_base_atk(level: int) -> int:
    return 12 + 4 * level


def _battle_ruleset_round_duration_ms(_level: int) -> int:
    return 1000


_OPS = frozenset({"Flat", "Increased", "More"})


def build_channels() -> "tuple[Channel, ...]":
    channels = []
    for channel_id in sorted(HP_SHAPED):
        channels.append(Channel(id=channel_id, unit=Unit.GAME_UNITS,
                                reference_base=_battle_ruleset_base_hp,
                                group="primary", ops=_OPS))
    for channel_id in sorted(ATK_SHAPED):
        channels.append(Channel(id=channel_id, unit=Unit.GAME_UNITS,
                                reference_base=_battle_ruleset_base_atk,
                                group="primary", ops=_OPS))
    for channel_id in sorted(INTERVAL_SHAPED):
        channels.append(Channel(id=channel_id, unit=Unit.MILLISECONDS,
                                reference_base=_battle_ruleset_round_duration_ms,
                                group="primary", ops=_OPS))
    return tuple(channels)


assert len(PRIMARY_CHANNEL_IDS) == 14, "bands.v1.json's primaryChannel lists 14 memberFamilies"
