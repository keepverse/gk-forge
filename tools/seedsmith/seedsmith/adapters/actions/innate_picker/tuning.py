"""seedsmith.adapters.actions.innate_picker.tuning — loads and strictly validates
`gk-core/data/tuning/action-innate-picker.v1.json` (spec-innate-picker.md §3.3's "new" Reads row): the
five `w_t` per-mille multipliers over the ranking tuple's five terms, in priority order
(roleLeanMatch, motifCoverage, elementMatch, categoryScarcity, -rungCeiling). Every `w_t` defaults
to 1000, at which `score` reproduces the lexicographic tuple order exactly (spec's own stated
identity) — the same "the neutral value reproduces the simplest defensible behaviour exactly"
precedent A-S0/A-T1/A-S1/A-R1 have all already used this session.

Refuses at LOAD time, naming the offending row — same discipline as `dedup_select/tuning.py` and
`type_weights/tuning.py`: a `float`, a JSON `bool` masquerading as an `int` (Python's `bool` is an
`int` subclass, checked explicitly, never inferred from `isinstance(x, int)` alone), a numeric
STRING, or a value outside 0..1000.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

__all__ = ["InnateWeights", "load_innate_weights", "INNATE_TUNING_PATH"]

REPO_ROOT = Path(__file__).resolve().parents[6]
INNATE_TUNING_PATH = REPO_ROOT / "data" / "tuning" / "action-innate-picker.v1.json"

_MIN_MILLI = 0
_MAX_MILLI = 1000


def _require_milli(value: object, where: str, path: Path) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path}: {where} must be a plain int (long) -- got {value!r}")
    if not (_MIN_MILLI <= value <= _MAX_MILLI):
        raise ValueError(f"{path}: {where} must be within {_MIN_MILLI}..{_MAX_MILLI} -- got {value!r}")
    return value


@dataclass(frozen=True)
class InnateWeights:
    role_lean_match_milli: int
    motif_coverage_milli: int
    element_match_milli: int
    category_scarcity_milli: int
    rung_ceiling_milli: int
    version: int


def load_innate_weights(path: Path = INNATE_TUNING_PATH) -> InnateWeights:
    doc = json.loads(path.read_text(encoding="utf-8"))

    role_lean = _require_milli(doc.get("wRoleLeanMatchMilli"), "wRoleLeanMatchMilli", path)
    motif = _require_milli(doc.get("wMotifCoverageMilli"), "wMotifCoverageMilli", path)
    element = _require_milli(doc.get("wElementMatchMilli"), "wElementMatchMilli", path)
    scarcity = _require_milli(doc.get("wCategoryScarcityMilli"), "wCategoryScarcityMilli", path)
    rung = _require_milli(doc.get("wRungCeilingMilli"), "wRungCeilingMilli", path)

    version = doc.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError(f"{path}: 'version' must be a plain int -- got {version!r}")

    return InnateWeights(
        role_lean_match_milli=role_lean, motif_coverage_milli=motif, element_match_milli=element,
        category_scarcity_milli=scarcity, rung_ceiling_milli=rung, version=version,
    )
