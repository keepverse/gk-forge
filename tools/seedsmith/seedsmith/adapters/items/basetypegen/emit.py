"""seedsmith.adapters.items.basetypegen.emit — ids, numeric resolution, and the final entry shape,
matching the real shipped corpus (`gk-data/packs/fusion/data/seed/items/base-types/humanoid-armament-primary-a.json`)
field for field.

Two independent things happen here, on purpose, the same split `affixfamgen.emit` documents for
its own corpus:

1. `assemble_entry` — turns a model ANSWER (matching `schema.base_type_schema`) plus its
   `PartitionContext` and sequence index into one entry dict. Re-validates the closed-vocabulary
   fields the schema's own enums already constrain (defense in depth — a schema is what a
   WELL-FORMED answer must satisfy, not a guarantee this function is only ever called with one).

2. `resolve_socket_max` / `resolve_power_band` / `resolve_enhance_track` (in `tuning.py`, called
   from here) — Acceptance #1's "every numeric field is resolved by deterministic code reading
   tuning data", never invented by a call and never random.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from . import successor_edges, tuning
from .brief import PartitionContext
from .. import registries
from ....pipeline.provenance import provenance_model

ENTRY_ID_RE = re.compile(r"^item\.[a-z0-9]+(-[a-z0-9]+)*-(\d{3,})$")
_SLUG_WORD_RE = re.compile(r"[A-Za-z0-9]+")


class MintRefused(ValueError):
    """An id, slug, or field this module refuses to mint, with the rule it would have broken."""


class IdCollisionError(ValueError):
    """The minted id already exists in this partition — never silently overwritten."""


class IllegalChoiceError(ValueError):
    """A `class` or `implicitFamily` value outside the partition's own closed vocabulary reached
    `assemble_entry` despite the schema enum — defense in depth, not the primary guard."""


class TagAxisViolationError(ValueError):
    """Two tags from the same `tags.v1.json` exclusive axis reached `assemble_entry` on one entry
    (e.g. both `defensive` and `utility`, both on `combat-posture`) — the schema's flat enum can
    restrict which strings are legal but not "at most one from this subset", so this is real
    defense in depth, not a duplicate of the schema (item-seed-regen cause 8, 2026-09-20: found live
    as 23 shipped base-types with exactly this defect, none of them caught here because the check
    never existed until now)."""


def slug_from_name(name: str) -> str:
    """`"Honed Hatchet"` -> `"honed-hatchet"` — the kebab slug every real entry's `nameKey` /
    `iconKey` / `flavorKey` shares (`base.honed-hatchet`, `icon.base.honed-hatchet`,
    `flavor.base.honed-hatchet`)."""
    words = _SLUG_WORD_RE.findall(name)
    if not words:
        raise MintRefused(f"name {name!r} has no word to slug")
    slug = "-".join(w.lower() for w in words)
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
        raise MintRefused(f"name {name!r} produced the non-kebab-legal slug {slug!r}")
    return slug


def name_key_for(slug: str) -> str:
    return f"base.{slug}"


def icon_key_for(slug: str) -> str:
    return f"icon.base.{slug}"


def flavor_key_for(slug: str) -> str:
    return f"flavor.base.{slug}"


def entry_id(frame: str, frame_role_name: str, band: str, seq: int) -> str:
    """`item.{frame}-{frameRoleName}-{band}-{seq:03}` — `naming.v1.json`'s own `idTemplate` for the
    `baseTypes` namespace, transcribed verbatim (`idNamespaces.baseTypes.idTemplate`)."""
    minted = f"item.{frame}-{frame_role_name}-{band}-{seq:03d}"
    if not ENTRY_ID_RE.match(minted):
        raise MintRefused(f"{minted!r} fails the item.<frame>-<slot>-<band>-<seq> id grammar")
    return minted


def next_seq(existing_ids: "tuple[str, ...] | list[str]") -> int:
    """Continues one past the highest `-{seq:03}` suffix already present in this partition — never
    reusing an id, the same "continue, never reuse" discipline `milestonegen.emit.next_entry_id`
    and `naming.v1.json`'s own `idPolicy.sequenceRange` (001-899, 900-999 reserved) both state."""
    max_seq = 0
    for eid in existing_ids:
        m = ENTRY_ID_RE.match(eid)
        if m:
            max_seq = max(max_seq, int(m.group(2)))
    if max_seq >= 899:
        raise MintRefused(
            f"partition already at seq {max_seq} — 900-899 is naming.v1.json's reserved "
            f"hand-authored-correction range; a generator does not mint into it")
    return max_seq + 1


def assemble_entry(answer: "Mapping[str, Any]", partition: PartitionContext, *, seq: int,
                   gen_tuning: "tuning.GenTuning | None" = None,
                   successor_edges_map: "Mapping[str, str] | None" = None) -> "dict[str, Any]":
    """Validates `answer` against the partition's real, current state and returns one entry dict
    shaped exactly like a real `gk-data/packs/fusion/data/seed/items/base-types/*.json` entry. Raises on the first
    violation found rather than silently coercing."""
    name = answer["name"]
    cls = answer["class"]
    implicit_family = answer["implicitFamily"]
    tags = tuple(dict.fromkeys(answer.get("tags") or []))

    if cls not in partition.class_choices:
        raise IllegalChoiceError(
            f"class {cls!r} is not legal for role {partition.role!r} frame {partition.frame!r}: "
            f"{partition.class_choices}")
    if implicit_family not in partition.implicit_families:
        raise IllegalChoiceError(
            f"implicitFamily {implicit_family!r} is not in role {partition.role!r}'s closed slate: "
            f"{partition.implicit_families}")
    if not tags:
        raise MintRefused("an entry needs at least one tag")
    axis_violation = registries.tag_axis_violation(
        tags, registries.load_tag_axes(applies_to="base-type"))
    if axis_violation is not None:
        raise TagAxisViolationError(axis_violation)

    slug = slug_from_name(name)
    minted_id = entry_id(partition.frame, partition.frame_role_name, partition.band, seq)
    if minted_id in partition.existing_ids:
        raise IdCollisionError(f"{minted_id!r} already exists in this partition")

    gt = gen_tuning or tuning.load_gen_tuning()
    seq_index = seq - 1  # 0-based for the round-robin ladders
    socket_max = tuning.resolve_socket_max(partition.role, partition.band, seq_index,
                                           gen_tuning=gt)
    power_band = tuning.resolve_power_band(partition.band, seq_index, gen_tuning=gt)
    # A partition FILE that already has entries has already committed to one enhanceTrack triple
    # (measured: every one of the 740 shipped entries in a given file shares one identical triple)
    # — an appended entry reuses it rather than minting a second, different one via the hash-based
    # `resolve_enhance_track` path, which is reserved for a genuinely new, empty partition.
    enhance_track = partition.existing_enhance_track or tuning.resolve_enhance_track(
        partition.role, partition.frame, partition.band, gen_tuning=gt)

    entry = {
        "id": minted_id,
        "nameKey": name_key_for(slug),
        "name": name,
        "frame": partition.frame,
        "role": partition.role,
        "class": cls,
        "band": partition.band,
        "implicit": {"family": implicit_family, "powerBand": power_band},
        "socketMax": socket_max,
        "iconKey": icon_key_for(slug),
        "flavorKey": flavor_key_for(slug),
        "flavor": answer.get("flavor", ""),
        "tags": list(tags),
        "enhanceTrack": [{"atLevel": lvl, "family": fam} for lvl, fam in enhance_track],
    }

    # species-gear-chain T38 (`successorOf`): the upgrade tree's authored edge for THIS base type,
    # read from `_registry/successor-edges.v1.json` (or an injected map — the seam a test uses, and
    # the same shape `gen_tuning` above already offers). Additive by construction: with no edge
    # authored the key is absent, so the shipped corpus is byte-identical to before this mechanism
    # existed. Never derived from a class ladder, and never model-authored.
    successor_edges.apply(
        entry,
        successor_edges_map if successor_edges_map is not None else successor_edges.load())
    return entry


def emit_document(entries: "list[dict[str, Any]]", *, batch: str, partition: str,
                  source_ref: str, model: str,
                  authored_utc: str = "") -> "dict[str, Any]":
    """The full base-type document wrapper, matching every real shipped file's own `_meta` shape."""
    return {
        "schemaVersion": 1,
        "kind": "base-type",
        "_meta": {
            "batch": batch,
            "partition": partition,
            "contractVersion": 1,
            "model": provenance_model(model),
            "authoredUtc": authored_utc,
            "sourceRef": source_ref,
        },
        "entries": entries,
    }


def merge_into_partition_document(existing_doc: "dict[str, Any]",
                                  new_entries: "list[dict[str, Any]]") -> "dict[str, Any]":
    """Append `new_entries` to an already-loaded partition document's `entries`, leaving every
    other field untouched — additive by default, matching `affixfamgen.emit`'s own contract and
    the spec's acceptance #2 ('append+reconcile by default')."""
    merged = dict(existing_doc)
    merged["entries"] = list(existing_doc.get("entries", [])) + list(new_entries)
    return merged


def write_document(path: Path, doc: "dict[str, Any]") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return path
