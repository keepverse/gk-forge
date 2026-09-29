"""seedsmith.adapters.actions.type_weights.derive — spec-type-weights.md §3's seven steps.

Reads ONLY `gk-data/packs/fusion/data/seed/actions/_generated/role-lean.json`'s already-derived fields
(`leanOrder`/`leanSource`/`separation`/`family`/`element`/`signals`) — never A-S0's own raw inputs
(the catalog, the anchor tree, motif/family-assignments), matching spec §2's Reads table exactly.
`RoleLeanRow` below is this module's own narrow view of one role-lean.json entry; the parser that
builds it lives in `generate_type_weights.py`, the one file in this feature that touches disk.

**F12, restated as code rather than prose** (spec §3 step 1, §6's binding correction): the uniform
floor applies *only* when `lean_source == "floor"` — a genuine five-way score tie A-S0 itself
detected — never merely because a species carries no family. `derived-nofloor` (a family-less
species with a real, differentiated `leanOrder`) is handled by the exact same branch as `derived`
below; there is no third code path for it, which is itself the proof this module never re-opens
F12 by inventing a family-null special case of its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..characteristic_pool.derive import CATEGORIES, rank_categories
from .tuning import ELEMENTS, TypeWeights

__all__ = [
    "RoleLeanRow", "TypeWeightEntry", "raw_category_scores", "largest_remainder_milli",
    "category_milli_for", "target_shape_for", "element_bias_for", "family_element_bias_inputs",
    "derive_all",
]

# The repo-wide `long` bound (docs/architecture/numeric-types.md's numeric-overflow table) — Python ints never actually
# overflow, so this is an EXPLICIT check, not a language guarantee: a magnitude this module ever
# produces must fit the same `long` every C# consumer will eventually read it as, and a value that
# would not throws here rather than silently round-tripping through a JSON number no real `long`
# could hold.
_LONG_MAX = 9_223_372_036_854_775_807
_LONG_MIN = -9_223_372_036_854_775_808


def _widen_mul(a: int, b: int) -> int:
    """`(long)a * b`, never `(long)(a * b)` — the cast/check happens on the OPERANDS widened to
    `long` before multiplying, never on a result that may already have overflowed a narrower type.
    Raises `OverflowError` (naming both operands) rather than wrapping when the product would not
    fit a `long` (docs/architecture/numeric-types.md rule 5: "Overflow throws, never wraps")."""
    a = int(a)
    b = int(b)
    product = a * b
    if product > _LONG_MAX or product < _LONG_MIN:
        raise OverflowError(f"_widen_mul({a}, {b}) = {product} does not fit a long "
                            f"({_LONG_MIN}..{_LONG_MAX})")
    return product


@dataclass(frozen=True)
class RoleLeanRow:
    """One `role-lean.json` entry, narrowed to exactly the fields spec §2 lists this module as
    reading: `leanOrder`, `separation`, `family`, `element`, `leanSource`, plus `reach` (parsed out
    of the entry's own `signals` list — role-lean.json carries no dedicated `reach` field)."""
    species_key: str
    family: "str | None"
    lean_order: "tuple[str, ...]"
    lean_source: str                    # "floor" | "derived" | "derived-nofloor"
    separation: "int | None"
    element_primary: str
    element_secondary: "str | None"
    reach: "str | None"
    families: "tuple[str, ...]" = ()


@dataclass(frozen=True)
class TypeWeightEntry:
    id: str
    scope: str                          # "species" | "family"
    scope_key: str
    category_milli: "dict[str, int]"
    target_mode_milli: "dict[str, int]"
    area_shape_milli: "dict[str, int]"
    element_bias_milli: "dict[str, int]"
    basis: str                          # "derived" | "floor"


# ---------------------------------------------------------------------------------------------
# §3 steps 1-2 — rank to raw score, then separation scaling. The uniform floor (leanSource ==
# "floor") skips separation scaling entirely: it is unconditionally flat, never contingent on
# `separationMilli[0]` happening to tune to 0 — "we have no signal at all" must stay flat under any
# future retune of row 0.
#
# **AC5 fix, 2026-09-03 (owner decision, post-build review).** Spec §3 step 2's literal text says
# `separation: null` "takes the same row as 0" — but the shipped v1 default for row 0 is exactly
# `0` ("collapses the spread to flat", spec §2's own stated reasoning for a genuine tie), and
# sharing that row made every family-less (`derived-nofloor`) species print a flat
# 200/200/200/200/200 vector under the real shipped defaults — measured directly against the real
# `type-weights.json`, not a hypothetical. That directly contradicts acceptance #5's own words: "a
# family-less species still gets a vector shaped by its own leanOrder rather than a flat
# 200/200/200/200/200." The two DECIDED provisions (§2's default table and §6's AC5) could not both
# hold at once under a shared row. Resolved by giving `separation: null` its OWN tuning row
# (`nullSeparationMilli`, default `500` — real signal, not the neutral 1000 `separationMilli[4]`
# carries, so a true tie (row 0, still exactly flat) and a family-less derivation (now visibly
# shaped) stop colliding on the same number for two different reasons.
# ---------------------------------------------------------------------------------------------

def raw_category_scores(lean_order: "tuple[str, ...]", lean_source: str,
                        separation: "int | None", weights: TypeWeights) -> "dict[str, int]":
    if lean_source == "floor":
        return {c: weights.base for c in CATEGORIES}

    factor = weights.null_separation_milli if separation is None else weights.separation_milli[separation]
    step_scaled = _widen_mul(weights.step, factor) // 1000   # 1000 = per-mille scale, structural
    n = len(lean_order)
    return {cat: weights.base + (n - 1 - idx) * step_scaled
            for idx, cat in enumerate(lean_order)}


# ---------------------------------------------------------------------------------------------
# §3 step 3 — largest-remainder normalisation, reused for every vector this module produces from
# a non-flat raw input (categoryMilli here; element-bias's own remainder split uses an equivalent
# equal-shares form directly, since primary/secondary are FIXED assignments rather than raw scores
# to be normalised — see `element_bias_for`'s own docstring).
# ---------------------------------------------------------------------------------------------

def largest_remainder_milli(raw: "Mapping[str, int]", order: "tuple[str, ...]") -> "dict[str, int]":
    """`weight_i = (raw_i * 1000) // total`, `long` throughout, widened before the multiply, one
    division per category. The `1000 - sum(floor)` remainder units go to the largest fractional
    parts; ties break on `order` — the declared, total tie-break order for whichever vocabulary
    this call is over. A total function: never depends on `raw`'s own iteration order, only on
    `order`."""
    total = sum(int(raw[k]) for k in order)
    if total <= 0:
        raise ValueError("largest_remainder_milli: the raw vector sums to <= 0 — nothing to "
                         "distribute")
    scaled = {k: _widen_mul(raw[k], 1000) for k in order}
    floor_milli = {k: scaled[k] // total for k in order}
    remainder = 1000 - sum(floor_milli.values())
    fracs = sorted(order, key=lambda k: (-(scaled[k] % total), order.index(k)))
    out = dict(floor_milli)
    for k in fracs[:remainder]:
        out[k] += 1
    return out


def category_milli_for(lean_order: "tuple[str, ...]", lean_source: str,
                       separation: "int | None", weights: TypeWeights) -> "dict[str, int]":
    raw = raw_category_scores(lean_order, lean_source, separation, weights)
    return largest_remainder_milli(raw, CATEGORIES)


# ---------------------------------------------------------------------------------------------
# §3 step 4 — the target-shape vector, keyed on the lean head plus `reach` when an anchor supplies
# one. `areaShapeMilli` is a single global row in this module's own tuning-file design (§2's
# neutral default states no per-head variation), returned unconditionally alongside every
# `targetModeMilli` row — `area`'s own board-presence gate stays at `ActionSeeder.cs:51-53` for the
# roll path and the bind-time validator's own equivalent check for the authored path, never
# duplicated here.
#
# **Who consumes these two vectors (spec §2's F5 decision) — restated here, not just in the spec,
# because this is the exact claim acceptance #6b tests against this module's own source.**
# `targetModeMilli` and `areaShapeMilli` are consumed by **A-S1, at PLAN time**, by largest
# remainder, the same discipline this module uses for `categoryMilli` — never by the shipped
# roll-time weighted picker (`ActionSeeder.cs:55`'s own `Pick` call), which is a different,
# already-shipped path this feature does not touch and never references from this package.
# ---------------------------------------------------------------------------------------------

def target_shape_for(lean_head: str, reach: "str | None",
                     weights: TypeWeights) -> "tuple[dict[str, int], dict[str, int]]":
    """A reach-qualified row (`"{head}:{reach}"`) wins over the bare head row when the tuning file
    ships one. v1 ships only the five bare head rows (spec §2's stated neutral default), so every
    lookup falls back to the head row today — the precedence itself is real and exercised by a
    synthetic tuning fixture in this module's own tests, not merely decorative."""
    if reach is not None:
        qualified = f"{lean_head}:{reach}"
        if qualified in weights.target_mode_milli:
            return dict(weights.target_mode_milli[qualified]), dict(weights.area_shape_milli)
    return dict(weights.target_mode_milli[lean_head]), dict(weights.area_shape_milli)


# ---------------------------------------------------------------------------------------------
# §3 step 5 — element bias. `primaryMilli`/`secondaryMilli` are ALREADY the final per-mille values
# (never raw scores to be renormalised) — the remainder is split evenly across the rest via plain
# integer division, which for an all-equal raw input (every remaining element weighted identically)
# is exactly what `largest_remainder_milli` would produce, just without a second, needless rounding
# pass on top of an already-fixed primary/secondary assignment.
# ---------------------------------------------------------------------------------------------

def element_bias_for(primary: str, secondary: "str | None",
                     weights: TypeWeights) -> "dict[str, int]":
    out = {e: 0 for e in ELEMENTS}
    out[primary] = weights.primary_milli
    rest = [e for e in ELEMENTS if e != primary]
    if secondary is not None:
        out[secondary] = weights.secondary_milli
        rest = [e for e in rest if e != secondary]

    assigned_total = out[primary] + (out[secondary] if secondary is not None else 0)
    remainder = 1000 - assigned_total
    n = len(rest)
    if n == 0:
        if remainder != 0:
            raise ValueError("element_bias_for: no elements left to absorb the remainder")
        return out

    base_each, leftover = divmod(remainder, n)
    for e in rest:
        out[e] = base_each
    for e in rest[:leftover]:            # `rest` already preserves ELEMENTS' declared order
        out[e] += 1
    return out


def family_element_bias_inputs(members: "list[RoleLeanRow]",
                               weights: TypeWeights) -> "tuple[str, 'str | None']":
    """A genuine judgment call, flagged plainly rather than presented as a spec citation (same
    discipline `characteristic_pool.derive`'s own `SIGNAL_CATEGORY` docstring uses): a family has
    no element slot of its own, so this builds one the same way a species' OWN secondary is scaled
    — "a secondary is half a primary" — applied here across MEMBERS instead of across one species'
    two element slots. Each member contributes 1000 (per-mille, the full weight — the same
    structural per-mille scale used everywhere else in this module) to its own primary element's
    score, and `weights.family_secondary_scale_milli` (this module's own tuning row, §2's
    `familySecondaryScaleMilli`) to its own secondary's (if any); the two highest-scoring elements
    become the family's own primary/secondary, ties broken on `ELEMENTS`' declared order. A family
    whose second-highest score is 0 gets no secondary — mirrors "elementSecondary: none" at the
    species level, never an invented bias toward an element no member actually carries."""
    score = {e: 0 for e in ELEMENTS}
    for m in members:
        score[m.element_primary] += 1000                 # 1000 = per-mille scale, structural
        if m.element_secondary is not None:
            score[m.element_secondary] += weights.family_secondary_scale_milli
    ranked = sorted(ELEMENTS, key=lambda e: (-score[e], ELEMENTS.index(e)))
    primary = ranked[0]
    secondary = ranked[1] if score[ranked[1]] > 0 else None
    return primary, secondary


# ---------------------------------------------------------------------------------------------
# §3 step 6 — family rows. "Computed identically from the family floor lean": a family's own raw
# category scores are the SUM of its members' raw (pre-normalisation) `raw_category_scores` — the
# same "summed step-4 scores" shape `characteristic_pool.derive.family_floor_order` uses, built
# from THIS module's own step-1/2 raw scores rather than A-S0's signal-weighted ones (role-lean.json
# carries no raw scores of its own — see this module's docstring). No separate separation dial is
# applied to the sum: each member's raw already reflects its OWN separation scaling before the sum,
# so summing is the whole "computed identically" step — no invented family-level separation value.
# ---------------------------------------------------------------------------------------------

def _family_raw_total(member_raw_scores: "list[Mapping[str, int]]") -> "dict[str, int]":
    total = {c: 0 for c in CATEGORIES}
    for raw in member_raw_scores:
        for c in CATEGORIES:
            total[c] += int(raw[c])
    return total


# ---------------------------------------------------------------------------------------------
# §3 step 7 orchestrated over every species + every family.
# ---------------------------------------------------------------------------------------------

def derive_all(rows: "list[RoleLeanRow]", weights: TypeWeights) -> "list[TypeWeightEntry]":
    """`rows` need not be pre-sorted — the caller (the writer) sorts the returned entries by `id`
    for the canonical write; this function's own output does not depend on `rows`' input order,
    since every downstream computation is either per-row or a `sum()`/`largest_remainder_milli`
    call, both of which are order-independent by construction."""
    entries: "list[TypeWeightEntry]" = []
    member_raw_by_family: "dict[str, list[dict[str, int]]]" = {}
    member_rows_by_family: "dict[str, list[RoleLeanRow]]" = {}

    for row in rows:
        raw = raw_category_scores(row.lean_order, row.lean_source, row.separation, weights)
        category_milli = largest_remainder_milli(raw, CATEGORIES)
        lean_head = row.lean_order[0]
        target_mode_milli, area_shape_milli = target_shape_for(lean_head, row.reach, weights)
        element_bias_milli = element_bias_for(row.element_primary, row.element_secondary, weights)
        basis = "floor" if row.lean_source == "floor" else "derived"

        entries.append(TypeWeightEntry(
            id=f"weights.species.{row.species_key}", scope="species", scope_key=row.species_key,
            category_milli=category_milli, target_mode_milli=target_mode_milli,
            area_shape_milli=area_shape_milli, element_bias_milli=element_bias_milli, basis=basis,
        ))

        family_ids = row.families or ((row.family,) if row.family else ())
        for family_id in family_ids:
            member_raw_by_family.setdefault(family_id, []).append(raw)
            member_rows_by_family.setdefault(family_id, []).append(row)

    for family_id in sorted(member_raw_by_family):
        total = _family_raw_total(member_raw_by_family[family_id])
        category_milli = largest_remainder_milli(total, CATEGORIES)
        lean_head = rank_categories(total)[0]
        target_mode_milli, area_shape_milli = target_shape_for(lean_head, None, weights)
        primary, secondary = family_element_bias_inputs(member_rows_by_family[family_id], weights)
        element_bias_milli = element_bias_for(primary, secondary, weights)
        basis = "floor" if len(set(total.values())) == 1 else "derived"

        entries.append(TypeWeightEntry(
            id=f"weights.family.{family_id}", scope="family", scope_key=family_id,
            category_milli=category_milli, target_mode_milli=target_mode_milli,
            area_shape_milli=area_shape_milli, element_bias_milli=element_bias_milli, basis=basis,
        ))

    return entries
