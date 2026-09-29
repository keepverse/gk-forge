"""seedsmith.adapters.items.recipegen.emit — ids, mechanical derivations, and the final entry
shape, matching the real shipped corpus (`gk-data/packs/fusion/data/seed/items/recipes/recipes.json`) field for field.

Three things are derived here, never authored (P1, restated for this corpus's own shape):

1. `outputKind` — mechanically follows from `operation` (`opvocab.OPERATION_OUTPUT_KIND`).
2. `outputRef` for an `upcycle` (`material`-output) recipe — the real 30-entry corpus's own
   `upcycle` rows (`recipe.005`..`recipe.008`) all follow ONE mechanical rule, confirmed by reading
   every one of them: the output is the SAME frame, one substrate grade above the recipe's own
   (single) substrate cost line. `substrate.humanoid.crude` (grade 1) upcycles to
   `substrate.humanoid.sound` (grade 2); `substrate.humanoid.sound` (grade 2) upcycles to
   `substrate.humanoid.fine` (grade 3). This module derives it the same way, rather than asking a
   model to name a second material id that would need to agree with the first.
3. `tags` — the real corpus's own `["crafted-only"]` appears on EVERY `forge` row and NO other row
   (checked directly against all 30 entries) — mechanical, not authored.

`outputRef` for a `forge` (`container`-output) recipe is NOT derived — it is the model's own
`outputTarget` choice (an existing candidate, or `schema.MINT_NEW_SENTINEL` resolved against the
brief's own `ForgeTarget.next_mint_id`), because unlike `upcycle` there is no mechanical rule for
"which base type" a themed forge recipe should mint.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from ..materialgen import vocab as material_vocab
from ....pipeline.provenance import provenance_model
from . import opvocab
from .brief import ForgeTarget
from .schema import MINT_NEW_SENTINEL

_ID_RE = re.compile(r"^recipe\.(\d{3,})$")
_SLUG_WORD_RE = re.compile(r"[A-Za-z0-9]+")

#: `MaterialTuning`'s own substrate grade ladder (`MaterialCatalog.SubstrateGrades`), mirrored via
#: `materialgen.vocab.SUBSTRATE_GRADES` rather than re-typed here.
_SUBSTRATE_GRADES = material_vocab.SUBSTRATE_GRADES


class MintRefused(ValueError):
    """An id, slug, or field this module refuses to mint, with the rule it would have broken."""


class IdCollisionError(ValueError):
    """The minted id already exists in the corpus — never silently overwritten."""


class IllegalChoiceError(ValueError):
    """An `operation`/`outputTarget`/cost-line value outside what this call's brief legalized
    reached `assemble_entry` despite the schema enum — defense in depth, matching every sibling
    module's "a schema is what a WELL-FORMED answer must satisfy, not a guarantee" stance."""


class NoUpcycleInputError(ValueError):
    """An `upcycle` answer names no substrate cost line to derive the output grade from, or the
    input is already at the top grade (`prime`) and has nowhere to upcycle to."""


def slug_from_name(name: str) -> str:
    words = _SLUG_WORD_RE.findall(name)
    if not words:
        raise MintRefused(f"name {name!r} has no word to slug")
    slug = "-".join(w.lower() for w in words)
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
        raise MintRefused(f"name {name!r} produced the non-kebab-legal slug {slug!r}")
    return slug


def name_key_for(token: str) -> str:
    """`recipe.<token>` — callers pass the unique `recipe.NNN` id, not a display-name slug.

    A recipe's display name repeats by design (one per material/frame/band), so the name cannot
    carry uniqueness; the id can, and the key adds no information beyond it (2026-09-12)."""
    return f"recipe.{token}"


def recipe_id(seq: int) -> str:
    minted = f"recipe.{seq:03d}"
    if not _ID_RE.match(minted):
        raise MintRefused(f"{minted!r} fails the recipe.<seq> id grammar")
    return minted


def next_seq(existing_ids: "tuple[str, ...] | list[str]") -> int:
    """Continues one past the highest `recipe.NNN` id already in the corpus — never reusing an id,
    matching `basetypegen.emit.next_seq`'s own discipline."""
    max_seq = 0
    for eid in existing_ids:
        m = _ID_RE.match(eid)
        if m:
            max_seq = max(max_seq, int(m.group(1)))
    return max_seq + 1


def derive_upcycle_output(cost_lines: "list[dict[str, Any]]") -> str:
    """The one substrate cost line's frame+grade, one grade up — see this module's own docstring
    for the real-corpus evidence. Raises if the answer names zero or more than one substrate line
    (an `upcycle` recipe with an ambiguous or absent input has nothing this module can derive from,
    and is refused rather than guessed), or if the input is already at the top grade."""
    substrate_lines = [
        cl for cl in cost_lines
        if material_vocab.ISSUABLE_BY_ID.get(cl["material"], None) is not None
        and material_vocab.ISSUABLE_BY_ID[cl["material"]].material_class == "substrate"
    ]
    if len(substrate_lines) != 1:
        raise NoUpcycleInputError(
            f"an upcycle recipe needs EXACTLY ONE substrate cost line to derive its output grade "
            f"from; found {len(substrate_lines)}")
    input_id = substrate_lines[0]["material"]
    input_material = material_vocab.ISSUABLE_BY_ID[input_id]
    grade = input_material.grade or 0
    if grade >= len(_SUBSTRATE_GRADES):
        raise NoUpcycleInputError(
            f"{input_id!r} is already the top substrate grade ({_SUBSTRATE_GRADES[-1]!r}) — "
            f"nothing to upcycle it into")
    output_id = f"substrate.{input_material.frame}.{_SUBSTRATE_GRADES[grade]}"
    material_vocab.require_issuable(output_id)  # defense in depth — must land back in the 27
    return output_id


def tags_for(operation: str) -> "list[str]":
    """`["crafted-only"]` for every `forge` row, `[]` for every other — the real corpus's own
    mechanical pattern, checked against all 30 shipped entries (see this module's own docstring)."""
    return ["crafted-only"] if operation == "forge" else []


def _validate_cost_lines(operation: str, cost_lines: "list[dict[str, Any]]") -> "list[dict[str, str]]":
    resolved: "list[dict[str, str]]" = []
    for line in cost_lines:
        material_id = line["material"]
        material = material_vocab.require_issuable(material_id)  # raises on a legacy/unknown id
        opvocab.check_cost_class(operation, material.material_class, material_id)
        resolved.append({"material": material_id, "costBand": line["costBand"]})
    return resolved


def _resolve_output_ref(operation: str, output_kind: str, validated_cost_lines: "list[dict[str, str]]",
                        answer: Mapping[str, Any],
                        forge_target: "ForgeTarget | None") -> "str | None":
    if output_kind == "mutation":
        return None
    if output_kind == "material":
        return derive_upcycle_output(validated_cost_lines)
    # container
    if forge_target is None:
        raise IllegalChoiceError(
            f"operation {operation!r} mints a container but no forge_target was scoped for this "
            f"call — a forge draw always names a caller-chosen (role, frame, band) partition")
    target = answer.get("outputTarget")
    if target is None:
        raise IllegalChoiceError("a forge recipe answer must set outputTarget")
    if target == MINT_NEW_SENTINEL:
        return forge_target.next_mint_id
    if target not in forge_target.existing_ids:
        raise IllegalChoiceError(
            f"outputTarget {target!r} is not an existing id in partition "
            f"{forge_target.partition_key!r} ({forge_target.existing_ids})")
    return target


def assemble_entry(answer: Mapping[str, Any], *, seq: int,
                   forge_target: "ForgeTarget | None" = None) -> "dict[str, Any]":
    """Validates `answer` and returns one entry dict shaped exactly like a real
    `gk-data/packs/fusion/data/seed/items/recipes/recipes.json` entry. Raises on the first violation found."""
    name = answer["name"]
    operation = opvocab.require_supported_operation(answer["operation"])
    if operation == "forge-gem":
        # species-gear-chain T9: forge-gem rows are DERIVED (same family, next tier), never
        # authored — briefing one would ask a model to retype facts `forgegem.py` already reads.
        # The deterministic emitter builds those entries directly, never through here.
        raise IllegalChoiceError(
            "operation 'forge-gem' is not briefable — forge-gem rows are emitted deterministically "
            "by forgegem.plan_rows, never assembled from a model answer")
    if operation == "repair":
        # species-gear-chain T23: same rule for the workbench repair row — its legs ARE its
        # operation's priced row, and its D5 shard leg is rung-gated there, so a model would only
        # retype facts `repair.py` already reads.
        raise IllegalChoiceError(
            "operation 'repair' is not briefable — the repair row is emitted deterministically by "
            "repair.plan_rows, never assembled from a model answer")
    output_kind = opvocab.output_kind_for(operation)
    frame = answer.get("frame", "any")
    cost_lines = _validate_cost_lines(operation, list(answer.get("costLines") or []))
    output_ref = _resolve_output_ref(operation, output_kind, cost_lines, answer, forge_target)

    slug = slug_from_name(name)
    minted_id = recipe_id(seq)

    entry: "dict[str, Any]" = {
        "id": minted_id,
        # ⛔ 2026-09-12: `nameKey` used to be `recipe.<slug of the display name>`. A recipe's name
        # is deliberately systematic and REPEATS — `Temper: Sunwoven Reinforcement` is a real,
        # distinct row per material/frame/band (recipe.033/034/044 share it and differ in
        # costLines, soulsCostBand and frame) — so slugging the name produced 30
        # NameKeyDuplicate findings across 4 keys. The id is the recipe's identity and is unique by
        # construction (`recipe.NNN`), and nothing consumes a recipe `nameKey` (only the validator
        # reads it), so the key is minted from the id.
        "nameKey": name_key_for(minted_id),
        "name": name,
        "operation": operation,
        "outputKind": output_kind,
    }
    if output_ref is not None:
        entry["outputRef"] = output_ref
    entry["outputQty"] = 1  # every real entry carries this — never authored
    entry["frame"] = frame
    entry["costLines"] = cost_lines
    souls_band = answer.get("soulsCostBand")
    if souls_band:
        entry["soulsCostBand"] = souls_band
    entry["tags"] = tags_for(operation)
    flavor = answer.get("flavor")
    if flavor:
        entry["flavor"] = flavor
    return entry


def emit_document(entries: "list[dict[str, Any]]", *, batch: str, source_ref: str,
                  model: str, authored_utc: str = "") -> "dict[str, Any]":
    """The full recipe document wrapper, matching the real shipped file's own `_meta` shape."""
    return {
        "schemaVersion": 1,
        "kind": "recipe",
        "_meta": {
            "batch": batch,
            "partition": "recipes",
            "contractVersion": 1,
            "model": provenance_model(model),
            "authoredUtc": authored_utc,
            "sourceRef": source_ref,
        },
        "entries": entries,
    }


def write_document(path: Path, doc: "dict[str, Any]") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=False, indent=2) + "\n",
                    encoding="utf-8")
    return path
