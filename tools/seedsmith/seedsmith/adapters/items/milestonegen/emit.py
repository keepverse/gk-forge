"""seedsmith.adapters.items.milestonegen.emit — ids, slugs, op/powerBand resolution, the final
entry shape.

**The `atom.<name>` id convention, read from the real corpus, not invented.** Every one of the ten
real `gk-data/packs/fusion/data/seed/items/enhancement-milestones/milestones.json` entries follows
`runtimeFamily = "atom.enhance-" + slug`, `nameKey = "enh.enhance-" + slug`, where `slug` is the
kebab-case tail of the `name` field after its `"Enhancement "` prefix (`"Enhancement Vigor"` ->
`vigor` -> `atom.enhance-vigor` / `enh.enhance-vigor`, `enh.001`). `slug_from_name` reproduces
exactly that split; `runtime_family_for` / `name_key_for` reproduce exactly that concatenation.

⛔ **P1 applied to `op`/`powerBand`, not just to slugging.** `resolve_op_and_band` is the ONE place
in this module that turns a model-chosen `channel` into a real op/powerBand pair, and it does so by
table lookup only (`schema.CHANNEL_TUNING`) — no formula, no model input, so re-running the same
channel choice always produces the identical pair.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import CHANNEL_TUNING, ILLEGAL_STAT_MODIFY_OP, KIND_ID, POWER_BANDS, STAT_MODIFY_OPS

#: `enh.<seq>` — the real corpus's own id shape (`enh.001` .. `enh.010`). Anchored and strict: a
#: permissive pattern does not reject a malformed id, it makes one invisible.
ENTRY_ID_RE = re.compile(r"^enh\.(\d{3,})$")

#: `atom.<kebab-body>` — the general "atom.<name>" convention this corpus's own `runtimeFamily`
#: field already follows (`atom.enhance-vigor`, `atom.enhance-edge`, ...). One dot, kebab body,
#: matching `combogen.emit.CONTAINER_ID_RE`'s own grammar discipline for a different corpus's ids.
RUNTIME_FAMILY_RE = re.compile(r"^atom\.[a-z0-9]+(-[a-z0-9]+)*$")

#: This module's own narrower convention within that grammar: every family it MINTS carries the
#: `enhance-` prefix the ten real entries already established, so a future `base-types-gen`
#: `enhanceTrack[].family` reference can recognize "this id belongs to enhancement-milestones-gen"
#: by shape alone.
ENHANCE_FAMILY_RE = re.compile(r"^atom\.enhance-[a-z0-9]+(-[a-z0-9]+)*$")

_NAME_PREFIX_RE = re.compile(r"^Enhancement\s+")
_KEBAB_WORD_RE = re.compile(r"[A-Za-z0-9]+")


class MintRefused(ValueError):
    """An id, slug, or op this module refuses to mint, with the rule it would have broken."""


def slug_from_name(name: str) -> str:
    """`"Enhancement Vigor"` -> `"vigor"`; `"Enhancement Storm Ward"` -> `"storm-ward"`. Requires
    the `"Enhancement "` prefix `schema.answer_schema`'s own pattern already enforces — a name
    reaching this function without it is a caller bug, not a data problem, so it raises rather than
    guessing a fallback slug."""
    if not _NAME_PREFIX_RE.match(name):
        raise MintRefused(
            f"{name!r} does not start with 'Enhancement ' — every real entry's name does "
            f"(enh.001..enh.010), and this module's slug/id minting depends on that prefix")
    tail = _NAME_PREFIX_RE.sub("", name).strip()
    words = _KEBAB_WORD_RE.findall(tail)
    if not words:
        raise MintRefused(f"{name!r} has no word after 'Enhancement ' to slug")
    slug = "-".join(w.lower() for w in words)
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
        raise MintRefused(f"{name!r} produced the non-kebab-legal slug {slug!r}")
    return slug


def runtime_family_for(slug: str) -> str:
    family = f"atom.enhance-{slug}"
    if not ENHANCE_FAMILY_RE.match(family):
        raise MintRefused(f"{family!r} fails the atom.enhance-<name> id convention")
    return family


def name_key_for(slug: str) -> str:
    return f"enh.enhance-{slug}"


def next_entry_id(existing_ids: "set[str] | frozenset[str]") -> str:
    """`enh.{n:03d}`, continuing one past the highest existing numeric suffix — never reusing an id
    a previous run (or the hand-authored wave) already committed, the same "continue, never
    overwrite by coincidence" discipline `generate_affixes.next_draw_start_index` uses for its own
    corpus."""
    max_seq = 0
    for entry_id in existing_ids:
        m = ENTRY_ID_RE.match(entry_id)
        if m:
            max_seq = max(max_seq, int(m.group(1)))
    return f"enh.{max_seq + 1:03d}"


def resolve_op_and_band(channel: str) -> "tuple[str, str]":
    """The ONE lookup that turns a model-chosen channel into `(op, powerBand)` — table-driven,
    deterministic, never a formula. Raises if `channel` is outside `CHANNEL_TUNING` (an answer the
    schema's own enum should already have refused) or if the table itself names an illegal op/band
    (a bug in this module, caught here rather than shipped)."""
    if channel not in CHANNEL_TUNING:
        raise MintRefused(
            f"channel {channel!r} is not offered by CHANNEL_TUNING — the schema's own enum should "
            f"have refused this answer before it reached emit")
    op, band = CHANNEL_TUNING[channel]
    if op == ILLEGAL_STAT_MODIFY_OP or op not in STAT_MODIFY_OPS:
        raise MintRefused(
            f"CHANNEL_TUNING[{channel!r}] names the illegal op {op!r} — stat.modify's real "
            f"vocabulary is {STAT_MODIFY_OPS} (AtomKindRegistry.cs); Override has no revert path")
    if band not in POWER_BANDS:
        raise MintRefused(
            f"CHANNEL_TUNING[{channel!r}] names the unrecognized powerBand {band!r}; "
            f"real values are {POWER_BANDS}")
    return op, band


@dataclass(frozen=True)
class MilestoneEntry:
    """One finished `enh.*` entry, in the real corpus's own field order."""

    entry_id: str
    name_key: str
    name: str
    runtime_family: str
    kind_id: str
    channel: str
    op: str
    power_band: str
    tags: "tuple[str, ...]"
    notes: str

    def to_dict(self) -> dict:
        return {
            "id": self.entry_id,
            "nameKey": self.name_key,
            "name": self.name,
            "runtimeFamily": self.runtime_family,
            "kindId": self.kind_id,
            "params": {"channel": self.channel, "op": self.op},
            "powerBand": self.power_band,
            "tags": list(self.tags),
            "notes": self.notes,
        }


def entry_for(*, entry_id: str, name: str, channel: str, flavor: str,
              tags: "list[str] | tuple[str, ...]") -> MilestoneEntry:
    """Assembles one finished entry from the model's answer plus deterministic resolution. `name`
    is the model's own answer (already validated against the schema's `"Enhancement "` pattern);
    everything else derives from it or from `channel` via table lookup — no field here is a second
    place a number or an op could be authored by hand.
    """
    if not tags:
        raise MintRefused("an entry needs at least one tag")
    slug = slug_from_name(name)
    op, power_band = resolve_op_and_band(channel)
    return MilestoneEntry(
        entry_id=entry_id,
        name_key=name_key_for(slug),
        name=name,
        runtime_family=runtime_family_for(slug),
        kind_id=KIND_ID,
        channel=channel,
        op=op,
        power_band=power_band,
        tags=tuple(dict.fromkeys(tags)),
        notes=flavor,
    )
