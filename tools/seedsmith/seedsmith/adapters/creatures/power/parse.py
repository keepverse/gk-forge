r"""`power-parse` (creature-seed module 3, spec-power-parse.md) — a deterministic parse of the almanac
capture into a numeric power seed and a four-value `basis`. No model calls; this module is the
reason most of the roster costs nothing to classify.

# 伤害：20×6/1.5秒  - damage, shot count, and interval in one line. The interval is the reason
# this module also feeds attackTempo: a stated tempo beats a classified one.
DAMAGE = re.compile(r"伤害[:：]\s*(\d+)")
"""
from __future__ import annotations

import re
from typing import Iterable

from .model import PowerSeed

# Half-width `:` and full-width `：` both appear in real captured text (RpgStore's own
# SunCostRx/CooldownRx already handle this for the cost field; this module handles it for the
# flavour/info field independently). One damage line yields damage, an optional shot count, and
# an optional interval — the interval is captured only when it rides directly on the damage line
# (`20×6/1.5秒`); a bare "N秒" elsewhere in the text (e.g. a recharge or production interval) is
# not conflated with attack tempo.
_DAMAGE_LINE = re.compile(r"伤害[:：]\s*(\d+)(?:\s*×\s*(\d+))?(?:\s*/\s*([\d.]+)\s*秒)?")
_TOUGHNESS = re.compile(r"韧性[:：]\s*(\d+)")


def _interval_to_ms(seconds_text: "str | None") -> "int | None":
    """`1.5秒` -> `1500`, never `1.5`. Held as an integer of milliseconds per spec §3 — the
    repo's numeric rule (docs/architecture/numeric-types.md rule 4: divide by 1000 last, exactly once) applies in reverse
    here: multiply by 1000 once, at the boundary, never carry a float past this point."""
    if seconds_text is None:
        return None
    # round() over float seconds*1000 is exact for the one/two-decimal values this format uses
    # (e.g. 1.5, 0.5, 7.5) — real captured text has never shown more than one decimal digit.
    return round(float(seconds_text) * 1000)


def parse_flavor_text(text: "str | None") -> dict:
    """Pure extraction, no precedence decisions — see `parse_power_seed` for that."""
    result: dict = {"damage": None, "shot_count": None, "interval_ms": None, "toughness": None}
    if not text:
        return result

    dmg_match = _DAMAGE_LINE.search(text)
    if dmg_match:
        result["damage"] = int(dmg_match.group(1))
        if dmg_match.group(2):
            result["shot_count"] = int(dmg_match.group(2))
        if dmg_match.group(3):
            result["interval_ms"] = _interval_to_ms(dmg_match.group(3))

    tou_match = _TOUGHNESS.search(text)
    if tou_match:
        result["toughness"] = int(tou_match.group(1))

    return result


def parse_power_seed(
    *,
    side: str,
    type_id: int,
    stats_observed: bool,
    hp: "int | None",
    attack: "int | None",
    flavor_text: "str | None",
    measured_hp: "int | None" = None,
    measured_attack: "int | None" = None,
    measured_cost: "int | None" = None,
) -> PowerSeed:
    """The four-basis precedence (spec §2), applied whole — a species with an observation never
    falls through to a parse, even when the text disagrees with it.

    `measured_hp`/`measured_attack` come from the game's OWN static table (`type_base_stats`, swept
    2026-09-17 and committed as `type-base-stats.json`). They sit at the TOP of the `observed` rung,
    above the spawn sample, for the same reason `RpgStore.ResolveCombatBaseline` already prefers the
    static table over a sample and falls back to it: a sample is one observation of one spawn, the
    static table is the number the game itself defines. This does not add a fifth basis — it adds a
    second, better supplier to the rung that already exists, which is exactly the upgrade path the
    four-value ordinal was designed for (creature-seed R-CS1).

    Both default to `None`, so every pre-capture caller and every fixture keeps its exact previous
    behaviour.
    """
    parsed = parse_flavor_text(flavor_text)
    text_damage = parsed["damage"]
    text_toughness = parsed["toughness"]
    shot_count = parsed["shot_count"]
    interval_ms = parsed["interval_ms"]

    if measured_hp is not None or measured_attack is not None:
        basis: str = "observed"
        toughness = measured_hp
        damage = measured_attack
        disagreement_toughness = text_toughness is not None and text_toughness != measured_hp
        disagreement_damage = text_damage is not None and text_damage != measured_attack
    elif stats_observed and hp is not None and attack is not None:
        basis = "observed"
        toughness = hp
        damage = attack
        disagreement_toughness = text_toughness is not None and text_toughness != hp
        disagreement_damage = text_damage is not None and text_damage != attack
    elif text_damage is not None or text_toughness is not None:
        basis = "stated"
        toughness = text_toughness
        damage = text_damage
        disagreement_toughness = False
        disagreement_damage = False
    elif flavor_text:
        # `inferred`: classify-pipelines supplies the band from lore (Q26) — this module never
        # invents a number for it.
        basis = "inferred"
        toughness = None
        damage = None
        disagreement_toughness = False
        disagreement_damage = False
    else:
        basis = "blocked"
        toughness = None
        damage = None
        disagreement_toughness = False
        disagreement_damage = False

    return PowerSeed(
        side=side,
        type_id=type_id,
        basis=basis,  # type: ignore[arg-type]
        toughness=toughness,
        damage=damage,
        text_toughness=text_toughness,
        text_damage=text_damage,
        shot_count=shot_count,
        interval_ms=interval_ms,
        disagreement_toughness=disagreement_toughness,
        disagreement_damage=disagreement_damage,
        # Independent of basis, like the text fields above: a price is an authored fact about the
        # type, not an observation of one spawn, so it is carried whenever the capture has it.
        cost=measured_cost,
    )


def basis_histogram(seeds: Iterable[PowerSeed]) -> dict:
    counts = {"observed": 0, "stated": 0, "inferred": 0, "blocked": 0}
    for s in seeds:
        counts[s.basis] += 1
    return counts


def disagreements(seeds: Iterable[PowerSeed]) -> list:
    """Species where an observation and the parsed text disagree — recorded as evidence for the
    audit pipeline (T2.5 `threat-audit`), never resolved here."""
    return [s for s in seeds if s.disagreement_toughness or s.disagreement_damage]
