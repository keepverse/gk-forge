"""seedsmith.adapters.items.affixfamgen.brief — partition context + the model-facing brief.

⛔ **P1, unamended, same as `setgen/brief.py`'s own opening line: the model writes identity, code
resolves every number.** The brief hands the model exactly four choices — a short mechanical
`word` (never a display word, per `naming.v1.json`'s own family-id rule), `channel` (constrained to
the partition's own already-used channels — see "Why channel is closed to the partition" below),
`roles`, and `tags`. It never sees a tier, a magnitude, an `amount`, or a power-band NUMBER (only
the closed `powerBand` enum word, which `bands.v1.json` itself defines as "what an author writes
INSTEAD of a magnitude"). The tier-band curve numerics are resolved afterwards, deterministically,
by `seedsmith.numerics` — never invented by a call.

**`kindId` is a caller input, never a model choice.** The spec's own "Ask first" boundary: whether
a NEW family should target `stat.modify` or `stat.derived` is a real design choice with downstream
consequences (module 5's two delivery paths) — this brief refuses to let the model pick it, the
same way `setgen`'s own charm brief fixes `charmClass`'s legality before the call rather than
asking the model to reason about ssot-charms itself.

**Why `channel` is closed to the partition's own already-used channels, not the full closed
vocabulary.** `AtomKindRegistry.cs` names two real per-kind channel vocabularies: `PrimaryChannels`
(a small, fixed set of real game channels for `stat.modify`, e.g. `atk`/`maxHp`/`hp`/`defense`/
`arm1Max`/`arm2Max`) and `DerivedChannels` (267+ registered derived channels for `stat.derived`).
Every real "NEW family" entry actually shipped in `gk-data/packs/fusion/data/seed/items/affix-families/*.json` reuses a
channel a SIBLING family in the same partition already uses, on a different `op` — `atom.life-graft`
reuses `hp` (already used by `mending`'s `Flat`); `atom.arm-hardening` reuses `defense` (already
used by `warding`/`resilience`); `atom.prec-fixation` reuses `combat.accuracy.{variant}` (already
used by `precision`). No shipped NEW family invents a channel absent from its own partition. This
module follows that real, observed pattern rather than re-transcribing either 8-or-14-entry
`PrimaryChannels` list or the 267-entry `DerivedChannels` list a second time in Python (which
`opvocab.py`'s own docstring explains is the reason C# vocabularies get transcribed with citation,
not casually re-derived): the brief offers only the partition's own existing channels, so a
generated family's channel is always a real, already-registered one by construction. Authoring a
family on a channel NEW to its partition is therefore explicitly out of this module's scope, not a
silent limitation — a real future need would extend this brief to accept an explicit allow-list
from the C# vocabulary, not lift the constraint unconditionally.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from seedsmith.pipeline.model import audit_schema

from ..naming_grammar import NAMING_GRAMMAR_RULES
from .. import registries

from . import opvocab
from .schema import affix_family_schema

from ....workspace_roots import owning_base  # noqa: E402

# `data/seed/**` is the CONTENT PACK's tree - gk-data/packs/fusion/data/seed - and gk-forge owns the
# GENERATOR, not the corpus. The split left generator inputs beside their generator, so a path walked
# up from this file lands on gk-forge and every registry read asked gk-forge/data/seed/items/_registry,
# a directory that does not exist. Measured, not assumed: owning_base() answers for this relative path
# and returns the pack; root_carrying() does NOT, because an ancestor walk reaches the workspace root,
# which does not carry data/seed; and content_root() RAISES for a temp directory, which these modules
# are imported by way of. `or REPO_ROOT` keeps that case working, which is what a non-raising lookup
# buys.
REPO_ROOT = Path(__file__).resolve().parents[6]


def _seed_root(relative: str) -> "Path":
    """The repository carrying `relative`, falling back to this one when none does."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative
NAMING_REGISTRY = _seed_root("data/seed/items/_registry") / "naming.v1.json"
TAGS_REGISTRY = _seed_root("data/seed/items/_registry") / "tags.v1.json"
CORE_REGISTRY = _seed_root("data/seed/items/_registry") / "core.v1.json"
BANDS_REGISTRY = _seed_root("data/seed/items/_registry") / "bands.v1.json"
FAMILIES_DIR = _seed_root("data/seed/items/affix-families")


class UnknownGroupError(ValueError):
    """`group_id` is not one of `naming.v1.json`'s registered affix-family groups."""


def load_group_stems(path: "Path | None" = None) -> "dict[str, str]":
    """`groupId -> stem` for every registered affix-family group
    (`naming.v1.json.idNamespaces.affixFamilies.groups[]`), read fresh — never hand-transcribed,
    matching `registries.py`'s own discipline ("registry facts are read, never transcribed")."""
    doc = json.loads((path or NAMING_REGISTRY).read_text(encoding="utf-8"))
    groups = doc["idNamespaces"]["affixFamilies"]["groups"]
    return {g["groupId"]: g["stem"] for g in groups}


def load_target_family_count(path: "Path | None" = None) -> int:
    """Read the affix-family sizing target from the naming registry.

    ``agentsEach`` is intentionally a human-readable registry field (currently ``"~7 families"``),
    so the planner must not duplicate that balance target as a code literal.  A malformed registry
    is a configuration error, not permission to schedule an unbounded generation pass.
    """
    doc = json.loads((path or NAMING_REGISTRY).read_text(encoding="utf-8"))
    value = doc["idNamespaces"]["affixFamilies"].get("agentsEach")
    match = re.search(r"(\d+)", value if isinstance(value, str) else "")
    if not match or int(match.group(1)) < 1:
        raise ValueError("naming.v1.json affixFamilies.agentsEach has no positive family target")
    return int(match.group(1))


def group_stem(group_id: str, path: "Path | None" = None) -> str:
    stems = load_group_stems(path)
    if group_id not in stems:
        raise UnknownGroupError(
            f"group {group_id!r} is not registered in naming.v1.json's affixFamilies groups — "
            f"known groups: {sorted(stems)}")
    return stems[group_id]


def load_role_vocabulary(path: "Path | None" = None) -> "tuple[str, ...]":
    """The 15 body roles plus the commander-only `standard` role, read fresh from
    `core.v1.json` — the same union `adapters.items.registries.load_vocabularies()['role']`
    already exposes, re-derived here so this package has no import-order dependency on that
    module's own snapshot-reading side (`registries.py` also reads a partitions snapshot file this
    package has no business touching)."""
    doc = json.loads((path or CORE_REGISTRY).read_text(encoding="utf-8"))
    body = [r["roleId"] for r in doc["roles"]["list"]]
    commander = [r["roleId"] for r in doc["roles"]["commanderOnly"]]
    return tuple(body + commander)


def load_tag_vocabulary(path: "Path | None" = None) -> "tuple[str, ...]":
    doc = json.loads((path or TAGS_REGISTRY).read_text(encoding="utf-8"))
    return tuple(t["id"] for t in doc["tags"])


def load_power_band_vocabulary(path: "Path | None" = None) -> "tuple[str, ...]":
    doc = json.loads((path or BANDS_REGISTRY).read_text(encoding="utf-8"))
    return tuple(doc["powerBand"]["enum"])


@dataclass(frozen=True)
class PartitionContext:
    """Everything the brief needs about ONE partition file (e.g. `g.armour`), gathered once and
    passed to both `build_affix_family_brief` and `schema.affix_family_schema` so the two can never
    silently disagree about what is legal."""

    group_id: str
    stem: str
    existing_ids: "tuple[str, ...]"
    #: channel -> the ops already used on that channel anywhere in the partition (across kinds —
    #: a channel is never reused across `stat.modify` and `stat.derived` in the real corpus, but
    #: this does not assume that; `emit.py`'s dedup check reads the per-kind pair, not this alone).
    channel_ops: "Mapping[str, tuple[str, ...]]"

    @property
    def channels(self) -> "tuple[str, ...]":
        return tuple(sorted(self.channel_ops))


def free_channel_ops(partition: PartitionContext, kind_id: str) -> "tuple[tuple[str, str], ...]":
    """The mechanically distinguishable slots still available in one partition.

    A model cannot create a new mechanic when every registered channel already carries every op
    legal for the requested kind. Detect that deterministic fact before spending a live call.
    """
    legal_ops = opvocab.legal_ops(kind_id)
    return tuple(
        (channel, op)
        for channel in partition.channels
        for op in legal_ops
        if op not in partition.channel_ops.get(channel, ())
    )


def load_partition_context(group_id: str, *, families_dir: "Path | None" = None,
                           naming_path: "Path | None" = None) -> PartitionContext:
    """Reads the real, current partition file for `group_id` (e.g. `g.armour` ->
    `gk-data/packs/fusion/data/seed/items/affix-families/g-armour.json`) and the group's registered stem. Raises
    `FileNotFoundError` if the partition has no shipped file yet — a genuinely new partition with
    zero existing families has no channel to constrain a NEW family to, which is exactly the
    out-of-scope case this brief's own docstring names, not a case to guess through."""
    stem = group_stem(group_id, naming_path)
    file_name = "g-" + group_id.split(".", 1)[1] + ".json"
    path = (families_dir or FAMILIES_DIR) / file_name
    doc = json.loads(path.read_text(encoding="utf-8"))
    ids: "list[str]" = []
    channel_ops: "dict[str, list[str]]" = {}
    for entry in doc.get("entries", []):
        ids.append(entry["id"])
        channel = entry.get("params", {}).get("channel")
        op = entry.get("params", {}).get("op")
        if channel is None or op is None:
            continue
        channel_ops.setdefault(channel, [])
        if op not in channel_ops[channel]:
            channel_ops[channel].append(op)
    return PartitionContext(
        group_id=group_id, stem=stem, existing_ids=tuple(ids),
        channel_ops={c: tuple(ops) for c, ops in channel_ops.items()},
    )


@dataclass(frozen=True)
class AffixFamilyBrief:
    """One brief: one partition, one declared `kindId`. `schema` is built alongside the text so
    the two are guaranteed to describe the same legal answer space.

    ⛔ Construction-time guard, mirroring `pipeline.model.Pipeline.__post_init__`: `audit_schema`
    runs on `self.schema` here, at `__post_init__`, so a schema that could let a model emit a bare
    number never reaches a call — the exact "rejected mechanically, not by review" discipline
    `pipeline/model.py`'s own module docstring states as guardrail #3.
    """

    partition: PartitionContext
    kind_id: str
    roles: "tuple[str, ...]"
    tags: "tuple[str, ...]"
    power_bands: "tuple[str, ...]"
    theme_note: str = ""
    schema: "Mapping[str, Any]" = field(default_factory=dict)

    def __post_init__(self) -> None:
        opvocab.legal_ops(self.kind_id)  # raises UnsupportedKindError early, before schema audit
        if not self.partition.channels:
            raise ValueError(
                f"partition {self.partition.group_id!r} has no existing channels — a brief cannot "
                f"offer an empty channel choice (see brief.py's own 'why channel is closed' note)")
        free = free_channel_ops(self.partition, self.kind_id)
        if not free and not self.schema:
            raise ValueError(
                f"partition {self.partition.group_id!r}/{self.kind_id!r} has no free "
                f"(channel, op) pair — refuse before building a schema")
        schema = self.schema or affix_family_schema(
            self.kind_id, free_pairs=free, roles=self.roles,
            tags=self.tags, power_bands=self.power_bands)
        defects = audit_schema(schema)
        if defects:
            raise ValueError(
                f"affix-family brief for {self.partition.group_id!r}/{self.kind_id!r} has an "
                f"unusable schema:\n" + "\n".join(f"  - {d}" for d in defects))
        object.__setattr__(self, "schema", schema)

    def render(self) -> str:
        free = free_channel_ops(self.partition, self.kind_id)
        free_lines = ", ".join(f"{c}|{o}" for c, o in free)
        existing = ", ".join(f"{c!r} (used with {', '.join(ops)})"
                             for c, ops in sorted(self.partition.channel_ops.items()))
        theme_line = f"\nTheme: {self.theme_note}" if self.theme_note else ""
        return f"""Author ONE NEW affix family for partition {self.partition.group_id!r}
(reserved id stem: {self.partition.stem!r}).{theme_line}

This family's kind is fixed: `{self.kind_id}`.

Choose, and nothing else:
1. `word` — a SHORT MECHANICAL identifier, not a display word (`naming.v1.json`'s own family-id
   rule: family ids are mechanical, distinct from the flavour vocabulary). The full id will be
   minted as `atom.{self.partition.stem}-{{word}}`.
2. `channelOp` — exactly ONE free token from this closed list (channel|op):
   {free_lines}
   Already used in this partition (do not repeat): {existing}
3. `roles` — one or more of the closed role vocabulary below.
4. `tags` — one or more of the closed tag vocabulary below.

{registries.tag_axis_brief_note("affix-family")}

5. `powerBand` — one of {self.power_bands} (a RELATIVE category, never a number — bands.v1.json's
   own words for "what an author writes instead of a magnitude").
6. `name`, `displayTemplate` — display identity only. Do NOT invent a nameKey; code derives it.

{NAMING_GRAMMAR_RULES}
(The rules above apply to `name` only, never to `displayTemplate`'s own runtime substitution text.)

Never choose a number, an amount, a tier or a per-mille value. Those are resolved after you answer,
by `seedsmith.numerics`, from the tier-band curve — never from this call.

Legal roles ({len(self.roles)}): {', '.join(self.roles)}

Legal tags ({len(self.tags)}): {', '.join(self.tags)}

If this partition cannot carry a new family you would be happy to ship, set `blocked` to a reason
string and set every other field to null."""


def build_affix_family_brief(group_id: str, kind_id: str, *, theme_note: str = "",
                             families_dir: "Path | None" = None) -> AffixFamilyBrief:
    """The one call site a `run.py` orchestration needs: partition + kindId in, a fully-guarded
    brief out. Roles/tags/powerBand are read fresh from the registries every time — the same
    "never a copy" discipline `AtomKindRegistry.Validate`'s own vocabulary loop documents on the
    C# side."""
    partition = load_partition_context(group_id, families_dir=families_dir)
    return AffixFamilyBrief(
        partition=partition, kind_id=kind_id, roles=load_role_vocabulary(),
        tags=load_tag_vocabulary(), power_bands=load_power_band_vocabulary(),
        theme_note=theme_note,
    )
