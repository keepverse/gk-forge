"""seedsmith.adapters.creatures.themes — the theme registry creatures publish for items/actions
(spec-creature-themes.md).

Direction is one-way and it matters (§2.2): this module builds a registry FROM creature motif data;
nothing here reads an item, and nothing in the items corpus writes a creature. The items side of the
bridge is exactly one edit — `adapters/items/registries.py` gains `themeKey` as a registry-backed
vocabulary — and that is the ONE file outside `adapters/creatures/` this feature is allowed to touch
(§4; matches `spec-adapter-creatures.md`'s own single permitted exception, §D-F1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

__all__ = [
    "CreatureThemeInput",
    "PublishedTheme",
    "THEME_PREFIX",
    "build_theme_registry",
    "EXPRESSION_RULES",
]

#: `creature.*`-prefixed, never `theme.*` — collision with the legacy vocabulary is impossible by
#: construction, not merely by convention (§2.2a, resolving audit S5).
THEME_PREFIX = "creature."

#: §2.3's own table, narrowed to the two kinds that actually consume a theme today (items and
#: actions) — `adapter-creatures.py`'s per-KIND `motif_expression` is a broader, creatures-adapter-wide
#: concept; this is the narrower, ITEM/ACTION-specific reading of the same idea, so both can be
#: cited without one silently standing in for the other.
EXPRESSION_RULES: "dict[str, str]" = {
    "item": "material and form — what it is made of, what shape it takes",
    "action": "tempo and effect shape — how fast, how it lands",
}


@dataclass(frozen=True)
class CreatureThemeInput:
    species_id: str
    display_name: str
    rarity: str
    motifs: "tuple[str, ...]"
    anti_motifs: "tuple[str, ...]"
    basis: str  # "text" | "name" | "enriched" | "blocked" — a creature whose OWN combined basis is "blocked"
                # publishes no theme at all (§2.4); "name" publishes one MARKED as such
    retired: bool = False


@dataclass(frozen=True)
class PublishedTheme:
    theme_key: str
    species_id: str
    display_name: str
    rarity: str  # the rarity this theme was PUBLISHED AGAINST — a snapshot, never re-derived
                 # later (§2.4a: rarity moves as the roster grows; this field is what lets a
                 # later reader see that a creature's tier has since changed rather than silently
                 # inheriting the new one)
    motifs: "tuple[str, ...]"
    anti_motifs: "tuple[str, ...]"
    expression: "Mapping[str, str]"
    basis: str  # "text" | "name" | "enriched" — never "blocked": a blocked creature has no PublishedTheme at all
    retired: bool = False
    lore: str = ""  # optional model-authored context; preserved across refreshes


def build_theme_registry(
    creatures: Sequence[CreatureThemeInput],
    *,
    existing_registry: "Mapping[str, PublishedTheme] | None" = None,
) -> "dict[str, PublishedTheme]":
    """One theme per non-`blocked` creature, keyed `creature.<speciesId>`. Append-only (§2.4a): an
    existing theme's `rarity`/`basis`/motifs are NEVER recomputed from a later run — once
    published, a theme is a snapshot, and a departed or re-tiered creature's theme is retired (kept,
    `retired=True`) rather than deleted or silently updated.
    """
    # Contract: `creatures` is the FULL current roster, every call — the same convention
    # `consolidate()` and `derive_motifs()` already use. A creature absent here is read as "no longer
    # in the roster", so a caller passing an incremental subset would wrongly retire everyone
    # else's theme. This is a real footgun if the contract is ever violated silently; documented
    # here rather than guarded in code, matching how the sibling modules document the same
    # assumption instead of enforcing it (there is no way to distinguish "genuinely departed" from
    # "caller passed a subset" from inside this function alone).
    registry: "dict[str, PublishedTheme]" = (
        dict(existing_registry) if existing_registry else {}
    )
    seen_this_run: "set[str]" = set()

    for d in sorted(creatures, key=lambda d: d.species_id):
        theme_key = f"{THEME_PREFIX}{d.species_id}"
        seen_this_run.add(theme_key)
        if theme_key in registry:
            continue  # published once; never recomputed (append-only, §2.3's discipline extended)
        if d.basis == "blocked":
            continue  # §2.4 — nothing to theme with; not an error, simply no publication
        registry[theme_key] = PublishedTheme(
            theme_key=theme_key, species_id=d.species_id, display_name=d.display_name,
            rarity=d.rarity, motifs=tuple(d.motifs), anti_motifs=tuple(d.anti_motifs),
            expression=dict(EXPRESSION_RULES), basis=d.basis, retired=False,
        )

    # §2.4a — a theme published in an earlier run whose creature is absent from THIS run's roster
    # (left the roster, or the caller only passed a subset) is retired, never deleted. A theme
    # explicitly requested as retired this run (d.retired=True) is retired even if still present.
    explicit_retired = {f"{THEME_PREFIX}{d.species_id}" for d in creatures if d.retired}
    for key, theme in list(registry.items()):
        if not key.startswith(THEME_PREFIX):
            continue  # never touch a foreign entry if this dict ever carries mixed content
        if theme.retired:
            continue
        if key not in seen_this_run or key in explicit_retired:
            registry[key] = PublishedTheme(**{**theme.__dict__, "retired": True})

    return registry
