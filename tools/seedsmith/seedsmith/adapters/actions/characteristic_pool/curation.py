"""seedsmith.adapters.actions.characteristic_pool.curation — the closed-trait bridge.

**The defect this module exists to fix, found by direct measurement 2026-09-11.** The action
pipeline scores a species' *traits* against the closed 14-member `CreatureTraitCatalog` pool
(`TRAIT_POOL` in `catalog.py`, and `_TRAIT_CATEGORY` in `derive.py`). That was correct when the
roster was the 84-row `CreatureSpeciesCatalog.Generated.cs`, whose `TraitPool` arrays held those
exact 14 ids. The roster is now the live seed folder (`gk-data/packs/fusion/data/seed/creatures/species/**/*.json`), whose
`traits` field is **open, free-form flavor text** — measured 2026-09-11: **2,312 distinct tokens**
across 904 species, of which exactly **one** (`guardian`, once) is a closed-pool member. Every
other species therefore contributed **zero** trait signal, and the derivation collapsed: 673 of 904
species landed on `separation == 0` and only 11 distinct `leanOrder`s existed across the whole
roster. The per-species differentiation the whole action corpus rests on was effectively absent.

The runtime already solved this exact problem. `CreatureTraitPoolCuration.PickFor(speciesId, rarity,
gameTypeId)` (`gk-core/src/FusionRpg.Core/Creatures/Generation/CreatureTraitPoolCuration.cs`) bridges a live
species' open flavor text to the closed gameplay vocabulary, and
`ConcreteSpeciesSeedReader.cs:103` is its real caller. This module mirrors that bridge so the
Python pipeline scores the **same closed trait pool the game actually uses**, rather than a
vocabulary the live seed does not speak.

**Why this reads the frozen `.cs` rather than a committed JSON projection.** There is no committed
artifact carrying the curated pool — the curation runs in C# at snapshot-build time and is never
written to `gk-data/packs/fusion/data/generated/`. The two inputs it needs are both frozen and committed:
`CreatureSpeciesLegacyTraitPoolOverlap.Generated.cs` (its own header: "Never regenerated from that
source again — it is gone. This file is now itself the frozen source of truth for this one-time
port.") and the FNV-1a fallback algorithm. `catalog.py` already establishes the precedent of
parsing a `.cs` source for a roster (`_load_legacy_catalog`), so this is the same discipline, not a
new one. The alternative — a second, hand-maintained copy of 68 species' trait pools in Python —
would drift from the C# SSOT the moment either side changed, which is the defect class this module
exists to close.

**Determinism and scope.** `curated_traits` is a pure function of `(species_id, rarity,
game_type_id)`, all three read from the live record. It invents no trait and drops no species: a
species absent from the frozen overlap map gets the same deterministic FNV pick the runtime gives
it, so the Python score and the in-game `TraitPool` agree by construction.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .ladders import COMBAT_TRAITS, PERSONALITY_TRAITS, RARITY_LADDER, RARITY_ORDINAL

__all__ = ["curated_traits", "LEGACY_TRAIT_OVERLAP_PATH"]

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

LEGACY_TRAIT_OVERLAP_PATH = (
    _owned("src/FusionRpg.Core/Creatures/Generation/CreatureSpeciesLegacyTraitPoolOverlap.Generated.cs")
)

# `CreatureTraitPoolCuration.Combat` / `.Personality` and the rarity ladder are read from `ladders.py`
# — the one shared transcription — rather than re-declared here. The 2026-09-11 review found the
# ladder duplicated in this file with no guard; a second copy that drifts silently shifts the
# `Heirloom` threshold below and changes which species get an essence trait.
_COMBAT = COMBAT_TRAITS
_PERSONALITY = PERSONALITY_TRAITS
_HEIRLOOM_ORDINAL = RARITY_ORDINAL["heirloom"]      # `CreatureRarityLadder.AtLeast(rarity, Heirloom)`
_TOP_RUNG = RARITY_LADDER[-1]                       # `CreatureRarityLadder.IsTopRung` -> Almanac

_ENTRY_RE = re.compile(r'\["(?P<id>[a-z0-9]+)"\]\s*=\s*new\[\]\s*\{\s*(?P<body>[^}]*)\}')
_TRAIT_RE = re.compile(r'"([a-z-]+)"')


@lru_cache(maxsize=1)
def _legacy_overlap() -> "dict[str, tuple[str, ...]]":
    """Parse the frozen port-forward map. Cached — the file is a one-time extraction that is never
    regenerated, so reading it once per process is sufficient and keeps the per-species call cheap."""
    text = LEGACY_TRAIT_OVERLAP_PATH.read_text(encoding="utf-8")
    out: "dict[str, tuple[str, ...]]" = {}
    for m in _ENTRY_RE.finditer(text):
        out[m.group("id")] = tuple(_TRAIT_RE.findall(m.group("body")))
    return out


def _fnv1a(type_id: int, salt: str) -> int:
    """`CreatureTraitPoolCuration.Hash` — FNV-1a over the salt then the type id, 32-bit unsigned,
    copied verbatim (the C# class itself copied it from the deleted legacy generator for the same
    cross-boundary reason: an algorithm is not a data file, and there is nothing left to reference)."""
    h = 2166136261
    for ch in salt:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    h ^= type_id & 0xFFFFFFFF
    h = (h * 16777619) & 0xFFFFFFFF
    return h


def curated_traits(species_id: str, rarity: str, game_type_id: int) -> "tuple[str, ...]":
    """The closed `CreatureTraitCatalog` pool for one live species — the exact pool the game gives it.

    Mirrors `CreatureTraitPoolCuration.PickFor`: the frozen legacy port-forward wins by species id
    when present; every other species gets the deterministic FNV pick (two guaranteed slots plus a
    third combat trait when distinct), with an essence trait at `Heirloom` and up and `immortal` at
    the top rung. `species_id` is normalised to lower case, matching the C# `Trim().ToLowerInvariant()`
    and `catalog.load_live_records`' own canonical key.
    """
    key = species_id.strip().lower()
    legacy = _legacy_overlap().get(key)
    if legacy is not None:
        return legacy

    pool = [
        _COMBAT[_fnv1a(game_type_id, "curate-t1") % len(_COMBAT)],
        _PERSONALITY[_fnv1a(game_type_id, "curate-t2") % len(_PERSONALITY)],
    ]
    third = _COMBAT[_fnv1a(game_type_id, "curate-t3") % len(_COMBAT)]
    if third not in pool:
        pool.append(third)

    ordinal = RARITY_ORDINAL.get(rarity, 0)
    if ordinal >= _HEIRLOOM_ORDINAL:
        pool.append("void-touched" if _fnv1a(game_type_id, "curate-essence") % 2 == 0
                    else "chaos-marked")
    if rarity == _TOP_RUNG:
        pool.append("immortal")
    return tuple(pool)
