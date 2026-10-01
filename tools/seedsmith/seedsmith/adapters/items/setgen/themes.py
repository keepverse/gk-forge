"""seedsmith.adapters.items.setgen.themes — the theme bridge, one-way.

⛔ **Creatures publish; items consume; nothing here writes a creature** (`spec-creature-themes.md` §2.2). This
module opens `gk-data/packs/fusion/data/seed/creatures/_registry/themes.v1.json` for reading and opens nothing under
`gk-data/packs/fusion/data/seed/creatures/` for writing — `nothing_in_the_generator_writes_the_creatures_corpus` asserts that
structurally rather than by promise.

Three populations of `themeKey`, collision-free by prefix:

| prefix | population | source |
|---|---|---|
| `theme.` | 13 legacy, 5 in use | `gk-data/packs/fusion/data/seed/items/_registry/themes.v1.json` (frozen) |
| `creature.` | one per species | `gk-data/packs/fusion/data/seed/creatures/_registry/themes.v1.json` (published) |
| `build.` | 36, aptitude x archetype | `gk-data/packs/fusion/data/seed/items/_registry/build-themes.v1.json` (new, D-ruled 2026-09-04) |

⚠ **D34's enrichment precondition remains visible here.** `theme-refresh` now reads the complete
almanac dump and appends themes for the full shipped roster. Themes whose source remains
`basis = "name"` are *held*, never generated from — `generatable` excludes them and
`holdback_report` names the count, so an incomplete run reports `not_measured` instead of a green
partial. Coverage counts are always derived by `coverage_report`; never transcribe a roster size.

⚠ **Nothing here may key on a theme's `rarity`** (§2.4a): `RarityForRank` is proportional in `count`,
so a species moves tier as the roster grows *without moving rank*. A theme records the rarity it was
published against precisely so a later reader sees the drift instead of inheriting it. `rarity` is
carried through to provenance and read by nothing else.
"""
from __future__ import annotations

import json
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

#: species-gear-chain T16: reads v2 (rarity corrected, keys unchanged) — v1 stays in place,
#: unretired, for whatever still binds it.
CREATURE_THEME_REGISTRY = _owned("data/seed/creatures/_registry/themes.v2.json")
CREATURE_SPECIES_ROOT = _owned("data/seed/creatures/species")
BUILD_THEME_REGISTRY = _owned("data/seed/items/_registry/build-themes.v1.json")
LEGACY_THEME_REGISTRY = _owned("data/seed/items/_registry/themes.v1.json")

#: The basis a theme must have reached before it may be generated from. `theme-enrich` (P0.3)
#: records model-authored lore as ``enriched`` rather than pretending it was observed source text.
#: Name-only themes remain held until that stage succeeds.
GENERATABLE_BASES: "frozenset[str]" = frozenset({"text", "derived", "enriched"})


@dataclass(frozen=True)
class Theme:
    """One row of whichever population it came from, normalised to what a brief needs."""

    theme_key: str
    species_id: "str | None"
    display_name: str
    motifs: "tuple[str, ...]"
    anti_motifs: "tuple[str, ...]"
    expression_item: str
    basis: str
    rarity: "str | None"
    retired: bool
    population: str          # "species" | "build" | "legacy"
    aptitude: "str | None" = None
    archetype: "str | None" = None
    lore: str = ""          # optional model-authored context from theme-enrich

    @property
    def generatable(self) -> bool:
        return (not self.retired) and self.basis in GENERATABLE_BASES and bool(self.motifs)

    @property
    def hold_reason(self) -> "str | None":
        if self.retired:
            return "retired"
        if self.basis not in GENERATABLE_BASES:
            return f"basis={self.basis}"
        if not self.motifs:
            return "no motifs"
        return None


def load_species_themes(path: "Path | None" = None) -> "list[Theme]":
    doc = json.loads((path or CREATURE_THEME_REGISTRY).read_text(encoding="utf-8"))
    out: "list[Theme]" = []
    for theme_key, row in sorted(doc["themes"].items()):
        out.append(Theme(
            theme_key=theme_key,
            species_id=row["speciesId"],
            display_name=row.get("displayName", ""),
            motifs=tuple(row.get("motifs") or ()),
            anti_motifs=tuple(row.get("antiMotifs") or ()),
            expression_item=(row.get("expression") or {}).get("item", ""),
            basis=row.get("basis", ""),
            rarity=row.get("rarity"),
            retired=bool(row.get("retired")),
            population="species",
            lore=str(row.get("flavor") or row.get("lore") or ""),
        ))
    return out


def load_build_themes(path: "Path | None" = None) -> "list[Theme]":
    doc = json.loads((path or BUILD_THEME_REGISTRY).read_text(encoding="utf-8"))
    return [
        Theme(
            theme_key=row["themeKey"], species_id=None, display_name=row["displayName"],
            motifs=tuple(row.get("motifs") or ()), anti_motifs=tuple(row.get("antiMotifs") or ()),
            expression_item=(row.get("expression") or {}).get("item", ""),
            basis=row.get("basis", ""), rarity=None, retired=bool(row.get("retired")),
            population="build", aptitude=row.get("aptitude"), archetype=row.get("archetype"),
        )
        for row in doc["themes"]
    ]


def build_theme_keys(path: "Path | None" = None) -> "frozenset[str]":
    doc = json.loads((path or BUILD_THEME_REGISTRY).read_text(encoding="utf-8"))
    return frozenset(row["themeKey"] for row in doc["themes"])


def legacy_theme_ids(path: "Path | None" = None) -> "frozenset[str]":
    """The bare ids of the legacy `theme.*` population — what a generated id must not collide with."""
    doc = json.loads((path or LEGACY_THEME_REGISTRY).read_text(encoding="utf-8"))
    return frozenset(t["id"] for t in doc["themes"])


def legacy_partition_ids(naming_path: "Path | None" = None) -> "frozenset[str]":
    """The FIVE `themeId`s `naming.v1.json` actually pinned as set partitions — a tighter set than
    the 13 registered legacy themes, and the one a generated set id is checked against."""
    path = naming_path or (_owned("data/seed/items/_registry/naming.v1.json"))
    doc = json.loads(path.read_text(encoding="utf-8"))
    return frozenset(doc["idNamespaces"]["sets"]["themeIds"])


def generatable(themes: "list[Theme]") -> "list[Theme]":
    return [t for t in themes if t.generatable]


@dataclass(frozen=True)
class HoldbackReport:
    """What a run may generate, and precisely what it may not — the input to the run verdict.

    A run that generated 53 of 84 themes is **not** a pass. It is `not_measured` for the held
    population, which is the honest answer and the one this module must not launder into green.
    """

    total: int
    generatable: int
    held: "tuple[tuple[str, str], ...]"     # (themeKey, reason)

    @property
    def complete(self) -> bool:
        return not self.held

    def held_by_reason(self) -> "dict[str, int]":
        counts: "dict[str, int]" = {}
        for _, reason in self.held:
            counts[reason] = counts.get(reason, 0) + 1
        return counts


def holdback_report(themes: "list[Theme]") -> HoldbackReport:
    held = tuple((t.theme_key, t.hold_reason) for t in themes if t.hold_reason)
    return HoldbackReport(total=len(themes), generatable=len(themes) - len(held), held=held)


def shipped_species_ids(root: "Path | None" = None) -> "frozenset[str]":
    """Every species the anchor tree actually ships.

    The index is the fast, canonical lookup, but it is not allowed to hide a freshly emitted
    family file (or a stale index entry).  Merge both views case-insensitively and keep one
    representative spelling.  The theme coverage gate then turns any index/tree drift into an
    explicit uncovered/orphaned result instead of silently planning a partial population.
    """
    base = root or CREATURE_SPECIES_ROOT
    index = base / "_index.json"
    indexed: "frozenset[str]" = frozenset()
    if index.exists():
        doc = json.loads(index.read_text(encoding="utf-8"))
        indexed = _species_ids_from_index(doc)

    # Family files are arrays of many species; filenames are family names, not species ids.
    on_disk: set[str] = set()
    for path in base.glob("*/*.json"):
        if path.name.startswith("_"):
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else (
            raw.get("entries", []) if isinstance(raw, dict) else [])
        on_disk.update(str(row.get("speciesId") or "").strip()
                       for row in rows if isinstance(row, dict) and row.get("speciesId"))

    # Prefer the index spelling (currently PascalCase) while adding any file-only ids.  The
    # coverage report folds case, so this also avoids counting `AllPeater` and `allpeater` twice.
    merged: "dict[str, str]" = {value.lower(): value for value in indexed}
    for value in on_disk:
        merged.setdefault(value.lower(), value)
    return frozenset(merged.values())


def _species_ids_from_index(doc) -> "frozenset[str]":
    """The index shape is the creatures feature's, not ours — read defensively rather than assume it,
    and fall back to the tree when it is a shape this module does not recognise.

    ⛔ **The shape that matters, and the one a filename count gets wrong.** `_index.json` is a flat
    `{speciesId: "plant/family.json"}` map — the *files* under `species/` are FAMILY files holding
    many species each, so `ls gk-data/packs/fusion/data/seed/creatures/species/{plant,zombie} | wc -l` counts families, not
    species. Re-measured 2026-09-06: **502 family files, 840 species** (was 496 files on 2026-09-04 —
    the concurrent stream keeps rewriting the tree, and the species count has held across every
    re-measure). Anything comparing the theme registry against the file count is comparing against the
    wrong denominator, which is why both numbers are functions and neither is a constant.

    ⚠ **Case is load-bearing.** Index keys are PascalCase (`AllPeater`); published theme `speciesId`s
    are lowercase (`allpeater`). `coverage_report` lowercases both sides. A new checker that compares
    them case-sensitively reports 840 uncovered and 84 orphans — every row wrong, and green-looking
    nowhere, so it fails loudly rather than silently. Match on the folded form.
    """
    if isinstance(doc, dict):
        for key in ("species", "entries", "anchors"):
            rows = doc.get(key)
            if isinstance(rows, list):
                out = {r.get("speciesId") or r.get("id") for r in rows if isinstance(r, dict)}
                return frozenset(s for s in out if s)
            if isinstance(rows, dict):
                return frozenset(rows)
        # The real, shipped shape: speciesId -> relative family path.
        if doc and all(isinstance(v, str) for v in doc.values()):
            return frozenset(doc)
    return frozenset()


def species_family_file_count(root: "Path | None" = None) -> int:
    """The count a naive `ls | wc -l` produces — kept as its own function precisely so a test can
    pin that it is NOT the species count, and the two can never be confused again."""
    base = root or CREATURE_SPECIES_ROOT
    return sum(1 for p in base.glob("*/*.json") if not p.stem.startswith("_"))


@dataclass(frozen=True)
class CoverageReport:
    """⛔ D34: the theme registry must cover every shipped species. 84 vs 386 was a stale snapshot of
    a GENERATED corpus quoted as a design proportion — the defect this report exists to make loud."""

    species: int
    themes: int
    uncovered: "tuple[str, ...]"
    orphaned: "tuple[str, ...]"    # themes naming a species the tree no longer ships

    @property
    def complete(self) -> bool:
        return not self.uncovered and not self.orphaned


def coverage_report(themes: "list[Theme]", species_root: "Path | None" = None) -> CoverageReport:
    species = shipped_species_ids(species_root)
    covered = {t.species_id for t in themes if t.species_id}
    lowered = {s.lower() for s in species}
    covered_lower = {c.lower() for c in covered}
    return CoverageReport(
        species=len(species), themes=len(themes),
        uncovered=tuple(sorted(s for s in species if s.lower() not in covered_lower)),
        orphaned=tuple(sorted(c for c in covered if c.lower() not in lowered)),
    )
