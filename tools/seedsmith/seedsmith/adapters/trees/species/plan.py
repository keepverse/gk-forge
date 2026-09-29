"""seedsmith.adapters.trees.species.plan — the mechanical-favour lock (task J5,
spec-species-tree.md §3, §4). Pure, deterministic, model-free: no model call, no file I/O, matching
`adapters.actions.distribution_planner.derive`'s own style (the spec's own Code style section names
that module as the mould).

**D17's lock, and why it needs its own arithmetic rather than reusing `nodegen.quota`'s six axes.**
`nodegen.quota` apportions ONE tree's own 40 nodes across six per-tree content axes (nodeClass,
trigger, element, status, channelFamily, exclusionForm) — a different question from the one here,
which apportions the WHOLE 904-species corpus across the cross product of THREE axes (aptitude,
element, status) that together form a species' mechanical-favour LOCK. `element` and `status` are
axis NAMES that exist in both places for unrelated reasons — a species tree's own node-level element
quota (which element a given node's atom is tagged with) has nothing to do with which element that
species' WHOLE TREE mechanically favours — so nothing here imports `nodegen.quota`'s axis machinery,
to avoid conflating the two.

**`legitimateSkew` (D32) is generic and, as of this module, has its first real consumer.**
`adapters.trees.targets.PassiveTreeTargets.legitimate_skew_rows` already parses and validates
`gk-core/data/tuning/passive-tree-targets.v2.json`'s `legitimateSkew.rows` (checked directly: shipped empty,
`[]`, as of 2026-09-07) — nothing in the repo has ever read a non-empty one. A row's `axis` is a free
string, so the SAME mechanism the quotas file already ships doubles as this module's own "earth may
run to roughly 1.5× uniform" declaration point (§3.2), keyed `axis: "aptitude" | "element" | "status"`
— no new tuning-file schema, no `publish.py` rebalance, needed for D32's target to be expressible.

**Why `weightsMilli` is DERIVED here rather than read as a literal JSON table** (the spec's own §
Code style block writes `targets["mechanicalFavour"]["weightsMilli"]` as if it already exists): the
joint space is 12 aptitudes × 6 elements × 24 statuses = 1,728 cells. Hand-authoring 1,728 per-mille
numbers summing to exactly 1000 is not a balance surface a person edits — it is a MECHANICAL
consequence of three small, real numbers a person WOULD edit: each axis's own near-uniform weights
(`uniform` by default, the same as `nodegen.quota`'s own four uniform-scheme axes) plus whichever
`legitimateSkew` rows exist. `mechanical_favour_weights_milli` computes the 1,728-cell table from
those three axis tables at call time, and IS the concrete, inspectable artifact the spec's pseudocode
refers to — just derived, not hand-typed, matching this repo's own "no axis lists its own members in
a tuning file" rule (`plan/vocabulary.py`'s module docstring) extended to this axis triple too.

This module also departs from the spec's own illustrative `targets: Mapping[str, Any]` parameter
type in favour of the REAL, already-shipped `PassiveTreeTargets` (a loaded, validated dataclass) —
matching `nodegen.quota.axis_weights_milli`'s own real signature, not the spec's loose shorthand —
so the mechanical-favour weights are derived from the SAME typed, "a missing key raises" object every
other tree quota already reads, rather than a second raw-dict view of the same file.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from ...actions.distribution_planner.derive import largest_remainder_count
from ..plan.vocabulary import BRANCH
from ..plan.vocabulary import load_roster as load_axis_roster
from ..targets import PassiveTreeTargets, SkewRow

_LONG_MAX = 9_223_372_036_854_775_807
_LONG_MIN = -9_223_372_036_854_775_808


def _widen_mul(a: int, b: int) -> int:
    """docs/architecture/numeric-types.md's numeric-overflow rule 3, as an explicit stand-in — Python ints never actually
    overflow, but every sibling module in this program keeps its own private copy of this guard
    rather than importing one (`metrics/passive_tree.py`'s own docstring states this convention)."""
    product = int(a) * int(b)
    if product > _LONG_MAX or product < _LONG_MIN:
        raise OverflowError(f"_widen_mul({a}, {b}) = {product} does not fit a long")
    return product


AXES: "tuple[str, ...]" = ("aptitude", "element", "status")


class FavourPlanError(ValueError):
    """A favour-lock computation could not proceed as declared — refused, never silently rebalanced
    or defaulted (spec-species-tree.md §3.1: *"nothing here mutates the draft into legality"*)."""


@dataclass(frozen=True)
class FavourCell:
    aptitude: str
    element: str
    status: str

    def key(self) -> str:
        return f"{self.aptitude}|{self.element}|{self.status}"


@dataclass(frozen=True)
class FavourAssignment:
    species_id: str
    cell: FavourCell
    #: 2–3 alternates (fewer only if the cell space itself is too small to offer that many — never
    #: true at the real 1,728-cell scale), every one of them a cell this run's own quota allocated
    #: at least one slot to (the 166× fix: no answer the later model-call stage can give is capable
    #: of landing outside the declared target, because nothing outside the quota is ever offered).
    alternates: "tuple[FavourCell, ...]"


def _skewed_weights_milli(members: "Sequence[str]", skew_rows: "Sequence[SkewRow]") -> "dict[str, int]":
    """One axis's own per-mille weights, summing to exactly 1000. `skew_rows` (already filtered to
    this axis) FIX their named member's weight; every other member on the axis splits what remains
    evenly, largest-remainder — the same "a forced value returns nothing to widen, the remainder
    covers what's left" shape `assign_favour_cells`'s own cell-forcing rebalance uses one layer up
    (§3.1's own line: *"skip it and the forced species consume their quota twice"* — here it is an
    axis WEIGHT being forced rather than a species' own cell, but an unaccounted-for fixed draw is
    the identical defect). No skew rows at all (today's shipped state) is exactly `weightScheme:
    "uniform"` — every member gets an even split, nothing forced.
    """
    fixed = {row.member: row.weight_milli for row in skew_rows}
    unknown = sorted(set(fixed) - set(members))
    if unknown:
        raise FavourPlanError(
            f"legitimateSkew names {unknown} — not a member of {list(members)!r}")
    fixed_total = sum(fixed.values())
    if fixed_total > 1000:
        raise FavourPlanError(
            f"legitimateSkew rows for {sorted(fixed)} overdraw the axis: {fixed_total}‰ > 1000‰")
    free = [m for m in members if m not in fixed]
    remaining = 1000 - fixed_total
    weights = dict(fixed)
    if not free:
        if remaining != 0:
            raise FavourPlanError(
                f"legitimateSkew rows leave {remaining}‰ unassigned with no free members left")
        return weights
    base = remaining // len(free)
    residual = remaining - base * len(free)
    for m in free:
        weights[m] = base
    for m in free[:residual]:
        weights[m] += 1
    return weights


def _cell_order(aptitudes: "Sequence[str]", elements: "Sequence[str]",
               statuses: "Sequence[str]") -> "tuple[FavourCell, ...]":
    """The declared cross-product order — aptitude-major, then element, then status, each in its
    own roster's declared order — never a dict's own iteration order. Every tie-break in this module
    (the joint weight table, the pool-to-species pairing) resolves against THIS one order."""
    return tuple(FavourCell(a, e, s) for a in aptitudes for e in elements for s in statuses)


def _joint_weights_milli(cells: "Sequence[FavourCell]", apt_w: "Mapping[str, int]",
                         elem_w: "Mapping[str, int]", stat_w: "Mapping[str, int]") -> "dict[str, int]":
    """The 1,728-cell (today's real axis sizes) per-mille table `assign_favour_cells` feeds to
    `largest_remainder_count`, built from three independent per-mille axis tables (each already
    summing to 1000) in ONE largest-remainder pass.

    This is deliberately NOT a second call to `largest_remainder_count`: a cell's raw joint weight
    is the PRODUCT of three per-mille numbers, so the full cross product sums to `1000**3`, not
    1000 — exactly the precondition mismatch `nodegen.quota.uniform_weights_milli`'s own docstring
    already names for its own, simpler case ("this function's own contract requires its input to
    already sum to 1000 and this is the step that produces such an input in the first place").
    Widened before dividing, divided exactly once, at the end, per docs/architecture/numeric-types.md rule 3/4.
    """
    order_keys = [c.key() for c in cells]
    raw = {c.key(): apt_w[c.aptitude] * elem_w[c.element] * stat_w[c.status] for c in cells}
    raw_total = 1000 * 1000 * 1000
    scaled = {k: _widen_mul(raw[k], 1000) for k in order_keys}
    floor = {k: scaled[k] // raw_total for k in order_keys}
    remainder = 1000 - sum(floor.values())
    if not (0 <= remainder <= len(order_keys)):
        raise FavourPlanError(
            f"mechanical-favour weight table failed to normalize to 1000 (remainder={remainder})")
    fracs = sorted(order_keys, key=lambda k: (-(scaled[k] % raw_total), order_keys.index(k)))
    out = dict(floor)
    for k in fracs[:remainder]:
        out[k] += 1
    return out


def axis_weight_tables(targets: PassiveTreeTargets, *, seed_root: "Path | None" = None,
                       ) -> "dict[str, dict[str, int]]":
    """The three independent per-mille axis tables (`aptitude`/`element`/`status`, each summing to
    1000) BEFORE they are combined into the joint cell table. Exposed on its own — not just inlined
    into `mechanical_favour_weights_milli` — because a per-axis MARGINAL target share is exactly one
    of these tables' own values (independent-factor marginalization needs no re-aggregation of the
    1,728-cell joint table, which would otherwise compound one more rounding step onto an already
    -quantized number). `FavourDriftMetric` (`metrics/passive_tree.py`) is the real caller this
    exists for.
    """
    axis_roster = load_axis_roster(seed_root)
    skew_by_axis: "dict[str, list[SkewRow]]" = {axis: [] for axis in AXES}
    for row in targets.legitimate_skew_rows:
        if row.axis in skew_by_axis:
            skew_by_axis[row.axis].append(row)
    return {
        "aptitude": _skewed_weights_milli(axis_roster.aptitudes, skew_by_axis["aptitude"]),
        "element": _skewed_weights_milli(axis_roster.elements, skew_by_axis["element"]),
        "status": _skewed_weights_milli(axis_roster.statuses, skew_by_axis["status"]),
    }


def mechanical_favour_weights_milli(
        targets: PassiveTreeTargets, *, seed_root: "Path | None" = None,
) -> "tuple[tuple[FavourCell, ...], dict[str, int]]":
    """The declared cell order plus its per-mille weight table — the concrete, inspectable artifact
    D32/§3.2 calls for ("the judgement gets argued once, in a file"), derived from the roster
    mirrors and `targets.legitimate_skew_rows` rather than hand-typed (module docstring)."""
    axis_roster = load_axis_roster(seed_root)
    axis_weights = axis_weight_tables(targets, seed_root=seed_root)
    cells = _cell_order(axis_roster.aptitudes, axis_roster.elements, axis_roster.statuses)
    weights_milli = _joint_weights_milli(
        cells, axis_weights["aptitude"], axis_weights["element"], axis_weights["status"])
    return cells, weights_milli


def _seed_int(key: str) -> int:
    """`blake2b(key, digest_size=8)` — the same construction `adapters.creatures.anchor.permute.py`'s
    own `_seed_int` uses (there, seeded per-field-per-sample; here, seeded per-species), so a species'
    own rank among its peers depends on ITS id alone, never on its position in the caller's list."""
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def _pick_alternates(species_id: str, candidates: "Sequence[str]", count: int) -> "list[str]":
    rng = random.Random(_seed_int(species_id))
    n = min(count, len(candidates))
    return rng.sample(list(candidates), n)


def assign_favour_cells(
        species_ids: "Sequence[str]", targets: PassiveTreeTargets,
        forced: "Mapping[str, FavourCell] | None" = None, *, alternates_count: int = 3,
        seed_root: "Path | None" = None) -> "dict[str, FavourAssignment]":
    """One mechanical-favour cell per species, plus 2–3 alternates from the SAME quota
    (spec-species-tree.md §3.1 steps 1–2, §4). `forced` holds species whose cell is fixed by a hard
    constraint; a forced species' drawn value returns to the pool and the remainder is re-apportioned
    over the free species — skip that and the forced species consume their quota twice, once by
    force and once by draw, and the residual species inherit the deficit (§3.1's own named defect).

    Deterministic: each free species' RANK (never its position in `species_ids`) is seeded from its
    own id, so re-running over the SAME roster in a different order reassigns nothing — every species
    lands on the identical cell and alternates regardless of `species_ids`' own ordering. Growing the
    roster is a DIFFERENT operation and makes no such promise: the quota itself is a function of
    `len(species_ids)`, recomputed fresh every call (the same discipline every other caller of
    `largest_remainder_count` in this codebase follows), so a wider total can legitimately shift
    several cells' own floor/remainder split, not just add one unit somewhere. Nothing in this
    module claims incremental stability across a roster-SIZE change — that property is real
    elsewhere in this spec (§5.3 rule 3's marked-node prefix order) but not here, and a caller that
    needs it must not assume this function provides it.
    """
    forced = dict(forced or {})
    cells, weights_milli = mechanical_favour_weights_milli(targets, seed_root=seed_root)
    order = [c.key() for c in cells]
    cell_by_key = {c.key(): c for c in cells}

    quota = largest_remainder_count(weights_milli, order, len(species_ids))

    for species_id, cell in forced.items():
        key = cell.key()
        if key not in cell_by_key:
            raise FavourPlanError(f"{species_id}: forced cell {key} is not a real mechanical-favour cell")
        quota[key] -= 1
        if quota[key] < 0:
            raise FavourPlanError(
                f"{species_id}: forced cell {key} overdraws its quota — refused, not rebalanced silently")

    free_species = [s for s in species_ids if s not in forced]
    pool: "list[str]" = []
    for key in sorted(order, key=lambda k: (-quota[k], order.index(k))):
        pool.extend([key] * quota[key])
    if len(pool) != len(free_species):
        raise FavourPlanError(
            f"favour quota totals {len(pool)} but there are {len(free_species)} free species to place "
            f"— this is an internal invariant break, not a caller error")

    quota_having_keys = [k for k in order if quota[k] > 0]

    assignments: "dict[str, FavourAssignment]" = {}
    for species_id, cell in forced.items():
        candidates = [k for k in quota_having_keys if k != cell.key()]
        alt_keys = _pick_alternates(species_id, candidates, alternates_count)
        assignments[species_id] = FavourAssignment(
            species_id=species_id, cell=cell, alternates=tuple(cell_by_key[k] for k in alt_keys))

    # Rank, don't position: which free species lands on which pool slot depends on each species'
    # own hash rank among its peers, never on where it sits in the caller's `species_ids` list.
    ranked_species = sorted(free_species, key=lambda sid: (_seed_int(sid), sid))
    for species_id, key in zip(ranked_species, pool):
        cell = cell_by_key[key]
        candidates = [k for k in quota_having_keys if k != key]
        alt_keys = _pick_alternates(species_id, candidates, alternates_count)
        assignments[species_id] = FavourAssignment(
            species_id=species_id, cell=cell, alternates=tuple(cell_by_key[k] for k in alt_keys))
    return assignments


def mark_species_unique_nodes(nodes: "Sequence[Mapping[str, object]]", k: int) -> "frozenset[str]":
    """Task J6, spec-species-tree.md §5.3 rule 3: the `k` node ids that will carry a species
    -namespace affix — the **deepest MECHANISM nodes**, deepest tier first, ties broken on branch
    order (`plan.vocabulary.BRANCH`, never alphabetical or dict order) then `nodeKey`. Planner-owned
    and deterministic, never a generation-time choice: `nodes` is a tree's own already-committed
    node list (each a mapping carrying at least `id`/`tier`/`branch`/`nodeClass`/`nodeKey` — the
    exact shape `nodegen.emit.NodeSeedRecord.to_dict` already produces for every tree, species
    included, since §1's own table states species trees reuse the generic node record verbatim).

    **Why this is a real, checked PREFIX property, not merely a sort:** this selects from a single
    FIXED total order over the tree's mechanism nodes (deepest tier, then branch, then nodeKey) —
    the same list, sorted once, sliced by `k`. Two different `k` values therefore never disagree
    about a node once both include it: raising `k` only ever ADDS nodes at the shallow end and never
    re-orders, renames, or drops one already marked (`raising_species_unique_affix_min_never_
    unmarks_a_marked_node`, proven by test as a real subset relationship, not assumed from the
    sort's own stability).

    `k = 0` is legal (spec §5.3 rule 2) and returns an empty set without error — U1/U2 still gate on
    an empty species-namespace requirement; only U3's own-namespace clause has nothing to report.
    """
    if k < 0:
        raise FavourPlanError(f"mark_species_unique_nodes: k must be >= 0, got {k}")
    branch_rank = {b: i for i, b in enumerate(BRANCH)}
    mechanism = [n for n in nodes if n.get("nodeClass") == "mechanism"]
    ordered = sorted(mechanism, key=lambda n: (
        -int(n["tier"]), branch_rank.get(n["branch"], len(BRANCH)), n["nodeKey"]))
    return frozenset(n["id"] for n in ordered[:k])
