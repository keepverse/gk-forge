"""seedsmith.adapters.actions.distribution_planner.tuning — loads and strictly validates
`gk-core/data/tuning/action-corpus-run.v1.json` (spec-distribution-planner.md §3 step 1, the "new" Reads
row) and, separately, the `k` / field-distance rule this module reads (never writes) from
`gk-core/data/tuning/action-dedup.v1.json` (§3 step 8).

Refuses at LOAD time, naming the offending row — same discipline as
`type_weights/tuning.py`: a `float`, a JSON `bool` masquerading as an `int` (Python's `bool` is an
`int` subclass, checked explicitly), a numeric STRING, or an unknown/malformed shape.

**`action-dedup.v1.json` does not exist in this checkout (confirmed 2026-09-03 — `test -f` returns
missing).** It is A-S3's file (`spec-dedup-select.md` §2: "the t3 threshold, k, and the t2
field-distance rule") and A-S3 is not built yet. The call made here, matching every other
"ship a stated, documented default rather than block on an unbuilt sibling" precedent this session
(A-S0/A-T1's own neutral-until-the-smoke-batch defaults): **A-S1 reads the file if present; if
absent, it uses a stated, derived default (`k = 8`) rather than refusing to run.** The default is
not invented — it is `FINGERPRINT_COMPONENT_COUNT + 1` (spec §3 step 8's own derivation: "the
smallest value that can show the model one neighbour per field tier 2 could reject on, plus one"),
and a test pins that arithmetic identity so a change to the fingerprint's shape that does not also
move `k` fails loudly. This module never WRITES `action-dedup.v1.json` — that file, if and when
A-S3 lands, remains the single owner of `k`'s real, tuned value.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "RunTuning", "load_run_tuning", "RUN_TUNING_PATH",
    "FINGERPRINT_COMPONENT_COUNT", "DEFAULT_AVOID_NEIGHBOUR_K", "load_dedup_k", "DEDUP_TUNING_PATH",
]

REPO_ROOT = Path(__file__).resolve().parents[6]
RUN_TUNING_PATH = REPO_ROOT / "data" / "tuning" / "action-corpus-run.v1.json"
DEDUP_TUNING_PATH = REPO_ROOT / "data" / "tuning" / "action-dedup.v1.json"

# spec-dedup-select.md §2's own fingerprint shape: sorted(atomFamilies) | category | targetMode |
# areaShape | relation | sorted(structureAxes) | pairingRole -- SEVEN components, always. This
# constant is the one place that count is named; `DEFAULT_AVOID_NEIGHBOUR_K` is derived from it,
# never re-typed, so a change to the fingerprint's own shape moves the default with it.
FINGERPRINT_COMPONENT_COUNT = 7
DEFAULT_AVOID_NEIGHBOUR_K = FINGERPRINT_COMPONENT_COUNT + 1


def _require_int(value: object, where: str, path: Path) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path}: {where} must be a plain int (long) -- got {value!r}")
    return value


def _require_pair(value: object, where: str, path: Path) -> "tuple[str, str]":
    if (not isinstance(value, list) or len(value) != 2
            or not all(isinstance(v, str) for v in value)):
        raise ValueError(f"{path}: {where} must be a 2-element array of atom-family id strings "
                         f"-- got {value!r}")
    return (value[0], value[1])


@dataclass(frozen=True)
class RunTuning:
    mode: str                                   # "smoke" | "full"
    general_count: int
    per_family_count: int
    per_species_count: int
    multiplicative_pairs: "tuple[tuple[str, str], ...]"
    family_motif_max: int
    version: int


def load_run_tuning(path: Path = RUN_TUNING_PATH) -> RunTuning:
    doc = json.loads(path.read_text(encoding="utf-8"))

    mode = doc.get("mode")
    if mode not in ("smoke", "full"):
        raise ValueError(f"{path}: 'mode' must be 'smoke' or 'full' -- got {mode!r}")

    general_count = _require_int(doc.get("generalCount"), "generalCount", path)
    per_family_count = _require_int(doc.get("perFamilyCount"), "perFamilyCount", path)
    per_species_count = _require_int(doc.get("perSpeciesCount"), "perSpeciesCount", path)
    if general_count < 0 or per_family_count < 0 or per_species_count < 0:
        raise ValueError(f"{path}: 'generalCount'/'perFamilyCount'/'perSpeciesCount' must be "
                         f"non-negative")

    pairs_raw = doc.get("multiplicativePairs")
    if not isinstance(pairs_raw, list):
        raise ValueError(f"{path}: 'multiplicativePairs' must be an array of 2-id pairs")
    pairs = tuple(_require_pair(p, f"multiplicativePairs[{i}]", path)
                 for i, p in enumerate(pairs_raw))

    family_motif_max = _require_int(doc.get("familyMotifMax"), "familyMotifMax", path)
    if family_motif_max < 0:
        raise ValueError(f"{path}: 'familyMotifMax' must be non-negative")

    version = _require_int(doc.get("version"), "version", path)

    return RunTuning(
        mode=mode, general_count=general_count, per_family_count=per_family_count,
        per_species_count=per_species_count, multiplicative_pairs=pairs,
        family_motif_max=family_motif_max, version=version,
    )


def load_dedup_k(path: Path = DEDUP_TUNING_PATH) -> "tuple[int, str]":
    """Returns `(k, source)` -- `source` is `"file"` when `action-dedup.v1.json` exists and
    carries a `k` row, `"default"` when it does not (this checkout, today). Never raises on a
    missing file -- see module docstring for why that is the right call here, not a refusal."""
    if not path.is_file():
        return DEFAULT_AVOID_NEIGHBOUR_K, "default"
    doc = json.loads(path.read_text(encoding="utf-8"))
    k = doc.get("k")
    if k is None:
        return DEFAULT_AVOID_NEIGHBOUR_K, "default"
    return _require_int(k, "k", path), "file"
