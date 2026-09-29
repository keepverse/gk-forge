"""seedsmith.adapters.items.trophyplan.plan — the deterministic, append-only trophy id registry
(spec-species-materials.md § Design 4). No model call; pure arithmetic over the species roster, the
species -> families map, and the two generation-run counts (`perSpecies`/`perFamily`).

**Id grammar -- structural, stays in code (spec § Design 4):**
`trophy.species.{speciesId}.{slot}`, `trophy.family.{familyId}.{slot}`, `slot` in `1..count` for
that scope. The scope word is a CLOSED two-value vocabulary (`species`/`family`, R9 -- the
`general` layer is REMOVED, not parked at 0); the ids minted under it are a POPULATION that grows
with the roster, never pinned to a count (`validation-ssot.md`).

**Append-only, because issued ids are player inventory (spec § Design 4).** Raising a parameter
appends new slots; lowering one never deletes an issued id -- it only stops NEW slots from being
minted for that scope key. Re-running `plan_trophy_registry` with the SAME `existing_rows` and
tuning it already satisfies mints zero new rows (proven by `test_trophy_plan.py`'s own idempotency
test) -- the property the caller relies on to decide whether a re-plan changed anything.

**A creature in no family (spec § Design 5 step 3).** Such a species mints its `perSpecies` ids and
no family ids; it is never assigned a fabricated filler family, and (R9) never falls back to a
removed general layer either. `PlanResult.species_with_no_family` reports every such id -- printed
by `run.py`, never asserted by a test (a report of a gap, not a population count).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

SCOPES: "tuple[str, ...]" = ("species", "family")


class TrophyRegistryError(ValueError):
    """The on-disk trophy registry (or a caller's own row list) failed to parse or is internally
    inconsistent -- refused, never silently repaired."""


@dataclass(frozen=True)
class TrophyRow:
    material_id: str
    scope: str
    scope_key: str
    slot: int

    def to_dict(self) -> dict:
        return {"materialId": self.material_id, "scope": self.scope,
                "scopeKey": self.scope_key, "slot": self.slot}

    @staticmethod
    def from_dict(row: Mapping[str, object]) -> "TrophyRow":
        scope = row.get("scope")
        scope_key = row.get("scopeKey")
        slot = row.get("slot")
        material_id = row.get("materialId")
        if scope not in SCOPES:
            raise TrophyRegistryError(f"trophy registry row has scope {scope!r}, not one of {SCOPES}")
        if not isinstance(scope_key, str) or not scope_key:
            raise TrophyRegistryError(f"trophy registry row has a non-string/empty scopeKey: {scope_key!r}")
        if isinstance(slot, bool) or not isinstance(slot, int) or slot < 1:
            raise TrophyRegistryError(f"trophy registry row has a non-positive-int slot: {slot!r}")
        if not isinstance(material_id, str) or not material_id:
            raise TrophyRegistryError(f"trophy registry row has a non-string/empty materialId: {material_id!r}")
        expected = compose_id(scope, scope_key, slot)
        if material_id != expected:
            raise TrophyRegistryError(
                f"trophy registry row's materialId {material_id!r} does not match its own "
                f"scope/scopeKey/slot -- expected {expected!r}")
        return TrophyRow(material_id=material_id, scope=scope, scope_key=scope_key, slot=slot)


def compose_id(scope: str, scope_key: str, slot: int) -> str:
    if scope not in SCOPES:
        raise TrophyRegistryError(f"compose_id: scope must be one of {SCOPES} -- got {scope!r}")
    return f"trophy.{scope}.{scope_key}.{slot}"


@dataclass(frozen=True)
class PlanResult:
    #: every row that already existed PLUS every row this plan appended, sorted deterministically
    #: (scope, then scope_key, then slot) -- the full registry this plan would write to disk.
    all_rows: "tuple[TrophyRow, ...]"
    #: only the rows this plan appended -- what `run.py --dry-run` reports as "would mint".
    new_rows: "tuple[TrophyRow, ...]"
    #: species present in the roster with an empty family list (spec § Design 5 step 3) -- reported,
    #: never asserted as a count.
    species_with_no_family: "tuple[str, ...]"

    def totals(self) -> "dict[str, int]":
        """Per-scope row counts -- printed by `run.py`, never pinned by a test (a derived
        population, `validation-ssot.md`)."""
        out = {scope: 0 for scope in SCOPES}
        for row in self.all_rows:
            out[row.scope] += 1
        return out


def _max_slot_by_key(rows: "Sequence[TrophyRow]", scope: str) -> "dict[str, int]":
    out: "dict[str, int]" = {}
    for row in rows:
        if row.scope != scope:
            continue
        out[row.scope_key] = max(out.get(row.scope_key, 0), row.slot)
    return out


def _mint_for_scope(scope: str, keys: "Sequence[str]", target: int,
                    existing: "Sequence[TrophyRow]") -> "list[TrophyRow]":
    """Appends slots `next..target` for every key in `keys`, where `next` continues from whatever
    slot that key already has issued -- never renumbers, never removes. `target <= already issued`
    mints nothing for that key (the lower-then-raise-again case stays gap-free by construction: the
    only way a slot number is ever minted is this loop, so issued slots for one key are always the
    contiguous run `1..max`)."""
    max_slot = _max_slot_by_key(existing, scope)
    minted: "list[TrophyRow]" = []
    for key in keys:
        start = max_slot.get(key, 0) + 1
        for slot in range(start, target + 1):
            minted.append(TrophyRow(material_id=compose_id(scope, key, slot),
                                    scope=scope, scope_key=key, slot=slot))
    return minted


def plan_trophy_registry(
        family_membership: "Mapping[str, Sequence[str]]", *, per_species: int, per_family: int,
        existing_rows: "Sequence[TrophyRow]" = (),
) -> PlanResult:
    """`family_membership` is a non-excluded species id -> its (possibly empty) family id tuple --
    already cross-validated against the seed tree by `species.resolve_family_membership`, or a
    synthetic fixture in a test. Deterministic: iterates species in sorted-id order, then families
    in sorted-id order, so two calls over the same inputs mint the SAME new rows in the SAME order.
    """
    if per_species < 0 or per_family < 0:
        raise TrophyRegistryError("per_species/per_family must be non-negative")

    species_ids = sorted(family_membership)
    family_ids = sorted({family for families in family_membership.values() for family in families})
    no_family = tuple(sid for sid in species_ids if not family_membership[sid])

    new_species_rows = _mint_for_scope("species", species_ids, per_species, existing_rows)
    new_family_rows = _mint_for_scope("family", family_ids, per_family, existing_rows)
    new_rows = tuple(new_species_rows + new_family_rows)

    all_rows = tuple(sorted(
        list(existing_rows) + list(new_rows),
        key=lambda r: (SCOPES.index(r.scope), r.scope_key, r.slot)))

    return PlanResult(all_rows=all_rows, new_rows=new_rows, species_with_no_family=no_family)
