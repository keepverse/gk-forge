"""seedsmith.adapters.items.charmgen.rules — the charm half of the distributor.

Same shape as `setgen.distribute`, different rules. Four of them, all from `ssot-charms.md`:

| Constraint | Source |
|---|---|
| **`Flat` only** — never `Increased`, never `More` | §3.4 |
| `max_tier` at most **one band below** an equip container of the same rarity | §3.4 |
| A family may not appear on both a `jewel-minor` base type and a charm — **at all**, not at a different tier | §3.6 (the ring layer is a DECLARED family list — see `ring_layer_families`) |
| A signet: `pool_rolls = 0`, `unique_carry = 1`, and it carries a **drawback** | §3.4 |

⭐ Module 12 already turned the last row from an observation into a refusal at the DAL
(`CharmCorpus.ValidateClassRules`, reason codes `charm-signet-has-rolled-half` / `-not-unique-carry`
/ `-has-no-drawback`). This module refuses the same three at GENERATION, before the row exists —
the same rule enforced at both ends on purpose, because the runtime check cannot stop a bad row
being authored and the generator check cannot stop one being hand-edited in later.

⚠ **The axis skew is a ceiling, not a target.** The authored corpus's own axis Gini is **0.133**
(economy 20 : 10 × 4 over the 60 authored rows). *"A skew this generator must not deepen"* is that
number: a generated population may be flatter, never more concentrated. It is an inequality
ceiling, not a content ceiling — nothing here caps how many charms may exist.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..setgen.tuning import SetCharmGenTuning
from ..setgen.vocab import FamilyPick

#: The five power categories the family library already uses — no new vocabulary (ssot-charms §3.5).
CHARM_AXES: "tuple[str, ...]" = ("offense", "survivability", "control", "utility", "economy")

#: `Increased`/`More` families named by ssot-charms §3.4 itself: "no fortitude, ferocity, bulwark,
#: savagery". Enumerated rather than derived, because the op is not a field on the family row — it
#: is a property of the atom kind, and this list is what the SSOT actually states.
NON_FLAT_FAMILIES: "frozenset[str]" = frozenset({
    "atom.fortitude", "atom.ferocity", "atom.bulwark", "atom.savagery",
})

#: The roles a charm's families must NOT share with (ssot-charms §3.6). Rings own the conditional
#: layer; charms own the always-on layer.
JEWEL_MINOR_ROLES: "frozenset[str]" = frozenset({"jewel-minor-a", "jewel-minor-b"})


class CharmPoolError(ValueError):
    """The declared ring layer and the shipped family corpus disagree. Raised at pool time so the
    drift lands before a brief is rendered, never as a mystery refusal mid-run."""


@dataclass
class CharmPlan:
    charm_class: str
    axis: str
    ap_cost: int
    unique_carry: bool
    prefix_rolls: int
    suffix_rolls: int
    families: "tuple[FamilyPick, ...]" = ()
    drawback: "FamilyPick | None" = None
    problems: "list[str]" = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def pool_rolls(self) -> int:
        return self.prefix_rolls + self.suffix_rolls


def families_on_jewel_minor(all_picks: "list[FamilyPick] | tuple[FamilyPick, ...]",
                            ) -> "frozenset[str]":
    """Every family the corpus's role table makes legal on a `jewel-minor` role.

    ⛔ **This is a DIAGNOSTIC, not §3.6's rule, and reading it as the rule was a real defect**
    (module 13, found 2026-09-06). A family row's `roles` list is a role × **GROUP** matrix, not a
    per-family one — `g-on-hit.json`'s own note says so: *"every entry in this file shares this
    identical roles list — the matrix has one row per role per GROUP, not per family."* A ring is a
    generic slot, so **84 of the 98 shipped families** carry a jewel-minor role, **including all
    seven §3.6 itself names as the CHARM set** (`vitality`, `might`, `mending`, `regeneration`,
    `sunbloom`, `midas`, `cleansing`). Used as the exclusion it left the charm brief with 14
    families, every one armour or shield, and no authorable offense / control / utility / economy
    charm at all.

    Kept because it is still the honest answer to *"what can a ring roll?"*, and because
    `ring_layer_families` cross-checks its own declaration against it. The rule is that function.
    """
    return frozenset(p.family for p in all_picks if JEWEL_MINOR_ROLES & set(p.roles))


def ring_layer_families(tuning: SetCharmGenTuning,
                        all_picks: "list[FamilyPick] | tuple[FamilyPick, ...]",
                        ) -> "frozenset[str]":
    """ssot-charms §3.6's jewel-minor family set — the closed list a charm may not draw from.

    Two halves, matching §3.6's own sentence. The named riders (`searing_strike`, `lifesteal`,
    `retribution`, `keen_edge`, `cruelty`, `warded`) are declared in `set-charm-gen.v1.json`, which
    is where this module's other design cuts already live (`capabilityKinds` / `statKinds`). The
    *"on-hit `status.apply`"* half is read off the corpus by kind, so a new affliction family joins
    the ring layer without an edit here.

    The declaration is **verified, not trusted**: a declared id that the corpus no longer ships, or
    that no longer carries a jewel-minor role, raises. That keeps the hand-list honest without
    letting the per-group role matrix become the rule again.
    """
    known = {p.family for p in all_picks}
    on_ring = families_on_jewel_minor(all_picks)
    missing = sorted(f for f in tuning.charm_ring_layer_families if f not in known)
    if missing:
        raise CharmPoolError(
            f"charm.ringLayerFamilies names {missing}, which no affix-family file ships — the "
            f"ssot-charms §3.6 declaration has drifted from the corpus")
    moved = sorted(f for f in tuning.charm_ring_layer_families if f not in on_ring)
    if moved:
        raise CharmPoolError(
            f"charm.ringLayerFamilies names {moved}, which the corpus no longer makes legal on a "
            f"jewel-minor role — a family that left the ring layer is not this module's to keep "
            f"excluding")
    by_kind = frozenset(p.family for p in all_picks
                        if p.kind_id in tuning.charm_ring_layer_kinds)
    return frozenset(tuning.charm_ring_layer_families) | by_kind


def charm_pool(tuning: SetCharmGenTuning,
               all_picks: "list[FamilyPick] | tuple[FamilyPick, ...]",
               ) -> "tuple[FamilyPick, ...]":
    """Every pick a charm may actually carry — **the one list the brief prints and the distributor
    accepts.**

    ⛔ The brief and the distributor drawing their pool from two different expressions is how a
    generator offers what it will then refuse; module 13 shipped exactly that (the brief printed
    `vocabulary.stat`, 242 picks, of which the distributor accepted 56). They read this function now,
    so they cannot disagree.

    ⚠ **`all_picks` is capability ∪ stat, not stat alone.** The capability/stat split is *ssot-sets
    §3.2*'s cut — one capability atom at a set's lowest threshold, stat families above — and charms
    have no such structure. §3.6's own charm family list spans four kinds (`stat.modify` for
    `vitality`/`might`/`mending`, `resource.delta` for `regeneration`, `resource.economy` for
    `sunbloom`/`midas`, `status.clear` for `cleansing`), and 22 of the 29 families the shipped 70
    charms use are capability-kind. Filtering a charm pool by `statKinds` applies the set's design
    cut to a container that does not have it.
    """
    excluded = ring_layer_families(tuning, all_picks)
    return tuple(p for p in all_picks
                 if p.family not in excluded and p.family not in NON_FLAT_FAMILIES)


def distribute_charm(*, charm_class: str, axis: str,
                     families: "tuple[FamilyPick, ...]",
                     drawback: "FamilyPick | None",
                     tuning: SetCharmGenTuning,
                     jewel_minor_families: "frozenset[str]" = frozenset(),
                     equip_max_tier: "int | None" = None,
                     charm_max_tier: "int | None" = None) -> CharmPlan:
    """Price a charm draft. `problems` is empty exactly when it is legal."""
    try:
        rule = tuning.charm_class(charm_class)
    except Exception as exc:                                  # noqa: BLE001 - re-raised as a plan
        plan = CharmPlan(charm_class=charm_class, axis=axis, ap_cost=0, unique_carry=False,
                         prefix_rolls=0, suffix_rolls=0)
        plan.problems.append(f"CharmClassUnknown: {exc}")
        return plan

    prefix = rule.max_pool_rolls // 2
    suffix = rule.max_pool_rolls - prefix
    plan = CharmPlan(
        charm_class=charm_class, axis=axis, ap_cost=rule.ap_cost,
        unique_carry=rule.unique_carry, prefix_rolls=prefix, suffix_rolls=suffix,
        families=families, drawback=drawback,
    )

    if axis not in CHARM_AXES:
        plan.problems.append(
            f"CharmAxisUnknown: {axis!r} is not one of the five power categories {list(CHARM_AXES)}")
    if not families:
        plan.problems.append("CharmHasNoEffect: a charm with no family grants nothing")

    for pick in families:
        if pick.family in NON_FLAT_FAMILIES:
            plan.problems.append(
                f"CharmForbiddenOp: {pick.family!r} is an Increased/More family; a charm carries "
                f"Flat only (ssot-charms §3.4 — a multiplicative bonus applied squad-wide compounds "
                f"with every other multiplier in the build)")
        if pick.family in jewel_minor_families:
            plan.problems.append(
                f"CharmFamilyOnJewelMinor: {pick.family!r} is legal on a jewel-minor base type; a "
                f"family may not appear on both — at all, not at a different tier (ssot-charms §3.6)")

    if rule.requires_drawback and drawback is None:
        plan.problems.append(
            f"CharmSignetHasNoDrawback: class {charm_class!r} must carry an authored negative atom")
    if not rule.requires_drawback and drawback is not None:
        plan.problems.append(
            f"CharmDrawbackNotAllowed: class {charm_class!r} does not carry a drawback; only a "
            f"signet does")
    if rule.max_pool_rolls == 0 and plan.pool_rolls != 0:
        plan.problems.append(
            f"CharmSignetHasRolledHalf: class {charm_class!r} rolls nothing, got {plan.pool_rolls}")

    if equip_max_tier is not None:
        ceiling = equip_max_tier - tuning.charm_max_tier_bands_below_equip
        effective = charm_max_tier if charm_max_tier is not None else ceiling
        if effective > ceiling:
            plan.problems.append(
                f"CharmTierTooHigh: max_tier {effective} exceeds {ceiling} — at equal rarity a "
                f"charm sits at most {tuning.charm_max_tier_bands_below_equip} band(s) below an "
                f"equip container (ssot-charms §3.4)")
    return plan


def gini_permille(counts: "list[int]") -> int:
    """Integer per-mille Gini over a count vector. No float ever reaches the comparison against the
    tuning ceiling — the multiply by 1000 happens before the divide, exactly once."""
    n = len(counts)
    total = sum(counts)
    if n == 0 or total == 0:
        return 0
    ordered = sorted(counts)
    weighted = sum((2 * i - n - 1) * x for i, x in enumerate(ordered, start=1))
    return (weighted * 1000) // (n * total)


def axis_gini_permille(axes: "list[str]") -> int:
    counts = Counter(axes)
    return gini_permille([counts.get(a, 0) for a in CHARM_AXES])


def min_axis_gini_permille(population: int) -> int:
    """The flattest axis Gini a population of this size can reach — the metric's own floor.

    ⚠ **Below five charms the 133‰ ceiling is unreachable at any diversity**, exactly the way the
    5‰ near-duplicate rate is unmeasurable below ~200 entries: three charms over five axes is
    `[1,1,1,0,0]` at best, which is 400‰. A run report that prints only *"400‰ against 133‰"* reads
    as a collapse when it is in fact as flat as `n` allows, so the floor is reported beside the
    measurement. It is a granularity note, never a softened gate — `cleared` is still the real
    comparison.
    """
    if population <= 0:
        return 0
    axes = len(CHARM_AXES)
    base, extra = divmod(population, axes)
    return gini_permille([base + 1] * extra + [base] * (axes - extra))


def smallest_measurable_axis_population(ceiling_permille: int, *, search_limit: int = 1000) -> int:
    """The smallest charm count whose FLOOR is at or under `ceiling_permille`.

    Computed, not asserted: the ceiling is a tunable and the axis list is closed, so the population
    at which the gate becomes reachable moves with the tuning file rather than with a comment.
    `0` means no population up to `search_limit` can reach it, which would itself be the finding.
    """
    for population in range(1, search_limit + 1):
        if min_axis_gini_permille(population) <= ceiling_permille:
            return population
    return 0
