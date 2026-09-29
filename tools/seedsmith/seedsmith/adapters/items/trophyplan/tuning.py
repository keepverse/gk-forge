"""seedsmith.adapters.items.trophyplan.tuning — loads and strictly validates
`gk-core/data/tuning/species-material-run.v1.json` (spec-species-materials.md § Design 4, R9/R-SC1).

Strict in the same shape as `adapters.actions.distribution_planner.tuning._require_int` (that
module's own docstring is the cited precedent for this one): a `float`, a JSON `bool` masquerading
as an `int` (Python's `bool` is an `int` subclass, checked explicitly), a numeric STRING, or a
negative count are all refused at load time, naming the offending field.

**Unknown-key refusal, added beyond `distribution_planner.tuning`'s own leniency.** That module's
`load_run_tuning` never checked for stray keys; this one does, because R9's whole point is that
`perGeneral` is REMOVED, not parked at 0 — "the strict loader's unknown key refusal then rejects a
stale `perGeneral` in the tuning file by name, rather than silently ignoring it" (spec § Design 4).
A silently-ignored stray key would let a `perGeneral` row live on in the file, unread and unnoticed,
exactly the drift the removal was meant to prevent.

This is a GENERATION-time file (`gk-core/data/tuning/species-material-run.v1.json`), read only by seedsmith.
It is not `gk-core/data/tuning/creature-yield.v1.json` (the C# host's own runtime tuning, task T31) — the two
files answer different questions ("which ids exist" vs "which shard drops at runtime") and a
generation-time count is never smuggled into a runtime tuning file or vice versa (one owner per
number, spec § Design 5 step 1).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

__all__ = ["RunTuning", "load_run_tuning", "RUN_TUNING_PATH", "TrophyTuningError"]

REPO_ROOT = Path(__file__).resolve().parents[6]
RUN_TUNING_PATH = REPO_ROOT / "data" / "tuning" / "species-material-run.v1.json"

_KNOWN_KEYS = frozenset({"schemaVersion", "version", "_meta", "perSpecies", "perFamily"})


class TrophyTuningError(ValueError):
    """`species-material-run.v1.json` failed to load or validate — refused, never defaulted."""


def _require_int(value: object, where: str, path: Path) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TrophyTuningError(f"{path}: {where} must be a plain int (long) -- got {value!r}")
    return value


@dataclass(frozen=True)
class RunTuning:
    per_species: int
    per_family: int
    version: int


def load_run_tuning(path: Path = RUN_TUNING_PATH) -> RunTuning:
    if not path.is_file():
        raise TrophyTuningError(f"{path}: species-material-run tuning file is missing")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TrophyTuningError(f"{path}: not valid JSON -- {exc}") from exc
    if not isinstance(doc, dict):
        raise TrophyTuningError(f"{path}: top level must be a JSON object -- got {type(doc).__name__}")

    unknown = sorted(set(doc) - _KNOWN_KEYS)
    if unknown:
        raise TrophyTuningError(
            f"{path}: unknown key(s) {unknown} -- R9 removed the general layer; a stale "
            f"'perGeneral' (or any other unrecognised key) is refused, never silently ignored")

    per_species = _require_int(doc.get("perSpecies"), "perSpecies", path)
    per_family = _require_int(doc.get("perFamily"), "perFamily", path)
    if per_species < 0 or per_family < 0:
        raise TrophyTuningError(f"{path}: 'perSpecies'/'perFamily' must be non-negative")

    version = _require_int(doc.get("version"), "version", path)

    return RunTuning(per_species=per_species, per_family=per_family, version=version)
