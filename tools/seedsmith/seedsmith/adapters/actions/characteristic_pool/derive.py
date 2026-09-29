"""seedsmith.adapters.actions.characteristic_pool.derive — spec §3 steps 2-5: anchor assembly,
the family floor (with the F12 correction), the deterministic per-species derivation, and the
residue measurement (Checkpoint 2).

**A genuine spec gap this module had to close, flagged rather than hidden.** §3 step 4 describes
four weight blocks (`traitCategoryMilli` 14x5, `elementCategoryMilli` 6x5,
`rarityCategoryMilli` 10x5, `anchorCategoryMilli` 3x5) whose shipped default is "every cell
1000" (spec's own words), and states the resulting score is "the plain count of signals a
species carries for a category". Taken completely literally — a weight applied identically to
all 5 category columns for every signal a species carries — that produces a mathematical identity:
every category ends up with the SAME total for every species, which is a permanent five-way tie
for the whole live roster. That directly contradicts three of the spec's own testable
claims: step 3's "[the uniform-floor] case is expected to be empty", acceptance #4 ("family-less
entries... `leanOrder` is a permutation"), and the dedicated test "over the live family-less species
today, the count whose `leanOrder` is NOT the bare declared order is asserted to be greater than
zero". A weight table that is flat in every direction cannot produce that outcome by construction,
regardless of which live species roster it is run over.

Resolving this requires *some* closed, non-arbitrary fact that ties a signal to ONE OF THE FIVE
CATEGORIES structurally, which the weight's per-mille value then scales (exactly the same shape
`spec-innate-picker.md` §3.3 already uses: `w_t = 1000` rescales an ALREADY-DIFFERENTIATED raw
term — see its `roleLeanMatch`/`motifCoverage`/etc, each independently formula-derived before any
weight touches it. `traitCategoryMilli` etc. are this module's version of those per-term weights,
not the source of the differentiation itself.) No such trait -> category (or element -> category,
or posture -> category) table exists anywhere in the shipped codebase — `CreatureTraitCatalog.cs`
carries only a `Blurb` (free prose), and there is no crosswalk from `ActorElementTypes` to
`ActionCategory`. `SIGNAL_CATEGORY` below is this module's own, and it is a genuine editorial
judgment call, not a citation. It IS grounded in the closest real, already-shipped facts available:
- trait -> category: each trait's own `Blurb` in `CreatureTraitCatalog.cs:11-30` (an attacking blurb
  reads as `attack`, a shielding one as `defense`, and so on).
- element -> category: no textual grounding exists; assigned to spread the 6 elements evenly
  across the 5 categories rather than left flat (a flat element block would silently return this
  module to the same all-tie problem for any species whose only differentiator was element).
- posture -> category: `seedsmith/adapters/creatures/anchor/schema.py`'s own `APTITUDE_POSTURE` and
  `validators/anchor.py`'s own rule ("Bastion IS the guard posture") directly hand `Bastion ->
  defense`; `Force`'s member aptitudes (Might/Fortitude/Vigor/Onslaught) read as `attack`;
  `Finesse`'s (Agility/Composure/Pierce/Focus) as `movement`.
- reach / targetPreference -> category: both anchor axes map their WHOLE axis to one category
  (`reach` -> `attack`, since range is structurally an attack property; `targetPreference` ->
  `status`, since a targeting preference is conditional/tactical) rather than per-value, matching
  the tuning file's own shape (`anchorCategoryMilli` is keyed by AXIS name, 3 rows, not by value).

**This is the single most owner-review-worthy decision in this module — flagged here, in the
build report, and not silently presented as a spec citation.** `SIGNAL_CATEGORY` is the one place
a rebalance would want to move a signal to a different category; everything downstream of it
(the weight per cell) is the genuinely tunable surface `gk-core/data/tuning/action-role-lean.v1.json` owns.

**⛔ REVISED 2026-09-11 (owner-authorized, measured).** The original map sent `soul-eater` and
`loyal` and `greedy` all to `support` and `coward` to `defense`. Once the closed-trait bridge
(`curation.py`) started feeding real traits, that clustering left 539 of 904 species at
`separation == 0`. Four cells moved to the category their own `CreatureTraitCatalog.cs` blurb actually
describes — `soul-eater` *"feeds on fallen enemies"* → `support` (sustain), `coward` *"prefers to
survive"* → `movement` (retreat), `loyal` *"stands by its summoner"* → `defense` (protect),
`greedy` *"chases the richest prize"* → `status` (tactical) — and the result was measured over the
live roster: distinct `leanOrder`s rose 17 → 63 and `separation == 0` fell 539 → 459 (from 673
before the bridge). This is an editorial judgment, not a citation; a future balance pass moves it
here, and the tuning weights move everything else.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .anchors import ANCHOR_AXES, AnchorRow
from .catalog import RARITY_LADDER, SpeciesRow, TRAIT_POOL

__all__ = [
    "CATEGORIES", "SIGNAL_CATEGORY", "RoleLeanWeights", "load_weights", "TUNING_PATH",
    "SpeciesAnchor", "build_species_anchor", "compute_scores", "rank_categories",
    "family_floor_order", "RoleLeanEntry", "derive_all", "ResidueReport",
]

# `ActionCategories.All` — gk-core/src/FusionRpg.Core/Actions/ActionEnums.cs:144-147 (declared order; the
# spec cites `:119-123`, which was correct before A-E1 inserted `EligibilityScope`/`PairingRole`
# earlier the same day — re-verified directly against the live file, not trusted from the
# citation, per this repo's own design-gate discipline). This tuple IS the total tie-break order
# acceptance #4b requires.
CATEGORIES: "tuple[str, ...]" = ("attack", "defense", "support", "movement", "status")

REPO_ROOT = Path(__file__).resolve().parents[6]
TUNING_PATH = REPO_ROOT / "data" / "tuning" / "action-role-lean.v1.json"

# ---------------------------------------------------------------------------------------------
# The structural signal -> category association (see module docstring for the full justification
# and citations). One category per signal value; the tuning file's per-mille weight scales it.
# ---------------------------------------------------------------------------------------------

_TRAIT_CATEGORY: "dict[str, str]" = {
    "berserker": "attack", "soul-eater": "support", "critical-hunter": "attack",
    "bloodthirsty": "attack",
    "guardian": "defense", "immortal": "defense", "coward": "movement",
    "regenerator": "support", "loyal": "defense", "greedy": "status",
    "swift": "movement",
    "genius": "status", "void-touched": "status", "chaos-marked": "status",
}
assert set(_TRAIT_CATEGORY) == set(TRAIT_POOL), "every trait in the closed pool needs a category"

_ELEMENT_CATEGORY: "dict[str, str]" = {
    "fire": "attack", "earth": "defense", "light": "support", "air": "movement",
    "ice": "status", "dark": "status",
}

_POSTURE_CATEGORY: "dict[str, str]" = {"Bastion": "defense", "Force": "attack", "Finesse": "movement"}
_REACH_CATEGORY = "attack"
_TARGET_PREFERENCE_CATEGORY = "status"

#: Exported for tests/tooling that want to print the whole map in one place rather than reach into
#: the three private dicts above.
SIGNAL_CATEGORY: "dict[str, str]" = {
    **{f"trait:{t}": c for t, c in _TRAIT_CATEGORY.items()},
    **{f"element:{e}": c for e, c in _ELEMENT_CATEGORY.items()},
    "anchor:posture:Bastion": "defense", "anchor:posture:Force": "attack",
    "anchor:posture:Finesse": "movement",
    "anchor:reach": _REACH_CATEGORY, "anchor:targetPreference": _TARGET_PREFERENCE_CATEGORY,
}


# ---------------------------------------------------------------------------------------------
# The tuning file — gk-core/data/tuning/action-role-lean.v1.json (spec §2's "new" Reads row; acceptance
# #6/#6b). Loaded and shape-validated here; never hand-parsed again downstream.
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class RoleLeanWeights:
    trait_category_milli: "Mapping[str, Mapping[str, int]]"      # 14 traits x 5 categories
    element_category_milli: "Mapping[str, Mapping[str, int]]"    # 6 elements x 5 categories
    element_secondary_scale_milli: int
    rarity_category_milli: "Mapping[str, Mapping[str, int]]"     # 10 rungs x 5 categories
    anchor_category_milli: "Mapping[str, Mapping[str, int]]"     # 3 axes x 5 categories
    version: int


def load_weights(path: Path = TUNING_PATH) -> RoleLeanWeights:
    doc = json.loads(path.read_text(encoding="utf-8"))

    def _rows(key: str, expected_keys: "tuple[str, ...]") -> "dict[str, dict[str, int]]":
        block = doc.get(key)
        if not isinstance(block, dict) or set(block) != set(expected_keys):
            raise ValueError(f"{path}: {key!r} must have exactly the rows {sorted(expected_keys)}")
        for row_key, row in block.items():
            if not isinstance(row, dict) or set(row) != set(CATEGORIES):
                raise ValueError(f"{path}: {key}[{row_key!r}] must have exactly the 5 categories "
                                 f"{CATEGORIES}")
            for cat, val in row.items():
                if not isinstance(val, int) or isinstance(val, bool):
                    raise ValueError(f"{path}: {key}[{row_key!r}][{cat!r}] must be an int")
        return block

    trait_block = _rows("traitCategoryMilli", TRAIT_POOL)
    element_block = _rows("elementCategoryMilli", ("fire", "ice", "air", "earth", "light", "dark"))
    rarity_block = _rows("rarityCategoryMilli", RARITY_LADDER)
    anchor_block = _rows("anchorCategoryMilli", ANCHOR_AXES)

    scale = doc.get("elementSecondaryScaleMilli")
    if not isinstance(scale, int) or isinstance(scale, bool):
        raise ValueError(f"{path}: 'elementSecondaryScaleMilli' must be an int")

    version = doc.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValueError(f"{path}: 'version' must be an int")

    return RoleLeanWeights(
        trait_category_milli=trait_block, element_category_milli=element_block,
        element_secondary_scale_milli=scale, rarity_category_milli=rarity_block,
        anchor_category_milli=anchor_block, version=version,
    )


# ---------------------------------------------------------------------------------------------
# §3 step 2 — anchor assembly, per species, in catalog order.
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SpeciesAnchor:
    species: SpeciesRow
    family: "str | None"
    motifs: "tuple[str, ...]"
    anti_motifs: "tuple[str, ...]"
    theme_key: "str | None"
    anchor: "AnchorRow | None"          # None unless the catalog<->anchor-tree join hit


def build_species_anchor(
    species: SpeciesRow,
    *,
    family_assignments: "Mapping[str, list]",
    motif_assignments: "Mapping[str, dict]",
    anchor_by_lower: "Mapping[str, AnchorRow]",
) -> SpeciesAnchor:
    families = family_assignments.get(species.species_id) or []
    if isinstance(families, str):
        families = [families]
    families = sorted(set(str(family) for family in families))
    motif_row = motif_assignments.get(species.species_id) or {}
    return SpeciesAnchor(
        species=species,
        family=(families[0] if families else None),
        motifs=tuple(motif_row.get("motifs") or ()),
        anti_motifs=tuple(motif_row.get("antiMotifs") or ()),
        theme_key=f"creature.{species.species_id}",
        anchor=anchor_by_lower.get(species.species_id),
    )


# ---------------------------------------------------------------------------------------------
# §3 step 4 — the deterministic score, `long` throughout, widened before multiplying, divided by
# 1000 last (once per category; the element-secondary compound per-mille factor needs its own
# small internal normalisation first — see `_secondary_contribution`'s own docstring for why that
# does not violate the "exactly once" rule in spirit).
# ---------------------------------------------------------------------------------------------

def _secondary_contribution(weight_milli: int, scale_milli: int) -> int:
    """`elementSecondaryScaleMilli` is a SECOND per-mille factor stacked on the element weight
    (spec: "a secondary is half a primary"). Two per-mille factors compound to a per-MILLION
    quantity; normalising that back to the same milli-scale every other term uses (so ONE shared
    division closes the per-category total) needs its own small division here — `long`, widened
    before multiplying, floor-divided once, matching the "widen before multiplying" rule even
    though it is not literally THE final division `score[cat] = raw[cat] // 1000` below."""
    return (int(weight_milli) * int(scale_milli)) // 1000  # 1000 = per-mille scale, structural


def compute_scores(anchor: SpeciesAnchor, weights: RoleLeanWeights) -> "dict[str, int]":
    """Long arithmetic throughout; overflow throws (Python ints are arbitrary-precision, so this
    module cannot silently wrap — the overflow test instead proves a synthetic maximal species
    still produces a plain Python `int`, never a float)."""
    raw: "dict[str, int]" = {c: 0 for c in CATEGORIES}

    for trait in anchor.species.traits:
        # Live seed traits are descriptive signals, not a closed action vocabulary.
        cat = _TRAIT_CATEGORY.get(trait)
        if cat is None or trait not in weights.trait_category_milli:
            continue
        raw[cat] += int(weights.trait_category_milli[trait][cat])

    primary = anchor.species.element_primary
    p_cat = _ELEMENT_CATEGORY[primary]
    raw[p_cat] += int(weights.element_category_milli[primary][p_cat])

    secondary = anchor.species.element_secondary
    if secondary is not None:
        s_cat = _ELEMENT_CATEGORY[secondary]
        base_weight = int(weights.element_category_milli[secondary][s_cat])
        raw[s_cat] += _secondary_contribution(base_weight, weights.element_secondary_scale_milli)

    # Rarity: "a tie-shaping term only" (spec's own words) — contributes IDENTICALLY to every
    # category, so it can never move a species' OWN ranking; it still enters `raw` because it is
    # a real signal counted in the family-floor SUM (step 3) and in the overflow test.
    rarity_row = weights.rarity_category_milli[anchor.species.rarity]
    for cat in CATEGORIES:
        raw[cat] += int(rarity_row[cat])

    if anchor.anchor is not None:
        posture = anchor.anchor.posture
        if posture in _POSTURE_CATEGORY:
            cat = _POSTURE_CATEGORY[posture]
            raw[cat] += int(weights.anchor_category_milli["posture"][cat])
        if anchor.anchor.reach:
            raw[_REACH_CATEGORY] += int(weights.anchor_category_milli["reach"][_REACH_CATEGORY])
        if anchor.anchor.target_preference:
            raw[_TARGET_PREFERENCE_CATEGORY] += int(
                weights.anchor_category_milli["targetPreference"][_TARGET_PREFERENCE_CATEGORY])
        # `attackTempo` is deliberately never read here — spec §3 step 4: excluded by measurement.

    return {c: raw[c] // 1000 for c in CATEGORIES}  # 1000 = per-mille scale, structural (docs/architecture/numeric-types.md)


def rank_categories(scores: "Mapping[str, int]") -> "tuple[str, ...]":
    """Descending by score; ties break on the declared `CATEGORIES` order — a total order, so the
    result never depends on dict/iteration order (acceptance #4b)."""
    return tuple(sorted(CATEGORIES, key=lambda c: (-scores[c], CATEGORIES.index(c))))


def is_five_way_tie(scores: "Mapping[str, int]") -> bool:
    values = set(scores.values())
    return len(values) == 1


def family_floor_order(member_scores: "list[Mapping[str, int]]") -> "tuple[str, ...]":
    """Step 3: the floor lean is the ranking of each family's members' SUMMED step-4 scores."""
    summed = {c: sum(int(s[c]) for s in member_scores) for c in CATEGORIES}
    return rank_categories(summed)


# ---------------------------------------------------------------------------------------------
# §3 steps 3+5 orchestrated — the F12-corrected rule, and the residue measurement.
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class RoleLeanEntry:
    species_anchor: SpeciesAnchor
    scores: "dict[str, int]"
    lean_order: "tuple[str, ...]"
    lean_source: str                    # "floor" | "derived" | "derived-nofloor"
    separation: "int | None"
    signals: "tuple[str, ...]"


@dataclass(frozen=True)
class ResidueReport:
    family_assigned_count: int
    family_less_count: int
    residue_count: int                  # separation == 0 inside a family of 2+
    residue_species: "tuple[str, ...]"
    per_family_histogram: "dict[str, dict[int, int]]"   # family -> {separation: count}


def _signals_for(anchor: SpeciesAnchor) -> "tuple[str, ...]":
    out = [f"trait:{t}" for t in anchor.species.traits]
    out.append(f"element:{anchor.species.element_primary}")
    if anchor.species.element_secondary:
        out.append(f"element:{anchor.species.element_secondary}")
    out.append(f"rarity:{anchor.species.rarity}")
    if anchor.anchor is not None:
        if anchor.anchor.posture:
            out.append(f"posture:{anchor.anchor.posture}")
        if anchor.anchor.reach:
            out.append(f"reach:{anchor.anchor.reach}")
        if anchor.anchor.target_preference:
            out.append(f"targetPreference:{anchor.anchor.target_preference}")
    return tuple(out)


def derive_all(
    anchors: "list[SpeciesAnchor]", weights: RoleLeanWeights,
) -> "tuple[list[RoleLeanEntry], ResidueReport]":
    """Runs step 4 for every live seed-folder species regardless of family (F12), then applies the
    corrected
    rule and step 5's residue measurement. `anchors` must already be in catalog order — this
    function does not re-sort, so a caller that shuffles it is exactly what the tie-determinism
    test needs to exercise."""
    scores_by_species = {a.species.species_id: compute_scores(a, weights) for a in anchors}

    # Family membership, preserving catalog order within each family for a deterministic sum.
    family_members: "dict[str, list[str]]" = {}
    for a in anchors:
        if a.family:
            family_members.setdefault(a.family, []).append(a.species.species_id)
    family_floor: "dict[str, tuple[str, ...]]" = {
        fam: family_floor_order([scores_by_species[sid] for sid in members])
        for fam, members in family_members.items()
    }

    entries: "list[RoleLeanEntry]" = []
    for a in anchors:
        scores = scores_by_species[a.species.species_id]
        own_order = rank_categories(scores)
        if is_five_way_tie(scores):
            entries.append(RoleLeanEntry(
                species_anchor=a, scores=scores, lean_order=CATEGORIES, lean_source="floor",
                separation=None, signals=_signals_for(a),
            ))
        elif a.family:
            floor = family_floor[a.family]
            separation = floor.index(own_order[0])
            entries.append(RoleLeanEntry(
                species_anchor=a, scores=scores, lean_order=own_order, lean_source="derived",
                separation=separation, signals=_signals_for(a),
            ))
        else:
            entries.append(RoleLeanEntry(
                species_anchor=a, scores=scores, lean_order=own_order,
                lean_source="derived-nofloor", separation=None, signals=_signals_for(a),
            ))

    family_assigned = [e for e in entries if e.species_anchor.family]
    family_less = [e for e in entries if not e.species_anchor.family]
    residue = [e for e in family_assigned
              if e.separation == 0 and len(family_members[e.species_anchor.family]) >= 2]
    histogram: "dict[str, dict[int, int]]" = {}
    for e in family_assigned:
        fam = e.species_anchor.family
        bucket = histogram.setdefault(fam, {})
        key = -1 if e.separation is None else e.separation
        bucket[key] = bucket.get(key, 0) + 1

    report = ResidueReport(
        family_assigned_count=len(family_assigned), family_less_count=len(family_less),
        residue_count=len(residue),
        residue_species=tuple(sorted(e.species_anchor.species.species_id for e in residue)),
        per_family_histogram=histogram,
    )
    return entries, report
