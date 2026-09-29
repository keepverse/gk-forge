"""base-defense `structure-corpus` (module 24, spec-structure-corpus.md). **Zero model calls, zero
tokens** — every row below is hand-authored, citing `base-defense-ideal.md` §5.18 (the obstacle
vocabulary) or §5.21 (the ten economic roles), or transcribed from `StructureCatalog.cs`'s own
already-shipped `Seed` array (task 24.1's "dump the shipped rows first" importer proof).

**A real, honestly-named drift from the spec's own text, found by reading code rather than trusting
the spec (`docs/DESIGN-GATE.md`'s own rule):** spec-structure-corpus.md (written 2026-09-04) says
"`StructureCatalog`'s four rows" — but by the time this module was built (2026-09-06), the shipped
catalog had grown to **eight** rows (`soul-conduit`/`extractor`/`hatchery` — all `Yield`-kind, added
by `loam-structures`/`world-map` waves the spec's own "what already exists" section never
mentions — plus `moat`, the first `Obstacle`-kind row, added THIS SESSION by `siege-construction`
15.3b). All eight are dumped here, not four.

**A second, consequent and equally honest drift:** with 8 already-dumped (not 4), reaching the
spec's own literal "~36 hand-authored" text on top would push grid density to 4.4/cell — outside
the very 2.4-4.0 safe band §4 computes and cites as the reason for the ~36 target in the first
place. This module targets the **band**, not the literal row count: 17 new rows (not ~36), landing
the TOTAL corpus (8 dumped + 17 new = 25) at exactly 2.5/cell — inside the safe band, and grounded
in real source material rather than padded with invented filler to hit a number written when the
dumped count was smaller. See `tasks/base-defense-todo.md` 24.1/24.2's own evidence for the full
accounting.

**File shape**, one per row under ``gk-data/packs/fusion/data/seed/structures/<role-lowercase>/<structureId>.json``,
matching ``seedsmith.corpus.Corpus.load``'s own generic ``{"kind", "_meta", "entries"}`` contract
(the shared corpus-loading SDK already used by the actions adapter — Law 1: no second loader)::

    {
      "kind": "structure-anchor",
      "_meta": {"partition": "<Role>"},
      "entries": [
        {
          "id": "<structureId>",
          "anchor": { ...the 21 fields `build_structure_anchor_schema()` validates, verbatim... },
          "_provenance": {"source": "AUTHORED", "citation": "<where this row comes from>"},
          "magnitudes": { ...only on an import-ready row, see below... }
        }
      ]
    }

``anchor`` is kept as its own nested object (rather than flattened beside ``_provenance``)
specifically so it validates against ``build_structure_anchor_schema()`` unmodified —
that schema declares ``additionalProperties: False`` over exactly its 21 keys, so a sibling
``_provenance`` key on the SAME object would fail validation. Nesting is this module's own
resolution of a real, undocumented ambiguity (no prior spec shows a worked example row) — stated
here rather than left implicit, per this program's own "say so" discipline for a judgment call.

**``magnitudes`` — a real, undocumented gap found while building `structure-catalog-import` (module
25), not invented ahead of need.** structure-schema's own foundational rule is that the anchor
"holds no numbers at all" (Law 2: a model must never author a magnitude) — but
spec-structure-catalog-import.md §4 requires the shipped rows to produce "same cost, same yield
multiplier, same build turns, same capacity bonus" through the corpus path, and those are
per-structure, independently-tuned numbers (`gk-core/data/tuning/loam.v4.json`'s own `structures` block —
`wellCost` 200 ≠ `granaryCost` 150 ≠ `waystationCost` 300, etc.) that no shared ordinal band (a
single `costProfile` value shared by many rows) could ever reproduce. See
`docs/architecture/base-defense/spec-structure-catalog-import.md`'s own new correction section for
the full reasoning. Resolution: a THIRD, sibling key, ``magnitudes`` — present only on a row that is
actually ready to be loaded as a real `StructureDef` (today: the 8 dumped rows, since their numbers
already exist and are exactly transcribed here). The 17 new anchor-only rows carry no
``magnitudes`` yet on purpose — they are identity-registered, not yet catalog-loadable, until
`structure-planner` (27) assigns each a real, deterministic number (never a model's own guess, per
Law 2) and the resulting row gains its own ``magnitudes`` block then. `magnitudes.materialTier` is
authored explicitly (never derived from `anchor.strengthBand`) for exactly the reason
spec-structure-catalog-import.md §4 itself states: the loam rows "author tier zero" (indestructible)
even though `strengthBand` (not nullable, no zero-tier value in its 3-rung vocabulary) carries a
real band — the two fields answer different questions and only `magnitudes.materialTier` is
authoritative for `StructureDef.MaterialTier` once a row has one.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

from .anchor.schema import build_structure_anchor_schema

_SCHEMA = build_structure_anchor_schema()


def _anchor(
    structure_id: str,
    *,
    role: str,
    required_slot_kind: str,
    reach: str = "melee",
    strength_band: str,
    rarity: str,
    cost_profile: str,
    footprint: str = "one-cell",
    cover_tier: str = "none",
    acquisition_paths: "tuple[str, ...]",
    control_point: bool,
    obstacle_verbs: "tuple[str, ...]" = (),
    tempo: str = "none",
    role_secondary: str = "none",
    element_primary: str = "none",
    element_secondary: str = "none",
    target_preference: str = "none",
) -> dict:
    """One row's 21-field ``anchor`` object. Fields held constant across every row in this corpus
    (``traits``/``variants`` empty, ``elementPrimary``/``elementSecondary``/``targetPreference``
    ``"none"``) are a deliberate, stated corpus-wide choice, not an oversight — nothing in
    §5.18/§5.21 grounds an elemental theme, a variant, a trait, or an AI targeting preference for
    any of these 25 concepts, and inventing one to fill the slot would be exactly the "generic
    flavour" / ungrounded-invention failure mode `spec-structure-corpus.md` §6 warns against.
    """
    return {
        "structureId": structure_id,
        "family": "siege-obstacles" if role in ("Defend", "See", "Deny") else "loam-structures",
        "role": role,
        "roleSecondary": role_secondary,
        "requiredSlotKind": required_slot_kind,
        "elementPrimary": element_primary,
        "elementSecondary": element_secondary,
        "tempo": tempo,
        "reach": reach,
        "strengthBand": strength_band,
        "rarity": rarity,
        "traits": [],
        "costProfile": cost_profile,
        "targetPreference": target_preference,
        "variants": [],
        "acquisitionPaths": list(acquisition_paths),
        "footprint": footprint,
        "coverTier": cover_tier,
        "controlPoint": control_point,
        "obstacleVerbs": list(obstacle_verbs),
        "reason": "",  # filled in by the row's own `reason=` kwarg at the call site below
    }


def _magnitudes(
    *,
    structure_kind: str,
    cost: int = 0,
    yield_multiplier_milli: int = 1000,
    build_turns: int = 0,
    capacity_bonus: int = 0,
    flat_yield_per_turn: int = 0,
    construct_rubble_cost: int = 0,
    construct_ironwork_cost: int = 0,
    material_tier: int = 0,
    blocks_movement: bool = False,
    blocks_line_of_fire: bool = False,
    obstacle_kind: str = "None",
    cover_power_milli: int = 0,
    cover_radius: int = 0,
    entry_stamina_multiplier_milli: int = 1000,
    vision_range_tiles: "int | None" = None,
    container_id: "str | None" = None,
) -> dict:
    """The real `StructureDef` numbers for an import-ready row — see this module's own top-of-file
    note on why this exists beside (never inside) `anchor`. Defaults mirror `StructureDef`'s own
    C# field defaults exactly, so a row only needs to name what its real shipped values override.
    `vision_range_tiles=None` means "use SiegeTuningPolicy.Fog.DefaultVisionRangeTiles", the same
    fallback `StructureDef.VisionRangeTiles`'s own C# default already expresses — resolved on the
    C# side, not baked into this JSON as a copy of a value tuning could later change independently.

    `container_id=None` means "nothing to roll" — a real, correct state for every one of this
    corpus's 25 rows today (spec-structure-instantiate.md §1: cost/HP/footprint never roll, only
    traits/actions do, and no structure has authored trait/action content yet — that is
    `structure-planner`/`structure-pipeline`'s (27/28) own job, not this module's).

    `structure_kind` is REQUIRED, never derived from `anchor.role` — a second, deeper instance of
    this same module's `cost`/byte-identity finding, found while writing the C# importer itself:
    `anchor/schema.py`'s own `ROLE_TO_STRUCTURE_KIND` dict (Extract/Multiply -> LoamSource,
    Store/Bank -> Storage) is ALREADY WRONG against real shipped rows, not just incomplete —
    `hatchery` (Multiply) and `soul-conduit`/`extractor` (Bank/Extract) are all real, shipped
    `StructureKind.Yield` rows, not `LoamSource`/`Storage` as that dict predicts. `StructureKind` is
    a per-row AUTHORED fact, exactly like `cost`, never a pure function of `role` — see
    spec-structure-catalog-import.md's own Correction 2 for the full account (that dict is left
    as-is, unused by the real import path, and named as its own separate, deferred cleanup).
    """
    return {
        "structureKind": structure_kind,
        "cost": cost,
        "yieldMultiplierMilli": yield_multiplier_milli,
        "buildTurns": build_turns,
        "capacityBonus": capacity_bonus,
        "flatYieldPerTurn": flat_yield_per_turn,
        "constructRubbleCost": construct_rubble_cost,
        "constructIronworkCost": construct_ironwork_cost,
        "materialTier": material_tier,
        "blocksMovement": blocks_movement,
        "blocksLineOfFire": blocks_line_of_fire,
        "obstacleKind": obstacle_kind,
        "coverPowerMilli": cover_power_milli,
        "coverRadius": cover_radius,
        "entryStaminaMultiplierMilli": entry_stamina_multiplier_milli,
        "visionRangeTiles": vision_range_tiles,
        "containerId": container_id,
    }


def _title(structure_id: str) -> str:
    """Title-cases a kebab-case id into a display name ("soul-conduit" -> "Soul Conduit") — every
    one of this corpus's 25 ids happens to title-case into its intended display name directly
    EXCEPT `loam-source-placeholder` (needs the parenthesis `_row`'s own `name=` override supplies),
    so this covers 24 of 25 rows with no per-row typing at all."""
    return " ".join(w.capitalize() for w in structure_id.split("-"))


def _row(anchor: dict, *, source: str, citation: str, magnitudes: "dict | None" = None,
         name: "str | None" = None) -> dict:
    """`name` — a real gap found alongside `magnitudes` (see this module's own top-of-file note):
    `StructureDef.Name` is a human-readable display string, and the 21-field anchor schema has no
    field for it at all (identity there means `structureId`/`family`/`role`, never a display
    string). Kept as a fourth top-level sibling, not folded into `magnitudes` — a display name is
    identity, not a number, even though (like `magnitudes`) it needs SOMEWHERE beside the anchor to
    live. Present on every row (unlike `magnitudes`) since even an anchor-only row deserves a real
    name today, not a placeholder pending some future module.
    """
    anchor = dict(anchor)
    jsonschema.validate(anchor, _SCHEMA)
    row = {
        "id": anchor["structureId"],
        "name": name or _title(anchor["structureId"]),
        "anchor": anchor,
        "_provenance": {"source": source, "citation": citation},
    }
    if magnitudes is not None:
        row["magnitudes"] = magnitudes
    return row


def _dumped(anchor: dict, citation: str, *, magnitudes: dict, name: "str | None" = None) -> dict:
    return _row(anchor, source="AUTHORED", citation=citation, magnitudes=magnitudes, name=name)


def _authored(anchor: dict, citation: str) -> dict:
    return _row(anchor, source="AUTHORED", citation=citation)


# ---------------------------------------------------------------------------------------------
# 24.1 — the eight rows StructureCatalog.cs already ships, dumped first (the importer proof).
# Costs/yields/tiers are C#-side magnitudes this Python anchor never carries (spec §"Numeric
# types": none) — only the identity/ordinal facts an anchor can express are transcribed.
# ---------------------------------------------------------------------------------------------

DUMPED_ROWS: "tuple[dict, ...]" = (
    _dumped(
        _anchor("loam-source-placeholder", role="Extract", required_slot_kind="Rootbed",
                strength_band="rubble", rarity="chaff", cost_profile="cheap",
                acquisition_paths=("built",), control_point=True),
        "StructureCatalog.cs Seed[0] — the placeholder LoamSource proving the Rootbed mechanism "
        "before Well existed.",
        name="Loam Source (placeholder)",  # StructureCatalog.cs's own exact Name, not a title-case
        magnitudes=_magnitudes(structure_kind="LoamSource")),  # every other field at its default
    _dumped(
        _anchor("well", role="Extract", required_slot_kind="Rootbed",
                strength_band="rubble", rarity="sprout", cost_profile="moderate",
                acquisition_paths=("built",), control_point=True),
        "StructureCatalog.cs Seed[1] — raises a Rootbed's own loam yield (YieldMultiplierMilli).",
        # gk-core/data/tuning/loam.v4.json structures.wellCost/wellYieldMultiplierMilli/wellBuildTurns
        magnitudes=_magnitudes(structure_kind="LoamSource", cost=200, yield_multiplier_milli=2000,
                                build_turns=2)),
    _dumped(
        _anchor("waystation", role="Move", required_slot_kind="Seat",
                strength_band="rubble", rarity="sprout", cost_profile="moderate",
                acquisition_paths=("built",), control_point=True),
        "StructureCatalog.cs Seed[2]. Matches base-defense-ideal.md §5.21 R5 Move exactly: "
        "'waystation gives range' — the one R5 sub-capability already shipped.",
        # loam.v4.json structures.waystationCost/waystationBuildTurns; yield multiplier irrelevant
        # to a Seat's own zero base yield, so it stays 1000 (unchanged) per StructureCatalog.cs's
        # own comment on this exact row.
        magnitudes=_magnitudes(structure_kind="LoamSource", cost=300, build_turns=4)),
    _dumped(
        _anchor("granary", role="Store", required_slot_kind="Wildland",
                strength_band="rubble", rarity="sprout", cost_profile="moderate",
                acquisition_paths=("built",), control_point=True),
        "StructureCatalog.cs Seed[3]. Matches §5.21 R4 Store exactly: 'granary, +300, one stock'.",
        # loam.v4.json structures.granaryCost/granaryCapacityBonus/granaryBuildTurns
        magnitudes=_magnitudes(structure_kind="Storage", cost=150, build_turns=2, capacity_bonus=300)),
    _dumped(
        _anchor("soul-conduit", role="Bank", required_slot_kind="EssenceDeposit",
                strength_band="timber", rarity="grafted", cost_profile="steep",
                acquisition_paths=("built",), control_point=True),
        "StructureCatalog.cs Seed[4]. Matches §5.21 R6 Bank exactly: 'the Tier-2 faucet designed "
        "(soul conduit)'.",
        # loam.v4.json structures.soulConduitCost/soulConduitFlatYieldPerTurn/soulConduitBuildTurns
        magnitudes=_magnitudes(structure_kind="Yield", cost=250, build_turns=3, flat_yield_per_turn=20)),
    _dumped(
        _anchor("extractor", role="Extract", required_slot_kind="ShardVein",
                strength_band="rubble", rarity="sprout", cost_profile="moderate",
                acquisition_paths=("built",), control_point=True),
        "StructureCatalog.cs Seed[5]. Matches §5.21 R1 Extract's own named ShardVein gap "
        "('shard-vein x4 ... yield zero').",
        # loam.v4.json structures.extractorCost/extractorFlatYieldPerTurn/extractorBuildTurns
        magnitudes=_magnitudes(structure_kind="Yield", cost=200, build_turns=2, flat_yield_per_turn=15)),
    _dumped(
        _anchor("hatchery", role="Multiply", required_slot_kind="Lair",
                strength_band="rubble", rarity="sprout", cost_profile="moderate",
                acquisition_paths=("built",), control_point=True),
        "StructureCatalog.cs Seed[6]. Raises a Lair's own recruit yield (YieldMultiplierMilli) — "
        "§5.21 R3 Multiply: 'raise another producer's yield'.",
        # loam.v4.json structures.hatcheryCost/hatcheryYieldMultiplierMilli/hatcheryBuildTurns —
        # "deliberately non-identity real content, not a placeholder shape-proof" per that file's
        # own _meta note.
        magnitudes=_magnitudes(structure_kind="Yield", cost=300, yield_multiplier_milli=1500, build_turns=3)),
    _dumped(
        _anchor("moat", role="Deny", required_slot_kind="Wildland",
                strength_band="rubble", rarity="sprout", cost_profile="moderate",
                acquisition_paths=("built", "assembled", "summoned", "laboured"),
                control_point=False, obstacle_verbs=("BLOCK", "BLOCK-LOF")),
        "StructureCatalog.cs Seed[7] (added by siege-construction 15.3b, 2026-09-06). Is §5.18 "
        "kind 2 Rampart under a different name — the source's own cut table: 'Moat / anti-tank "
        "ditch -> Rampart: a cell you cannot enter and cannot stand on IS a wall. Identical "
        "verbs.'",
        # siege.v1.json construction.labourMoatTurns/refineRubblePerIronwork; MaterialTier=1 here
        # happens to already agree with Bands.MaterialTierOf("rubble") -- authored explicitly
        # anyway, per this module's own stated rule that magnitudes.materialTier is always the
        # authoritative source once present, never left to agree with strengthBand by coincidence.
        magnitudes=_magnitudes(structure_kind="Obstacle", build_turns=2, material_tier=1,
                                blocks_movement=True, blocks_line_of_fire=True,
                                obstacle_kind="Rampart", construct_rubble_cost=4,
                                construct_ironwork_cost=1)),
)

# ---------------------------------------------------------------------------------------------
# 24.2 — 17 new hand-authored rows, every one citing §5.18 or §5.21. See this module's own
# top-of-file note for why 17 (not ~36) is the honestly-grounded number at this corpus size.
# ---------------------------------------------------------------------------------------------

AUTHORED_ROWS: "tuple[dict, ...]" = (
    # ---- Deny (2 new; moat above makes 3 total) — §5.18 kinds 3 and 4 -------------------------
    _authored(
        _anchor("wire", role="Deny", required_slot_kind="Wildland",
                strength_band="rubble", rarity="sprout", cost_profile="cheap",
                acquisition_paths=("built", "laboured"), control_point=False,
                obstacle_verbs=("SLOW",)),
        "§5.18 kind 3, Wire: SLOW verb, bulk material, 'the cheapest' — multiplies the stamina "
        "cost of entering the cell. NOT a block, NOT cover (source's own distinction from "
        "Rampart)."),
    _authored(
        _anchor("mine", role="Deny", required_slot_kind="Wildland",
                strength_band="timber", rarity="sprout", cost_profile="moderate",
                acquisition_paths=("laboured", "summoned", "assembled"), control_point=False,
                obstacle_verbs=("BITE", "DENY")),
        "§5.18 kind 4, Mine: BITE+DENY, ironwork, damage-on-entry, single-use, unrevealed to the "
        "other side, 'the only obstacle that punishes the safe-looking cell' — ignores cover."),

    # ---- Defend (2 new) — §5.18 kind 1 and the one named building -----------------------------
    _authored(
        _anchor("trench", role="Defend", required_slot_kind="Wildland",
                strength_band="rubble", rarity="sprout", cost_profile="cheap",
                cover_tier="trench", acquisition_paths=("built", "laboured"),
                control_point=False, obstacle_verbs=("COVER",)),
        "§5.18 kind 1, Trench: COVER verb, bulk, occupiable and passable, grants a flat "
        "combat.dodge delta. 'Two tiers by value (sandbag / revetted)' resolves via strengthBand "
        "at import — never a second row (spec's own 'never a tier chain as separate rows')."),
    _authored(
        _anchor("emplacement", role="Defend", required_slot_kind="Wildland",
                tempo="steady", reach="short", strength_band="stone", rarity="grafted",
                cost_profile="steep", footprint="small", cover_tier="heavy",
                acquisition_paths=("built",), control_point=True, obstacle_verbs=("COVER",)),
        "§5.18's Emplacement row: 'a building, not an obstacle', ironwork, garrisoned, acts "
        "through its occupant who gets high cover plus a ranged action. Decision 25's own table: "
        "the one Defend-role row WITH a control point — 'Occupies, blocks, has HP — fires "
        "nothing' ungarrisoned."),

    # ---- See (2 new) — structure-schema's own reserved-but-unmapped role, given real content ---
    _authored(
        _anchor("watchtower", role="See", required_slot_kind="Spire",
                reach="long", strength_band="timber", rarity="grafted", cost_profile="steep",
                acquisition_paths=("built",), control_point=True),
        "structure-schema's reserved-but-unmapped See role, given its first real content per "
        "spec-siege-fog.md §2: a See-role structure authors a larger VisionRangeTiles than the "
        "default. Spire (an unused SlotKind until now) fits height-for-vision thematically."),
    _authored(
        _anchor("lookout-post", role="See", required_slot_kind="Wildland",
                reach="short", strength_band="rubble", rarity="sprout", cost_profile="cheap",
                acquisition_paths=("built", "laboured"), control_point=True),
        "A cheaper, shorter-range See-role structure than Watchtower — a distinct acquisition "
        "niche per §5.24's own Laboured path ('digging a moat, throwing up a berm ... any actor, "
        "no materials at all'), not a tier of the same building."),
    _authored(
        _anchor("beacon", role="See", required_slot_kind="Spire",
                reach="long", strength_band="timber", rarity="sprout", cost_profile="moderate",
                acquisition_paths=("built",), control_point=True),
        "A network-effect See-role structure, same spec-siege-fog.md §2 VisionRangeTiles payoff "
        "as Watchtower (extends allied vision chain-of-sight rather than a single high point) — "
        "the third distinct See niche alongside Watchtower's authored range and Lookout-post's "
        "cheap range."),

    # ---- Extract (1 new; 3 dumped make 4 total) — §5.21 R1's own named MaterialSeam gap --------
    _authored(
        _anchor("seam-works", role="Extract", required_slot_kind="MaterialSeam",
                strength_band="rubble", rarity="sprout", cost_profile="moderate",
                acquisition_paths=("built",), control_point=True),
        "§5.21 R1's own named gap: 'material-seam x3 yield ZERO'. Closes the second half of R1's "
        "stated deficiency (extractor, dumped above, already closes the ShardVein half)."),

    # ---- Refine (1 new) — §5.21's own explicitly-named 'strongest addition' -------------------
    _authored(
        _anchor("refinery", role="Refine", required_slot_kind="Wildland",
                strength_band="timber", rarity="grafted", cost_profile="steep",
                acquisition_paths=("built",), control_point=True),
        "§5.21's own R2 Refine, called out as the 'strongest addition' and missing until now: "
        "'ironwork is produced from bulk material at a lossy, gated rate ... couples the two "
        "stocks by a build decision.' Matches the already-tunable "
        "SiegeTuningPolicy.Construction.RefineRubblePerIronwork this session's own "
        "siege-construction 15.3b work introduced."),

    # ---- Multiply (1 new; hatchery above makes 2 total) ----------------------------------------
    _authored(
        _anchor("workshop", role="Multiply", required_slot_kind="Wildland",
                strength_band="rubble", rarity="sprout", cost_profile="moderate",
                acquisition_paths=("built",), control_point=True),
        "§5.21 R3 Multiply's own definition ('raise another producer's yield') given a second, "
        "generic instance beyond Hatchery's Lair-only case."),

    # ---- Store (2 new; granary above makes 3 total) — per-stock capacity, not a shared pool ----
    _authored(
        _anchor("stockyard", role="Store", required_slot_kind="Wildland",
                strength_band="rubble", rarity="sprout", cost_profile="moderate",
                acquisition_paths=("built",), control_point=True),
        "§5.21 Storage: 'per-stock capacity, extending what the granary already does' — the "
        "bulk/rubble stock's own capacity building. A shared pool would silently undo P4's "
        "min(bulk, ironwork) bottleneck (§5.21's own explicit warning)."),
    _authored(
        _anchor("coffer", role="Store", required_slot_kind="Wildland",
                strength_band="timber", rarity="sprout", cost_profile="steep",
                acquisition_paths=("built",), control_point=True),
        "§5.21 Storage, the same per-stock rule as Stockyard, for the ironwork stock specifically."),

    # ---- Move (2 new; waystation above makes 3 total) — throughput and protection, named gaps -
    _authored(
        _anchor("causeway", role="Move", required_slot_kind="Wildland",
                strength_band="rubble", rarity="sprout", cost_profile="moderate",
                acquisition_paths=("built",), control_point=True),
        "§5.21 R5 Move's own named gap: 'nothing gives throughput' (waystation gives only "
        "range). Ties to WorldLane.Width, the shipped-but-unread logistics field §5.21 names "
        "directly."),
    _authored(
        _anchor("convoy-depot", role="Move", required_slot_kind="Wildland",
                strength_band="rubble", rarity="sprout", cost_profile="moderate",
                acquisition_paths=("built",), control_point=True),
        "§5.21 R5 Move's third named gap: 'nothing gives protection'. Ties to "
        "WorldLane.WardLevel, the shipped-but-unread interdiction field §5.21 names directly."),

    # ---- Bank (1 new; soul-conduit above makes 2 total) ----------------------------------------
    _authored(
        _anchor("reliquary", role="Bank", required_slot_kind="Shrine",
                strength_band="timber", rarity="grafted", cost_profile="steep",
                acquisition_paths=("built",), control_point=True),
        "§5.21's R6 Bank role, a second concept beyond Soul Conduit's EssenceDeposit case, sited "
        "on Shrine (an unused SlotKind until now)."),

    # ---- Enable (2 new) — §5.21 R8's own named gap: gates what may be built ---------------------
    _authored(
        _anchor("district-charter", role="Enable", required_slot_kind="Market",
                strength_band="stone", rarity="grafted", cost_profile="steep",
                acquisition_paths=("built",), control_point=True),
        "§5.21 R8 Enable's own definition: 'gates what may be built here — the district tier'. "
        "Sited on Market (an unused SlotKind until now) — a trade/rights hub gating further "
        "economic construction."),
    _authored(
        _anchor("garrison-charter", role="Enable", required_slot_kind="Vault",
                strength_band="stone", rarity="grafted", cost_profile="steep",
                acquisition_paths=("built",), control_point=True),
        "§5.21's R8 Enable role, a second concept distinct from district-charter: gates MILITARY "
        "(Defend/See/Deny) construction rather than economic, since base-defense's own combat "
        "roles are new territory separate from the pre-existing R1-R6 economy §5.21 describes. "
        "Sited on Vault (an unused SlotKind until now)."),
)

ALL_ROWS: "tuple[dict, ...]" = DUMPED_ROWS + AUTHORED_ROWS


def file_tree() -> "dict[str, dict[str, Any]]":
    """Maps ``<role-lowercase>/<structureId>.json`` (posix-style relative path) to that file's
    full on-disk document. Pure and deterministic — no timestamp, no random id, so two calls (or
    two processes) always produce byte-identical output (task 24.3's own idempotency contract)."""
    tree: "dict[str, dict[str, Any]]" = {}
    for row in ALL_ROWS:
        role = row["anchor"]["role"]
        rel = f"{role.lower()}/{row['id']}.json"
        tree[rel] = {"kind": "structure-anchor", "_meta": {"partition": role}, "entries": [row]}
    return tree


def write_corpus(root: Path) -> "list[Path]":
    """Writes `file_tree()` under `root`, creating role directories as needed. Returns the list
    of paths written, sorted, for a caller that wants to hash or list them."""
    written: "list[Path]" = []
    for rel, doc in sorted(file_tree().items()):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        # sort_keys + trailing newline: stable, byte-identical across reruns and across OSes.
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    import sys

    repo_root = Path(__file__).resolve().parents[5]
    out_root = repo_root / "data" / "seed" / "structures"
    paths = write_corpus(out_root)
    print(f"wrote {len(paths)} structure anchor rows under {out_root}", file=sys.stderr)
