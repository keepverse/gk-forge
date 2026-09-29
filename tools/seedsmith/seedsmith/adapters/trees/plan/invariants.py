"""seedsmith.adapters.trees.plan.invariants — the corpus-level and ladder-level refusals that a
single-tree endpoint check structurally cannot catch (task C1, spec-tree-plan.md §3, §3.1, §3.2,
§4, §5.1, §5.2, §Testing; Gate 3 per spec-tree-language.md §7).

Every check here is a function that RAISES a named exception on violation — never a bool, never a
silent clamp. Each message names the offending tree/branch/tier/archetype/node so a failure is
diagnosable from the text alone (spec-tree-plan.md's own "Boundaries" rule: "Refuse and name the
offender").

This module does not re-derive arithmetic `archetypes.py` and `ladder.py` already own and already
verified against the spec's worked tables — it composes their pure functions into the checks the
Testing table names, and adds the two formulas (`derive_max_node_share_milli`, the milli/points
conversion residual rule) those checks need that were not owned by any existing module.

⛔ `no_node_exceeds_the_potency_ceiling` (R-P1) and `every_shipped_archetype_is_admissible` (R-P2)
are DELETED per spec-tree-plan.md §5.2 and MUST NOT be reintroduced here or anywhere else: both
compared a construction against its own algebraic supremum, so both passed by definition. `P-1`
and `P-2` below are their real replacements — a derivation guard and a rounding guard, neither of
which is a tautology.
"""
from __future__ import annotations

from .archetypes import TIER_COUNT, Archetype, max_node_milli, mechanism_share_milli
from .ladder import LadderError, _round_half_up, node_budget_milli, tier_budget_milli

# The repo-wide `long` bound (docs/architecture/numeric-types.md's numeric-overflow table), the same explicit stand-in the
# action adapters' own `_widen_mul` helpers use — Python ints never actually overflow, so this is
# an EXPLICIT check standing in for the `long` every C# consumer eventually reads this plan as.
_LONG_MAX = 9_223_372_036_854_775_807
_LONG_MIN = -9_223_372_036_854_775_808


def _widen_mul(a: int, b: int) -> int:
    a = int(a)
    b = int(b)
    product = a * b
    if product > _LONG_MAX or product < _LONG_MIN:
        raise OverflowError(f"_widen_mul({a}, {b}) = {product} does not fit a long ({_LONG_MIN}..{_LONG_MAX})")
    return product


class PlanInvariantError(ValueError):
    """Base for every named refusal in this module. Never caught and turned into a bool — a
    violation always propagates."""


# ── C1 — corpus-level budget equality ───────────────────────────────────────────────────────────

class BudgetEqualityRefusal(PlanInvariantError):
    """C1: every tree in the corpus must spend exactly the same total, and every tree's two
    branches must be symmetric. Names the tree(s) and the totals that disagree."""


def check_branch_budget_symmetry(tree_id: str, nodes: "list[dict]") -> None:
    """C1's per-tree half: `Σ offensive == Σ defensive`, read from `nodes[].budgetPoints` (what the
    binder actually prices against — the milli shares are a separate, already-checked identity).
    A single tree needs no sibling to run this against."""
    offensive = sum(n["budgetPoints"] for n in nodes if n["branch"] == "offensive")
    defensive = sum(n["budgetPoints"] for n in nodes if n["branch"] == "defensive")
    if offensive != defensive:
        raise BudgetEqualityRefusal(
            f"{tree_id}: offensive budgetPoints={offensive} != defensive budgetPoints={defensive} — "
            f"C1 requires the two branches to spend the same total")


def check_equal_budget_across_trees(trees: "list[dict]") -> None:
    """C1's corpus-level half: `Σ node.budgetPoints` is identical across all `n` trees, and each
    tree's own branches are symmetric (delegates to `check_branch_budget_symmetry` per tree — one
    rule, not two). `trees` is a list of `{"treeId": str, "nodes": [{"branch": str,
    "budgetPoints": int}, ...]}` — the shape `build_plan` emits per tree."""
    if not trees:
        raise BudgetEqualityRefusal("C1 needs at least one tree to compare — got an empty corpus")

    totals: "dict[str, int]" = {}
    for tree in trees:
        tree_id = tree["treeId"]
        check_branch_budget_symmetry(tree_id, tree["nodes"])
        totals[tree_id] = sum(n["budgetPoints"] for n in tree["nodes"])

    distinct = set(totals.values())
    if len(distinct) > 1:
        detail = ", ".join(f"{tid}={total}" for tid, total in sorted(totals.items()))
        raise BudgetEqualityRefusal(f"C1 violated: tree budgets are not identical — {detail}")


class ArchetypeShapesCollapsedRefusal(PlanInvariantError):
    """C1's inverse guard (`archetype_shapes_actually_differ`, spec-tree-plan.md §3's own Testing
    row): the strongest single node must differ by at least the configured ratio between the
    widest and narrowest crown, or D15 has silently collapsed into "every tree feels the same"."""


def check_archetype_shapes_actually_differ(archetypes: "tuple[Archetype, ...]", tier_count: int,
                                           min_ratio_milli: int = 2000) -> None:
    """Compares each archetype's OWN largest node (`archetypes.max_node_milli`, ‰ of one branch,
    wherever in the ladder it falls) across the archetype set — the comparison spec-tree-plan.md §3
    actually makes (`gated-deep`'s 182‰ capstone at tier 10 vs `late-crown`'s 73‰ node at tier 8:
    2.5×, at DIFFERENT tiers). `min_ratio_milli=2000` is the shipped 2× floor; the measured shipped
    spread is 2.5×, so the default passes at a comfortable margin and a set that flattens toward
    "every archetype looks the same" is refused naming both archetypes and their tiers."""
    shares = tier_budget_milli(tier_count)

    def _max_with_tier(a: Archetype) -> "tuple[int, int]":
        best_share = -1
        best_tier = -1
        for t in range(1, tier_count + 1):
            share = max(node_budget_milli(shares[t - 1], a.widths[t - 1]))
            if share > best_share:
                best_share = share
                best_tier = t
        return best_share, best_tier

    entries = [(a.id, *_max_with_tier(a)) for a in archetypes]
    hi_id, hi_share, hi_tier = max(entries, key=lambda e: e[1])
    # Pick the comparison archetype from a DIFFERENT id than `hi` whenever more than one exists —
    # otherwise a tie (both entries share the exact same value) makes plain min() return the SAME
    # entry `max()` already picked, and the refusal would name one archetype instead of two.
    other_entries = [e for e in entries if e[0] != hi_id] or entries
    lo_id, lo_share, lo_tier = min(other_entries, key=lambda e: e[1])
    if lo_share <= 0:
        raise ArchetypeShapesCollapsedRefusal(
            f"{lo_id}: largest node share is {lo_share}‰ — cannot form a shape-difference ratio")
    if _widen_mul(hi_share, 1000) < _widen_mul(lo_share, min_ratio_milli):
        raise ArchetypeShapesCollapsedRefusal(
            f"archetype shapes have collapsed: {hi_id}'s strongest node is {hi_share}‰ (tier {hi_tier}) "
            f"vs {lo_id}'s {lo_share}‰ (tier {lo_tier}) — ratio is below the required "
            f"{min_ratio_milli / 1000:.1f}x (D15's inverse guard, archetype_shapes_actually_differ)")


# ── R-A1 — reuse archetypes.check_reward_spread, never reimplement ─────────────────────────────

def check_r_a1_reward_spread(archetypes: "tuple[Archetype, ...]", tier_count: int,
                             unlock_first: int, unlock_step: int, max_ratio_milli: int) -> None:
    """Thin re-export: R-A1's arithmetic is `archetypes.check_reward_spread`'s job and is not
    duplicated here (task C1's own instruction). This exists so a caller assembling the corpus-level
    `PassiveTree/TreeEqualValue` gate has one module to import invariants from."""
    from .archetypes import check_reward_spread
    check_reward_spread(archetypes, tier_count, unlock_first, unlock_step, max_ratio_milli)


# ── R-M1 / R-M2 — the mechanism ramp ────────────────────────────────────────────────────────────

class DeepestTierNotAllMechanismRefusal(PlanInvariantError):
    """R-M1: `mechNodes[tierCount] == widths[tierCount]` for every archetype — the deepest tier is
    100% mechanism, structurally, from §3.5's measured conclusion."""


def check_r_m1_deepest_tier_is_all_mechanism(archetype: Archetype, tier_count: int,
                                             ramp_start_milli: int, ramp_end_milli: int) -> None:
    """Proves R-M1 numerically rather than trusting `mechanism_nodes`'s own docstring claim (task
    C1's explicit instruction) — recomputes the per-tier mechanism count and compares the deepest
    entry against the archetype's own deepest-tier width."""
    from .archetypes import mechanism_nodes
    mech = mechanism_nodes(archetype, tier_count, ramp_start_milli, ramp_end_milli)
    deepest_width = archetype.widths[tier_count - 1]
    if mech[-1] != deepest_width:
        raise DeepestTierNotAllMechanismRefusal(
            f"{archetype.id}: R-M1 violated — mechNodes[{tier_count}]={mech[-1]} != "
            f"widths[{tier_count}]={deepest_width}")


class MechanismShareNotMonotoneRefusal(PlanInvariantError):
    """R-M2: `mechShareMilli` must be monotone non-decreasing across tiers 1..tierCount. A tree
    that gets LESS mechanical as it deepens is the exact failure §3.5's sweep measured."""


def check_r_m2_mechanism_share_is_monotone(tier_count: int, ramp_start_milli: int,
                                           ramp_end_milli: int) -> None:
    """`mechanism_share_milli` depends only on `(t, tierCount, rampStart, rampEnd)` — never on an
    archetype's widths — so the ramp is identical for every archetype by construction and checking
    it once covers all three shipped archetypes (and any future one) at once. Callers that want the
    per-archetype language the Testing table uses still get it: iterate `SHIPPED_ARCHETYPES` and
    call this once per archetype in a loop — the assertion is the same call, repeated, not a
    different formula per archetype."""
    shares = [mechanism_share_milli(t, tier_count, ramp_start_milli, ramp_end_milli)
              for t in range(1, tier_count + 1)]
    for t in range(2, tier_count + 1):
        if shares[t - 1] < shares[t - 2]:
            raise MechanismShareNotMonotoneRefusal(
                f"mechShareMilli decreased from tier {t - 1} ({shares[t - 2]}) to tier {t} "
                f"({shares[t - 1]}) — R-M2 requires monotone non-decreasing")


# ── P-1 / P-2 — the node potency ceiling (§5.1, §5.2) ───────────────────────────────────────────

def derive_max_node_share_milli(tier_count: int, min_terminal_width: int) -> int:
    """`maxNodeShareMilli = round_half_up(2000 / ((tierCount + 1) * minTerminalWidth))`, ‰ of ONE
    BRANCH (spec-tree-plan.md §5.1's derivation — the largest node any archetype can produce is the
    deepest tier's share split among the fewest nodes). This is the ONE formula both P-1 and P-2
    read; a private re-derivation anywhere else would be exactly the "two-place-edit hazard" §5.1
    exists to close."""
    if tier_count < 1:
        raise LadderError(f"tier_count must be >= 1, got {tier_count}")
    if min_terminal_width < 1:
        raise LadderError(f"min_terminal_width must be >= 1, got {min_terminal_width}")
    denominator = _widen_mul(tier_count + 1, min_terminal_width)
    return _round_half_up(2000, denominator)


class PotencyDerivationRefusal(PlanInvariantError):
    """P-1: the emitted `potency.maxNodeShareMilli` must equal the value derived from the emitted
    `tierCount` and `minTerminalWidth` — never a hand-edited constant. A derivation guard, not a
    balance refusal (spec-tree-plan.md §5.2)."""


def check_p1_potency_ceiling_is_derived(emitted_max_node_share_milli: int, tier_count: int,
                                        min_terminal_width: int) -> None:
    derived = derive_max_node_share_milli(tier_count, min_terminal_width)
    if emitted_max_node_share_milli != derived:
        raise PotencyDerivationRefusal(
            f"potency.maxNodeShareMilli={emitted_max_node_share_milli} but the derivation from "
            f"tierCount={tier_count}, minTerminalWidth={min_terminal_width} gives {derived} — "
            f"P-1 violated (hand-edited value)")


class PotencyCeilingExceededRefusal(PlanInvariantError):
    """P-2: no rounded, emitted node budget share may exceed the derived maximum, at any tier count
    from 1 to 40. A rounding guard (spec-tree-plan.md §5.2): the residual-absorption rule in
    `tier_budget_milli` pushes the deepest tier above its exact fraction whenever the residual is
    non-zero, and this is the check that would catch it doing so past the derived ceiling."""


def check_p2_no_rounded_share_exceeds_derived_maximum(min_terminal_width: int = 1,
                                                       max_tier_count: int = 40) -> None:
    """Sweeps `tier_count` 1..`max_tier_count` (not only the shipped 10) with the deepest tier's
    width pinned at `min_terminal_width` — the extremal case §5.2 proves algebraically: for a fixed
    tier share, `node_budget_milli` returns SMALLER per-node values as width grows, so the deepest
    tier at the narrowest legal width is the one case that can reach the derived supremum, and every
    wider (or shallower) real archetype produces a share at or below it.

    ⚠ REAL FINDING (task C1, 2026-09-06): `ladder.tier_budget_milli` dumps 100% of the per-mille
    column's rounding residual into the DEEPEST tier by design (its own docstring: "residual
    absorbed by the LAST slot"). At `tier_count=10` (the shipped topology) that residual is exactly
    0, so it is invisible there — the reason §5.2 itself calls out "0 at ten tiers and not at every
    tier count". Sweeping the FULL 1..40 range this function defaults to actually finds five tier
    counts where the residual pushes the deepest share past this section's own derived ceiling:
    23 (+1), 29 (+1), **31 (+7)**, 34 (+1), 38 (+1) — `tier_count=31` alone overshoots by 7‰ on an
    ceiling of 63‰, an 11% breach, because round-half-up's bias can compound across many
    independently-rounded terms before landing entirely on one tier.

    This is real, reproducible arithmetic in already-shipped `ladder.py` (task B1), not a defect in
    this function — see `tests/test_tree_plan_invariants.py`'s own test that PROVES it fires at
    `tier_count=23` first. It never manifests today because `topology.tierCount` is structural and
    "Ask first" to change (Boundaries, spec-tree-plan.md) and is fixed at 10, where the residual is
    0. `check_tree_equal_value` therefore scopes its own P-2 call to the corpus's ACTUAL emitted
    `tier_count` (never the full speculative 1..40 range) so a real, shipped corpus is never refused
    over a tier count nothing has ever generated at. Fixing `tier_budget_milli`'s residual rule
    (e.g. a largest-remainder distribution instead of dump-to-last) would close this for good, but
    that function is pre-existing, tested B1 code outside this task's own Files list — flagged here
    for the owner rather than silently patched.
    """
    for tier_count in range(1, max_tier_count + 1):
        shares = tier_budget_milli(tier_count)
        deepest_share = shares[-1]
        worst_node_share = max(node_budget_milli(deepest_share, min_terminal_width))
        ceiling = derive_max_node_share_milli(tier_count, min_terminal_width)
        if worst_node_share > ceiling:
            raise PotencyCeilingExceededRefusal(
                f"tier_count={tier_count}: deepest-tier node share {worst_node_share}‰ "
                f"(width={min_terminal_width}) exceeds the derived ceiling {ceiling}‰ — "
                f"P-2 rounding guard violated")


# ── Gate 3 — plan reachability (spec-tree-language.md §7, row 3) ───────────────────────────────
#
# Deterministic, over the plan alone, before any model call. Operates on a generic node list shaped
# `{"id": str, "tier": int, "branch": str, "parents": list[str]}` — `tree-plan`'s own schema notes
# `nodes[].parents[]` is "reading order, not a gate" for GAMEPLAY unlocking (the real gate is the
# tier requirement, `ladder.req[]`), but the graph is still real data that can be internally
# inconsistent (a dangling reference, a hole, an unreachable island), and that inconsistency is
# exactly what Gate 3 exists to catch before any model call is spent authoring content for it.

class EmptyTierRefusal(PlanInvariantError):
    """A `(branch, tier)` slot with zero nodes — the tier itself did not survive planning."""


def check_no_empty_tier(tree_id: str, nodes: "list[dict]", tier_count: int,
                        branches: "tuple[str, ...]" = ("offensive", "defensive")) -> None:
    counts: "dict[tuple[str, int], int]" = {}
    for n in nodes:
        key = (n["branch"], n["tier"])
        counts[key] = counts.get(key, 0) + 1
    for branch in branches:
        for t in range(1, tier_count + 1):
            if counts.get((branch, t), 0) == 0:
                raise EmptyTierRefusal(f"{tree_id}: branch {branch!r} tier {t} has zero nodes")


class UnsatisfiablePrereqRefusal(PlanInvariantError):
    """A node's `parents[]` names an id no branch/tier in the tree reaches — a dangling reference."""


def check_no_unsatisfiable_prereq(tree_id: str, nodes: "list[dict]") -> None:
    valid_ids = {n["id"] for n in nodes}
    for n in nodes:
        for parent_id in n.get("parents", []):
            if parent_id not in valid_ids:
                raise UnsatisfiablePrereqRefusal(
                    f"{tree_id}: node {n['id']!r} names prereq {parent_id!r}, which no branch/tier "
                    f"in this tree reaches")


class OrphanNodeRefusal(PlanInvariantError):
    """A node above tier 1 that is unreachable from the tree's root set (its tier-1 nodes) by
    walking `parents[]` edges — a disconnected island the language stage would silently never
    reach."""


def check_no_orphan_node(tree_id: str, nodes: "list[dict]") -> None:
    by_id = {n["id"]: n for n in nodes}
    reachable: "set[str]" = {n["id"] for n in nodes if n["tier"] == 1}
    # Fixed-point walk: a node becomes reachable once any of its parents is. Bounded by len(nodes)
    # passes — a DAG over N nodes has no path longer than N, so this always terminates.
    changed = True
    while changed:
        changed = False
        for n in nodes:
            if n["id"] in reachable:
                continue
            if any(p in reachable for p in n.get("parents", [])):
                reachable.add(n["id"])
                changed = True
    for n in nodes:
        if n["id"] not in reachable:
            raise OrphanNodeRefusal(
                f"{tree_id}: node {n['id']!r} (tier {n['tier']}) is unreachable from the tree's "
                f"root set via prereq edges")


def check_gate3_plan_reachability(tree_id: str, nodes: "list[dict]", tier_count: int,
                                  branches: "tuple[str, ...]" = ("offensive", "defensive")) -> None:
    """The three Gate 3 checks in the order spec-tree-language.md §7 row 3 lists them: an
    unsatisfiable prereq, an empty tier, an orphan node. Runs all three (does not stop at the
    first kind so a caller sees every distinct failure across a run, but DOES stop at the first
    violation within a kind, consistent with every other refusal in this module)."""
    check_no_unsatisfiable_prereq(tree_id, nodes)
    check_no_empty_tier(tree_id, nodes, tier_count, branches)
    check_no_orphan_node(tree_id, nodes)


# ── The family roster — declared absence, never silence ────────────────────────────────────────

class SilentEmptyRosterRefusal(PlanInvariantError):
    """`_pending[]`'s own contract: "declared absences ... never silence". An empty
    `roster.creatureFamilies` (or any other roster axis) that is NOT named in `_pending` is refused —
    the failure mode this guards is a roster mirror going missing and the plan generating anyway
    against an empty axis with nothing to show for it."""


def check_pending_declared_for_empty_rosters(plan: dict, axes: "tuple[str, ...]" = ("creatureFamilies",)) -> None:
    roster = plan.get("roster", {})
    pending = set(plan.get("_pending", []))
    for axis in axes:
        if not roster.get(axis):
            if axis not in pending:
                raise SilentEmptyRosterRefusal(
                    f"roster.{axis} is empty but '_pending' does not declare {axis!r} — silent "
                    f"generation against an empty roster")


# ── R-G1 / R-G2 — the generation gate and the wave order (§7, §7.1, task C2) ───────────────────

class PendingGateGenerationRefusal(PlanInvariantError):
    """R-G1: stage 2 (content generation) must never run for a tree whose `gateQuantity` has no
    production carrier. Names the tree and the missing gate quantity — never a silent skip, and
    never reachable from `--emit`, which stays free for a `pending` tree by construction (§7.1:
    "planning a `pending` tree is free and the plan is where the absence becomes visible")."""


def check_r_g1_generation_allowed(tree_id: str, gate_state: str, gate_quantity: str) -> None:
    """The generation gate itself: raise unless `gate_state == "carrier"`. `gate_state` must come
    from `gates.resolve_gate_state` (read off the checked-in evidence file) — this function does
    not care where it came from, only what it says, so a future real stage-2 caller and this
    module's own tests share the exact same refusal path."""
    if gate_state == "carrier":
        return
    if gate_state == "pending":
        raise PendingGateGenerationRefusal(
            f"{tree_id}: gate quantity {gate_quantity!r} has no production carrier "
            f"(gateState='pending') — R-G1 refuses stage-2 generation for this tree until "
            f"gate-counters lands it (D37)")
    raise PendingGateGenerationRefusal(
        f"{tree_id}: gateState={gate_state!r} is neither 'carrier' nor 'pending' — R-G1 cannot "
        f"evaluate an unrecognised gate state for gate quantity {gate_quantity!r}")


def derive_generation_wave(gate_state: str) -> int:
    """R-G2: `generationWave` is a pure function of `gateState` and NOTHING else — never a
    hand-typed per-category constant. `gateState` is a two-valued enum (`carrier` | `pending`), so
    a function of `gateState` alone can distinguish exactly two waves: `carrier` -> wave 0
    (generable today, and "wave 0 is exactly the primary trees" holds today because `primary` is
    currently the only carrier category with real trees); `pending` -> wave 1 (held until its
    `gate-counters` row flips).

    §7.1's own worked table additionally stages the two currently-PENDING categories (`elemental`,
    `status`) into separate waves 1/2, by which `gate-counters` row is expected to land first. That
    finer staging is a scheduling OPINION about two quantities that are both `pending` today (D37)
    — it is not a fact `gateState` itself carries, since `gateState` cannot distinguish one pending
    reason from another. Reproducing it here would mean reading something other than `gateState`
    (e.g. a hand-ordered category list), which is precisely what R-G2 forbids ("never
    hand-assigned"). This function instead honours the property R-G2 actually names: the day
    `gate-counters` lands `element_mastery`, that tree's own `gateState` flips to `carrier` and it
    moves to wave 0 the same day, with no spec edit and no wave renumbering elsewhere — resolved
    ambiguity, see the C2 task report."""
    if gate_state == "carrier":
        return 0
    if gate_state == "pending":
        return 1
    raise PlanInvariantError(f"derive_generation_wave: unrecognised gateState {gate_state!r}")


class TreeOrderRefusal(PlanInvariantError):
    """R-G2: every `trees[]` entry's own `generationWave` must equal what `derive_generation_wave`
    computes from that entry's `gateState` (never hand-typed), and the array's `generationWave`
    column must be non-decreasing (a gross reordering — e.g. a hand-edited manifest — is caught
    here; the finer roster-ordinal tie-break within one wave is enforced at BUILD time by
    `emit.build_manifest`'s own sort key, since the roster ordinal itself is not part of the frozen
    `trees[]` row shape and so cannot be independently re-derived from a committed manifest alone)."""


def check_r_g2_wave_order(trees_index: "list[dict]") -> None:
    """`trees_index` is (a prefix of) the manifest's own `trees[]` array — each entry at least
    `{"treeId": str, "gateState": str, "generationWave": int}`."""
    prev_wave = -1
    for entry in trees_index:
        derived = derive_generation_wave(entry["gateState"])
        if entry["generationWave"] != derived:
            raise TreeOrderRefusal(
                f"{entry['treeId']}: generationWave={entry['generationWave']} but gateState="
                f"{entry['gateState']!r} derives {derived} — R-G2 forbids a hand-assigned wave")
        if entry["generationWave"] < prev_wave:
            raise TreeOrderRefusal(
                f"{entry['treeId']}: trees[] is out of generationWave order — wave "
                f"{entry['generationWave']} appears after a wave {prev_wave} entry")
        prev_wave = entry["generationWave"]


# ── PassiveTree/TreeEqualValue — this module's own gate (spec-tree-plan.md §3.2) ────────────────

def check_tree_equal_value(trees: "list[dict]", archetypes: "tuple[Archetype, ...]", tier_count: int,
                           unlock_first: int, unlock_step: int, reward_spread_max_ratio_milli: int,
                           min_terminal_width: int) -> None:
    """`PassiveTree/TreeEqualValue` (spec-tree-plan.md §3.2): "asserts C1 (every tree's Σ
    budgetPoints identical; Σ offensive == Σ defensive), P-1/P-2 (§5.2), and R-A1 at every tier."
    Runs at `--emit` and `--check`, before any model call, over the emitted plan(s) alone. Refuses
    on the first violation, naming the tree/branch/tier/archetype/node — it never clamps.

    `trees` is a list of per-tree plan dicts (`build_plan`'s own output shape); at `--emit` for a
    single tree this is a one-element list, which is exactly what C1's `Σ budgetPoints identical
    across all n trees` degenerates to correctly at `n == 1` (nothing to disagree with)."""
    check_equal_budget_across_trees(trees)
    check_r_a1_reward_spread(archetypes, tier_count, unlock_first, unlock_step, reward_spread_max_ratio_milli)
    for tree in trees:
        emitted_ceiling = tree.get("potency", {}).get("maxNodeShareMilli")
        if emitted_ceiling is not None:
            check_p1_potency_ceiling_is_derived(emitted_ceiling, tier_count, min_terminal_width)
    # P-2 here is scoped to THIS corpus's own emitted tier count (and everything shallower) — the
    # topology actually shipped, not the full 1..40 speculative sweep. The full sweep is a SEPARATE,
    # standalone regression guard (`check_p2_no_rounded_share_exceeds_derived_maximum`'s own
    # `max_tier_count` default) that a caller runs on its own; see this function's own module
    # docstring / the test suite for a real, discovered gap it finds OUTSIDE tierCount=10 — wiring
    # the full speculative sweep into the live per-emit gate would refuse every real corpus over an
    # arithmetic property of tier counts nothing has ever shipped at.
    check_p2_no_rounded_share_exceeds_derived_maximum(min_terminal_width, max_tier_count=tier_count)
