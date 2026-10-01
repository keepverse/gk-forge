"""seedsmith.adapters.items.recipegen.forgegem — the DETERMINISTIC forge-gem row emitter
(species-gear-chain T9, spec-gem-tier.md §4).

Why deterministic, not briefed: a forge-gem row carries no authored choice. Same family, tier k
to tier k+1, output the lowest container id in (family, k+1) — every one of those is read off the
gem corpus, so a model call would only retype facts. The LLM authors identity (names, flavor) and
atom-family picks; magnitudes and derivations are table-owned — and this row is ALL derivation.
No ledger either: planning is idempotent (a step already covered by a shipped forge-gem row with
the same outputRef is skipped), so re-running converges instead of duplicating.

Deterministic rules, all stated here (a future author changes the RULE, never a row):
- steps: every (family, t -> t+1) with entries on both tiers. 97 of 98 shipped families are
  single-tier — only atom.elemental-power spans (t2+t3) — so this emits ONE row today. More
  multi-tier families (gemgen's future) mean more rows with no code change.
- output: the lowest container id in (family, t+1).
- cost lines: shard.<rung-at-tier-index> (RungIds[outputTier] — the tier-indexed rung, the same
  deterministic rule the C# verb documents for its rung input), essence.<output element, else
  fire>, catalyst.forge — the operation's own three priced legs (operations.forge-gem).
- bands: tier-scaled {3: modest, 4: standard, 5: steep} for every line incl. souls.
- name: "Forge Gem: <Family Words> <t> to <t+1>" (family suffix after "atom.", title-cased).

Band->tier is `UniqueBudget.TierOfPowerBand` (UniqueBudget.cs:24-33: low 2, medium 3, high 4),
transcribed with citation — the same discipline opvocab states for the operation vocabulary.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..materialgen import vocab as material_vocab
from . import emit as emit_mod
from . import opvocab

REPO_ROOT = Path(__file__).resolve().parents[6]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from ....workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

GEMS_DIR = _owned("data/seed/items/gems")

#: `UniqueBudget.TierOfPowerBand` (gk-core/src/FusionRpg.Core/Items/Uniques/UniqueBudget.cs:24-33).
BAND_TIER = {"low": 2, "medium": 3, "high": 4}

#: Cost-band ladder by OUTPUT tier — steeper gems cost steeper bands on every line.
TIER_BAND = {3: "modest", 4: "standard", 5: "steep"}

#: The ten rung ids, weakest first — read live from `seedsmith.ladders` (T-2: never
#: re-transcribed here).
from seedsmith.ladders import RARITY_LADDER


def load_gem_entries(gems_dir: "Path | None" = None) -> "list[dict[str, Any]]":
    directory = gems_dir or GEMS_DIR
    entries: "list[dict[str, Any]]" = []
    for path in sorted(directory.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for entry in doc.get("entries", []):
            if isinstance(entry.get("id"), str):
                entries.append(entry)
    return entries


def plan_steps(entries: "list[dict[str, Any]]") -> "list[tuple[str, int, dict[str, Any]]]":
    """Every (family, t -> t+1) step with entries on both tiers — (family, outputTier, outputEntry).
    Output entry: the lowest container id in (family, t+1). Sorted by (family, tier) for a stable
    plan across runs."""
    by_family_tier: "dict[tuple[str, int], list[dict[str, Any]]]" = {}
    for entry in entries:
        tier = BAND_TIER.get(entry.get("powerBand", ""))
        if tier is None:
            continue
        by_family_tier.setdefault((entry["family"], tier), []).append(entry)
    steps: "list[tuple[str, int, dict[str, Any]]]" = []
    for (family, tier), group in by_family_tier.items():
        ups = by_family_tier.get((family, tier + 1))
        if not ups:
            continue
        steps.append((family, tier + 1, sorted(ups, key=lambda e: e["id"])[0]))
    steps.sort(key=lambda s: (s[0], s[1]))
    return steps


def build_entry(family: str, output_tier: int, output: "dict[str, Any]", *, seq: int) -> "dict[str, Any]":
    """One forge-gem recipe entry, shaped exactly like a real recipes.json entry."""
    band = TIER_BAND.get(output_tier)
    if band is None:
        raise ValueError(f"no cost band laddered for output tier {output_tier}")
    element = output.get("element") or "fire"
    cost_lines = [
        {"material": f"shard.{RARITY_LADDER[output_tier]}", "costBand": band},
        {"material": f"essence.{element}", "costBand": band},
        {"material": "catalyst.forge", "costBand": band},
    ]
    for line in cost_lines:
        material_vocab.require_issuable(line["material"])
        opvocab.check_cost_class("forge-gem", material_vocab.ISSUABLE_BY_ID[line["material"]].material_class,
                                 line["material"])
    family_words = family.split(".")[-1].replace("-", " ").title()
    name = f"Forge Gem: {family_words} {output_tier - 1} to {output_tier}"
    minted_id = emit_mod.recipe_id(seq)
    return {
        "id": minted_id,
        "nameKey": emit_mod.name_key_for(minted_id),
        "name": name,
        "operation": "forge-gem",
        "outputKind": opvocab.output_kind_for("forge-gem"),
        "outputRef": output["id"],
        "outputQty": 1,
        "frame": "any",
        "costLines": cost_lines,
        "soulsCostBand": band,
        "tags": emit_mod.tags_for("forge-gem"),
    }


def plan_rows(entries: "list[dict[str, Any]]", *, existing: "dict[str, dict]",
              start_seq: int) -> "list[dict[str, Any]]":
    """Rows for every planned step not already covered by a shipped forge-gem row with the same
    outputRef — idempotent: re-running after a write plans nothing."""
    covered = {e.get("outputRef") for e in existing.values() if e.get("operation") == "forge-gem"}
    rows: "list[dict[str, Any]]" = []
    seq = start_seq
    for family, output_tier, output in plan_steps(entries):
        if output["id"] in covered:
            continue
        rows.append(build_entry(family, output_tier, output, seq=seq))
        seq += 1
    return rows
