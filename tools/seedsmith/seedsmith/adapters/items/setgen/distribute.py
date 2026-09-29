"""seedsmith.adapters.items.setgen.distribute — the deterministic half of P1.

The model has chosen identity. This module prices it: capability at the lowest threshold, stats
above, a magnitude for every one of them through `numerics`, a roll plan for every member piece, and
a refusal for every constraint the choice broke. **It emits no number of its own** — every magnitude
is a `numerics.resolve` result, and the AE budget is compared in integer per-mille.

The constraint table, and where each row comes from:

| Constraint | Source |
|---|---|
| Exactly **one** capability atom, at the **lowest** threshold | ssot-sets §3.2 |
| Every higher threshold: `stat.modify` / `stat.derived` only | §3.2 |
| **No `More`-op modifier on any set tier** | §3.5 rule 2 |
| A threshold at **2**; top threshold ≤ member count | §3.4 |
| At most 6 roles, all inside the twelve | §3.4, §3.7 |
| At most one armament role | §3.5 rule 4 (`SetRoleForbidden`) |
| Total set value ≤ 1.5 AE per member piece | §3.5 rule 3 |
| 2 fixed atoms + 2 rolls over a 2-tier window per piece | §3.9 |
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .roles import refuse_roles
from .tuning import SetCharmGenTuning
from .vocab import FamilyPick, Vocabulary

#: `More` is the multiplicative op on `stat.modify` — the one a set tier may never carry. The two
#: families that are `More` in the shipped corpus are named in ssot-sets §3.5 rule 2 itself.
MORE_OP_FAMILIES: "frozenset[str]" = frozenset({"atom.bulwark", "atom.savagery"})

#: Match-scope-only defence families D14 refuses everywhere in v1 (module 8's `AffixFilters` already
#: flags them; repeated here because a set tier is a different emitter and would otherwise bypass it).
MATCH_SCOPE_ONLY_FAMILIES: "frozenset[str]" = frozenset({"atom.warding", "atom.resilience"})


def legal_set_stat_pool(vocabulary: Vocabulary,
                        tuning: "SetCharmGenTuning | None" = None) -> "tuple[FamilyPick, ...]":
    """Stat picks a set brief/schema may offer — distributor-legal only (D14 / More ban).

    Charm already filters via `charm_pool`. Set used to print the raw `vocabulary.stat` pool,
    including match-scope-only and More-op families that `distribute_set` then refuses — the
    brief/schema vs distributor mismatch that produced live escalate on `atom.resilience`.
    """
    kinds = frozenset(tuning.stat_kinds) if tuning is not None else None
    return tuple(
        pick for pick in vocabulary.stat
        if pick.family not in MORE_OP_FAMILIES
        and pick.family not in MATCH_SCOPE_ONLY_FAMILIES
        and (kinds is None or pick.kind_id in kinds)
    )


def capability_family_ids(vocabulary: Vocabulary) -> "tuple[str, ...]":
    """Closed `capability.family` enum values — unique family ids from the capability pool."""
    seen: "list[str]" = []
    for pick in vocabulary.capability:
        if pick.family not in seen:
            seen.append(pick.family)
    return tuple(seen)


@dataclass(frozen=True)
class RollPlan:
    """ssot-sets §3.9's member-piece shape, in the columns that actually exist.

    ⚠ `pool_rolls` is not a column (item-ideal §2g #12) — `Instantiator.Draw` runs `DrawBudget`
    twice, over `PrefixRolls` / `SuffixRolls`. The pair below is that, not a second invention.
    """

    fixed_atoms: int
    prefix_rolls: int
    suffix_rolls: int
    min_tier: int
    max_tier: int

    @property
    def pool_rolls(self) -> int:
        return self.prefix_rolls + self.suffix_rolls


@dataclass(frozen=True)
class ThresholdPlan:
    pieces: int
    capability: "FamilyPick | None"
    stats: "tuple[FamilyPick, ...]"
    power_band: str
    value_milli: int


@dataclass
class SetPlan:
    """What a distributed set looks like before it is emitted as JSON."""

    member_roles: "tuple[str, ...]"
    thresholds: "tuple[ThresholdPlan, ...]" = ()
    roll_plan: "RollPlan | None" = None
    problems: "list[str]" = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def total_value_milli(self) -> int:
        return sum(t.value_milli for t in self.thresholds)


def roll_plan(tuning: SetCharmGenTuning, *, min_tier: int) -> RollPlan:
    """A set piece's rolled half, fixed at the same moment as its identity half.

    The window is `tierWindowWidth` tiers wide from `min_tier`. Both named failure modes are
    refused structurally rather than trusted to the tuning: `_validate` in `tuning.py` already
    rejects `fixedIdentityAtoms = 0` ("fixed like a unique") and a total roll count at or above the
    rare comparison ("rolled like a rare").
    """
    if min_tier < 1:
        raise ValueError(f"min_tier must be at least 1, got {min_tier}")
    return RollPlan(
        fixed_atoms=tuning.fixed_identity_atoms,
        prefix_rolls=tuning.prefix_rolls,
        suffix_rolls=tuning.suffix_rolls,
        min_tier=min_tier,
        max_tier=min_tier + tuning.tier_window_width - 1,
    )


def threshold_ladder(tuning: SetCharmGenTuning, member_count: int) -> "tuple[int, ...]":
    """The piece counts a set of this size must carry.

    Always 2 (§3.4, no exceptions). A grand set additionally carries 4 so a partial grand set is
    playable and the last two pieces are a chase rather than a cliff. Then the top threshold is the
    **highest legal piece count the set can actually reach** — §3.4's own rule is *"the top
    threshold must be ≤ the member count"*, not *"= the member count"*.

    ⚠ **That last sentence used to read `if member_count in legal_threshold_pieces`, and it made a
    five-member set unauthorable** (module 13 defect 4, 2026-09-06). 5 is not in the closed
    `{2,3,4,6}` vocabulary, so the ladder came back `(2,)` — a single threshold, against a schema
    that required two — and nothing refused the member count either, so the state was simply
    unreachable. Taking the highest legal count *at or below* the member count gives `(2, 4)` and
    changes no other size: 2 → `(2,)`, 3 → `(2,3)`, 4 → `(2,4)`, 6 → `(2,4,6)`.
    """
    wanted = {tuning.mandatory_threshold_pieces}
    if member_count >= tuning.grand_members:
        wanted.update(tuning.grand_required_threshold_pieces)
    reachable = [p for p in tuning.legal_threshold_pieces if p <= member_count]
    if reachable:
        wanted.add(max(reachable))
    return tuple(sorted(p for p in wanted if p <= member_count))


def _value_milli(tuning: SetCharmGenTuning, atom_count: int, total_atoms: int,
                 member_count: int) -> int:
    """One threshold's share of the set's AE budget, in integer per-mille.

    Apportioned by atom count over the whole set, so the sum can never exceed the budget by
    construction — the division happens once, here, and the remainder goes to the last threshold
    via `distribute_set` rather than being rounded up per row (which is how an apportionment quietly
    overspends). `total_atoms` is widened before the multiply for the same reason the C# side
    widens: the product, not the operand, is what overflows.
    """
    if total_atoms <= 0:
        return 0
    budget = tuning.set_budget_milli(member_count)
    return (budget * atom_count) // total_atoms


def distribute_set(*, member_roles: "list[str] | tuple[str, ...]",
                   capability: "FamilyPick | None",
                   stats_by_threshold: "dict[int, tuple[FamilyPick, ...]]",
                   tuning: SetCharmGenTuning,
                   vocabulary: "Vocabulary | None" = None,
                   min_tier: int = 1) -> SetPlan:
    """Price a model draft. Returns a plan whose `problems` list is empty exactly when it is legal.

    Nothing here mutates the draft into legality. A draft that broke a rule is REFUSED with the rule
    named, because silently repairing it teaches the next call nothing — the same reasoning
    `llm_caller.call_with_self_heal` already applies to a schema defect.
    """
    plan = SetPlan(member_roles=tuple(member_roles))
    plan.problems.extend(refuse_roles(member_roles))

    member_count = len(set(member_roles))
    if member_count > tuning.max_roles:
        plan.problems.append(
            f"SetRoleForbidden: {member_count} member roles exceeds the {tuning.max_roles}-role "
            f"cap (ssot-sets §3.4 — at least nine slots stay rare/unique territory)")

    ladder = threshold_ladder(tuning, member_count)
    if tuning.mandatory_threshold_pieces not in ladder:
        plan.problems.append(
            f"SetThresholdMissing: no threshold at {tuning.mandatory_threshold_pieces} — a set "
            f"whose first bonus is higher has an invisible first step and cannot be splashed "
            f"(ssot-sets §3.4)")
    for pieces in ladder:
        if pieces > member_count:
            plan.problems.append(
                f"SetThresholdUnreachable: threshold at {pieces} pieces on a {member_count}-member "
                f"set")

    if capability is None:
        plan.problems.append(
            "SetCapabilityMissing: every set grants exactly one capability atom, at its LOWEST "
            "threshold (ssot-sets §3.2's inversion) — a set with none is stat filler")
    elif capability.kind_id not in tuning.capability_kinds:
        plan.problems.append(
            f"SetTierForbiddenAtom: {capability.family!r} is kind {capability.kind_id!r}, not a "
            f"capability kind {sorted(tuning.capability_kinds)}")
    elif vocabulary is not None and capability.roles and not (
            set(member_roles) & set(capability.roles)):
        plan.problems.append(
            f"SetCapabilityOffRole: {capability.family!r} is legal on {sorted(capability.roles)}, "
            f"none of which this set claims — a capability family's own roles narrow the legal pool")

    higher = [p for p in ladder if p != ladder[0]] if ladder else []
    for pieces in sorted(stats_by_threshold):
        if ladder and pieces == ladder[0]:
            plan.problems.append(
                f"SetTierForbiddenAtom: the lowest threshold ({pieces}) carries the capability, "
                f"never stat atoms (ssot-sets §3.2)")
        elif pieces not in higher:
            plan.problems.append(
                f"SetThresholdUnreachable: stats declared at {pieces} pieces, which is not a "
                f"threshold of this set {list(ladder)}")
        for pick in stats_by_threshold[pieces]:
            if pick.kind_id not in tuning.stat_kinds:
                plan.problems.append(
                    f"SetTierForbiddenAtom: {pick.family!r} at threshold {pieces} is kind "
                    f"{pick.kind_id!r}; higher thresholds grant stat.modify / stat.derived only")
            if pick.family in MORE_OP_FAMILIES:
                plan.problems.append(
                    f"SetTierForbiddenAtom: {pick.family!r} is a More-op modifier; a set tier may "
                    f"never carry one (ssot-sets §3.5 rule 2 — this is the rule that makes the "
                    f"Diablo 3 failure literally unauthorable)")
            if pick.family in MATCH_SCOPE_ONLY_FAMILIES:
                plan.problems.append(
                    f"SetTierForbiddenAtom: {pick.family!r} is match-scope-only and refused "
                    f"everywhere in v1 (D14)")

    total_atoms = (1 if capability is not None else 0) + sum(
        len(v) for v in stats_by_threshold.values())
    thresholds: "list[ThresholdPlan]" = []
    spent = 0
    for index, pieces in enumerate(ladder):
        is_lowest = index == 0
        picks = () if is_lowest else tuple(stats_by_threshold.get(pieces, ()))
        count = 1 if is_lowest and capability is not None else len(picks)
        value = _value_milli(tuning, count, total_atoms, member_count)
        if index == len(ladder) - 1:
            # The apportionment remainder lands on the top threshold rather than being rounded up
            # per row — an integer-exact split whose sum is the budget, never above it.
            value = max(0, tuning.set_budget_milli(member_count) - spent)
        spent += value
        thresholds.append(ThresholdPlan(
            pieces=pieces,
            capability=capability if is_lowest else None,
            stats=picks,
            power_band=_power_band_for(index, len(ladder)),
            value_milli=value,
        ))
    plan.thresholds = tuple(thresholds)

    budget = tuning.set_budget_milli(member_count)
    if plan.total_value_milli > budget:
        plan.problems.append(
            f"SetBudgetExceeded: {plan.total_value_milli} milli-AE over {member_count} members "
            f"exceeds {budget} ({tuning.ae_per_member_milli} per member, ssot-sets §3.5 rule 3)")

    plan.roll_plan = roll_plan(tuning, min_tier=min_tier)
    return plan


def _power_band_for(index: int, count: int) -> str:
    """The band a threshold's atoms are resolved at.

    Deterministic and positional: the capability sits low (it is the identity, not the payoff), the
    top threshold sits high, everything between is medium. The *magnitude* still comes from
    `numerics.resolve`; this only chooses which band it resolves in, which is exactly the split P1
    draws — the model never sees this function.
    """
    if index == 0:
        return "low"
    if index == count - 1:
        return "high"
    return "medium"
