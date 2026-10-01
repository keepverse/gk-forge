"""seedsmith.adapters.actions.type_weights.tuning — loads and strictly validates
`gk-core/data/tuning/action-type-weights.v1.json` (spec-type-weights.md §2's "new" Reads row). Every
coefficient the algorithm in `derive.py` uses comes from this file; nothing here is re-typed as a
code literal (spec §4's "never carry a number a balance pass would move in code").

Refuses at LOAD time, naming the offending row:
    - a `float` (e.g. `0.4`) in place of an int
    - a JSON `bool` in place of an int (Python's `bool` is an `int` subclass, so a naive
      `isinstance(x, int)` check would silently accept `true`/`false` — guarded explicitly)
    - a numeric STRING (e.g. `"400"`) in place of an int, including a whole array of numeric
      strings (`separationMilli` shipped as `["0", "250", ...]`)
    - an unknown member: a `targetModeMilli`/`areaShapeMilli` key that is not one of the closed,
      wire-string vocabularies below, or a row whose inner vector is missing a key, carries an
      extra one, or does not sum to exactly 1000

The three closed, ordered vocabularies below (`TARGET_MODES`, `AREA_SHAPES`, `ELEMENTS`) are
transcribed from the C# code of record's own `Name` functions — never the enum member names (the
exact F10 mistake spec-type-weights.md §2 documents: PascalCase `"Area"`/`"Row"` leaking into an
earlier draft's example) — and re-verified directly against the live files while this module was
built (2026-09-03), matching this repo's own design-gate discipline rather than trusted from the
spec's citations:
    TARGET_MODES  ActionTargetMode enum (declared order) + ActionTargetModes.Name —
                  gk-core/src/FusionRpg.Core/Actions/ActionTargetSpec.cs:14-33, :103-112
    AREA_SHAPES   ActionAreaShape enum (declared order) + ActionAreaShapes.Name — same file,
                  :42-48, :134-141
    ELEMENTS      ElementTypeId enum (declared order) + ToElementId —
                  gk-core/src/FusionRpg.Core/Stats/Derived/ActorElementTypes.cs:3-11, :93-102

The five action categories are NOT re-transcribed here — `CATEGORIES` is imported straight from
`characteristic_pool.derive`, which already carries the corrected live citation
(`ActionEnums.cs:144-147`, not the spec's stale `:119-123`) and its own re-verification note. A
second, independently-typed copy of that tuple is exactly the kind of drift this repo's design-gate
discipline exists to prevent.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..characteristic_pool.derive import CATEGORIES

__all__ = [
    "TARGET_MODES", "AREA_SHAPES", "ELEMENTS", "TypeWeights", "load_type_weights", "TUNING_PATH",
]

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

TUNING_PATH = _owned("data/tuning/action-type-weights.v1.json")

# ActionTargetModes.Name — ActionTargetSpec.cs:14-33 (enum, declared order), :103-112 (Name).
TARGET_MODES: "tuple[str, ...]" = ("self", "single", "multi", "rolledTarget", "all", "area")

# ActionAreaShapes.Name — ActionTargetSpec.cs:42-48 (enum, declared order), :134-141 (Name).
AREA_SHAPES: "tuple[str, ...]" = ("row", "column", "square", "rectangle")

# ElementTypeId + ToElementId — ActorElementTypes.cs:3-11 (enum, declared order), :93-102.
ELEMENTS: "tuple[str, ...]" = ("fire", "ice", "air", "earth", "light", "dark")


@dataclass(frozen=True)
class TypeWeights:
    base: int
    step: int
    separation_milli: "tuple[int, ...]"                 # index 0..4, a REAL A-S0 `separation`
    null_separation_milli: int                          # `separation: null` — its own row, not row 0
    target_mode_milli: "dict[str, dict[str, int]]"       # row key ("attack" or "attack:melee") -> 6 modes
    area_shape_milli: "dict[str, int]"                   # one global row, 4 shapes
    primary_milli: int
    secondary_milli: int
    family_secondary_scale_milli: int                    # step 6's own family-element-bias scale
    version: int


def _require_int(value: object, where: str) -> int:
    """Refuses a `float`, a `bool` (an `int` subclass in Python — checked explicitly, never
    inferred from `isinstance(x, int)` alone), and a numeric string. Every magnitude in this
    program is `long`; a coefficient that is not a plain Python `int` is refused here, naming the
    row, rather than silently coerced (spec §4's "never emit a float or a double")."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{TUNING_PATH}: {where} must be a plain int (long) — got {value!r}")
    return value


def _require_vector(value: object, expected_keys: "tuple[str, ...]", label: str) -> "dict[str, int]":
    if not isinstance(value, dict) or set(value) != set(expected_keys):
        raise ValueError(f"{TUNING_PATH}: {label} must have exactly the keys "
                         f"{sorted(expected_keys)} — got {value!r}")
    out = {k: _require_int(v, f"{label}[{k!r}]") for k, v in value.items()}
    total = sum(out.values())
    if total != 1000:
        raise ValueError(f"{TUNING_PATH}: {label} sums to {total}, must sum to exactly 1000")
    return out


def load_type_weights(path: Path = TUNING_PATH) -> TypeWeights:
    doc = json.loads(path.read_text(encoding="utf-8"))

    base = _require_int(doc.get("base"), "base")
    step = _require_int(doc.get("step"), "step")
    if base < 0 or step < 0:
        raise ValueError(f"{path}: 'base' and 'step' must be non-negative")

    sep_raw = doc.get("separationMilli")
    if not isinstance(sep_raw, list) or len(sep_raw) != 5:
        raise ValueError(f"{path}: 'separationMilli' must be a 5-element array "
                         f"(A-S0's separation 0..4) — got {sep_raw!r}")
    separation_milli = tuple(_require_int(v, f"separationMilli[{i}]") for i, v in enumerate(sep_raw))
    if any(v < 0 for v in separation_milli):
        raise ValueError(f"{path}: every 'separationMilli' entry must be non-negative")

    # `separation: null` (a family-less species, A-S0's F12 correction) is its OWN row, deliberately
    # never `separationMilli[0]` — see this module's own AC5 fix note in derive.py's module
    # docstring for why sharing row 0 with a genuine tie made every family-less species print flat
    # under the shipped v1 defaults, directly contradicting acceptance #5's own stated requirement.
    null_separation_milli = _require_int(doc.get("nullSeparationMilli"), "nullSeparationMilli")
    if null_separation_milli < 0 or null_separation_milli > 1000:
        raise ValueError(f"{path}: 'nullSeparationMilli' must be within 0..1000")

    tmm_raw = doc.get("targetModeMilli")
    if not isinstance(tmm_raw, dict) or not tmm_raw:
        raise ValueError(f"{path}: 'targetModeMilli' must be a non-empty object of rows")
    target_mode_milli: "dict[str, dict[str, int]]" = {}
    for row_key, row_value in tmm_raw.items():
        head = row_key.split(":", 1)[0]
        if head not in CATEGORIES:
            raise ValueError(f"{path}: targetModeMilli row {row_key!r} — unknown category "
                             f"{head!r}, must be one of {CATEGORIES}")
        target_mode_milli[row_key] = _require_vector(
            row_value, TARGET_MODES, f"targetModeMilli[{row_key!r}]")
    missing_heads = [c for c in CATEGORIES if c not in target_mode_milli]
    if missing_heads:
        raise ValueError(f"{path}: targetModeMilli is missing its bare fallback row for "
                         f"{missing_heads} — every lean head needs at least its own row")

    area_shape_milli = _require_vector(doc.get("areaShapeMilli"), AREA_SHAPES, "areaShapeMilli")

    primary_milli = _require_int(doc.get("primaryMilli"), "primaryMilli")
    secondary_milli = _require_int(doc.get("secondaryMilli"), "secondaryMilli")
    if primary_milli < 0 or secondary_milli < 0 or primary_milli + secondary_milli > 1000:
        raise ValueError(f"{path}: 'primaryMilli' + 'secondaryMilli' must be within 0..1000 — "
                         f"got {primary_milli} + {secondary_milli}")

    # Step 6's own family-element-bias scale — "a secondary is half a primary", the same fact
    # `action-role-lean.v1.json`'s `elementSecondaryScaleMilli` states for a SPECIES' two element
    # slots, restated here as its own tuning row because this module reads only its own tuning
    # file (spec §2's Reads table) and never A-S0's (spec §4: never carry a number a balance pass
    # would move in code — this is exactly such a number, so it gets its own named row rather than
    # a borrowed or hard-coded one).
    family_secondary_scale_milli = _require_int(
        doc.get("familySecondaryScaleMilli"), "familySecondaryScaleMilli")
    if family_secondary_scale_milli < 0 or family_secondary_scale_milli > 1000:
        raise ValueError(f"{path}: 'familySecondaryScaleMilli' must be within 0..1000")

    version = _require_int(doc.get("version"), "version")

    return TypeWeights(
        base=base, step=step, separation_milli=separation_milli,
        null_separation_milli=null_separation_milli,
        target_mode_milli=target_mode_milli, area_shape_milli=area_shape_milli,
        primary_milli=primary_milli, secondary_milli=secondary_milli,
        family_secondary_scale_milli=family_secondary_scale_milli, version=version,
    )
