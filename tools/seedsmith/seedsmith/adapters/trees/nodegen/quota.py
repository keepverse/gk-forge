"""seedsmith.adapters.trees.nodegen.quota — `largest_remainder_count` over the six quota axes,
plus **H3's own addition**: the per-slot cell walk, hard-constraint overrides and the step-5
rebalance (task H3, spec-tree-language.md §4, spec-tree-plan.md §8).

**What H1 built.** §4.2's algorithm has seven steps; steps 1-3 and 6 are pure apportionment
arithmetic with no dependency on a specific tree's plan, and were real from the start:

- step 1: `N` is read off the loaded plan's own `len(nodes)`, never hardcoded to 1,560 — correct
  at today's real corpus size (one committed tree, `might`) and at the eventual 39-tree corpus
  alike (see `quota_for_plan`'s own docstring)
- step 2: `axis_marginals` — exact integer marginals per axis, `Σ == N`, via the SHARED
  `largest_remainder_count` (`adapters.actions.distribution_planner.derive`) — reused, not
  reimplemented, per this module's own spec footnote naming that exact function by file:line
- step 3: `expand_counts` — the same shared function, re-exported here so a caller never has to
  reach across two adapter packages to flatten one allocation
- step 6: `permitted` — narrows a vocabulary to the ids matching one `QuotaCell`'s value on one
  axis; this is the "load-bearing line" the spec's own Code style section shows verbatim, and this
  module's version matches it

**What H3 adds: steps 4 and 5, and the plan-facing wiring around them.**

- Step 4 — `build_slot`/`assign_quota_cells`: the per-slot walk assigning a `QuotaCell` to every
  one of a tree's node slots, in the caller's own canonical (tree, branch, tier, index) order.
  **`nodeClass` is a hard override on EVERY slot, not only an elemental/status tree's** — B1's own
  archetype mechanism ramp (`plan.archetypes.mechanism_nodes`) already fixes it per node before
  this stage ever runs (`plan_read.TreePlanNode.node_class`), so this axis is never drawn from a
  free sequence at all; `element`/`status` are forced only for an elemental/status tree
  (spec-tree-plan.md §8 step 4's own two category overrides). `trigger`, `channelFamily` and
  `exclusionForm` are never overridden — every slot draws them freely.
- Step 5 — `rebalance_axis`: returns an overridden slot's drawn value to the pool by SUBTRACTING
  the forced tally from the axis's own corpus-wide quota (both were computed over the SAME total,
  so the residual sums out exactly — see the function's own docstring for why no second
  `largest_remainder_count` pass is needed) — and refuses (`OverdrawnQuota`), rather than silently
  clamping or borrowing, the moment a forced value's own demand exceeds what the targets file ever
  allocated it. That refusal is H3's own acceptance bullet: "an overdrawn cell is refused, not
  rebalanced silently."
- `quota_for_plan`/`permitted_ids_for_cell` — the plan-facing convenience wrapper: reads a real
  `plan_read.TreePlan`'s own `property_vocabulary` for every axis's member list (already counted
  fresh by B1 from the real mirrors — never a second roster read here) and `nodegen.targets
  .PassiveTreeTargets` for the declared weights, so a caller never hand-assembles `quota`/`order`
  itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from ...actions.distribution_planner.derive import expand_counts, largest_remainder_count
# The `none` member's own canonical name lives in one place (this is the same constant the schema
# enum and the corpus metric read) — quota needs it to lead the exclusionForm axis's hand-out
# order inside `quota_for_plan`.
from . import exclusion as nodegen_exclusion

__all__ = [
    "AXES",
    "AXIS_PROPERTY_VOCAB_KEY",
    "NON_AUTHORABLE_TRIGGERS",
    "QuotaCell",
    "QuotaSlot",
    "UnsatisfiableCell",
    "OverdrawnQuota",
    "RETIRED_FAMILY_SUCCESSOR",
    "resolve_retired_channel_family",
    "resolve_retired_quota_cell",
    "uniform_weights_milli",
    "axis_marginals",
    "expand_counts",
    "permitted",
    "axis_members",
    "axis_order",
    "axis_weights_milli",
    "build_slot",
    "tally_forced",
    "rebalance_axis",
    "assign_quota_cells",
    "quota_for_plan",
    "permitted_ids_for_cell",
]

#: §4.2 step 2's six quota axes, in the spec's own declared order — the ORDER a caller passes to
#: `axis_marginals`/`expand_counts` matters (tie-breaking is positional, never dict-iteration-order
#: dependent), so this tuple is the one place that order is written down.
AXES: "tuple[str, ...]" = ("nodeClass", "trigger", "element", "status", "channelFamily", "exclusionForm")

#: A quota axis's own name does not always match the key it is filed under in a committed plan's
#: `propertyVocabulary` (counted this session against the real `might.v1.json`): every axis but
#: `trigger` matches verbatim; `trigger` is filed as `atomTrigger` there (§3 row 3's own name for
#: the vocabulary, "Atom triggers"). One dict, so a caller never re-derives this by hand.
AXIS_PROPERTY_VOCAB_KEY: "dict[str, str]" = {
    "nodeClass": "nodeClass",
    "trigger": "atomTrigger",
    "element": "element",
    "status": "status",
    "channelFamily": "channelFamily",
    "exclusionForm": "exclusionForm",
}

#: §3 row 3: "13 declared, 11 authorable" — `OnGranted`/`OnRemoved` are runtime lifecycle states no
#: kind may carry (`AtomKind.cs:104-111`), not choices this stage's brief may ever offer. The
#: committed plan's `propertyVocabulary.atomTrigger` lists all 13 (it is a roster mirror, not a
#: brief-facing enum), so `axis_members("trigger", ...)` filters these two out here rather than
#: leaking them into a quota target or a permitted subset.
NON_AUTHORABLE_TRIGGERS: "tuple[str, ...]" = ("OnGranted", "OnRemoved")


class UnsatisfiableCell(ValueError):
    """§4.2 step 6 / the spec's own Code style section: an empty permitted subset is HELD, never
    widened. Raised here so a caller cannot accidentally treat an empty list as "no constraint"."""


class OverdrawnQuota(ValueError):
    """§4.2 step 5 / H3's own acceptance bullet: "an overdrawn cell is refused, not rebalanced
    silently." Raised by `rebalance_axis`/`assign_quota_cells` the moment a hard-forced axis value
    demands more slots than the corpus-wide quota ever allocated it, or forces a value the axis's
    own declared members do not contain at all — both are the targets file (or the roster it was
    built from) failing to anticipate the real slot count, which must surface as a refusal rather
    than a silently clamped or borrowed count."""


@dataclass(frozen=True)
class QuotaCell:
    """One node's `(nodeClass, trigger, element, status, channelFamily, exclusionForm)` allocation
    (§2's `quotaCell` row). H3 constructs these by walking a tree's node slots in canonical order;
    this module only defines the shape every axis value must eventually fill.
    """

    node_class: str
    trigger: str
    element: str
    status: str
    channel_family: str
    exclusion_form: str

    def value_for(self, axis: str) -> str:
        mapping = {
            "nodeClass": self.node_class, "trigger": self.trigger, "element": self.element,
            "status": self.status, "channelFamily": self.channel_family,
            "exclusionForm": self.exclusion_form,
        }
        if axis not in mapping:
            raise KeyError(f"{axis!r} is not one of {AXES}")
        return mapping[axis]


# ---------------------------------------------------------------------------------------------
# solid-enforcement `retire-atk` (owner ruling 2026-09-18: "my design don't have atk, it only have
# power and defense, seem like atk is adundant need to retire") — R5's own closed successor map.
#
# `progression.bonus.atk` is retired everywhere else in the stack (`DerivedStatChannels.Retired`,
# `AptitudeTuning.Parse` drops the edge, `aptitudes.v9` no longer names it). The 16 already-accepted
# nodes that named it as their ONLY effect (`quotaCell.channelFamily`) cannot simply drop the axis —
# a node must still grant SOMETHING — so they RE-TARGET to the channel Might/Ferocity already pay
# instead, keeping every other axis (the cell's own `element`, `status`, `trigger`, `exclusionForm`)
# and every LLM-authored field (`name`, `flavor`, `affixIds`, tier, budget) untouched. This is a
# closed vocabulary exactly like `DerivedStatChannels.Retired`: a new entry is a reviewed change, and
# an unlisted `channelFamily` is returned unchanged by `resolve_retired_channel_family` (never a
# refusal here — an unknown value is `permitted()`'s problem, not this map's).
RETIRED_FAMILY_SUCCESSOR: "dict[str, str]" = {"progression.bonus.atk": "combat.power"}


def resolve_retired_channel_family(channel_family: str) -> str:
    """One `channelFamily` value, resolved through `RETIRED_FAMILY_SUCCESSOR` — identity for any
    value not in the map (the overwhelming majority; only ever a no-op past the 16 nodes this was
    written for)."""
    return RETIRED_FAMILY_SUCCESSOR.get(channel_family, channel_family)


def resolve_retired_quota_cell(cell: "Mapping[str, str]") -> "dict[str, str]":
    """A persisted, camelCase `quotaCell` dict (the shape `nodegen.emit.quota_cell_to_dict` writes),
    with `channelFamily` alone resolved through `RETIRED_FAMILY_SUCCESSOR`. Every other axis —
    `nodeClass`, `trigger`, `element`, `status`, `exclusionForm` — is copied verbatim: the successor
    map re-targets the ONE axis a design ruling retired, never anything else about the cell. Returns
    a NEW dict; `cell` itself is never mutated. A no-op when `channelFamily` is not retired (returns
    an equal, but still new, dict) — the caller (`migrate_retired_atk.find_retired_quota_cells`)
    is what decides whether anything actually changed."""
    return {**dict(cell), "channelFamily": resolve_retired_channel_family(cell.get("channelFamily", ""))}


def uniform_weights_milli(members: "Sequence[str]") -> "dict[str, int]":
    """`weightScheme: "uniform"` (`passive-tree-targets.v2.json`'s own four uniform-scheme axes —
    trigger, element, status, channelFamily): an even per-mille split over `members`, summing to
    exactly 1000. Built with the SAME largest-remainder discipline as the weighted axes, over a
    trivial all-equal weight vector, so a caller never has to special-case "uniform" as a different
    kind of arithmetic from "weighted".
    """
    if not members:
        raise ValueError("uniform_weights_milli: at least one member is required")
    n = len(members)
    # Every member gets floor(1000/n) permille, the largest-remainder residual breaking on the
    # caller's own declared order — this IS largest_remainder_count with an all-equal input,
    # spelled out rather than reused, because that function's own contract requires its input to
    # already sum to 1000 and this is the step that produces such an input in the first place.
    base = 1000 // n
    residual = 1000 - base * n
    weights = {m: base for m in members}
    for m in members[:residual]:
        weights[m] += 1
    return weights


def axis_marginals(weights_milli: "Mapping[str, int]", order: "Sequence[str]", total: int,
                   ) -> "dict[str, int]":
    """§4.2 step 2, one axis: exact integer marginals summing to `total`. A thin, named wrapper over
    the shared primitive so every caller in this package spells the same call the same way."""
    return largest_remainder_count(weights_milli, order, total)


def permitted(axis: str, cell: "Mapping[str, str]", vocab_ids: "Mapping[str, tuple[str, ...]]",
             tag_of: "Mapping[str, Mapping[str, str]]") -> "list[str]":
    """The spec's own Code style section, reproduced with this module's names: `cell`'s value on
    `axis`, narrowed to the ids of `axis` whose tag equals it. **This list IS the schema `enum`**,
    so an out-of-quota value is UNSAMPLEABLE rather than rejected afterwards (§4.2 step 6).

    `vocab_ids[axis]` is the full ordered id list for that axis; `tag_of[axis][id]` is that id's
    value on the axis (e.g. `tag_of["element"]["fire"] == "fire"` for a single-valued axis, or a
    many-valued axis's own tag lookup for one whose members carry more than one label — H3 supplies
    both, sourced from `plan_read`'s `property_vocabulary` and `vocab`'s affix corpus.) An empty
    result is HELD, never widened: "an id that left the corpus cannot be printed, and one that
    joined it needs no edit here."
    """
    if axis not in cell:
        raise KeyError(f"cell has no value for axis {axis!r}: {cell!r}")
    wanted = cell[axis]
    ids = [i for i in vocab_ids.get(axis, ()) if tag_of.get(axis, {}).get(i) == wanted]
    if not ids:
        raise UnsatisfiableCell(f"{axis}={wanted!r} in cell {cell!r}: no id satisfies this cell — held")
    return ids


# ---------------------------------------------------------------------------------------------
# task H3 — §4.2 steps 4-5 / §8 steps 4-5: the per-slot cell walk, hard-constraint overrides and
# the return-to-pool rebalance, plus the plan-facing wiring (`quota_for_plan`,
# `permitted_ids_for_cell`) that reads a real `plan_read.TreePlan` rather than hand-built axis
# tables.
# ---------------------------------------------------------------------------------------------

def axis_members(axis: str, property_vocabulary: "Mapping[str, Sequence[str]]") -> "tuple[str, ...]":
    """One axis's own member list, read off a plan's `propertyVocabulary` — never a second roster
    read, and never a hardcoded count (`AXIS_PROPERTY_VOCAB_KEY` maps this axis's name to the key
    it is actually filed under). `trigger` additionally drops the two non-authorable triggers
    (`NON_AUTHORABLE_TRIGGERS`) so neither a quota target nor a permitted subset ever offers one."""
    key = AXIS_PROPERTY_VOCAB_KEY[axis]
    if key not in property_vocabulary:
        raise KeyError(
            f"propertyVocabulary has no {key!r} entry for axis {axis!r} — this stage refuses to "
            f"synthesise a member list, the same rule it applies to the vocabulary as a whole")
    members = tuple(property_vocabulary[key])
    if axis == "trigger":
        members = tuple(m for m in members if m not in NON_AUTHORABLE_TRIGGERS)
    if not members:
        raise ValueError(f"axis {axis!r} (propertyVocabulary.{key}) has no authorable members")
    return members


def axis_order(axis: str, targets: object, members: "Sequence[str]") -> "tuple[str, ...]":
    """The declared ORDER `axis_marginals`/`expand_counts` tie-break and flatten against.
    `nodeClass`/`exclusionForm` carry an explicit `_order` in the targets file (both are small,
    named enums where an author-chosen order is meaningful); the four uniform-scheme axes have no
    such array by design (`passive-tree-targets.v2.json`'s own `_note`: "a roster addition changes
    the grid by construction with no edit here"), so their order is simply the plan's own
    `propertyVocabulary` listing, unmodified — a total order that exists regardless of scheme.
    """
    if axis == "nodeClass":
        return tuple(targets.node_class_order)
    if axis == "exclusionForm":
        return tuple(targets.exclusion_form_order)
    return tuple(members)


def axis_weights_milli(axis: str, targets: object, members: "Sequence[str]") -> "dict[str, int]":
    """One axis's ‰ weights: the two explicitly-weighted axes (`nodeClass`, `exclusionForm`) read
    their declared `weightsMilli`/`_order` straight off `targets` (mismatched membership is refused
    here rather than silently zip-truncated); the four `weightScheme: "uniform"` axes get an even
    split over their OWN real member count via `uniform_weights_milli` — never a number the targets
    file would have had to keep in sync with a roster it does not own."""
    if axis == "nodeClass":
        order, weights = targets.node_class_order, targets.node_class_weights_milli
        if set(order) != set(members):
            raise ValueError(
                f"quotas.nodeClass._order {order!r} does not match the plan's own nodeClass "
                f"members {members!r}")
        return dict(zip(order, weights))
    if axis == "exclusionForm":
        order, weights = targets.exclusion_form_order, targets.exclusion_form_weights_milli
        if set(order) != set(members):
            raise ValueError(
                f"quotas.exclusionForm._order {order!r} does not match the plan's own "
                f"exclusionForm members {members!r}")
        return dict(zip(order, weights))
    return uniform_weights_milli(members)


@dataclass(frozen=True)
class QuotaSlot:
    """One node's own identity for the §4.2/§8 per-slot walk: `node_id` addresses it, `forced` is
    the (possibly empty) map of axis -> HARD-forced value this slot never draws for. Built by
    `build_slot`, consumed by `assign_quota_cells` — a caller never hand-assembles `forced` itself,
    so the "which axes are ever forced, and under which category" rule lives in exactly one place.
    """

    node_id: str
    forced: "Mapping[str, str]"


def build_slot(node: object, *, category: str, forced_element: "str | None" = None,
              forced_status: "str | None" = None) -> QuotaSlot:
    """§8 step 4's own two category overrides, plus the universal `nodeClass` override B1's own
    archetype ramp already decided (§2.1 of this module's docstring). `node` is a
    `plan_read.TreePlanNode` (typed as `object` here to avoid an import cycle with `plan_read`,
    which does not need to know this module exists); only `.node_id` and `.node_class` are read.

    Task J8 (2026-09-07): `elif` -> two independent `if`s. A species tree forces BOTH `element`
    AND `status` from its own mechanical-favour lock simultaneously (spec-species-tree.md §3/§4) —
    a real, different shape from elemental/status trees, which force exactly ONE of the two. The
    original `if category == "elemental": ... elif category == "status": ...` could never express
    "both," and silently forced NEITHER for any other category (including `"species"`, which did
    not exist as shipped content when this was first written) — found while wiring `TreeSpec.
    mechanical_favour` through `build_plan` and checking this function's own body before assuming
    the forced values it now derives would actually reach the quota; they would not have, without
    this fix. `category in (..., "species")` on BOTH branches, not a third `elif`, is what lets a
    species tree hit both without becoming a third, incompatible shape.
    """
    forced: "dict[str, str]" = {"nodeClass": node.node_class}
    if category in ("elemental", "species"):
        if not forced_element:
            raise ValueError(f"build_slot: a {category} tree's forced_element must be given")
        forced["element"] = forced_element
    if category in ("status", "species"):
        if not forced_status:
            raise ValueError(f"build_slot: a {category} tree's forced_status must be given")
        forced["status"] = forced_status
    return QuotaSlot(node_id=node.node_id, forced=forced)


def tally_forced(slots: "Sequence[QuotaSlot]") -> "dict[str, dict[str, int]]":
    """Pass one of the two-pass walk: how many slots hard-force each axis to each value, before
    any free draw is handed out. `{axis: {}}` for every axis even when nothing forces it, so
    `rebalance_axis` never has to special-case a missing key."""
    tally: "dict[str, dict[str, int]]" = {axis: {} for axis in AXES}
    for slot in slots:
        for axis, value in slot.forced.items():
            tally[axis][value] = tally[axis].get(value, 0) + 1
    return tally


def rebalance_axis(quota_for_axis: "Mapping[str, int]", forced_for_axis: "Mapping[str, int]",
                   ) -> "dict[str, int]":
    """§4.2 step 5, one axis: "a slot whose draw was overridden returns its drawn value to the
    pool, and the pool is re-apportioned over the REMAINING slots."

    The residual is a SUBTRACTION, not a second `largest_remainder_count` pass: `quota_for_axis`
    was computed via `axis_marginals` over the SAME total `N` that includes the forced slots
    (`Σ quota_for_axis.values() == N` by that function's own contract), so
    `Σ (quota[v] - forced[v]) == N - Σ forced[v]`, which is EXACTLY the number of free slots left to
    hand values out to — an identity, not an approximation, and it holds regardless of how the
    forced counts are distributed across values.

    Refuses (`OverdrawnQuota`), never clamps or borrows from another value, when a forced value's
    own demand exceeds what the corpus-wide quota ever allocated it, or when a forced value is not
    even one of this axis's declared members — both mean the targets file (or the roster it was
    built from) did not anticipate the real slot count, which is a calibration defect the run must
    surface (H3's own acceptance bullet), not paper over.
    """
    for value in forced_for_axis:
        if value not in quota_for_axis:
            raise OverdrawnQuota(
                f"{forced_for_axis[value]} slot(s) are hard-forced to {value!r}, which this "
                f"axis's quota does not name at all among {sorted(quota_for_axis)} — the targets "
                f"file (or the roster it was built from) is missing it")
    residual: "dict[str, int]" = {}
    for value, quota_count in quota_for_axis.items():
        forced_count = forced_for_axis.get(value, 0)
        if forced_count > quota_count:
            raise OverdrawnQuota(
                f"{value!r} is hard-forced on {forced_count} slot(s) but the corpus-wide quota "
                f"only allocated it {quota_count} — refused, never silently rebalanced onto "
                f"another value")
        residual[value] = quota_count - forced_count
    return residual


def assign_quota_cells(slots: "Sequence[QuotaSlot]", quota: "Mapping[str, Mapping[str, int]]",
                       order: "Mapping[str, Sequence[str]]") -> "dict[str, QuotaCell]":
    """§4.2 steps 4-5 / §8 steps 4-5: every slot in `slots` (the caller's own canonical
    (tree, branch, tier, index) walk — this function never sorts) gets a `QuotaCell` whose value on
    each axis is either its own hard-forced one, or the next free draw off that axis's rebalanced
    residual sequence.

    Two passes, because the residual sequence for a free axis cannot be built until every slot's
    forced values are known: pass one (`tally_forced`) counts what is forced, `rebalance_axis` turns
    each axis's corpus-wide `quota` into the residual owed to the free slots, `expand_counts`
    flattens that residual into a sequence exactly as long as the number of free slots for that
    axis, and pass two hands that sequence out in the caller's own canonical order — a defensive
    `OverdrawnQuota` fires if a sequence ever runs out before the slots do (it should never happen
    once `rebalance_axis` has already proven the counts match; kept as a named, loud failure rather
    than an `IndexError` two frames away if that invariant is ever violated by a caller).
    """
    forced_tally = tally_forced(slots)
    free_sequence: "dict[str, list[str]]" = {}
    for axis in AXES:
        residual = rebalance_axis(quota.get(axis, {}), forced_tally.get(axis, {}))
        free_sequence[axis] = expand_counts(residual, order[axis])

    cursor = {axis: 0 for axis in AXES}
    cells: "dict[str, QuotaCell]" = {}
    for slot in slots:
        values: "dict[str, str]" = {}
        for axis in AXES:
            if axis in slot.forced:
                values[axis] = slot.forced[axis]
                continue
            seq = free_sequence[axis]
            if cursor[axis] >= len(seq):
                raise OverdrawnQuota(
                    f"axis {axis!r} ran out of free draws before slot {slot.node_id!r} — the "
                    f"corpus-wide quota and the real free-slot count have drifted apart")
            values[axis] = seq[cursor[axis]]
            cursor[axis] += 1
        cells[slot.node_id] = QuotaCell(
            node_class=values["nodeClass"], trigger=values["trigger"], element=values["element"],
            status=values["status"], channel_family=values["channelFamily"],
            exclusion_form=values["exclusionForm"],
        )
    return cells


def quota_for_plan(plan: object, targets: object, *, category: str,
                   forced_element: "str | None" = None, forced_status: "str | None" = None,
                   ) -> "dict[str, QuotaCell]":
    """The plan-facing convenience wrapper: one committed tree's own `QuotaCell` per node.

    `plan` is a `plan_read.TreePlan` (typed `object` to avoid a `plan_read` import cycle — this
    module is lower-level than `plan_read`, the same layering `permitted`'s own docstring already
    assumes). `total = len(plan.nodes)` is read off the plan itself, never hardcoded to 1,560:
    correct today, when the real committed corpus is one 40-node tree (`might`), and correct once
    the full 39-tree/1,560-node corpus lands, because nothing here assumes a specific tree count.

    Every axis's member list comes from `plan.property_vocabulary` (B1's own fresh count off the
    real mirrors — `axis_members`); every axis's weights come from `targets` (`axis_weights_milli`)
    — **except an axis this tree forces on EVERY slot**, found real (2026-09-06, generalizing plan
    emission past `might`) and generalized past its first instance the same day (an adversarial spec
    audit, not a second real crash — see below). `nodeClass` is never drawn from a free pool at all
    for ANY tree (`build_slot` forces it on every slot, unconditionally); `element`/`status` are
    forced on every slot **only for an elemental/status category tree** (`build_slot`'s own two
    category overrides), never for a primary/family/species tree. In either case, a flat,
    tree-oblivious `targets` weight (`node_class_weights_milli`, or a uniform per-element/per-status
    split) can never match a specific tree's own 100%-forced distribution unless that distribution
    happens to equal the flat target by coincidence — confirmed live for `nodeClass`
    (`quota_for_plan("fortitude"/"agility"/"focus"/"precision", ...)` raised `OverdrawnQuota` the
    moment a second, non-`broad-and-flat` primary tree's plan was generated for real: two of the
    three shipped archetypes split mechanism/magnitude 16/24 or 24/16, not `might`'s own 20/20) and
    reproduced by direct construction for `element` (a synthetic elemental-category plan forcing all
    40 slots to `"fire"` against the real `might`-shaped plan/targets: `OverdrawnQuota — 'fire' is
    hard-forced on 40 slot(s) but the corpus-wide quota only allocated it 6`, since the flat
    per-element weight assumes an even ~1/7 split, never "this whole tree is one element"). Neither
    of the two real 40-slot-of-40 forced counts (`nodeClass` always; `element`/`status` for their own
    category) is drawable from any single-tree-scoped flat weight, so the general rule replaces the
    `nodeClass`-only special case: **whenever an axis's `tally_forced` sums to the WHOLE tree
    (`total`), that tally IS the quota, read back rather than independently computed** — this covers
    `nodeClass` (always true) and `element`/`status` (true only when this tree's own `category`
    triggers the override) with one rule, and changes nothing for the three axes (`trigger`,
    `channelFamily`, `exclusionForm`) that are never forced at all, nor for a primary tree's own
    `element`/`status` (0% forced there, so the sum-check is false and the original weighted-target
    path runs exactly as before).
    """
    total = len(plan.nodes)
    slots = [
        build_slot(node, category=category, forced_element=forced_element,
                  forced_status=forced_status)
        for node in plan.nodes
    ]
    forced_tally = tally_forced(slots)

    # 2026-09-11, the exclusionForm axis's own DOMAIN defect (found by re-reading the whole chain
    # against spec-tree-language.md §4.2 + §5 while closing the audit's A2/C todos): the axis's
    # 450/450/100 weights were apportioned over ALL N slots, so ~100% of cells carried a non-none
    # form — while `exclusion.targetShareMilli` (§5's own "~2% of nodes", D14) targets the
    # exclusion RATE and the brief tells the model "most nodes have none". The quota, the brief and
    # the gate disagreed BY CONSTRUCTION, and `PassiveTree/QuotaDrift` could not see it (it compares
    # emitted vs re-derived cells — the same wrong domain both sides, tautologically equal). The
    # corrected domain: `none` vs non-none is apportioned over the WHOLE tree by the target share
    # (spec §4.2 step 2's own arithmetic, applied to the two-valued first split), then the non-none
    # residual is split by the declared 450/450/100 form weights. A cell now says what §5 actually
    # intends: ~98% `none`, a designated ~2% carrying a real rung — which is what makes the cell's
    # own `exclusionForm` enum-narrowing (§4.2 step 6, `schema_for_call`) and the brief's allocation
    # line truthful, and turns QuotaDrift's exclusionForm axis into a REAL check of emitted forms.
    none_member = nodegen_exclusion.NONE_FORM
    exclusion_share_permille = targets.exclusion_target_share_milli
    excluded_total = largest_remainder_count(
        {none_member: 1000 - exclusion_share_permille, "excluded": exclusion_share_permille},
        (none_member, "excluded"), total)["excluded"]

    quota: "dict[str, dict[str, int]]" = {}
    order: "dict[str, tuple[str, ...]]" = {}
    for axis in AXES:
        members = axis_members(axis, plan.property_vocabulary)
        axis_ord = axis_order(axis, targets, members)
        axis_forced = forced_tally.get(axis, {})
        if axis == "exclusionForm":
            # Two-stage apportionment (see the block comment above): the excluded subset's own size
            # first, then the declared rung weights over THAT subset — with `none` holding the rest
            # exactly. `largest_remainder_count` at each stage keeps both splits exact integers
            # summing to their own totals. `none` is NOT in the targets file's `_order` (that
            # array splits the EXCLUDED subset only): it is prepended HERE, once, for the hand-out
            # order, so `expand_counts` hands every `none` cell out BEFORE any rung cell in the
            # canonical slot walk and never meets a quota key its order does not name.
            form_weights = axis_weights_milli(axis, targets, members)
            form_quota = axis_marginals(form_weights, axis_ord, excluded_total)
            quota[axis] = {none_member: total - excluded_total, **form_quota}
            order[axis] = (none_member, *axis_ord)
            continue
        order[axis] = axis_ord
        if sum(axis_forced.values()) == total:
            quota[axis] = {value: axis_forced.get(value, 0) for value in axis_ord}
            continue
        weights = axis_weights_milli(axis, targets, members)
        quota[axis] = axis_marginals(weights, axis_ord, total)
    return assign_quota_cells(slots, quota, order)


def permitted_ids_for_cell(cell: QuotaCell, property_vocabulary: "Mapping[str, Sequence[str]]",
                           ) -> "dict[str, list[str]]":
    """§4.2 step 6 over every axis at once: `permittedIds` is what a plan/brief prints into a
    schema `enum` (§6.3), and every one of these six axes is a FLAT roster — element, status,
    channelFamily, exclusionForm and nodeClass ids double as their own single tag, so narrowing to
    "the ids whose tag equals the cell's value" collapses to "the cell's own value, alone" for all
    but the degenerate case of an id that is not even in the vocabulary (`permitted` still raises
    `UnsatisfiableCell` for that, exactly as it does for any other axis).

    2026-09-11 (A2): `exclusionForm` now also allocates `none` (the two-stage apportionment's
    ~98% majority), and `none` is deliberately NOT a `propertyVocabulary.exclusionForm` member —
    that roster splits the EXCLUDED subset only. A `none` cell therefore short-circuits to
    `[NONE_FORM]` rather than being handed to `permitted`, whose "no id satisfies this cell" hold
    exists for ids a real roster could name; `none` is the schema enum's own default, defined once
    in `nodegen.exclusion`, and a designated cell is returned untouched (the rung itself).
    """
    result: "dict[str, list[str]]" = {}
    for axis in AXES:
        if axis == "exclusionForm":
            cell_form = cell.value_for(axis)
            if cell_form == nodegen_exclusion.NONE_FORM:
                result[axis] = [nodegen_exclusion.NONE_FORM]
                continue
        members = axis_members(axis, property_vocabulary)
        vocab_ids = {axis: members}
        tag_of = {axis: {m: m for m in members}}
        result[axis] = permitted(axis, {axis: cell.value_for(axis)}, vocab_ids, tag_of)
    return result
