"""The dungeon planner (D1.9, spec-dungeon-seed-contract.md §4) — model-free, runs first.

**Built here:** cell enumeration from the adapter's own legality function (§3.6's (kind, climate)
rule), id minting from a high-water mark (§1's "every id is PLANNED... the planner mints
`<kind>.<cell>-<nnn>` from the cell and a sequence that continues from the high-water mark"), and
(2026-09-07) the motif-brief allocator (§4 step 2) — see the three functions below.

**Built 2026-09-07, previously deferred as needing a registry that turned out to already exist:**
`select_planning_themes`/`allocate_event_targets`/`motif_brief_for_slot` — D1.10's own same-day
correction found `gk-data/packs/fusion/data/seed/creatures/_registry/themes.v1.json` (904 rows today; the "84 rows" the
original note cited was the old 84-species catalog size, unrelated to anything counted here — see
spec-ladder-consistency-repair.md Defect 1) already shipped and wired
into `adapters/dungeon/registries.py`'s `load_themes()`, which is what this module's own docstring
was waiting on ("needs a dungeon motif registry that does not exist yet").

**Still deliberately deferred, named rather than hidden:** the Hopcroft-Karp feasibility check
(§4 step 5 — `seedsmith.planner.feasibility.check_feasibility` already exists generically and is
the right tool once real slot-demand data exists to feed it) — a wiring gap against ALREADY-BUILT
shared infrastructure (`seedsmith/planner/feasibility.py`, `seedsmith/planner/demand.py`), not a
missing algorithm.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .schema import ELEMENTS, EVENT_KIND


@dataclass(frozen=True)
class Cell:
    corpus: str
    dimension_values: "tuple[str, ...]"  # e.g. ("cache", "ice") for a room cell
    cell_key: str                        # the id-minting slug, e.g. "cache-ice"


def enumerate_cells(
    corpus: str,
    dimensions: "Sequence[tuple[str, tuple[str, ...]]]",  # [(dim_id, values), ...]
    legal: Callable[..., bool],
) -> "list[Cell]":
    """The full (legal) cell grid for one corpus — e.g. room's (kind x climate) 53 cells. `legal`
    is the adapter's own `legal_combinations()` result, called pairwise exactly as the Coverage
    metric does, so a cell this function yields is a cell the metric would also count."""
    if len(dimensions) == 1:
        dim_id, values = dimensions[0]
        return [Cell(corpus, (v,), v) for v in sorted(values)]

    if len(dimensions) != 2:
        raise NotImplementedError("enumerate_cells supports 1 or 2 dimensions today (every dungeon corpus is <=2-D)")

    (dim_a, values_a), (dim_b, values_b) = dimensions
    cells: "list[Cell]" = []
    for a in sorted(values_a):
        for b in sorted(values_b):
            if legal(dim_a, a, dim_b, b):
                cells.append(Cell(corpus, (a, b), f"{a}-{b}"))
    return cells


class IdMinter:
    """Mints `<namespace>.<cell>-<nnn>` ids, continuing from a supplied high-water mark per
    (namespace, cell) pair — never restarting at 1, which is exactly the four tracking-id defects
    the item build hit (seedsmith-map Appendix A row 6, cited by this module's own spec)."""

    def __init__(self, high_water_marks: "Mapping[tuple[str, str], int] | None" = None) -> None:
        self._marks: "dict[tuple[str, str], int]" = dict(high_water_marks or {})

    def next_id(self, namespace: str, cell_key: str) -> str:
        key = (namespace, cell_key)
        n = self._marks.get(key, 0) + 1
        self._marks[key] = n
        return f"{namespace}.{cell_key}-{n:03d}"

    def high_water_marks(self) -> "dict[tuple[str, str], int]":
        return dict(self._marks)


def plan_ids_for_cells(cells: "Sequence[Cell]", namespace: str, count_per_cell: "Mapping[str, int]", minter: IdMinter) -> "dict[str, list[str]]":
    """`cell_key -> [minted ids]`, `count_per_cell[cell.cell_key]` entries each — the planner's own
    §4 step 3 ("Ids minted per cell, sequence from the high-water mark"), independent of whatever
    fills each entry's content (that is the pipeline's job, §4 step ahead of this one)."""
    result: "dict[str, list[str]]" = {}
    for cell in cells:
        n = count_per_cell.get(cell.cell_key, 0)
        result[cell.cell_key] = [minter.next_id(namespace, cell.cell_key) for _ in range(n)]
    return result


def select_planning_themes(themes: "Mapping[str, dict]", *, per_rarity: int = 2) -> "tuple[str, ...]":
    """The event corpus's own "8 planner-fixed theme subset of the 84" (spec-dungeon-seed-
    contract.md §1.4). Deterministic and reproducible: `per_rarity` alphabetically-first,
    non-retired theme ids from EACH real rarity band (`common · epic · legendary · rare`, in
    alphabetical order) in the real registry (`registries.load_themes()`).

    Picking by raw motif+antiMotif richness instead was tried and rejected by direct measurement:
    the top 8 by combined richness cluster on one flavor family (six of eight land on `cherry`-
    themed creatures, sharing near-identical motif lists) — exactly the monoculture a planner-fixed
    SUBSET exists to avoid. Spreading across the registry's own rarity bands needs no judgment call
    (only counting) and cannot repeat that failure mode by construction.
    """
    # Theme refresh can carry a source-only fallback rarity (currently ``almanac``) for species
    # whose anchor has not published a four-band rarity yet.  That value is valid for the creature
    # registry but is not a dungeon planning band; admitting it silently expanded the fixed
    # eight-theme subset to 28 when the roster grew from 84 to 904.  Keep the planner on the
    # dungeon contract's four legal bands and leave unclassified themes available for later
    # enrichment rather than changing the event budget.
    legal_rarities = {"common", "rare", "epic", "legendary"}
    by_rarity: "dict[str, list[str]]" = {}
    for theme_id, row in themes.items():
        if row.get("retired"):
            continue
        if row.get("rarity") not in legal_rarities:
            continue
        by_rarity.setdefault(row["rarity"], []).append(theme_id)
    chosen: "list[str]" = []
    for rarity in sorted(by_rarity):
        chosen.extend(sorted(by_rarity[rarity])[:per_rarity])
    return tuple(chosen)


def allocate_event_targets(
    theme_subset: "Sequence[str]", kinds: "Sequence[str]", *, doubled_per_kind: int = 2,
) -> "dict[tuple[str, str], int]":
    """Per-`(kind, theme)` target count for the event corpus's 48-cell grid (6 kind x 8 theme,
    `budget.v1.json`'s own firstShip 60, firstShipPerCell 1.25). The SAME `doubled_per_kind` themes
    (by `theme_subset`'s own fixed order — never a per-kind independent pick, which would let one
    kind's own choice silently diverge from the rest) get target 2 for every kind; the remaining
    themes get target 1: with the defaults, 6 kinds x (2 themes x 2 + 6 themes x 1) = 60, matching
    firstShip exactly with no remainder to place ad hoc.
    """
    doubled = set(theme_subset[:doubled_per_kind])
    return {(kind, theme): (2 if theme in doubled else 1) for kind in kinds for theme in theme_subset}


def motif_brief_for_slot(theme_row: "Mapping[str, object]", slot_index: int, total_slots: int) -> "dict[str, list[str]]":
    """One cell's own theme, partitioned across `total_slots` sibling entries (spec §4 step 2: "a
    disjoint partition of the motif registry ... into `target` slots ... every cell-sibling's
    motifs as anti-motifs"). The partition is WITHIN one cell's own already-theme-filtered motif
    pool (never reaching into another cell's different theme) — "filtered by ... theme" in the
    spec's own words.

    `total_slots == 1` needs no partition: the entry gets the theme's whole motif list and its own
    already-published `antiMotifs`, untouched. `total_slots == 2` splits the theme's own motif list
    by alternating index — stable regardless of odd/even length, and every real theme has >= 2
    motifs (measured against the live registry, `AtomFamilyTests`' own sibling check in
    `test_dungeon_registries.py` proves the analogous floor for atom families; themes are checked
    in `test_dungeon_planner.py` directly) so neither half is ever empty. Each slot's OWN half goes
    in `motifs`; the OTHER slot's half joins the theme's own `antiMotifs`, so the two sibling
    entries can never legally reuse each other's assigned words. `allocate_event_targets`'s own
    `doubled_per_kind` caps every event cell at target <= 2, so a 3-way split is out of scope today.
    """
    motifs = list(theme_row.get("motifs") or [])
    anti = list(theme_row.get("antiMotifs") or [])
    if total_slots <= 1:
        return {"motifs": motifs, "antiMotifs": anti}
    if total_slots > 2:
        raise NotImplementedError("motif_brief_for_slot supports at most 2 slots per cell today — "
                                   "no event cell needs more (allocate_event_targets caps target<=2)")
    mine = motifs[slot_index::2]
    theirs = motifs[(slot_index + 1) % 2::2]
    return {"motifs": mine, "antiMotifs": anti + theirs}


def allocate_even_targets(cell_keys: "Sequence[str]", total: int) -> "dict[str, int]":
    """An even split of `total` entries across `cell_keys`, remainder going to the alphabetically
    FIRST cells (never the caller's own iteration order, so the result is reproducible regardless
    of how `cell_keys` was built). `dungeon-encounter`'s own `budget.v1.json` row has
    `perCell: null` BY DESIGN ("density measured as distinct shapes reached, not raw entries per
    cell") -- meaning nothing in the seed contract prescribes a per-cell count the way `firstShip
    PerCell` does for event/room/domain, so this is a real, named authoring decision (a plain even
    split), not a derived fact.

    **Superseded for `dungeon-encounter` itself by `allocate_encounter_targets` below** (2026-09-07):
    a real 40-entry batch measured this plain split assigning `boss`-formation cells (only 3 real
    distinct posture multisets exist for a 1-slot formation, `posture_multisets_for`'s own doc
    comment) the SAME 4-5-entry target as pack/party cells (6/10 multisets each) -- a real,
    structural over-allocation the model could never fill distinctly no matter how it was prompted.
    Kept here, unchanged, for any FUTURE corpus whose own cells are not posture-shaped."""
    n = len(cell_keys)
    if n == 0:
        return {}
    base, remainder = divmod(total, n)
    ordered = sorted(cell_keys)
    return {key: base + (1 if i < remainder else 0) for i, key in enumerate(ordered)}


def posture_multisets_for(n_slots: int) -> "tuple[tuple[str, ...], ...]":
    """Every DISTINCT posture multiset a formation's own `n_slots` can express — order-independent
    (`EncounterCoverage.cs`'s own key groups `(Bastion, Finesse)` and `(Finesse, Bastion)` as the
    SAME shape), so this is combinations-WITH-replacement over the three real postures, sorted for
    determinism: exactly 3 for `n_slots=1` (boss), 6 for `n_slots=2` (pack), 10 for `n_slots=3`
    (party) -- a real, measured ceiling, not an estimate (`itertools.combinations_with_replacement`
    over 3 items choose `n_slots`)."""
    postures = ("Bastion", "Finesse", "Force")
    return tuple(itertools.combinations_with_replacement(postures, n_slots))


def allocate_encounter_targets(
    cells: "Sequence[Cell]", slot_count_by_formation: "Mapping[str, int]", total: int,
) -> "dict[str, int]":
    """Shape-aware allocation for `dungeon-encounter`'s own 9-cell budget (`budget.v1.json`'s own
    `perCell: null`) — replaces the naive `allocate_even_targets` after a real, measured failure:
    a plain even split gave every `boss` cell (only 3 distinct posture multisets, `posture_
    multisets_for(1)`) the same 4-5-entry target as `pack`/`party` cells (6/10 multisets), which is
    structurally unfillable no matter how the model is prompted (a live batch resolved only 1/4 on
    a `pack` cell even with per-attempt enum permutation and an explicit "pick a different
    combination" retry message — the model's own content prior for a small team comp is strong
    enough that neither fix moved the needle; see `run_encounter_draws`'s own doc comment for the
    full measurement). Every cell is capped at its own REAL shape ceiling; the total this caps away
    is redistributed evenly (remainder to the alphabetically-first) across cells still under their
    own ceiling, repeating until the full `total` is placed or every cell is at its ceiling (the
    real, honest stopping condition if `total` exceeds the corpus's own combined ceiling — never
    silently over-allocated past what the shapes can express)."""
    ceilings = {c.cell_key: len(posture_multisets_for(slot_count_by_formation[c.dimension_values[0]])) for c in cells}
    allocated: "dict[str, int]" = {key: 0 for key in ceilings}
    remaining = total

    while remaining > 0:
        open_keys = sorted(key for key in ceilings if allocated[key] < ceilings[key])
        if not open_keys:
            break  # every cell is at its own real ceiling -- the corpus cannot honestly hold more
        share, extra = divmod(remaining, len(open_keys))
        placed_this_round = 0
        for i, key in enumerate(open_keys):
            room = ceilings[key] - allocated[key]
            want = share + (1 if i < extra else 0)
            grant = min(room, want)
            allocated[key] += grant
            placed_this_round += grant
        remaining -= placed_this_round
        if placed_this_round == 0:
            break  # defensive -- every open cell had zero room, should be unreachable given the filter above
    return allocated


#: The seven climate values in ROTATION order: the six elements, then `none`. A structural ordering
#: over a closed vocabulary (not a balance number), so it lives here rather than in a tuning file.
EVENT_CLIMATES: "tuple[str, ...]" = tuple(ELEMENTS) + ("none",)


def event_kind_of(cell_key: str) -> str:
    """The event kind a cell key names. Cell keys are `{kind}-{theme}` by this adapter's own
    construction, and two real kinds contain a hyphen (`encounter-event`), so this matches the closed
    kind vocabulary by LONGEST prefix — never by splitting on the first hyphen. A key naming no kind
    raises rather than guessing."""
    matches = [kind for kind in EVENT_KIND if cell_key == kind or cell_key.startswith(f"{kind}-")]
    if not matches:
        raise ValueError(
            f"cell key {cell_key!r} names no event kind of {sorted(EVENT_KIND)} — the planner cannot "
            f"assign a climate to a cell it cannot place in a kind")
    return max(matches, key=len)


def assign_event_climates(planned_ids_by_cell: "Mapping[str, list[str]]") -> "dict[str, str]":
    """Assign each planned event a climate (spec-dungeon-generator-repair.md §5): within each kind,
    sort that kind's planned ids, then give them the seven climates in rotation. Deterministic — two
    calls over the same mapping return the same dict, key order aside — and a kind with seven or more
    slots covers every climate. The model no longer decides this field."""
    ids_by_kind: "dict[str, list[str]]" = {}
    for cell_key, ids in planned_ids_by_cell.items():
        ids_by_kind.setdefault(event_kind_of(cell_key), []).extend(ids)
    assigned: "dict[str, str]" = {}
    for kind in sorted(ids_by_kind):
        for index, event_id in enumerate(sorted(ids_by_kind[kind])):
            assigned[event_id] = EVENT_CLIMATES[index % len(EVENT_CLIMATES)]
    return assigned
