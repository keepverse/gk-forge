"""The committed `type-base-stats.json` capture — the game's OWN static stat table, read from the
dump tree instead of from a database.

Why this module exists at all, stated plainly because it is the precondition creature-seed R-CS1
never named: the measured stats live only in `dist/FusionRpg.Server/data/rpg-hot.sqlite`, which is
**not committed**, while `gk-data/packs/fusion/data/generated/creatures/**` **is** committed and CI byte-compares it. A
generator that read the live database would make a committed artifact depend on uncommitted local
state, so the capture is exported once by `gk-forge/tools/CreatureCorpusDump --base-stats` and read from
disk here — the same committed-capture pattern the almanac/recipes/spawn-baseline files in the same
directory already established.

This module parses; it decides nothing. `parse_power_seed` owns the precedence, `derive` owns the
kind, and neither of them knows where the file lives.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: Filename written by `DumpWriter.TypeBaseStatsFileName` — one name, two languages, stated once.
TYPE_BASE_STATS_FILE = "type-base-stats.json"


@dataclass(frozen=True)
class MeasuredBaseStats:
    """One `(side, typeId)`'s measured stats, as the game's own static table holds them.

    `hp`, `attack` and `cost` are the three fields the power ladder reads; the rest of `stats_json`
    (cooldown, armour, summon tier) is deliberately NOT surfaced — a field nothing reads is a field
    that drifts. `cost` joined them on 2026-09-18 (creature-seed R-CS5) and stopped being an example
    of that rule: the two-field score could not tell 154 species apart, and `cost` is the game's own
    statement of what a creature is worth, so it separates them. `captured_utc` is carried so a later re-capture can tell a 2026-09-17 static read
    from whatever replaces it, which is the provenance gap the ideal doc named as still open.
    """

    side: str
    type_id: int
    type_name: "str | None"
    hp: "int | None"
    attack: "int | None"
    #: The game's authored sun price. Floored at 0 by the scorer, never here — two species really
    #: do carry a negative price (`ZombieEndoFlame` -125, `PresentZombie` -100) and dropping that
    #: fact at load time would hide it from anything else that wants to look.
    cost: "int | None"
    captured_utc: str


def _as_int(value) -> "int | None":
    """The static table stores whole-unit magnitudes, but JSON gives them back as `int` or `float`
    depending on how the game emitted them. A value with a real fractional part is NOT silently
    truncated into a magnitude — it is dropped, because a magnitude this module cannot represent
    exactly is a capture defect and must not read as a smaller number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    return None


def load_measured_base_stats(dump_dir: Path) -> "dict[tuple[str, int], MeasuredBaseStats]":
    """`(side, typeId) -> MeasuredBaseStats` from the committed capture.

    Returns an EMPTY dict (never raises) when the file is absent or unreadable — a dump tree
    without a base-stat capture is a real, supported state (every tree before 2026-09-17, plus
    every test fixture), and every caller already has correct behaviour for "no measured stat for
    this species". The file's own `contentHash` is verified by
    `CreatureCorpusDump --verify`, which owns that check in one language rather than two.
    """
    path = dump_dir / TYPE_BASE_STATS_FILE
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    entries = doc.get("entries") if isinstance(doc, dict) else None
    if not isinstance(entries, list):
        return {}

    out: "dict[tuple[str, int], MeasuredBaseStats]" = {}
    for row in entries:
        if not isinstance(row, dict):
            continue
        side = row.get("side")
        type_id = row.get("typeId")
        if not isinstance(side, str) or not isinstance(type_id, int) or isinstance(type_id, bool):
            continue
        try:
            stats = json.loads(row.get("statsJson") or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(stats, dict):
            continue
        out[(side, type_id)] = MeasuredBaseStats(
            side=side,
            type_id=type_id,
            type_name=row.get("typeName"),
            hp=_as_int(stats.get("hpBase")),
            attack=_as_int(stats.get("attackBase")),
            cost=_as_int(stats.get("cost")),
            captured_utc=row.get("capturedUtc") or "",
        )
    return out


def resolves_natively(side: str, game_type_id: int,
                      measured: "dict[tuple[str, int], MeasuredBaseStats]") -> bool:
    """Does this `(side, gameTypeId)` name a real `PlantType`/`ZombieType` member?

    The base-stat sweep is the oracle, and that is a deliberate choice rather than a convenience:
    `GameHooks.EnqueueBaseStats` walks BOTH game enums and reads the game's own static tables, so a
    value with a row is a value the enum defines, and a value with no row is one it does not. That
    is how the twelve phantom rows (`Pit`, `Refrash`, `Extract_single`, `Extract_ten`,
    `EnumValue261`–`268`) were found in the first place — the sweep gave every real type a row, and
    the only rows it could not fill were the rows that are not types.

    ⚠️ **An EMPTY capture means "no oracle available", never "nothing resolves"** — a dump tree with
    no capture (every tree before 2026-09-17, every fixture, a bad `git checkout`) would otherwise
    mark an entire corpus `excluded` in one pass. This function stays a pure membership test and
    cannot tell the two apart, so **the emptiness guard belongs to the caller**, which must check
    `measured` is non-empty before marking anything. `rederive_from_measured_capture` does, and two
    tests pin it.
    """
    return (side, game_type_id) in measured
