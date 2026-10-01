"""seedsmith.adapters.items.trophyplan.species — the two corpus-shaped inputs the trophy planner
needs: the non-excluded species roster (the seed TREE, not a C# runtime mirror) and the species ->
families map, joined and cross-validated (spec-species-materials.md § Design 4, Input table).

⛔ **Why this owns its own family-map loader instead of calling
`adapters.actions.vocab.load_family_map_keys()`** (spec's own explicit warning, quoted here so the
refusal is traceable to source, not paraphrase): that function

  1. returns only the family-id VALUES (a flat `frozenset[str]`), never the species -> families
     MAPPING this planner needs to decide, per species, which family scopes to mint into;
  2. returns an EMPTY SET when `family-map.json` is absent, so a caller degrades to "nothing known"
     -- exactly wrong here, where an absent file must refuse the whole plan by name, never silently
     mint zero family trophies; and
  3. UNIONS the legacy `gk-data/packs/fusion/data/seed/creatures/_registry/families.v1.json` compatibility registry into
     its result, which would mint `trophy.family.*` ids for families no LIVE species belongs to.

Both conditions this module refuses instead (missing/unparsable file; a non-excluded species absent
from the map's key set) are exercised in `gk-forge/tools/seedsmith/tests/test_trophy_plan.py`.

**Species roster source: the seed tree, not the C# runtime.** `speciesKind` (the `"excluded"` mark,
R-CS3/R-CS4: an excluded row is *"not a creature ... never counts as roster"*) has no C# runtime
mirror yet (`creature-seed-ideal.md` header) -- `CreatureSpeciesCatalog` cannot answer "is this
species excluded" today. The seed tree carries the mark directly, so this module reads
`gk-data/packs/fusion/data/seed/creatures/species/**/*.json` rather than the runtime catalog.

**Casing.** `family-map.json`'s own keys are the LOWERCASED runtime id (confirmed 2026-09-19:
`"abyssswordstar"`, `"acientsunnut"`, ...) -- the same casing `species_repair.py`'s own
`speciesId` field already writes into `gk-data/packs/fusion/data/seed/items/sets/*.json` (task T28). This module
lower-cases every raw `speciesId` it reads from the seed tree at the one point it leaves the tree,
so every id this package hands the planner (and every id the planner mints from it) matches that
established casing -- never the tree's own mixed-case `speciesId` field verbatim.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "TrophyPlanError", "SpeciesRow", "SPECIES_ROOT", "FAMILY_MAP_PATH",
    "load_species_roster", "load_family_map", "resolve_family_membership",
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

SPECIES_ROOT = _owned("data/seed/creatures/species")
FAMILY_MAP_PATH = _owned("data/seed/actions/_generated/family-map.json")

_EXCLUDED_KIND = "excluded"


class TrophyPlanError(ValueError):
    """The trophy planner's own inputs failed to load or cross-validate -- refused, never a filler
    or a silent skip (spec § Design 5.3: *"nothing here mutates the draft into legality"*, the same
    posture `trees.species.plan.FavourPlanError` already takes for a sibling species-scale planner)."""


@dataclass(frozen=True)
class SpeciesRow:
    species_id: str    # lower-cased, the runtime/family-map casing
    raw_species_id: str  # the tree's own `speciesId` field, for legible error messages only
    source_file: Path


def load_species_roster(seed_root: "Path | None" = None) -> "tuple[SpeciesRow, ...]":
    """Every non-`excluded` species record across the seed tree, lower-cased and de-duplicated by
    id. Refuses (never skips) a file that is not a JSON list of objects, or a record missing its own
    `speciesId` -- both are corpus-shape defects, not something a planner should paper over."""
    root = seed_root or SPECIES_ROOT
    if not root.is_dir():
        raise TrophyPlanError(f"{root}: species seed root is missing")

    # `_index.json` (and any other underscore-prefixed file) is corpus metadata, not a species
    # record list -- the same skip `adapters.creatures.completeness`/`generate_themes` already
    # apply when walking this same tree.
    files = sorted(p for p in root.rglob("*.json") if not p.name.startswith("_"))
    if not files:
        raise TrophyPlanError(f"{root}: no species seed files found")

    by_id: "dict[str, SpeciesRow]" = {}
    for file_path in files:
        try:
            doc = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise TrophyPlanError(f"{file_path}: not valid JSON -- {exc}") from exc
        if not isinstance(doc, list):
            raise TrophyPlanError(f"{file_path}: expected a JSON array of species records")
        for record in doc:
            if not isinstance(record, dict) or "speciesId" not in record:
                raise TrophyPlanError(f"{file_path}: a species record is missing 'speciesId'")
            raw_id = str(record["speciesId"])
            if record.get("speciesKind") == _EXCLUDED_KIND:
                continue
            species_id = raw_id.lower()
            existing = by_id.get(species_id)
            if existing is not None and existing.raw_species_id != raw_id:
                raise TrophyPlanError(
                    f"{file_path}: speciesId {raw_id!r} collides case-insensitively with "
                    f"{existing.raw_species_id!r} from {existing.source_file} -- refused, not merged")
            by_id[species_id] = SpeciesRow(
                species_id=species_id, raw_species_id=raw_id, source_file=file_path)
    return tuple(by_id[key] for key in sorted(by_id))


def load_family_map(path: "Path | None" = None) -> "dict[str, tuple[str, ...]]":
    """The RAW species -> families mapping, verbatim (never unioned with the legacy registry, never
    collapsed to a flat id set -- see module docstring). Refuses an absent or unparsable file by
    name; never degrades to `{}`."""
    map_path = path or FAMILY_MAP_PATH
    if not map_path.is_file():
        raise TrophyPlanError(f"{map_path}: family map is missing")
    try:
        doc = json.loads(map_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TrophyPlanError(f"{map_path}: not valid JSON -- {exc}") from exc
    if not isinstance(doc, dict):
        raise TrophyPlanError(f"{map_path}: top level must be a JSON object keyed by species id")

    out: "dict[str, tuple[str, ...]]" = {}
    for species_id, families in doc.items():
        if not isinstance(families, list) or not all(isinstance(f, str) for f in families):
            raise TrophyPlanError(
                f"{map_path}: {species_id!r} must map to an array of family-id strings -- got {families!r}")
        out[species_id] = tuple(families)
    return out


def resolve_family_membership(
        roster: "tuple[SpeciesRow, ...]", family_map: "dict[str, tuple[str, ...]]",
) -> "dict[str, tuple[str, ...]]":
    """Cross-validates the two inputs and returns the roster's own species -> families view.

    Refuses any non-excluded roster species absent from `family_map`'s key set -- "a species that
    shipped after `family-map.json` was last regenerated" (spec § Design, Input table) -- naming
    every missing id at once rather than failing on the first. A species PRESENT with an EMPTY
    family list is legal (§ Design 5 step 3, the no-family case) and is returned as `()`, not
    dropped and not raised on.
    """
    missing = [row.raw_species_id for row in roster if row.species_id not in family_map]
    if missing:
        raise TrophyPlanError(
            f"{len(missing)} non-excluded species are absent from {FAMILY_MAP_PATH.name}'s own key "
            f"set (regenerate the family map before planning trophies): {sorted(missing)}")
    # Normalized to `tuple` regardless of what the caller's own `family_map` values were shaped as
    # (a synthetic test fixture may hand in plain lists) -- this function's contract is a tuple,
    # matching `load_family_map`'s own return shape exactly.
    return {row.species_id: tuple(family_map[row.species_id]) for row in roster}
