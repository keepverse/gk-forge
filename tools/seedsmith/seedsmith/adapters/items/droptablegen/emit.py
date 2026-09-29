"""seedsmith.adapters.items.droptablegen.emit — ids, slugs, and the final drop-table entry shape,
matching the real shipped corpus (`gk-data/packs/fusion/data/seed/items/drop-tables/d1.json`) field for field and row for
row.

⛔ **Always symbolic, never a concrete weight.** This module emits `dropBand` (a closed enum value)
and `qtyCurve` (a curve REFERENCE), exactly what the current 468 rows already carry -- never a raw
integer weight or a min/max count. That is the (out-of-scope, separate) band→row expander's job,
per `docs/architecture/item-seedgen-map.md` §5 and this module's own boundary.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from . import tuning

TABLE_ID_RE = re.compile(r"^droptable\.d[1-4]-\d{3}$")
NAME_KEY_RE = re.compile(r"^droptable\.[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_SLUG_WORD_RE = re.compile(r"[A-Za-z0-9]+")


class MintRefused(ValueError):
    """An id, slug, or field this module refuses to mint, with the rule it would have broken."""


class IdCollisionError(ValueError):
    """The minted table id already exists in this partition -- never silently overwritten."""


class IllegalChoiceError(ValueError):
    """A field outside its own closed vocabulary reached `assemble_entry` despite the schema's own
    enum -- defense in depth, not the primary guard (mirrors `basetypegen.emit.IllegalChoiceError`
    and `sockets-gen`'s own discipline)."""


def slug_from_name(name: str) -> str:
    words = _SLUG_WORD_RE.findall(name)
    if not words:
        raise MintRefused(f"name {name!r} has no word to slug")
    slug = "-".join(w.lower() for w in words)
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
        raise MintRefused(f"name {name!r} produced the non-kebab-legal slug {slug!r}")
    return slug


def mint_table_id(slot: int, seq: int) -> str:
    if slot not in tuning.LEGAL_SLOTS:
        raise MintRefused(
            f"slot {slot} is not one of naming.v1.json's frozen dropTables partitions "
            f"{tuning.LEGAL_SLOTS} -- a 5th partition is a reviewed registry bump, not this "
            f"module's call to make")
    if not (1 <= seq <= 999):
        raise MintRefused(f"seq {seq} does not fit the id template's {{seq:03}} range (1-999)")
    minted = tuning.ID_TEMPLATE.format(slot=slot, seq=seq)
    if not TABLE_ID_RE.match(minted):
        raise MintRefused(f"{minted!r} fails the droptable.d<slot>-<seq:03> id grammar")
    return minted


def next_seq(existing_ids: "tuple[str, ...] | list[str]", slot: int) -> int:
    """Continues one past the highest `-{seq:03}` suffix already minted for THIS slot -- never
    reusing an id, the same "continue, never reuse" discipline every sibling emit module states."""
    prefix = f"droptable.d{slot}-"
    max_seq = 0
    for eid in existing_ids:
        if eid.startswith(prefix):
            suffix = eid[len(prefix):]
            if suffix.isdigit():
                max_seq = max(max_seq, int(suffix))
    return max_seq + 1


@dataclass(frozen=True)
class RowPlan:
    """One row this module will emit, with everything CODE has already decided about it. Only
    `dropBand` (and, for one equipment row, `rarityFloor`) are left for the model to answer --
    mirrors `gemgen`'s "which family a subject gets is decided by code, never the model" split."""

    entry_kind: str                       # "equipment" | "material" | "currency" | "nothing"
    role: "str | None" = None
    frame: "str | None" = None
    ref: "str | None" = None


def _equipment_row(role: str, frame: str, drop_band: str, rarity_floor: "str | None",
                   legal_pairs: "frozenset[tuple[str, str]]") -> "dict[str, Any]":
    if (role, frame) not in legal_pairs:
        raise IllegalChoiceError(
            f"role {role!r} frame {frame!r} resolves to zero real base-type entries -- "
            f"base-types-gen's own corpus has nothing at this (role, frame) pair")
    row: "dict[str, Any]" = {"entryKind": "equipment", "role": role, "frame": frame,
                             "dropBand": drop_band}
    if rarity_floor is not None:
        row["rarityFloor"] = rarity_floor
    return row


def _material_row(ref: str, drop_band: str, legal_refs: "frozenset[str]") -> "dict[str, Any]":
    if ref not in legal_refs:
        raise IllegalChoiceError(
            f"material ref {ref!r} does not resolve against materials-gen's real corpus "
            f"(matched on runtimeId, never id)")
    return {"entryKind": "material", "ref": ref, "dropBand": drop_band,
           "qtyCurve": tuning.MATERIAL_QTY_CURVE_ID}


#: species-gear-chain T30b (`creature-drop-tables` d) — R9's closed two-value scope vocabulary
#: (`general` was removed, not parked at 0). Pinning this size is correct: it is a closed
#: vocabulary the code owns, never a population.
_TROPHY_SCOPES = ("species", "family")


def _trophy_row(scope: str, slot: int, drop_band: str) -> "dict[str, Any]":
    """One parametric trophy directive (spec-creature-drop-tables.md Open question 3, Strengthen
    pass item 1): `scope` + `slot` INSTEAD OF a literal ref — a per-rung table cannot name the
    KILLED species' trophy without 904 tables. Resolved against the killed species/family at draw
    time (species-gear-chain T34c), never authored here.

    **Code decides scope and slot; the model answers only `dropBand`** — mirrors `_material_row`'s
    own `ref` (there, a real id CODE has already chosen from the real corpus; here, a scope+slot
    pair CODE has already chosen from the trophy registry's own shape) with the SAME division of
    labor `assemble_entry`'s own docstring states for every row kind in this module. Neither
    `scope` nor `slot` ever reaches a model-facing schema — this function is called with values a
    caller (T34c's own content-authoring pipeline) has already decided, exactly like
    `_material_row`'s `ref` parameter.

    Refuses (never silently accepts) a scope outside the closed vocabulary or a non-positive slot —
    the same `IllegalChoiceError`/`MintRefused` split every sibling row function in this file uses:
    a closed-vocabulary violation vs. a shape violation.
    """
    if scope not in _TROPHY_SCOPES:
        raise IllegalChoiceError(
            f"trophy scope {scope!r} is not one of {_TROPHY_SCOPES} (R9 removed the general layer)")
    if slot < 1:
        raise MintRefused(f"trophy slot {slot} must be a positive integer, got {slot}")
    return {"entryKind": "material", "trophyScope": scope, "trophySlot": slot, "dropBand": drop_band}


def _consumable_row(ref: str, drop_band: str, legal_refs: "frozenset[str]") -> "dict[str, Any]":
    if ref not in legal_refs:
        raise IllegalChoiceError(
            f"consumable ref {ref!r} does not resolve against consumables-gen's real corpus")
    return {"entryKind": "consumable", "ref": ref, "dropBand": drop_band}


def _insert_row(ref: str, drop_band: str, legal_refs: "frozenset[str]") -> "dict[str, Any]":
    if ref not in legal_refs:
        raise IllegalChoiceError(
            f"insert (gem) ref {ref!r} does not resolve against sockets-gen's real corpus")
    return {"entryKind": "insert", "ref": ref, "dropBand": drop_band}


def _relic_row(ref: str, drop_band: str, legal_refs: "frozenset[str]") -> "dict[str, Any]":
    """One `relic`-kind drop-table row (spec-relic-item-kind.md §Design 4a, empire-development
    Task 1.3b). Mirrors `_insert_row`/`_consumable_row` exactly: the ref must resolve against the
    real, on-disk relic corpus (`tuning.load_relic_ids()`, on `id`), and the row stays symbolic --
    `entryKind` + `ref` + `dropBand`, never a weight or count (this module's own header rule). The
    shape matches the shipped `r2-unique` precedent (`{"entryKind": "unique", "ref", "dropBand"}`,
    d1.json) field for field, with only the kind swapped -- a relic is unique's non-equip sibling,
    never equipment."""
    if ref not in legal_refs:
        raise IllegalChoiceError(
            f"relic ref {ref!r} does not resolve against the real relics corpus "
            f"(matched on id, never a display name)")
    return {"entryKind": "relic", "ref": ref, "dropBand": drop_band}


def assemble_entry(*, table_id: str, name: str, drop_bands: "list[str]",
                   equipment_slots: "list[tuple[str, str]]", material_refs: "list[str]",
                   consumable_refs: "list[str]", gem_refs: "list[str]",
                   rarity_floor: "str | None", legal_role_frames: "frozenset[tuple[str, str]]",
                   legal_material_refs: "frozenset[str]", legal_consumable_refs: "frozenset[str]",
                   legal_gem_refs: "frozenset[str]", legal_drop_bands: "tuple[str, ...]",
                   legal_rarity_ids: "tuple[str, ...]") -> "dict[str, Any]":
    """One full drop-table entry: a `<slug>-gear` group (equipment slots + a `nothing` filler), a
    `<slug>-mat` group (material refs), a `<slug>-con` group (consumable refs), a `<slug>-ins`
    group (gem/insert refs), and a `<slug>-cur` group (the fixed `souls` currency row) -- the same
    group split the 40 shipped tables already use, minus any group this call's row-slot plan left
    empty (a table with zero consumable/insert rows omits those groups entirely, matching most of
    the shipped corpus).

    `drop_bands` supplies one band per row IN ORDER: equipment slots, then material refs, then
    consumable refs, then gem/insert refs, then the currency row (the `nothing` filler is fixed at
    `staple`, see this module's own `_NOTHING_ROW_BAND` note). `rarity_floor`, if given, is applied
    to the FIRST equipment row only -- matching the real corpus's own pattern (never more than one
    `rarityFloor` per table's gear group, confirmed across all 40 shipped tables)."""
    if not TABLE_ID_RE.match(table_id):
        raise MintRefused(f"{table_id!r} fails the droptable id grammar")
    if not name:
        raise MintRefused("name must be non-empty")
    if not equipment_slots:
        raise MintRefused("a drop table needs at least one equipment slot")
    if not material_refs:
        raise MintRefused("a drop table needs at least one material row")
    n_eq, n_mat, n_con, n_gem = (len(equipment_slots), len(material_refs), len(consumable_refs),
                                len(gem_refs))
    expected_row_count = n_eq + n_mat + n_con + n_gem + 1  # + the currency row
    if len(drop_bands) != expected_row_count:
        raise MintRefused(
            f"expected {expected_row_count} dropBand answers (equipment, material, consumable, "
            f"insert, then the currency row), got {len(drop_bands)}")
    for band in drop_bands:
        if band not in legal_drop_bands:
            raise IllegalChoiceError(f"dropBand {band!r} is not one of {legal_drop_bands}")
    if rarity_floor is not None and rarity_floor not in legal_rarity_ids:
        raise IllegalChoiceError(f"rarityFloor {rarity_floor!r} is not a real rarity_id")

    slug = slug_from_name(name)
    eq_bands = drop_bands[:n_eq]
    mat_bands = drop_bands[n_eq:n_eq + n_mat]
    con_bands = drop_bands[n_eq + n_mat:n_eq + n_mat + n_con]
    gem_bands = drop_bands[n_eq + n_mat + n_con:n_eq + n_mat + n_con + n_gem]
    cur_band = drop_bands[n_eq + n_mat + n_con + n_gem]

    gear_entries = [
        _equipment_row(role, frame, band, rarity_floor if i == 0 else None, legal_role_frames)
        for i, ((role, frame), band) in enumerate(zip(equipment_slots, eq_bands))
    ]
    gear_entries.append({"entryKind": "nothing", "dropBand": _NOTHING_ROW_BAND})

    mat_entries = [_material_row(ref, band, legal_material_refs)
                  for ref, band in zip(material_refs, mat_bands)]

    groups = [
        {"groupKey": f"{slug}-gear", "entries": gear_entries},
        {"groupKey": f"{slug}-mat", "entries": mat_entries},
    ]

    if consumable_refs:
        con_entries = [_consumable_row(ref, band, legal_consumable_refs)
                      for ref, band in zip(consumable_refs, con_bands)]
        groups.append({"groupKey": f"{slug}-con", "entries": con_entries})

    if gem_refs:
        gem_entries = [_insert_row(ref, band, legal_gem_refs)
                      for ref, band in zip(gem_refs, gem_bands)]
        groups.append({"groupKey": f"{slug}-ins", "entries": gem_entries})

    groups.append({"groupKey": f"{slug}-cur",
                   "entries": [{"entryKind": "currency", "ref": tuning.CURRENCY_ID,
                              "dropBand": cur_band}]})

    return {
        "id": table_id,
        "nameKey": f"droptable.{slug}",
        "name": name,
        "sourceAllow": ["web"],
        "groups": groups,
        "tags": [],
    }


#: Every shipped table's `nothing` filler row in its `-gear` group is `staple` in the large
#: majority of cases (confirmed: 8 of 10 in d1.json alone; the two exceptions -- d1-005 and
#: d1-010, both `frequent` -- pair with `seldom` equipment rows, a deliberate rebalance for a
#: rarer gear group). `staple` is this module's structural default for the filler row -- the row
#: exists so a gear-group draw can legally yield nothing, and its OWN band is not something a model
#: call should be spent choosing; a balance pass that wants a different filler weight per table is
#: better served by a reviewed change here than by a per-call model guess.
_NOTHING_ROW_BAND = "staple"
