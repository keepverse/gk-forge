"""seedsmith.adapters.items.basetypegen.brief — partition context + the model-facing brief.

⛔ P1, same opening line every sibling module states: **the model writes identity, code resolves
every number.** The brief hands the model exactly four choices — `name`, `flavor`, `class` (one
class-ladder rung legal for this role+frame) and `implicitFamily` (one family from this role's own
closed implicit slate), plus `tags`. It never sees `socketMax`, an `enhanceTrack` level, or a
`powerBand` NUMBER — `emit.py` resolves all three from `tuning.py`, which reads
`gk-core/data/tuning/base-types-gen.v1.json` and the real registries, never a model call.

**`role`, `frame` and `band` are caller inputs, never a model choice** — the same disposition
`affixfamgen.brief`'s own docstring states for its `kindId` ("a real design choice with downstream
consequences ... this brief refuses to let the model pick it"). Here the reasons are sharper still:
spec-base-types-gen.md's own boundary is "Ask first: changing the 30-role-frame taxonomy itself",
and a per-call model-chosen role/frame would BE that change, made silently, once per call. `band`
is `naming.v1.json`'s own "symbolic class-band split ... F4 owns what 'a' vs 'b' means" — a
partition token this module reads out of the caller-supplied slot, never invents.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..naming_grammar import NAMING_GRAMMAR_RULES
from .. import registries

from seedsmith.pipeline.model import audit_schema

from . import tuning
from . import partitions
from .schema import base_type_schema

REPO_ROOT = tuning.REPO_ROOT


@dataclass(frozen=True)
class PartitionContext:
    """Everything the brief and the schema need about ONE `(role, frame, band)` partition, gathered
    once so brief text and schema enum can never silently disagree about what is legal — the same
    reason `affixfamgen.brief.PartitionContext` exists."""

    role: str
    frame: str
    band: str
    frame_role_name: str
    class_choices: "tuple[str, ...]"
    implicit_families: "tuple[str, ...]"
    existing_ids: "tuple[str, ...]"
    existing_names: "tuple[str, ...]"
    existing_enhance_track: "tuple[tuple[int, str], ...] | None"

    @property
    def partition_key(self) -> str:
        return f"{self.role}:{self.frame}:{self.band}"

    @property
    def output_file_stem(self) -> str:
        """`{frame}-{role}-{band}` — matches every real shipped filename
        (`humanoid-armament-primary-a.json`)."""
        return f"{self.frame}-{self.role}-{self.band}"


def load_partition_context(role: str, frame: str, band: str, *,
                           base_types_dir: "Path | None" = None,
                           core_path: "Path | None" = None,
                           classes_path: "Path | None" = None) -> PartitionContext:
    """Reads the real, current partition file for `(role, frame, band)` if one already exists
    (`gk-data/packs/fusion/data/seed/items/base-types/{frame}-{role}-{band}.json`), and the role's closed vocabularies
    fresh from the registries. A partition with no shipped file yet is legal — `existing_ids` and
    `existing_names` are simply empty, and `emit.next_entry_id` starts the sequence at 1."""
    if frame not in tuning.FRAMES:
        raise ValueError(f"frame must be one of {tuning.FRAMES}, got {frame!r}")
    info = tuning.role_info(role, core_path)
    class_choices = tuning.load_class_choices(role, frame, classes_path)
    if not class_choices:
        raise ValueError(
            f"role {role!r} frame {frame!r} has no legal class-ladder rung — classes.v2.json's "
            f"class ladders name no rung whose roles list includes this role on this frame")
    implicit_families = tuning.load_legal_implicit_families(role, frame, classes_path)

    directory = base_types_dir or tuning.BASE_TYPES_DIR
    file_path = partitions.file_for(role, frame, band, base_types_dir=directory)
    existing_ids: "list[str]" = []
    existing_names: "list[str]" = []
    existing_enhance_track: "tuple[tuple[int, str], ...] | None" = None
    if file_path.exists():
        import json
        doc = json.loads(file_path.read_text(encoding="utf-8"))
        for entry in doc.get("entries", []):
            existing_ids.append(entry["id"])
            if entry.get("name"):
                existing_names.append(entry["name"])
            if existing_enhance_track is None and entry.get("enhanceTrack"):
                # ⚠ Found while generating a real sample entry (2026-09-07): every one of the 740
                # shipped entries in a given partition FILE shares one identical enhanceTrack — see
                # this package's own module docstring. Reading the file's own already-established
                # triple here, rather than always re-deriving one from tuning.resolve_enhance_track,
                # is what keeps an APPENDED entry consistent with its 12 (or however many) existing
                # siblings instead of introducing a second, different triple into the same file.
                existing_enhance_track = tuple(
                    (t["atLevel"], t["family"]) for t in entry["enhanceTrack"])

    return PartitionContext(
        role=role, frame=frame, band=band, frame_role_name=info.frame_role_name(frame),
        class_choices=class_choices, implicit_families=implicit_families,
        existing_ids=tuple(existing_ids), existing_names=tuple(existing_names),
        existing_enhance_track=existing_enhance_track,
    )


def _existing_names_line(names: "tuple[str, ...]", limit: int = 20) -> str:
    if not names:
        return "  (none yet)"
    shown = names[:limit]
    lines = [f"  - {n}" for n in shown]
    if len(names) > limit:
        lines.append(f"  - ...and {len(names) - limit} more")
    return "\n".join(lines)


@dataclass(frozen=True)
class BaseTypeBrief:
    """One brief, one partition. `schema` is built alongside the text so the two are guaranteed to
    describe the same legal answer space.

    ⛔ Construction-time guard, mirroring `pipeline.model.Pipeline.__post_init__` and
    `affixfamgen.brief.AffixFamilyBrief.__post_init__`: `audit_schema` runs on `self.schema` here,
    at `__post_init__`, so a schema that could let a model emit a bare number never reaches a call.
    """

    partition: PartitionContext
    tag_vocab: "tuple[str, ...]"
    theme_note: str = ""
    schema: "Mapping[str, Any]" = field(default_factory=dict)

    def __post_init__(self) -> None:
        schema = self.schema or base_type_schema(
            class_choices=self.partition.class_choices,
            implicit_families=self.partition.implicit_families, tags=self.tag_vocab)
        defects = audit_schema(schema)
        if defects:
            raise ValueError(
                f"base-type brief for {self.partition.partition_key!r} has an unusable schema:\n"
                + "\n".join(f"  - {d}" for d in defects))
        object.__setattr__(self, "schema", schema)

    def render(self) -> str:
        p = self.partition
        theme_line = f"\nTheme: {self.theme_note}" if self.theme_note else ""
        return f"""Author ONE NEW base-type identity for role {p.role!r}, frame {p.frame!r} \
(displayed slot: {p.frame_role_name!r}), band {p.band!r}.{theme_line}

This is an EQUIPMENT BASE TYPE — the un-rolled chassis a rarity's affix pool later dresses. You are
naming ONE physical object a body of this frame could plausibly wear or wield in this role. Do not
invent a rarity, a level, a socket count, or a magnitude of any kind — those are resolved after you
answer, from tuning data, never from this call.

Choose, and nothing else:
1. `name` — a short, concrete display name for the object itself (e.g. "Honed Hatchet", "Cracked
   Buckler"), matching this partition's own naming register. Avoid a name already used in this
   partition (listed below).

{NAMING_GRAMMAR_RULES}

2. `flavor` — one or two sentences of grounded, mechanical flavor for the object — never a number.
3. `class` — one of this role+frame's own legal class-ladder rungs, closed below.
4. `implicitFamily` — one of this role's own closed implicit-family slate, closed below. This is
   the ONE affix family every copy of this base type always carries — pick the one that best fits
   the object you named.
5. `tags` — one or more from the closed tag vocabulary below.

{registries.tag_axis_brief_note("base-type")}

Legal `class` rungs ({len(p.class_choices)}): {', '.join(p.class_choices)}

Legal `implicitFamily` values ({len(p.implicit_families)}): {', '.join(p.implicit_families)}

Legal tags ({len(self.tag_vocab)}):
{chr(10).join('  - ' + t for t in self.tag_vocab)}

Existing names already in this partition (pick something distinct):
{_existing_names_line(p.existing_names)}

If this role+frame+band cannot carry a base type you would be happy to ship, set `blocked` and say
why."""


def build_base_type_brief(role: str, frame: str, band: str, *, theme_note: str = "",
                          base_types_dir: "Path | None" = None) -> BaseTypeBrief:
    """The one call site a `run.py` orchestration needs: `(role, frame, band)` in, a fully-guarded
    brief out."""
    partition = load_partition_context(role, frame, band, base_types_dir=base_types_dir)
    return BaseTypeBrief(partition=partition, tag_vocab=tuning.load_tag_vocab(),
                         theme_note=theme_note)
