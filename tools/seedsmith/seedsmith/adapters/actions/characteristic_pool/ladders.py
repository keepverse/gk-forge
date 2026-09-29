"""Closed vocabularies transcribed from C#, in one leaf module so nothing can drift apart.

**Why a leaf module.** These constants are transcriptions of C# enums/arrays that have no JSON
export, so they are "code, not data" (the same discipline `adapters/creatures/registries.py` states for
itself). Two callers need them — `catalog.py` (the roster loader) and `curation.py` (the trait
bridge). `catalog.py` imports `curation.py` for `curated_traits`, so `curation.py` importing
`catalog.py` back would be a cycle. A leaf module both import from breaks the cycle **and** removes
the duplicate transcription of the rarity ladder that previously existed in both files — the
2026-09-11 review's own duplication finding: a second copy of `RARITY_LADDER` with no guard, which
would silently shift `curated_traits`'s `Heirloom` threshold if the C# enum widened (and it has
widened before, 4 -> 10 rungs). One definition, imported everywhere, is the fix.

`catalog.py` re-exports `RARITY_LADDER`/`TRAIT_POOL` so every existing importer keeps working.
"""
from __future__ import annotations

from seedsmith.ladders import RARITY_LADDER

__all__ = [
    "RARITY_LADDER", "RARITY_ORDINAL", "TRAIT_POOL", "COMBAT_TRAITS", "PERSONALITY_TRAITS",
]

# Re-exported declaring read — gk-data/packs/fusion/data/seed/rarity/ladder.v1.json via seedsmith.ladders
# (tier-propagation-contract T-2). `catalog.py` re-exports this name further, so every existing
# importer keeps working with zero restatements anywhere on the path.
RARITY_ORDINAL = {rid: i for i, rid in enumerate(RARITY_LADDER)}

# `CreatureTraitCatalog.All` — gk-core/src/FusionRpg.Core/Creatures/CreatureTraitCatalog.cs:11-30. The closed
# 14-member trait pool (spec §3 step 4's own citation), never re-derived from a species scan, so a
# species whose `TraitPool` happens to omit one this run does not silently shrink the vocabulary.
TRAIT_POOL: "tuple[str, ...]" = (
    "berserker", "regenerator", "soul-eater", "critical-hunter", "guardian", "swift", "immortal",
    "loyal", "greedy", "bloodthirsty", "coward", "genius", "void-touched", "chaos-marked",
)

# `CreatureTraitPoolCuration.Combat` / `.Personality` — the two closed sub-pools its FNV fallback picks
# from, in their declared order (`CreatureTraitPoolCuration.cs:28-31`). Order is load-bearing: the
# fallback's `% Length` picks depend on it.
COMBAT_TRAITS: "tuple[str, ...]" = (
    "berserker", "regenerator", "soul-eater", "critical-hunter", "guardian", "swift",
)
PERSONALITY_TRAITS: "tuple[str, ...]" = ("loyal", "greedy", "bloodthirsty", "coward", "genius")
