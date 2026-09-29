"""Prose for every structure anchor attribute (base-defense `structure-schema`, module 23,
spec-structure-schema.md §1) — the reliability mechanism, not documentation. Each description
states what the field means, what distinguishes it from its nearest neighbour, and an explicit
**negative clause**: what the field is *not*. Ports `adapters/creatures/anchor/descriptions.py`'s own
convention verbatim onto the structure anchor's 17-field contract.

Edited far more often than schema.py's shape, which is why it lives in its own module.
"""
from __future__ import annotations

DESCRIPTIONS: dict = {
    "structureId": (
        "The structure's stable, kebab-case identifier, e.g. 'stone-rampart'. This is an "
        "identifier for lookups, NOT a display name and NOT a description of the structure."
    ),
    "family": (
        "A loose grouping label such as 'earthwork', 'emplacement', or 'works' — for organizing "
        "the roster, not for gameplay. This is NOT the role (what the structure is FOR) and NOT "
        "the requiredSlotKind (WHERE it sits)."
    ),
    "role": (
        "What this structure is for, on the ten-role vocabulary (Extract, Refine, Multiply, "
        "Store, Move, Bank, Enable, Defend, See, Deny). This is NOT which engine path reads it — "
        "that is StructureKind, DERIVED from this field, never authored beside it."
    ),
    "roleSecondary": (
        "A second role this structure leans on, or 'none' if its purpose is singular. NOT a "
        "ranking of importance versus role — a genuinely secondary purpose, at lower weight. Most "
        "structures legitimately have none; do not invent a secondary role just because the field "
        "exists."
    ),
    "requiredSlotKind": (
        "Which of the fourteen shipped slot kinds this structure must sit on (e.g. Rootbed, "
        "ShardVein, Wildland). This is NOT the structure's role and NOT a description of terrain — "
        "it is a hard placement requirement checked against the world's own slot catalog."
    ),
    "elementPrimary": (
        "The element this structure is attuned to (fire, ice, air, earth, light, dark), or 'none' "
        "if it has no elemental attunement — most structures legitimately have none. This is NOT a "
        "resistance and NOT a weakness."
    ),
    "elementSecondary": (
        "A second attuned element alongside elementPrimary, or 'none' if it has only one (or "
        "none). NOT a resistance — do not invent a secondary element just because the field exists."
    ),
    "tempo": (
        "For an emplacement, how quickly it acts, on the shared attack-tempo ladder (ponderous, "
        "slow, steady, quick, flurry), or 'none' for every non-emplacement structure — this field "
        "is NOT authored for a structure that never acts on its own initiative. NOT a magnitude: "
        "the deterministic layer turns the ordinal into a real interval, never the model."
    ),
    "reach": (
        "How far this structure's effect extends, on the shared reach ladder (melee, short, long, "
        "siege). This is NOT a cell count — the deterministic layer converts the ordinal into board "
        "cells; the model never picks a number of cells directly."
    ),
    "strengthBand": (
        "This structure's position on the authored material-tier ladder (e.g. 'rubble' < "
        "'timber' < 'stone', extended by structure-planner before any model call). This IS "
        "decision 32's material tier — it feeds HP and damage through P(Theta) via a tuning-file "
        "multiplier. NOT a raw HP value, NOT a raw damage value, and there is NO separate "
        "'materialTier' field beside it — this ordinal is the only one."
    ),
    "rarity": (
        "This structure's position on the shared ten-rung rarity ladder. Per the rarity SSOT, "
        "rarity buys BREADTH and CEILING — how many variants exist and what the top of the range "
        "looks like — and NEVER buys power directly. NOT a strength value."
    ),
    "traits": (
        "An open list of trait ids this structure carries, from the shared trait registry. This is "
        "NOT free-form flavour text — every entry must be a real, registered trait id, checked "
        "against that registry, never invented here."
    ),
    "costProfile": (
        "WHICH materials this structure costs, in what ratio band (e.g. 'cheap', 'moderate', "
        "'steep') — NEVER an amount. The actual rubble/ironwork quantities live in the tuning file, "
        "keyed by this ordinal; this field names the band, not a number."
    ),
    "targetPreference": (
        "Which kind of enemy this structure's own attack (if any) prefers, on the closed "
        "First/Last/Close/Strong vocabulary, or 'none' if it has no attack of its own. NOT a "
        "targeting UI control — see base-defense's own 'statability, not configurability' rule; "
        "this is what the structure does, stated once, never a player-facing dial."
    ),
    "variants": (
        "An open list naming this structure's own sibling tier ids (e.g. a stone wall's list "
        "naming its iron-wall and rubble-wall siblings) — a tier CHAIN is one row with a variants "
        "list, NOT four separate catalog rows. NOT a list of cosmetic skins."
    ),
    "acquisitionPaths": (
        "Which of the four ways (built, assembled, summoned, laboured) can put this structure on "
        "the board. MAY NOT be empty — a structure no path can produce is a catalog row that can "
        "never appear on a board. This is NOT the same question as how a structure reached the map "
        "(that fact is derivable from world state and is never a seed field — there is no "
        "'acquisition' field here, deliberately)."
    ),
    "footprint": (
        "How much space this structure occupies (one cell, small, or large). NOT a cell count and "
        "NOT a radius — the deterministic layer turns this ordinal into real board geometry."
    ),
    "coverTier": (
        "How much cover this structure projects (none, light, heavy, or trench). NOT a numeric "
        "cover value — the deterministic layer resolves this ordinal into the real per-mille power "
        "`siege-cover` already computes."
    ),
    "reason": (
        "Free text explaining why this structure exists / what makes it distinct from its nearest "
        "neighbour on the roster. This is IDENTITY text for a human reviewer, NEVER a magnitude and "
        "never parsed for a number."
    ),
    "controlPoint": (
        "Whether this structure functions as a contested objective in its own right, DERIVED from "
        "role + requiredSlotKind by the importer. NEVER authored freehand, and NEVER a magnitude."
    ),
    "obstacleVerbs": (
        "An open list of interaction verbs this structure supports (e.g. 'raze', 'garrison'), "
        "DERIVED from role + requiredSlotKind by the importer. NEVER authored freehand by a model."
    ),
}
