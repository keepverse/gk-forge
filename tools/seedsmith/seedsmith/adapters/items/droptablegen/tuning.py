"""seedsmith.adapters.items.droptablegen.tuning — every closed vocabulary and real-corpus reader a
drop-table generation run needs, read fresh from disk. Nothing here is transcribed by hand from
memory or from the spec's own worked examples: every function reads the real, current shipped
content, the same "registry facts are read, never copied" discipline every sibling module states.

**The five reference kinds this module resolves against, confirmed by reading the real corpus
directly (not by reasoning — spec-drop-tables-gen.md's own correction note), plus one more found
while building this module (see `MATERIAL_QTY_CURVE_ID` below):**

| Field | Kind | Real target | Resolved by |
|---|---|---|---|
| `role`+`frame` | categorical | `base-types-gen`'s corpus | `legal_role_frame_pairs()` |
| `.ref` (material rows) | hard | `materials-gen`'s corpus, on **`runtimeId`**, never `id` | `load_material_runtime_ids()` |
| `.ref` (consumable rows) | hard | `consumables-gen`'s corpus, on `id` | `load_consumable_ids()` |
| `.ref` (gem/insert rows) | hard | `sockets-gen`'s corpus, on `id` | `load_gem_ids()` |
| `.ref` (relic rows) | hard | `relics`' corpus, on `id` | `load_relic_ids()` |

**Real finding (2026-09-07): a material `.ref` resolves against `materials.json`'s `runtimeId`
field, never its `id`.** `materials.json` entries carry both — `id: "material.004"` (the file's own
PK) and `runtimeId: "essence.earth"` (what every drop-table row, recipe, and curve template
actually names). The reference manifest's own worked example (`d1.json:58`: `"ref":
"essence.earth"`) already showed this, but a first pass resolving `.ref` against `id` would silently
report every real material row as unresolved — confirmed by trying it against the live corpus."""
from __future__ import annotations

import json
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

DROP_TABLES_DIR = _owned("data/seed/items/drop-tables")
BASE_TYPES_DIR = _owned("data/seed/items/base-types")
MATERIALS_PATH = _owned("data/seed/items/materials/materials.json")
CONSUMABLES_DIR = _owned("data/seed/items/consumables")
GEMS_DIR = _owned("data/seed/items/gems")
#: spec-relic-item-kind.md §Design 1/4a (empire-development Task 1.3b): relic anchors live here
#: once authored through the new `relic` KindSpec. Empty/missing until Task 1.3c authors content --
#: `load_relic_ids()` below reads it fresh, so an empty corpus resolves to an empty set, never an
#: error (a missing directory simply globs to nothing, the same shape as an empty partition).
RELICS_DIR = _owned("data/seed/items/relics")
CURVES_PATH = _owned("data/seed/items/curves/curves.json")
CORE_REGISTRY = _owned("data/seed/items/_registry/core.v1.json")
BANDS_REGISTRY = _owned("data/seed/items/_registry/bands.v1.json")
NAMING_REGISTRY = _owned("data/seed/items/_registry/naming.v1.json")

#: naming.v1.json idNamespaces.dropTables: partitionCount is a FROZEN 4 (d1..d4), unlike gems/
#: materials/base-types, which grow open-endedly. A new batch appends to one of the four existing
#: slots -- it never mints a fifth partition file without a reviewed registry bump (a real finding:
#: the spec's own "or a d5.json continuation" phrasing reads as open-ended, but naming.v1.json's
#: `dropTables.partitionCount: 4` says this corpus is closed at four, matching the four acquisition
#: channels ssot-uniques.md §4.5 already names).
LEGAL_SLOTS: "tuple[int, ...]" = (1, 2, 3, 4)

#: `naming.v1.json` idNamespaces.dropTables.idTemplate: "droptable.d{slot}-{seq:03}", transcribed
#: verbatim.
ID_TEMPLATE = "droptable.d{slot}-{seq:03d}"

#: entry-shapes.md §9's own worked example authors `qtyCurve: "curve.qty-material-standard"`, but
#: curves.json's own `idVsNameKeyNote` (real finding) says that DESCRIPTIVE string predates the
#: numeric id template and is not a literal id any curve entry carries -- the real numeric id is
#: `curve.019` (`nameKey: "curve.qty-material-standard"`). Confirmed against the real corpus: every
#: one of the 49 `qtyCurve` values across d1..d4 is this exact id, with no second value ever used.
#: This module reuses it verbatim rather than asking the model to choose a curve id -- there is
#: only ever one legal choice for a stacking material's yield curve today, and inventing a second
#: would be authoring a numeric resolution table, which seed-contract.md §1 reserves for the curve
#: registry, never a per-table seed.
MATERIAL_QTY_CURVE_ID = "curve.019"

#: `souls` is the only currency id any of the 468 shipped rows ever name (23/23, confirmed by
#: reading every drop-table currency row). Structural, not a magic number: there is exactly one
#: currency in this game, so there is no vocabulary to close here -- a second currency id would be
#: a new game system, not a balance-pass tweak to this generator.
CURRENCY_ID = "souls"


class UnresolvedReference(ValueError):
    """A reference this module would mint but cannot resolve against the real, current corpus it
    targets -- raised at generation time rather than left for `items validate --deps` to catch
    later, matching the sibling modules' "refuses to mint" discipline."""


def load_material_runtime_ids(path: "Path | None" = None) -> "frozenset[str]":
    """Every real material's `runtimeId` -- the field a drop-table `material` row's `.ref` actually
    resolves against (see this module's own docstring)."""
    doc = json.loads((path or MATERIALS_PATH).read_text(encoding="utf-8"))
    return frozenset(e["runtimeId"] for e in doc.get("entries", []) if e.get("runtimeId"))


def load_consumable_ids(directory: "Path | None" = None) -> "frozenset[str]":
    directory = directory or CONSUMABLES_DIR
    ids: "set[str]" = set()
    for p in sorted(directory.glob("*.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        ids.update(e["id"] for e in doc.get("entries", []) if e.get("id"))
    return frozenset(ids)


def load_gem_ids(directory: "Path | None" = None) -> "frozenset[str]":
    directory = directory or GEMS_DIR
    ids: "set[str]" = set()
    for p in sorted(directory.glob("*.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        ids.update(e["id"] for e in doc.get("entries", []) if e.get("id"))
    return frozenset(ids)


def load_relic_ids(directory: "Path | None" = None) -> "frozenset[str]":
    """Every real relic anchor's `id` -- the field a drop-table `relic` row's `.ref` resolves
    against (spec-relic-item-kind.md §Design 4a, empire-development Task 1.3b). Mirrors
    `load_consumable_ids`/`load_gem_ids` exactly: one directory of `*.json` files, each carrying
    an `entries` list with `id` fields. A missing or still-empty `relics/` directory (the state
    until Task 1.3c authors content) yields an empty set -- callers refuse the ref, never the
    read."""
    directory = directory or RELICS_DIR
    ids: "set[str]" = set()
    for p in sorted(directory.glob("*.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        ids.update(e["id"] for e in doc.get("entries", []) if e.get("id"))
    return frozenset(ids)


def load_curve_ids(path: "Path | None" = None) -> "frozenset[str]":
    """Not one of the spec's own four reference-manifest rows, but a real fifth HARD reference
    (`qtyCurve`) this module found while reading the real corpus. Checked as a courtesy -- this
    module always emits the one legal `MATERIAL_QTY_CURVE_ID`, so the check can never fail from
    this module's own output, but it proves that id is real rather than assumed."""
    doc = json.loads((path or CURVES_PATH).read_text(encoding="utf-8"))
    return frozenset(e["id"] for e in doc.get("entries", []) if e.get("id"))


def legal_role_frame_pairs(base_types_dir: "Path | None" = None) -> "frozenset[tuple[str, str]]":
    """Every `(role, frame)` pair that resolves to at least one real base-type entry today --
    read from the actual `gk-data/packs/fusion/data/seed/items/base-types/*.json` files, never from `core.v1.json`'s
    15-role list alone, because a `(role, frame)` pair with zero authored base types (e.g.
    `standard`+`plant` before `plant-standard.json` shipped) is unresolved even though both the
    role and the frame are individually legal. `frame` here is deliberately narrower than the
    drop-table corpus's own vocabulary -- see `RealCorpusFindingsTests` in this module's test file
    for the real `hybrid`-frame rows this excludes on purpose (`base-types-gen` only ever authors
    `humanoid`/`plant`; `hybrid` is not one of its two frames, confirmed by reading its own
    `tuning.FRAMES` and by there being zero `hybrid-*.json` files on disk)."""
    directory = base_types_dir or BASE_TYPES_DIR
    pairs: "set[tuple[str, str]]" = set()
    for p in sorted(directory.glob("*.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        for e in doc.get("entries", []):
            role, frame = e.get("role"), e.get("frame")
            if role and frame:
                pairs.add((role, frame))
    return frozenset(pairs)


def load_drop_band_enum(path: "Path | None" = None) -> "tuple[str, ...]":
    """`bands.v1.json` -> `dropBand.enum`, transcribed live -- never hand-copied, so a future
    registry bump (a reviewed, versioned change per that file's own `appendOnlyRule`) is picked up
    without a code change here."""
    doc = json.loads((path or BANDS_REGISTRY).read_text(encoding="utf-8"))
    return tuple(doc["dropBand"]["enum"])


def load_rarity_ids(path: "Path | None" = None) -> "tuple[str, ...]":
    """`core.v1.json` -> `rarity.ladder[].id`, in ladder (ordinal) order -- the closed vocabulary a
    `rarityFloor` value must be one of (entry-shapes.md §9: "a `rarity_id`, never an ordinal")."""
    doc = json.loads((path or CORE_REGISTRY).read_text(encoding="utf-8"))
    return tuple(r["id"] for r in doc["rarity"]["ladder"])


def load_source_allow_enum(path: "Path | None" = None) -> "tuple[str, ...]":
    """entry-shapes.md §9: the closed `web` | `injector` | `sim` set. Not read from a registry file
    (none carries it) -- this is the one small vocabulary this module states directly, matching the
    doc's own prose rather than a JSON source, with the doc line cited so a future edit has
    somewhere to look."""
    return ("web", "injector", "sim")


def entries_by_partition(drop_tables_dir: "Path | None" = None) -> "dict[int, list[dict]]":
    """Every existing drop-table entry, grouped by its own partition slot (`droptable.d{slot}-...`)
    -- read fresh, never cached, so an append run always sees the latest on-disk state."""
    directory = drop_tables_dir or DROP_TABLES_DIR
    out: "dict[int, list[dict]]" = {}
    for p in sorted(directory.glob("d*.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        for e in doc.get("entries", []):
            slot = e["id"].split(".d", 1)[1].split("-", 1)[0]
            out.setdefault(int(slot), []).append(e)
    return out
