"""seedsmith.adapters.items.combogen.grid — 12 aptitudes x 3 archetypes -> 36; C(12,2) -> 66.

⭐ **The grid is what makes 102 affordable.** 12 + 3 authored values produce 36; 12 produce 66.
Nobody authors 102 rows, and nobody transcribes twelve aptitude ids either — both axes are READ:

- the twelve from `gk-data/packs/fusion/data/seed/aptitudes/roster.json`, the checked-in mirror of
  `AptitudeCatalog.All` (whose own `Count` is `PostureCount x PerPosture`, so a thirteenth aptitude
  changes this grid by construction rather than by a forgotten edit);
- the three from `gk-data/packs/fusion/data/seed/items/_registry/build-themes.v1.json`, module 13's derived
  (aptitude, archetype) registry. Reading the archetype axis from there rather than re-declaring it
  is what keeps a Strain's grid and a build set's grid the SAME grid — `combo.strain-might-offense`
  and `build.might-offense` are the same cell, and a second literal tuple would be the place they
  drift apart.

`assert_grid_agrees()` re-measures both axes against each other on every call and RAISES on drift,
the same discipline `setgen.roles.assert_core_agrees` applies to the role table.
"""
from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass
from pathlib import Path

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

APTITUDE_ROSTER = _owned("data/seed/aptitudes/roster.json")
BUILD_THEMES = _owned("data/seed/items/_registry/build-themes.v1.json")

#: ⛔ D20. Checked against every rarity rung, slot role, plant slot name and power class for
#: collision before `Strain`/`Splice` were chosen; the banned word is the one that failed.
BANNED_WORD = "runeword"


class GridDrift(ValueError):
    """The two axes disagree. Raised, never logged: a grid that has moved under a generator which
    already emitted content against the old one is a content defect, not a warning."""


@dataclass(frozen=True)
class AptitudeRow:
    """One aptitude, as the grid needs it. `reading` and `meaning` are the roster's own strings and
    reach the brief verbatim — no flavour is invented in this package."""

    id: str
    ordinal: int
    posture: str
    meaning: str
    reading: str

    @property
    def token(self) -> str:
        """The id as it appears inside a container id: lower-case, kebab-legal."""
        return self.id.lower()


@dataclass(frozen=True)
class Cell:
    """One subject of the run: a Strain cell (one aptitude + one archetype) or a Splice cell (two
    aptitudes). `combination_kind` is the field the emitted entry carries."""

    combination_kind: str            # "strain" | "splice"
    aptitudes: "tuple[AptitudeRow, ...]"
    archetype: "str | None"
    motifs: "tuple[str, ...]"
    anti_motifs: "tuple[str, ...]"
    theme_key: "str | None"          # a Strain cell is also a build theme; a Splice cell is not

    @property
    def key(self) -> str:
        if self.combination_kind == "strain":
            return f"{self.aptitudes[0].token}-{self.archetype}"
        return "-".join(a.token for a in self.aptitudes)


def load_aptitudes(path: "Path | None" = None) -> "tuple[AptitudeRow, ...]":
    """The twelve, in ordinal order. Ordinal order is load-bearing: it is what makes a Splice pair
    unordered by construction (`splice_id` sorts on it)."""
    doc = json.loads((path or APTITUDE_ROSTER).read_text(encoding="utf-8"))
    rows = [
        AptitudeRow(id=str(e["id"]), ordinal=int(e["ordinal"]), posture=str(e["posture"]),
                    meaning=str(e.get("role", "")), reading=str(e.get("reading", "")))
        for e in doc["entries"]
    ]
    rows.sort(key=lambda r: r.ordinal)
    ordinals = [r.ordinal for r in rows]
    if ordinals != list(range(len(rows))):
        raise GridDrift(
            f"the aptitude roster's ordinals are {ordinals}, not a dense 0..n-1 run — a Splice id "
            f"sorts on the ordinal, so a hole or a duplicate makes C(n,2) ambiguous")
    return tuple(rows)


def load_build_themes(path: "Path | None" = None) -> "tuple[dict, ...]":
    doc = json.loads((path or BUILD_THEMES).read_text(encoding="utf-8"))
    return tuple(t for t in doc["themes"] if not t.get("retired"))


def archetypes(themes: "tuple[dict, ...] | None" = None) -> "tuple[str, ...]":
    """The archetype axis, in the registry's own per-aptitude order.

    Not `sorted(...)`: the registry emits `offense, defense, balance` per aptitude and that order is
    the one module 13's 36 rows already ship in. Sorting here would silently renumber nothing today
    and reorder every brief the day a fourth archetype lands.
    """
    rows = themes if themes is not None else load_build_themes()
    seen: "list[str]" = []
    for row in rows:
        arch = str(row["archetype"])
        if arch not in seen:
            seen.append(arch)
    return tuple(seen)


def assert_grid_agrees(aptitude_rows: "tuple[AptitudeRow, ...] | None" = None,
                       themes: "tuple[dict, ...] | None" = None) -> "tuple[int, int]":
    """Re-measure the two axes against each other. Returns `(aptitudes, archetypes)`.

    Four failure directions, all raised rather than absorbed: the registry names an aptitude the
    roster does not, the roster names one the registry does not, the registry is not a complete
    product of the two axes, or a cell appears twice.
    """
    rows = aptitude_rows if aptitude_rows is not None else load_aptitudes()
    theme_rows = themes if themes is not None else load_build_themes()
    roster_ids = {r.id for r in rows}
    registry_ids = {str(t["aptitude"]) for t in theme_rows}
    if roster_ids != registry_ids:
        raise GridDrift(
            f"build-themes.v1.json's aptitude axis disagrees with the roster — only in the roster "
            f"{sorted(roster_ids - registry_ids)}, only in the registry "
            f"{sorted(registry_ids - roster_ids)}")
    arch = archetypes(theme_rows)
    cells = [(str(t["aptitude"]), str(t["archetype"])) for t in theme_rows]
    if len(set(cells)) != len(cells):
        duplicated = sorted({c for c in cells if cells.count(c) > 1})
        raise GridDrift(f"build-themes.v1.json repeats the cells {duplicated}")
    expected = len(rows) * len(arch)
    if len(cells) != expected:
        raise GridDrift(
            f"build-themes.v1.json holds {len(cells)} cells, not {len(rows)} aptitudes x "
            f"{len(arch)} archetypes = {expected} — the grid is not a complete product, so some "
            f"(aptitude, archetype) pair has no Strain to generate")
    return len(rows), len(arch)


def strain_cells(aptitude_rows: "tuple[AptitudeRow, ...] | None" = None,
                 themes: "tuple[dict, ...] | None" = None) -> "tuple[Cell, ...]":
    """36 = 12 x 3, in the registry's own order. Motifs come from the registry row, so a Strain and
    the build set on the same cell express the same words."""
    rows = aptitude_rows if aptitude_rows is not None else load_aptitudes()
    theme_rows = themes if themes is not None else load_build_themes()
    assert_grid_agrees(rows, theme_rows)
    by_id = {r.id: r for r in rows}
    cells: "list[Cell]" = []
    for theme in theme_rows:
        apt = by_id[str(theme["aptitude"])]
        cells.append(Cell(
            combination_kind="strain",
            aptitudes=(apt,),
            archetype=str(theme["archetype"]),
            motifs=tuple(theme.get("motifs") or ()),
            anti_motifs=tuple(theme.get("antiMotifs") or ()),
            theme_key=str(theme["themeKey"]),
        ))
    return tuple(cells)


def splice_cells(aptitude_rows: "tuple[AptitudeRow, ...] | None" = None) -> "tuple[Cell, ...]":
    """C(12,2) = 66 unordered pairs.

    `itertools.combinations` over the ordinal-sorted roster yields each pair exactly once with the
    lower ordinal first — so the pair is unordered by CONSTRUCTION, and `emit.splice_id` sorts again
    rather than trusting that. A uniqueness check would only discover (Might, Agility) and
    (Agility, Might) after both had been generated, which is 66 wasted calls.

    A Splice cell carries NO themeKey: it is not a build theme, it is a pair of them, and minting a
    `build.might-agility` key here would add a 37th row to a registry module 13 owns.
    """
    rows = aptitude_rows if aptitude_rows is not None else load_aptitudes()
    cells: "list[Cell]" = []
    for lo, hi in itertools.combinations(rows, 2):
        cells.append(Cell(
            combination_kind="splice",
            aptitudes=(lo, hi),
            archetype=None,
            motifs=(lo.token, hi.token, "fusion"),
            anti_motifs=(),
            theme_key=None,
        ))
    return tuple(cells)


def all_cells(aptitude_rows: "tuple[AptitudeRow, ...] | None" = None,
              themes: "tuple[dict, ...] | None" = None) -> "tuple[Cell, ...]":
    rows = aptitude_rows if aptitude_rows is not None else load_aptitudes()
    return strain_cells(rows, themes) + splice_cells(rows)


def scan_for_banned_word(text: str) -> "list[str]":
    """⛔ D20's one hard vocabulary rule, as a function so every surface can apply the same check.

    Case-insensitive and substring-based on purpose: `RuneWord`, `runewords` and `rune_word` are all
    the same defect, and a word-boundary regex would let the plural through.
    """
    hits = [m.group(0) for m in re.finditer(BANNED_WORD, text, flags=re.IGNORECASE)]
    hits += [m.group(0) for m in re.finditer(r"rune[_\- ]word", text, flags=re.IGNORECASE)]
    return hits
