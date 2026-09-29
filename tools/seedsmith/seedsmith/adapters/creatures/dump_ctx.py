"""`CreatureDumpCtx` — the loaded `corpus-dump` tree plus its `power-parse` classification, bundled
once so `metrics/corpus_coverage.py` (T1.10) doesn't re-read and re-parse the dump per metric.
Lives beside `preflight.py` rather than inside `metrics/`, because loading creature-specific JSON is
adapter knowledge, not something the generic metrics package should know how to do (the same split
`creature_coverage.py`'s own docstring states for its metric/adapter boundary).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .power.measured import MeasuredBaseStats, load_measured_base_stats
from .power.model import PowerSeed
from .power.parse import parse_power_seed


@dataclass(frozen=True)
class CreatureDumpCtx:
    dump_dir: Path
    manifest: dict
    seeds: "tuple[PowerSeed, ...]"
    #: The committed `type-base-stats.json` capture, keyed `(side, typeId)`. Empty when the dump
    #: tree predates the 2026-09-17 sweep or is a fixture — never an error, and `resolves_natively`
    #: must not be read as "nothing resolves" in that case.
    measured: "dict[tuple[str, int], MeasuredBaseStats]" = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.seeds)


def load_creature_dump_ctx(dump_dir: Path) -> "CreatureDumpCtx | None":
    """Returns None (never raises) when the dump tree isn't there or doesn't parse — the caller
    (a metric's `run`, via `needs={"creature_dump"}`) turns that into NOT_MEASURED, never a pass."""
    manifest_path = dump_dir / "_manifest.json"
    plant_path = dump_dir / "almanac" / "plant.json"
    zombie_path = dump_dir / "almanac" / "zombie.json"
    if not (manifest_path.exists() and plant_path.exists() and zombie_path.exists()):
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows = (json.loads(plant_path.read_text(encoding="utf-8"))
                + json.loads(zombie_path.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return None

    # The game's own static table, overlaid onto every seed it covers (creature-seed R-CS1). One
    # place, on purpose: this loader is where "the dump's power seeds" is defined, so every consumer
    # (corpus-coverage metrics, run-control's score-first threat fill, the re-derivation pass) sees
    # the same upgraded seed rather than three independently-overlaid copies of it.
    measured = load_measured_base_stats(dump_dir)
    parsed_seeds: "list[PowerSeed]" = []
    for r in rows:
        m = measured.get((r["side"], r["typeId"]))
        parsed_seeds.append(parse_power_seed(
            side=r["side"], type_id=r["typeId"], stats_observed=r["statsObserved"],
            hp=r["hp"], attack=r["attack"], flavor_text=r["flavorInfo"],
            measured_hp=m.hp if m is not None else None,
            measured_attack=m.attack if m is not None else None,
            measured_cost=m.cost if m is not None else None))
    seeds = tuple(parsed_seeds)
    return CreatureDumpCtx(dump_dir=dump_dir, manifest=manifest, seeds=seeds, measured=measured)
