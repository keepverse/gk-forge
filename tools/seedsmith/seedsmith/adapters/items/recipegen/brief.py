"""seedsmith.adapters.items.recipegen.brief — the model-facing brief, and every closed vocabulary
it draws from, read fresh from real registries/tuning/corpora rather than hand-copied.

**`(role, frame, band)` is a caller input, never a model choice, for a `forge`-operation draw** —
the same disposition `basetypegen.brief`'s own docstring states for its own partition triple: a
per-call model-chosen target partition would silently redraw the 30-role-frame taxonomy once per
call. A caller wanting a `forge` recipe names the partition; the model then either points at an
EXISTING, un-recipe'd base type in it or asks to mint a new one (`schema.MINT_NEW_SENTINEL`) —
never an arbitrary id string.

**Material ids and cost bands are the full closed vocabularies, always** — 27 issuable ids
(`materialgen.vocab.ISSUABLE`) and 5 cost bands (`bands.v1.json`, mirrored into
`gk-core/data/tuning/materials.v2.json`'s own `costBandMultiplierPerMille` and read fresh from there, never
hand-typed a second time in this package — the same "read the mirror the C# class itself reads"
discipline `materialgen.vocab`'s own module docstring states).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from seedsmith.adapters.items.acquisition import Acquisition
from seedsmith.corpus import Corpus
from seedsmith.pipeline.model import audit_schema

from ..basetypegen import emit as basetype_emit
from ..basetypegen import run as basetype_run
from ..basetypegen import tuning as basetype_tuning
from ..materialgen import vocab as material_vocab
from . import opvocab
from .schema import FRAMES, MINT_NEW_SENTINEL, recipe_schema

REPO_ROOT = Path(__file__).resolve().parents[6]
#: Mirrors the C# `SocketTuningFiles.Materials` (strain-splice-host SSH8.4) — currently v5, and it
#: moves with that constant when a reprice publishes the next revision.
MATERIALS_TUNING_PATH = REPO_ROOT / "data" / "tuning" / "materials.v6.json"
RECIPES_CORPUS_PATH = REPO_ROOT / "data" / "seed" / "items" / "recipes" / "recipes.json"

_NOTE_KEYS = {"mirrorNote", "applicationNote"}


class BriefBuildError(ValueError):
    """This module's own inputs (tuning, a forge target) are structurally unusable."""


def load_cost_bands(path: "Path | None" = None) -> "tuple[str, ...]":
    """The real, closed cost-band vocabulary, read fresh from `materials.v2.json`'s own
    `costBandMultiplierPerMille` (the mirror `MaterialTuning.ParseBands` itself parses) — sorted by
    ascending multiplier, matching `MaterialTuning.BandMultiplier`'s own error message ordering
    (`OrderBy(k => BandMultipliersPerMille[k])`)."""
    doc = json.loads((path or MATERIALS_TUNING_PATH).read_text(encoding="utf-8"))
    bands = doc.get("costBandMultiplierPerMille")
    if not isinstance(bands, dict):
        raise BriefBuildError("materials.v2.json has no costBandMultiplierPerMille object")
    numeric = {k: v for k, v in bands.items() if k not in _NOTE_KEYS and isinstance(v, (int, float))}
    if not numeric:
        raise BriefBuildError("materials.v2.json's costBandMultiplierPerMille has no bands")
    return tuple(sorted(numeric, key=lambda k: numeric[k]))


def load_material_pool(items_root: "Path | None" = None) -> "tuple[str, ...]":
    """Issued materials the player can obtain in the current corpus, in catalog order.

    Issuable is necessary but insufficient: a recipe spending an issued material that no drop table
    yields and no material-output recipe produces is a gated reachability defect. This mirrors
    `metrics.linkage.RecipeInputs` before the model sees its vocabulary, so new recipes cannot add
    another unreachable input while old corpus debt is reconciled separately.
    """
    corpus = Corpus.load(items_root or REPO_ROOT / "data" / "seed" / "items")
    acquisition = Acquisition.build(corpus)
    obtainable = set(acquisition.material_runtime_ids)
    obtainable.update(
        recipe.get("outputRef")
        for recipe in corpus.by_kind("recipe")
        if recipe.get("outputKind") == "material" and recipe.get("outputRef")
    )
    return tuple(m.runtime_id for m in material_vocab.ISSUABLE if m.runtime_id in obtainable)


def load_used_container_refs(recipes_path: "Path | None" = None) -> "frozenset[str]":
    """Every `outputRef` an EXISTING `container`-output recipe already names, read fresh from the
    real corpus — an `existing_forge_candidates` call excludes these so this generator never
    proposes a second recipe crafting the exact same base type twice."""
    p = recipes_path or RECIPES_CORPUS_PATH
    if not p.exists():
        return frozenset()
    doc = json.loads(p.read_text(encoding="utf-8"))
    return frozenset(
        e["outputRef"] for e in doc.get("entries", [])
        if e.get("outputKind") == "container" and e.get("outputRef"))


@dataclass(frozen=True)
class ForgeTarget:
    """One `(role, frame, band)` base-types-gen partition a `forge`-operation draw may reference.
    Resolved once so the brief text, the schema enum, and `emit.py`'s own resolution can never
    silently disagree about what is legal — the same reason `basetypegen.brief.PartitionContext`
    exists."""

    role: str
    frame: str
    band: str
    frame_role_name: str
    existing_ids: "tuple[str, ...]"
    next_mint_id: str

    @property
    def partition_key(self) -> str:
        return f"{self.role}:{self.frame}:{self.band}"


def load_forge_target(role: str, frame: str, band: str, *,
                      base_types_dir: "Path | None" = None,
                      recipes_path: "Path | None" = None) -> ForgeTarget:
    """Reads the real, current state of one base-types-gen partition and computes the exact next
    mintable id in it, via `basetypegen`'s own `emit.entry_id`/`emit.next_seq` — never a guess, and
    never a second id-minting formula living in this package."""
    if frame not in ("humanoid", "plant"):
        raise BriefBuildError(f"frame must be 'humanoid' or 'plant', got {frame!r}")
    info = basetype_tuning.role_info(role)
    frame_role_name = info.frame_role_name(frame)
    existing = basetype_run.load_existing(role, frame, band, base_types_dir=base_types_dir)
    next_seq = basetype_emit.next_seq(tuple(existing))
    next_mint_id = basetype_emit.entry_id(frame, frame_role_name, band, next_seq)
    return ForgeTarget(role=role, frame=frame, band=band, frame_role_name=frame_role_name,
                       existing_ids=tuple(sorted(existing)), next_mint_id=next_mint_id)


def existing_forge_candidates(target: ForgeTarget, *, recipes_path: "Path | None" = None,
                              limit: int = 20) -> "tuple[str, ...]":
    """Ids in `target`'s partition NOT already crafted by an existing recipe — the small,
    partition-scoped pool a model may point `outputTarget` at instead of minting a new one. Capped
    at `limit` (never the whole partition) the same way `basetypegen.brief`'s own
    `_existing_names_line` caps its printed sample, so the brief text stays readable."""
    used = load_used_container_refs(recipes_path)
    free = tuple(i for i in target.existing_ids if i not in used)
    return free[:limit]


@dataclass(frozen=True)
class RecipeBrief:
    """One brief, one generation call. `forge_target` is `None` for a call that must not offer
    `"forge"` at all (no partition has been scoped) — `__post_init__` enforces that pairing so a
    schema offering `"forge"` with no way to resolve its target can never be constructed."""

    forge_target: "ForgeTarget | None"
    operations: "tuple[str, ...]"
    material_pool: "tuple[str, ...]"
    cost_bands: "tuple[str, ...]"
    theme_note: str = ""
    existing_names: "tuple[str, ...]" = ()
    schema: "Mapping[str, Any]" = field(default_factory=dict)

    def __post_init__(self) -> None:
        if "forge" in self.operations and self.forge_target is None:
            raise BriefBuildError(
                "operations includes 'forge' but no forge_target was scoped — a forge draw always "
                "names a caller-chosen (role, frame, band) partition, never lets the model invent one")
        for op in self.operations:
            opvocab.require_supported_operation(op)
        schema = self.schema or recipe_schema(
            operations=self.operations, material_pool=self.material_pool,
            cost_bands=self.cost_bands,
            container_candidates=(existing_forge_candidates(self.forge_target)
                                  if self.forge_target is not None else None))
        defects = audit_schema(schema)
        if defects:
            raise BriefBuildError(
                "recipe brief has an unusable schema:\n" + "\n".join(f"  - {d}" for d in defects))
        object.__setattr__(self, "schema", schema)

    def render(self) -> str:
        theme_line = f"\nTheme: {self.theme_note}" if self.theme_note else ""
        def cost_rule(operation: str) -> str:
            allowed = ', '.join(sorted(opvocab.ALLOWED_CLASSES[operation])) or '(no materials)'
            catalyst = opvocab.catalyst_for(operation)
            return f"  - {operation}: {allowed}" + (
                f"; if using a catalyst, it must be {catalyst}" if catalyst else "")

        cost_rules = "\n".join(cost_rule(operation) for operation in self.operations)
        forge_lines = ""
        if self.forge_target is not None:
            candidates = existing_forge_candidates(self.forge_target)
            forge_lines = f"""

If you choose `operation: "forge"`, this draw mints for partition
{self.forge_target.partition_key!r} (frame-role slot {self.forge_target.frame_role_name!r}).
Set `outputTarget` to one of these existing, not-yet-recipe'd base types:
{chr(10).join('  - ' + c for c in candidates) or '  (none free — every existing entry already has a recipe)'}
...or to the literal {MINT_NEW_SENTINEL!r} to request a brand new one (its exact id, resolved by
code, would be {self.forge_target.next_mint_id!r})."""

        return f"""Author ONE NEW crafting recipe.{theme_line}

Choose, and nothing else:
1. `name` — a short authored display name, e.g. "Forge: Cloth Armor" or "Reroll: Reshape Common".
2. `flavor` — optional, one short sentence, never a number.
3. `operation` — the craft verb. `outputKind` follows mechanically from this, never a second
   choice: `forge` mints a container, `upcycle` mints a material, everything else mutates an
   instance the player already owns.
4. `frame` — `humanoid`, `plant`, or `any` (every mutation-output recipe in the shipped corpus is
   `any`, since it works on whatever instance the player owns).
5. `costLines` — zero or more `{{material, costBand}}` pairs. `material` is one of the
   {len(self.material_pool)} obtainable, issuable ids below; `costBand` is one of the 5 bands below.
   Never invent a material id or a bare number — a band is what you author, not a quantity. An empty list is always legal. If you add a material,
   its class MUST be permitted for your chosen operation by this matrix:
{cost_rules}
6. `soulsCostBand` — optional, one of the 5 bands below.{forge_lines}

Legal operations ({len(self.operations)}): {', '.join(self.operations)}

Obtainable material ids ({len(self.material_pool)}): {', '.join(self.material_pool)}

Legal cost bands ({len(self.cost_bands)}): {', '.join(self.cost_bands)}

If this draw cannot be satisfied, set `blocked` and say why."""


def build_recipe_brief(*, operations: "tuple[str, ...] | None" = None,
                       forge_target: "ForgeTarget | None" = None, theme_note: str = "",
                       materials_tuning_path: "Path | None" = None,
                       recipes_path: "Path | None" = None) -> RecipeBrief:
    """The one call site an orchestration needs. `operations` defaults to
    `opvocab.SUPPORTED_FOR_GENERATION` minus `"forge"` when `forge_target` is `None` (nothing to
    resolve a forge target against), or the full supported set when one is given."""
    cost_bands = load_cost_bands(materials_tuning_path)
    material_pool = load_material_pool()
    ops = operations
    if ops is None:
        ops = opvocab.SUPPORTED_FOR_GENERATION if forge_target is not None else tuple(
            o for o in opvocab.SUPPORTED_FOR_GENERATION if o != "forge")
    return RecipeBrief(forge_target=forge_target, operations=ops, material_pool=material_pool,
                       cost_bands=cost_bands, theme_note=theme_note)
