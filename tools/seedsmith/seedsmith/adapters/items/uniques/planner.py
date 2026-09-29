"""The uniques planner (D4.29, spec-unique-pipeline.md "Metrics" section) -- model-free, runs
first. Builds the `frame x axis x band` grid (2 x 5 x 3 = 30 cells) and mints ids per cell.

**Not imported from `adapters.dungeon.planner`**, despite that module's `Cell`/`IdMinter` being
structurally identical in shape. Cross-adapter imports are not this codebase's convention --
`adapters/items/combogen/grid.py` and `adapters/items/setgen/` each already keep their OWN local
Cell/grid rather than sharing one, even within `items/` itself, and `dungeon/planner.py`'s own
`enumerate_cells` is capped at 2 dimensions ("every dungeon corpus is <=2-D") where this grid
needs 3. Duplicating the small, stable shape here matches precedent; importing across adapters
would not.

**Id grammar, and why it differs from the existing 144-corpus's poetic slugs.** The shipped
corpus's ids read `unique.<theme>-<band>-<nnn>` where `<theme>` is a hand-picked flavour slug
(`charnel-bloom`, `windswept-spore`, ...) chosen before any model call, exactly like a PLANNED
field must be (kinds.py's own `UNIQUE_OWNERSHIP["id"] == "PLANNED"`: "the planner fixes it... the
model may not change it"). A planner has no business inventing NEW flavour slugs -- picking a
name is real content judgement, the job `briefs.py` hands to the model's `name`/`flavor` output,
never to deterministic id-minting code. So this planner mints from the grid's own dimensions
instead: `unique.<frame>-<axis>-<band>-<nnn>`, e.g. `unique.plant-offense-firstseed-001` --
deterministic, unambiguous, and openly a grid id rather than a borrowed flavour slug.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

#: frame (2) -- core.v1.json's frame vocabulary restricted to the two non-hybrid values; the grid
#: (spec "Metrics": "frame 2 x axis 5 x band 3 = 30 cells") deliberately excludes `hybrid` -- zero
#: `"frame": "hybrid"` in the sampled real 144-corpus, and hybrid is a commander-only frame shape
#: (`registries.py`'s own `HYBRID_FRAME_CITATION`) a wearable unique never occupies.
FRAMES: "tuple[str, ...]" = ("humanoid", "plant")

#: axis (5) -- `gk-data/packs/fusion/data/seed/items/_registry/core.v1.json` `powerCategories.list`, the same
#: vocabulary `unique.powerAxis` already reads in every real shipped anchor.
AXES: "tuple[str, ...]" = ("control", "economy", "offense", "survivability", "utility")

#: band (3) -- the three rungs at/above `uniques.v1.json`'s own `rungFloorOrdinal` (80, D4.23):
#: `firstseed` (80), `sunwoven` (90), `almanac` (100). Never re-derived from a second copy of the
#: rarity ladder here -- these three names are cited directly from `item-rarity.v1.json` via
#: ssot-rarity.md §3.3 ("8+ is 80 firstseed; 9+ is 90 sunwoven and 100 almanac").
BANDS: "tuple[str, ...]" = ("firstseed", "sunwoven", "almanac")


@dataclass(frozen=True)
class Cell:
    frame: str
    axis: str
    band: str
    cell_key: str   # the id-minting slug, e.g. "plant-offense-firstseed"


def enumerate_cells(
    frames: "tuple[str, ...]" = FRAMES,
    axes: "tuple[str, ...]" = AXES,
    bands: "tuple[str, ...]" = BANDS,
) -> "list[Cell]":
    """The full 30-cell grid, sorted deterministically (frame, then axis, then band) so a rerun
    enumerates in the same order (seed-contract §6's "rerun byte-identical" discipline). Every
    cell is legal -- unlike dungeon's (kind, climate) grid, nothing about a unique's frame, axis
    or band combination is mutually exclusive (spec §1's field table names no such rule), so this
    function takes no `legal` predicate at all rather than a `lambda *_: True` placeholder that
    would only invite a real rule to be bolted on silently later without a test noticing."""
    cells: "list[Cell]" = []
    for frame in sorted(frames):
        for axis in sorted(axes):
            for band in sorted(bands):
                cells.append(Cell(frame, axis, band, f"{frame}-{axis}-{band}"))
    return cells


class IdMinter:
    """Mints `unique.<cell>-<nnn>` ids, continuing from a supplied high-water mark per cell --
    never restarting at 1 (seedsmith-map Appendix A row 6's tracking-id defect, dungeon/planner.py's
    own precedent, duplicated here for the same "no cross-adapter import" reason as `Cell` above)."""

    def __init__(self, high_water_marks: "Mapping[str, int] | None" = None) -> None:
        self._marks: "dict[str, int]" = dict(high_water_marks or {})

    def next_id(self, cell_key: str) -> str:
        n = self._marks.get(cell_key, 0) + 1
        self._marks[cell_key] = n
        return f"unique.{cell_key}-{n:03d}"

    def high_water_marks(self) -> "dict[str, int]":
        return dict(self._marks)


def plan_ids_for_cells(cells: "list[Cell]", count_per_cell: "Mapping[str, int]", minter: IdMinter) -> "dict[str, list[str]]":
    """`cell_key -> [minted ids]`, `count_per_cell[cell.cell_key]` entries each. First ship is 1
    per cell (30 cells, 30 ids); `count_per_cell` stays a mapping rather than a bare int so a later
    "2-3 per cell at full" pass (spec Metrics: 60-90 at full) is the same function, a different
    input, never a second code path."""
    result: "dict[str, list[str]]" = {}
    for cell in cells:
        n = count_per_cell.get(cell.cell_key, 0)
        result[cell.cell_key] = [minter.next_id(cell.cell_key) for _ in range(n)]
    return result
