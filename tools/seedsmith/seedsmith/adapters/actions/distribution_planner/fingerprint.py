"""seedsmith.adapters.actions.distribution_planner.fingerprint — the rendering and distance
functions §3 step 8 needs, built to A-S3's own definition (`spec-dedup-select.md` §2), quoted
rather than re-derived: **one** definition, never a second one shaped like it.

The fingerprint has seven components, in this fixed order:
`sorted(atomFamilies) | category | targetMode | areaShape | relation | sorted(structureAxes) |
pairingRole`. The two list-valued components render as their members joined by `+` (matching the
brief JSON example's own rendering, `"burn+spread"` / `"condition+riderStatus"`); the seven
components then join with `|`. **Field distance is a Hamming distance over the seven RENDERED
strings** -- a one-member difference inside `atomFamilies` is a distance of 1 (the two rendered
strings differ), never a set-difference count. Ties break on action id (ordinal, lexicographic --
the brief/action id's own zero-padded ordinal suffix sorts correctly as a plain string).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

__all__ = ["FingerprintComponents", "render_fingerprint", "field_distance", "k_nearest",
          "NONE_AREA_SHAPE"]

COMPONENT_JOIN = "|"
LIST_JOIN = "+"

# spec-dedup-select.md SS2's own canonical fingerprint definition, quoted verbatim: "areaShape is
# the literal `none` when targetMode != area -- a missing key is a defect, `none` is a value."
NONE_AREA_SHAPE = "none"


@dataclass(frozen=True)
class FingerprintComponents:
    atom_families: "tuple[str, ...]"     # rendered sorted
    category: str
    target_mode: str
    area_shape: "str | None"
    relation: str
    structure_axes: "tuple[str, ...]"    # rendered sorted
    pairing_role: str


def render_fingerprint(c: FingerprintComponents) -> "tuple[str, ...]":
    """The seven RENDERED strings, in fixed order -- what `field_distance` actually compares.

    **CORRECTED 2026-09-04 (A-S3 build, dedup-select).** A `None` `area_shape` used to render as
    `""` here. `spec-dedup-select.md` SS2 -- the fingerprint's own canonical definition, which this
    function exists to be the ONE implementation of -- states the rule explicitly: "`areaShape` is
    the literal `none` when `targetMode != area` -- a missing key is a defect, `none` is a value."
    `""` is neither the real areaShape vocabulary nor the stated literal, so it was a second,
    silently-different reading of the one definition this module's own docstring says it renders.
    No A-S1 test pinned the old `""` rendering: round 1's own `avoidNeighbours` is always empty
    (an empty accepted corpus, spec-distribution-planner.md SS7), so the two renderings never
    diverged in any file `distribution_planner` has actually written -- confirmed by re-running
    `test_distribution_planner.py` unaffected by this change.
    """
    return (
        LIST_JOIN.join(sorted(c.atom_families)),
        c.category,
        c.target_mode,
        c.area_shape if c.area_shape is not None else NONE_AREA_SHAPE,
        c.relation,
        LIST_JOIN.join(sorted(c.structure_axes)),
        c.pairing_role,
    )


def render_fingerprint_string(c: FingerprintComponents) -> str:
    """The single joined string a brief's `avoidNeighbours[].fingerprint` carries -- the same
    seven rendered components, `|`-joined, matching the brief JSON example
    (`"burn+spread|attack|area|row|enemy|condition+riderStatus|enabler"`)."""
    return COMPONENT_JOIN.join(render_fingerprint(c))


def field_distance(a: "Sequence[str]", b: "Sequence[str]") -> int:
    """Hamming distance over two RENDERED 7-tuples (from `render_fingerprint`) -- the count of
    positions whose rendered strings differ, range 0..7. Raises on a length mismatch rather than
    silently zero-padding: two fingerprints of different shapes are a caller defect, not a
    legitimate distance-7."""
    if len(a) != len(b):
        raise ValueError(f"field_distance: fingerprint length mismatch ({len(a)} vs {len(b)})")
    return sum(1 for x, y in zip(a, b) if x != y)


def k_nearest(target: "Sequence[str]", candidates: "Sequence[tuple[str, Sequence[str]]]",
             k: int) -> "list[tuple[str, int]]":
    """`candidates`: `(action_id, rendered_fingerprint)` pairs, already restricted by the caller to
    the same `(scope, scopeKey)` group -- this function has no opinion on grouping, only on
    ordering. Returns up to `k` `(action_id, distance)` pairs, ordered by field distance then by
    action id (ties on the id string itself -- a zero-padded ordinal suffix sorts correctly as a
    plain string, per this module's own `briefId`/`actionId` convention). A total function over an
    empty `candidates` list -- returns `[]`, never raises (round 1 has no accepted corpus yet,
    spec §7, and this is the exact call site that must degrade cleanly rather than crash)."""
    scored = [(action_id, field_distance(target, fp)) for action_id, fp in candidates]
    scored.sort(key=lambda row: (row[1], row[0]))
    return scored[:k]
