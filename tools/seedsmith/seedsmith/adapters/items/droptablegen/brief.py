"""seedsmith.adapters.items.droptablegen.brief — the deterministic row-slot plan + the model-facing
brief for ONE new drop table.

⛔ P1, same opening line every sibling module states: **the model writes identity and bands, code
resolves every reference.** Which equipment role/frame pairs and which material refs a given table
offers are picked by CODE (`build_row_slot_plan`, a deterministic rotation over the real, current
`base-types-gen` and `materials-gen` corpora) -- never by the model. The model's only choices are
`name`/`nameKey` and one `dropBand` per row, plus an optional `rarityFloor` on the first equipment
row. This mirrors `gemgen.brief`'s own split ("which family a subject gets is decided by CODE, not
the model... an extra, uncontrolled degree of freedom") applied to drop-table row composition.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from seedsmith.pipeline.model import audit_schema

from . import tuning
from .schema import drop_table_answer_schema
from ..naming_grammar import NAMING_GRAMMAR_RULES

#: How many of each row kind a generated table offers -- matches the modal shape of the 40 shipped
#: tables (a `-gear` group with 2 named equipment rows + a `nothing` filler, a `-mat` group with
#: 1-2 material rows; confirmed by reading d1..d4 directly). Consumable/insert rows are given ONE
#: slot each here rather than the large flat pools some hand-authored tables use (one shipped
#: table's `r2-consumable` group alone lists 60 rows) -- that pool SIZE is a content-authoring
#: choice this module leaves open for a future brief revision, not a shape this module's own tests
#: need to reproduce; what acceptance criterion 2 requires is that a consumable/insert `.ref` this
#: module DOES emit resolves against the real corpus, which one slot each already proves. Fixed
#: here rather than authored per table: composition WIDTH is a content-shape decision this module
#: owns, the same way `gemgen` fixes "one gem grants one family" rather than asking per call.
EQUIPMENT_SLOT_COUNT = 2
MATERIAL_SLOT_COUNT = 2
CONSUMABLE_SLOT_COUNT = 1
GEM_SLOT_COUNT = 1
#: spec-relic-item-kind.md §Design 4a (empire-development Task 1.3b): how many relic rows a
#: brand-new table offers. 0 -- relic entries reach tables through the targeted append operation
#: (`append.py`, aimed at an already-shipped, already-wired table id), never by landing on every
#: newly minted table. Offered per call rather than on every row, mirroring `rarityFloor`'s own
#: "optional, not on every row" shape: a future caller raises this constant (or threads an
#: explicit count through `build_row_slot_plan`) the day a new table should mint with relics.
RELIC_SLOT_COUNT = 0


def _rotate(sorted_pool: "list", seq_index: int, count: int, *, pool_name: str) -> tuple:
    """A deterministic modulo rotation over an already-sorted pool: which `count` items `seq_index`
    gets, stable across reruns against unchanged on-disk state. Generic over the item type -- used
    for role/frame pairs as well as plain string ids."""
    n = len(sorted_pool)
    if n < count:
        raise ValueError(f"{pool_name} has only {n} real entries -- fewer than the {count} this "
                         f"module needs per table")
    start = (seq_index * count) % n
    return tuple(sorted_pool[(start + i) % n] for i in range(count))


@dataclass(frozen=True)
class RowSlotPlan:
    """Everything CODE has already decided about ONE new table's row composition, before any model
    call happens. Field order here (and in `emit.assemble_entry`'s `drop_bands` reading) is fixed:
    equipment, material, consumable, gem/insert, then the one currency row -- matching this
    module's own brief text and schema `rowBands` ordering exactly."""

    equipment_slots: "tuple[tuple[str, str], ...]"   # ((role, frame), ...)
    material_refs: "tuple[str, ...]"
    consumable_refs: "tuple[str, ...]"
    gem_refs: "tuple[str, ...]"
    legal_role_frames: "frozenset[tuple[str, str]]"
    legal_material_refs: "frozenset[str]"
    legal_consumable_refs: "frozenset[str]"
    legal_gem_refs: "frozenset[str]"
    drop_band_enum: "tuple[str, ...]"
    rarity_ids: "tuple[str, ...]"
    #: Relic rows CODE has picked for a brand-new table. Empty while `RELIC_SLOT_COUNT` is 0 --
    #: relic entries reach shipped tables through `append.py`, not through this plan. The field
    #: (and `legal_relic_refs` below) exists so the day a new table mints with relics, the refs
    #: are already code-picked and corpus-resolved, never model-invented.
    relic_refs: "tuple[str, ...]" = ()
    legal_relic_refs: "frozenset[str]" = frozenset()

    @property
    def row_count(self) -> int:
        # Relic rows are excluded on purpose: while RELIC_SLOT_COUNT is 0 this plan never offers
        # one, and a relic that DOES reach a table travels via the append operation (which carries
        # its own band per call), never via this plan's per-row `rowBands` answer shape.
        return (len(self.equipment_slots) + len(self.material_refs) + len(self.consumable_refs)
                + len(self.gem_refs) + 1)  # + the currency row


def build_row_slot_plan(seq_index: int, *, base_types_dir: "Any | None" = None,
                        materials_path: "Any | None" = None,
                        consumables_dir: "Any | None" = None,
                        gems_dir: "Any | None" = None,
                        relics_dir: "Any | None" = None) -> RowSlotPlan:
    """`seq_index` is the subject's own zero-based position within its run -- the SAME kind of
    "position decides content, not iteration order" discipline `gemgen.emit.resolve_power_band`
    documents. A deterministic modulo rotation over the real, current, SORTED vocabularies, so a
    rerun against unchanged on-disk state always proposes the same slots for the same index.
    """
    legal_pairs = tuning.legal_role_frame_pairs(base_types_dir)
    equipment_slots = _rotate(sorted(legal_pairs), seq_index, EQUIPMENT_SLOT_COUNT,
                              pool_name="base-types-gen's real (role, frame) corpus")

    legal_materials = tuning.load_material_runtime_ids(materials_path)
    material_refs = _rotate(sorted(legal_materials), seq_index, MATERIAL_SLOT_COUNT,
                            pool_name="materials-gen's real corpus")

    legal_consumables = tuning.load_consumable_ids(consumables_dir)
    consumable_refs = _rotate(sorted(legal_consumables), seq_index, CONSUMABLE_SLOT_COUNT,
                              pool_name="consumables-gen's real corpus")

    legal_gems = tuning.load_gem_ids(gems_dir)
    gem_refs = _rotate(sorted(legal_gems), seq_index, GEM_SLOT_COUNT,
                       pool_name="sockets-gen's real corpus")

    # Never `_rotate` over the relic corpus while RELIC_SLOT_COUNT is 0: a zero-count rotation
    # over a still-empty (Task 1.3c authors content later) pool would divide by zero instead of
    # yielding the empty tuple this plan promises. The legal set is still resolved fresh every
    # call, so the day the count rises the refs are corpus-backed from the first table.
    legal_relics = tuning.load_relic_ids(relics_dir)
    relic_refs: "tuple[str, ...]" = ()
    if RELIC_SLOT_COUNT:
        relic_refs = _rotate(sorted(legal_relics), seq_index, RELIC_SLOT_COUNT,
                             pool_name="relics' real corpus")

    return RowSlotPlan(
        equipment_slots=equipment_slots, material_refs=material_refs,
        consumable_refs=consumable_refs, gem_refs=gem_refs,
        legal_role_frames=legal_pairs, legal_material_refs=legal_materials,
        legal_consumable_refs=legal_consumables, legal_gem_refs=legal_gems,
        drop_band_enum=tuning.load_drop_band_enum(), rarity_ids=tuning.load_rarity_ids(),
        relic_refs=relic_refs, legal_relic_refs=legal_relics,
    )


@dataclass(frozen=True)
class DropTableBrief:
    """One brief, one row-slot plan. `schema` is built alongside the text so the two are guaranteed
    to describe the same legal answer space -- same construction-time guard every sibling brief
    dataclass runs (`gemgen.brief`, `basetypegen.brief.BaseTypeBrief.__post_init__`)."""

    plan: RowSlotPlan
    theme_note: str = ""
    schema: "Mapping[str, Any]" = field(default_factory=dict)

    def __post_init__(self) -> None:
        schema = self.schema or drop_table_answer_schema(
            row_count=self.plan.row_count, drop_band_enum=self.plan.drop_band_enum,
            rarity_ids=self.plan.rarity_ids, offer_rarity_floor=True)
        defects = audit_schema(schema)
        if defects:
            raise ValueError(
                "drop-table brief has an unusable schema:\n" + "\n".join(f"  - {d}" for d in defects))
        object.__setattr__(self, "schema", schema)

    def render(self) -> str:
        p = self.plan
        theme_line = f"\nTheme: {self.theme_note}" if self.theme_note else ""
        eq_lines = "\n".join(f"  {i+1}. {role!r} equipment, {frame!r} frame"
                             for i, (role, frame) in enumerate(p.equipment_slots))
        mat_lines = "\n".join(f"  {i+1}. material ref {ref!r}"
                              for i, ref in enumerate(p.material_refs))
        con_lines = "\n".join(f"  {i+1}. consumable ref {ref!r}"
                              for i, ref in enumerate(p.consumable_refs))
        gem_lines = "\n".join(f"  {i+1}. insert (gem) ref {ref!r}"
                              for i, ref in enumerate(p.gem_refs))
        row_labels = (
            [f"equipment row {i+1} ({role}/{frame})" for i, (role, frame) in
             enumerate(p.equipment_slots)]
            + [f"material row {i+1} ({ref})" for i, ref in enumerate(p.material_refs)]
            + [f"consumable row {i+1} ({ref})" for i, ref in enumerate(p.consumable_refs)]
            + [f"insert row {i+1} ({ref})" for i, ref in enumerate(p.gem_refs)]
            + ["the currency (souls) row"]
        )
        return f"""Author ONE NEW drop table.{theme_line}

This is a LOOT TABLE for a web-reachable source (a battle, an expedition tick, a sector clear).
Code has already picked which rows this table offers -- your only job is to name the table and
say how common each row should be. Never invent a role, a frame, a material, a weight, or a count;
those are either fixed by code or resolved later, never here.

Choose:
1. `name` -- a short, evocative table name, e.g. "Compost Cache" or "Boneyard Scrap". `nameKey` is
   derived from this afterwards -- never authored directly.

{NAMING_GRAMMAR_RULES}

2. `rowBands` -- one dropBand per row below, IN THIS ORDER:
{chr(10).join(f'   {i+1}. {label}' for i, label in enumerate(row_labels))}
   Legal dropBand values ({len(p.drop_band_enum)}): {', '.join(p.drop_band_enum)}
   `staple` is by far the most common row; `exceptional` should be rare across a whole batch.
3. `rarityFloor` (optional) -- a rarity_id floor for equipment row 1 only, from this closed ladder:
   {', '.join(p.rarity_ids)}. Omit it entirely if this table has no reason to floor a rarity.

This table's fixed equipment slots:
{eq_lines}

This table's fixed material rows:
{mat_lines}

This table's fixed consumable rows:
{con_lines}

This table's fixed insert (gem) rows:
{gem_lines}

If this row plan cannot carry a table you would be happy to ship, set `blocked` and say why."""


def build_drop_table_brief(seq_index: int, *, theme_note: str = "",
                           base_types_dir: "Any | None" = None,
                           materials_path: "Any | None" = None) -> DropTableBrief:
    plan = build_row_slot_plan(seq_index, base_types_dir=base_types_dir,
                               materials_path=materials_path)
    return DropTableBrief(plan=plan, theme_note=theme_note)
