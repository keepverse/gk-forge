"""seedsmith.adapters.items.setgen.tuning — the pure parser over `gk-core/data/tuning/set-charm-gen.v1.json`.

One class, no defaults, no fallbacks: a missing key raises rather than substituting a plausible
number, because a generator silently running on a default is exactly how an unreviewed balance value
reaches ~1,800 generated entries. Mirrors the `*TuningLoader` pattern the C# side uses
(`ItemRarityTuning`, `FrameMixTuning`) — parse, validate the structural invariants at load, then hand
back an immutable view.
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

TUNING_PATH = _owned("data/tuning/set-charm-gen.v1.json")


class SetCharmTuningError(ValueError):
    """The tuning file is structurally unusable. Raised at load, so a defect lands before the first
    model call rather than on the four-hundredth generated set."""


@dataclass(frozen=True)
class CharmClassRule:
    id: str
    ap_cost: int
    min_pool_rolls: int
    max_pool_rolls: int
    unique_carry: bool
    requires_drawback: bool
    target_weight: int


@dataclass(frozen=True)
class SetCharmGenTuning:
    archetypes: "tuple[str, ...]"
    species_sets_per_species: int
    species_charms_per_species: int

    typical_members: int
    grand_members: int
    max_roles: int
    mandatory_threshold_pieces: int
    legal_threshold_pieces: "tuple[int, ...]"
    grand_required_threshold_pieces: "tuple[int, ...]"

    fixed_identity_atoms: int
    prefix_rolls: int
    suffix_rolls: int
    tier_window_width: int
    rare_comparison_rolls: int

    ae_per_member_milli: int

    charm_max_tier_bands_below_equip: int
    charm_legal_ops: "tuple[str, ...]"
    charm_forbidden_ops: "tuple[str, ...]"
    charm_ring_layer_families: "frozenset[str]"
    charm_ring_layer_kinds: "frozenset[str]"
    charm_classes: "tuple[CharmClassRule, ...]"

    median_cell_occupancy_max: int
    near_duplicate_rate_max_permille: int
    charm_axis_gini_max_permille: int
    exact_duplicate_names_max: int

    capability_kinds: "frozenset[str]"
    stat_kinds: "frozenset[str]"
    variant_generator: str
    variant_expansion: int

    @property
    def total_pool_rolls(self) -> int:
        """The `pool_rolls = 2` of ssot-sets §3.9, emitted as the pair the schema actually has."""
        return self.prefix_rolls + self.suffix_rolls

    def charm_class(self, class_id: str) -> CharmClassRule:
        for rule in self.charm_classes:
            if rule.id == class_id:
                return rule
        raise SetCharmTuningError(
            f"unknown charm class {class_id!r} — the classes are "
            f"{[r.id for r in self.charm_classes]}")

    def set_budget_milli(self, member_count: int) -> int:
        """Total milli-AE a set of `member_count` pieces may spend (ssot-sets §3.5 rule 3).

        Integer per-mille throughout, multiplied before any division — there is no division here at
        all, which is the point: the per-mille denominator is carried to the display boundary.
        """
        if member_count < 1:
            raise SetCharmTuningError(f"a set has at least one member, got {member_count}")
        return self.ae_per_member_milli * member_count


def _require(doc: dict, *path: str):
    node = doc
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise SetCharmTuningError(
                f"set-charm-gen tuning is missing {'.'.join(path)!r} — refusing to substitute a "
                f"default; an unreviewed number here reaches every generated entry")
        node = node[key]
    return node


def load(path: "Path | None" = None) -> SetCharmGenTuning:
    doc = json.loads((path or TUNING_PATH).read_text(encoding="utf-8"))

    classes = tuple(
        CharmClassRule(
            id=str(row["id"]), ap_cost=int(row["apCost"]),
            min_pool_rolls=int(row["minPoolRolls"]), max_pool_rolls=int(row["maxPoolRolls"]),
            unique_carry=bool(row["uniqueCarry"]),
            requires_drawback=bool(row["requiresDrawback"]),
            target_weight=int(row["targetWeight"]),
        )
        for row in _require(doc, "charm", "classes")
    )

    tuning = SetCharmGenTuning(
        archetypes=tuple(_require(doc, "populations", "archetypes")),
        species_sets_per_species=int(_require(doc, "populations", "speciesSetsPerSpecies")),
        species_charms_per_species=int(_require(doc, "populations", "speciesCharmsPerSpecies")),
        typical_members=int(_require(doc, "setShape", "typicalMembers")),
        grand_members=int(_require(doc, "setShape", "grandMembers")),
        max_roles=int(_require(doc, "setShape", "maxRoles")),
        mandatory_threshold_pieces=int(_require(doc, "setShape", "mandatoryThresholdPieces")),
        legal_threshold_pieces=tuple(int(p) for p in _require(doc, "setShape", "legalThresholdPieces")),
        grand_required_threshold_pieces=tuple(
            int(p) for p in _require(doc, "setShape", "grandRequiredThresholdPieces")),
        fixed_identity_atoms=int(_require(doc, "piece", "fixedIdentityAtoms")),
        prefix_rolls=int(_require(doc, "piece", "prefixRolls")),
        suffix_rolls=int(_require(doc, "piece", "suffixRolls")),
        tier_window_width=int(_require(doc, "piece", "tierWindowWidth")),
        rare_comparison_rolls=int(_require(doc, "piece", "rareComparisonRolls")),
        ae_per_member_milli=int(_require(doc, "budget", "aePerMemberMilli")),
        charm_max_tier_bands_below_equip=int(_require(doc, "charm", "maxTierBandsBelowEquip")),
        charm_legal_ops=tuple(_require(doc, "charm", "legalOps")),
        charm_forbidden_ops=tuple(_require(doc, "charm", "forbiddenOps")),
        charm_ring_layer_families=frozenset(_require(doc, "charm", "ringLayerFamilies")),
        charm_ring_layer_kinds=frozenset(_require(doc, "charm", "ringLayerKinds")),
        charm_classes=classes,
        median_cell_occupancy_max=int(_require(doc, "distinctness", "medianCellOccupancyMax")),
        near_duplicate_rate_max_permille=int(
            _require(doc, "distinctness", "nearDuplicateRateMaxPermille")),
        charm_axis_gini_max_permille=int(_require(doc, "distinctness", "charmAxisGiniMaxPermille")),
        exact_duplicate_names_max=int(_require(doc, "distinctness", "exactDuplicateNamesMax")),
        capability_kinds=frozenset(_require(doc, "capabilityVocabulary", "capabilityKinds")),
        stat_kinds=frozenset(_require(doc, "capabilityVocabulary", "statKinds")),
        variant_generator=str(_require(doc, "capabilityVocabulary", "variantGenerator")),
        variant_expansion=int(_require(doc, "capabilityVocabulary", "variantExpansion")),
    )
    _validate(tuning)
    return tuning


def _validate(t: SetCharmGenTuning) -> None:
    """The structural invariants, each with its own message so a balance pass reads which one it
    broke — the same discipline module 12's frame-mix curve parser applies to its knots."""
    if t.mandatory_threshold_pieces not in t.legal_threshold_pieces:
        raise SetCharmTuningError(
            f"mandatoryThresholdPieces {t.mandatory_threshold_pieces} is not in "
            f"legalThresholdPieces {list(t.legal_threshold_pieces)} — every set must be able to "
            f"carry the threshold that is mandatory for it")
    if sorted(t.legal_threshold_pieces) != list(t.legal_threshold_pieces):
        raise SetCharmTuningError(
            f"legalThresholdPieces {list(t.legal_threshold_pieces)} is not ascending — the lowest "
            f"threshold is where the capability sits (ssot-sets §3.2), so the order is load-bearing")
    if t.grand_members < t.typical_members:
        raise SetCharmTuningError(
            f"grandMembers {t.grand_members} is below typicalMembers {t.typical_members}")
    if t.grand_members > t.max_roles:
        raise SetCharmTuningError(
            f"grandMembers {t.grand_members} exceeds maxRoles {t.max_roles} — a grand set could "
            f"not be authored at all (ssot-sets §3.4)")
    if t.fixed_identity_atoms < 1:
        raise SetCharmTuningError(
            "fixedIdentityAtoms 0 is 'fixed like a unique' inverted — a set piece with no fixed "
            "identity is just a rare (ssot-sets §3.9)")
    if t.total_pool_rolls >= t.rare_comparison_rolls:
        raise SetCharmTuningError(
            f"prefixRolls + suffixRolls = {t.total_pool_rolls} is not below rareComparisonRolls "
            f"{t.rare_comparison_rolls} — 'rolled like a rare' makes a set piece a rare PLUS a set "
            f"bonus, which is set jail arriving through the item layer (ssot-sets §3.9)")
    if t.tier_window_width < 1:
        raise SetCharmTuningError("tierWindowWidth below 1 leaves no window to roll in")
    if t.ae_per_member_milli < 1:
        raise SetCharmTuningError(
            "aePerMemberMilli below 1 means a set may grant nothing at any threshold")
    for op in t.charm_legal_ops:
        if op in t.charm_forbidden_ops:
            raise SetCharmTuningError(
                f"charm op {op!r} is both legal and forbidden — ssot-charms §3.4 allows Flat only")
    if not t.charm_ring_layer_families and not t.charm_ring_layer_kinds:
        raise SetCharmTuningError(
            "charm.ringLayerFamilies and charm.ringLayerKinds are both empty — ssot-charms §3.6 "
            "splits the ring layer from the charm layer by FAMILY, and an empty split lets a "
            "conditional per-actor rider be authored as an always-on side-wide charm")
    ids = [c.id for c in t.charm_classes]
    if len(set(ids)) != len(ids):
        raise SetCharmTuningError(f"duplicate charm class id in {ids}")
    for rule in t.charm_classes:
        if rule.min_pool_rolls > rule.max_pool_rolls:
            raise SetCharmTuningError(
                f"charm class {rule.id!r} has minPoolRolls {rule.min_pool_rolls} above "
                f"maxPoolRolls {rule.max_pool_rolls}")
        if rule.target_weight < 1:
            raise SetCharmTuningError(
                f"charm class {rule.id!r} has targetWeight {rule.target_weight}; every class "
                "must have positive deterministic allocation weight")
    if t.median_cell_occupancy_max < 1:
        raise SetCharmTuningError(
            "medianCellOccupancyMax below 1 is unreachable — a cell that exists holds at least one")
