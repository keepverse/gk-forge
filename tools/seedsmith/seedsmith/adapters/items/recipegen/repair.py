"""seedsmith.adapters.items.recipegen.repair — the DETERMINISTIC workbench-repair row emitter
(species-gear-chain T23, `spec-item-durability-repair.md` §5, D1/D2/D5).

Why deterministic, not briefed: a repair row carries no authored choice. Its legs ARE its
operation's own priced row (`operations.repair` in the shipped materials tuning), and the D5 shard leg is
rung-gated by that row's `variable`, so a model call would only retype facts. Same discipline
`forgegem.py` states for its own row.

One row, `frame: "any"` with an explicit substrate line — the shape `elevate` already ships
(`recipe.009`), because a mutation verb whose target frame varies per item cannot author one
substrate id per frame.

Deterministic rules, all stated here (a future author changes the RULE, never a row):
- one row, ever: `plan_rows` emits nothing once any shipped row's operation is `repair`
  (idempotent — re-running converges instead of duplicating).
- cost lines: `substrate.humanoid.crude` + `catalyst.temper`, the two legs the operation's own
  `Allows` arm admits besides souls and the rung-gated shard; both bands `standard`, matching
  elevate's first values.
- name: "Repair: Restore Durability".
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..materialgen import vocab as material_vocab
from . import emit as emit_mod
from . import opvocab


def build_entry(*, seq: int) -> "dict[str, Any]":
    """The one repair recipe entry, shaped exactly like a real `recipes.json` entry."""
    cost_lines = [
        {"material": "substrate.humanoid.crude", "costBand": "standard"},
        {"material": "catalyst.temper", "costBand": "standard"},
    ]
    for line in cost_lines:
        material_vocab.require_issuable(line["material"])
        opvocab.check_cost_class("repair", material_vocab.ISSUABLE_BY_ID[line["material"]].material_class,
                                 line["material"])
    minted_id = emit_mod.recipe_id(seq)
    return {
        "id": minted_id,
        "nameKey": emit_mod.name_key_for(minted_id),
        "name": "Repair: Restore Durability",
        "operation": "repair",
        "outputKind": opvocab.output_kind_for("repair"),
        "outputQty": 1,
        "frame": "any",
        "costLines": cost_lines,
        "soulsCostBand": "standard",
        "tags": emit_mod.tags_for("repair"),
    }


def plan_rows(*, existing: "dict[str, dict]", start_seq: int) -> "list[dict[str, Any]]":
    """The row to add, or nothing when the corpus already carries a `repair` row — idempotent."""
    if any(e.get("operation") == "repair" for e in existing.values()):
        return []
    return [build_entry(seq=start_seq)]
