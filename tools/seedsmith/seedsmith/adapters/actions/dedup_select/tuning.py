"""seedsmith.adapters.actions.dedup_select.tuning — loads and strictly validates
`gk-core/data/tuning/action-dedup.v1.json` (spec-dedup-select.md §2's "new" Reads row). A-S3 is this
file's real owner: A-S1 (`distribution_planner/tuning.py`'s `load_dedup_k`) already reads the same
file for its own narrow `k`-only need and keeps its own documented fallback default for a checkout
where this file is absent -- that loader is untouched here. This module owns the FULL shape: `k`,
`similarityThresholdMilli` (the tier-3 review-queue trigger), and `t2FieldDistance` (the tier-2
near-duplicate rule).

Refuses at LOAD time, naming the offending row -- same discipline as `distribution_planner/
tuning.py` and `type_weights/tuning.py`: a `float`, a JSON `bool` masquerading as an `int`
(Python's `bool` is an `int` subclass, checked explicitly), a numeric STRING, or an
out-of-range/unimplemented value.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

__all__ = ["DedupTuning", "load_dedup_tuning", "DEDUP_TUNING_PATH", "IMPLEMENTED_T2_FIELD_DISTANCE"]

REPO_ROOT = Path(__file__).resolve().parents[6]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from ....workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

DEDUP_TUNING_PATH = _owned("data/tuning/action-dedup.v1.json")

#: Tier 2's shipped algorithm (`derive.run_tier2`) is a masked-hash-set implementation of "exactly
#: ONE field apart" (spec §3 step 3's own wording) -- generalising it to N fields apart would mean
#: hashing every N-of-7 masked projection instead of every 1-of-7 one, a different algorithm, not a
#: config edit. The value still lives in the tuning file (spec §2 names it as one of the file's
#: three rows) so a future re-derivation is a reviewed, visible change rather than a silent one.
IMPLEMENTED_T2_FIELD_DISTANCE = 1

_MIN_MILLI = 0
_MAX_MILLI = 1000


def _require_int(value: object, where: str, path: Path) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path}: {where} must be a plain int (long) -- got {value!r}")
    return value


@dataclass(frozen=True)
class DedupTuning:
    k: int
    similarity_threshold_milli: int
    t2_field_distance: int
    version: int


def load_dedup_tuning(path: Path = DEDUP_TUNING_PATH) -> DedupTuning:
    doc = json.loads(path.read_text(encoding="utf-8"))

    k = _require_int(doc.get("k"), "k", path)
    if k < 0:
        raise ValueError(f"{path}: 'k' must be non-negative -- got {k!r}")

    threshold = _require_int(doc.get("similarityThresholdMilli"), "similarityThresholdMilli", path)
    if not (_MIN_MILLI <= threshold <= _MAX_MILLI):
        raise ValueError(f"{path}: 'similarityThresholdMilli' must be 0..1000 -- got {threshold!r}")

    t2 = _require_int(doc.get("t2FieldDistance"), "t2FieldDistance", path)
    if t2 != IMPLEMENTED_T2_FIELD_DISTANCE:
        raise ValueError(
            f"{path}: t2FieldDistance={t2!r} -- the shipped masked-hash-set tier-2 algorithm only "
            f"implements {IMPLEMENTED_T2_FIELD_DISTANCE!r} (spec-dedup-select.md §3 step 3's own "
            f"'exactly one field apart' rule); a different value needs a new algorithm "
            f"(derive.run_tier2's own docstring), not a config edit -- refused")

    version = _require_int(doc.get("version"), "version", path)

    return DedupTuning(k=k, similarity_threshold_milli=threshold, t2_field_distance=t2,
                       version=version)
