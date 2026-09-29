"""seedsmith.adapters.items.gemgen.emit — ids, icon keys, the power-band rotation, and the final
entry shape.

Mirrors `setgen/emit.py`'s own discipline: an id (or field) this module would refuse to mint raises
`IdRefused` naming the exact rule it would have broken, rather than silently producing something
`ContainerValidator.cs` (or `ItemSeedValidator`) would reject later. The contract this module targets
is `docs/architecture/item/entry-shapes.md` §1's own gem shape:

    {
      "id": "gem.g2-014",
      "nameKey": "gem.ember-shard",
      "name": "Ember Shard",
      "family": "atom.elemental-power",
      "element": "fire",
      "powerBand": "medium",
      "affinityElement": "fire",
      "iconKey": "icon.gem.ember-shard",
      "tags": ["offensive"]
    }

`element`/`affinityElement` are omitted for a family with no element variant (§1's own rule) —
`assemble_entry` follows the same omission, never writing a `null`. `affinityElement` additionally
may never be the omni element id (`registries.load_omni_element_id()`) — a socket affinity must be
concrete, so `assemble_entry` refuses an omni value here even though the SAME value is a legal
`element` pick (item-seed-regen cause 8b/3, `GemAffinityNotConcrete`).
"""
from __future__ import annotations

import re

from .. import registries

#: `naming.v1.json`'s `idNamespaces.gems` template is `gem.g{slot}-{seq:03}` — the slot is the
#: partition number VERBATIM (`gems/2` -> slot `"2"`), never zero-padded. Confirmed against both
#: shipped partitions' own ids (`gem.g1-001`, `gem.g3-001`) and entry-shapes.md §1's own example
#: (`gem.g2-014`).
PARTITION_RE = re.compile(r"^gems/([1-9]\d*)$")
GEM_ID_RE = re.compile(r"^gem\.g[1-9]\d*-\d{3}$")

#: A gem's `nameKey` is `gem.<kebab-body>` — the same kebab discipline `setgen/emit.py`'s own
#: `CONTAINER_ID_RE` enforces for container ids, narrowed to the one-dot `gem.` prefix this kind
#: always takes.
NAME_KEY_RE = re.compile(r"^gem\.[a-z][a-z0-9]*(-[a-z0-9]+)*$")

#: entry-shapes.md §1's own "Rejects" line: "the id outside the `gems` prefix or its 001-899
#: wave-1 range." 900-999 stays reserved in every partition for later hand-authored corrections,
#: identical to `setgen/emit.py`'s own `SEQ_MAX` and for the same reason.
SEQ_MIN = 1
SEQ_MAX = 899

#: The three power bands every shipped gem partition has actually used (g1.json, g3.json, both read
#: fresh in the corpus's own test — see test_sockets_gen.py). `bands.v1.json`'s own `powerBand.enum`
#: is wider (adds `trivial`/`extreme`), but this module stays inside the PROVEN subset until a real
#: balance need asks for the other two rungs — widening this rotation is a one-line, reviewed change,
#: not a silent guess at what an unused rung should mean here.
#:
#: A fixed round robin, not a per-family judgement call, because gem partitioning itself has "no
#: thematic or mechanical meaning" (entry-shapes.md §1's own finding) — the same is true of which
#: rung a given batch position lands on.
POWER_BAND_ROTATION: "tuple[str, ...]" = ("medium", "high", "low")


class IdRefused(ValueError):
    """An id/field this module refuses to mint, with the rule it would have broken."""


def partition_slot(partition: str) -> str:
    match = PARTITION_RE.match(partition)
    if not match:
        raise IdRefused(f"{partition!r} is not a gems/<N> partition (e.g. 'gems/2')")
    return match.group(1)


def mint_gem_id(partition: str, seq: int) -> str:
    """`gem.g{slot}-{seq:03}`. Refuses a `seq` outside the wave-1 range rather than minting
    something `ItemSeedValidator` would reject on import."""
    slot = partition_slot(partition)
    if not (SEQ_MIN <= seq <= SEQ_MAX):
        raise IdRefused(
            f"seq {seq} is outside {SEQ_MIN}-{SEQ_MAX}; 900-999 is reserved in every partition for "
            f"later hand-authored corrections (entry-shapes.md §1)")
    minted = f"gem.g{slot}-{seq:03d}"
    if not GEM_ID_RE.match(minted):
        raise IdRefused(f"{minted!r} fails the gem id grammar gem.g<slot>-<seq:03>")
    return minted


def resolve_power_band(index: int) -> str:
    """`index` is the entry's zero-based position within its OWN partition batch. Deterministic and
    reproducible across runs — the harness's own resume/idempotency requirement (spec-generator-
    harness.md, RunLedger acceptance #1) extends to every value a re-run would recompute, not only
    the id."""
    if index < 0:
        raise IdRefused(f"index {index} must be >= 0")
    return POWER_BAND_ROTATION[index % len(POWER_BAND_ROTATION)]


def icon_key(name_key: str) -> str:
    if not NAME_KEY_RE.match(name_key):
        raise IdRefused(f"nameKey {name_key!r} fails the gem nameKey grammar gem.<kebab-body>")
    return f"icon.{name_key}"


def assemble_entry(*, entry_id: str, name_key: str, name: str, family_id: str, power_band: str,
                   tags: "tuple[str, ...]", element: "str | None" = None,
                   affinity_element: "str | None" = None) -> dict:
    """Field ORDER matches the shipped `g1.json`/`g3.json` shape exactly: `id`, `nameKey`, `name`,
    `family`, `[element]`, `powerBand`, `[affinityElement]`, `iconKey`, `tags`.
    `GemInsertCorpus.Load` (ItemCardEndpoints.cs) reads by key name, not position, so this ordering
    is not load-bearing for the production reader — it is kept anyway so a future diff against the
    hand-authored corpus stays about content, never about a generator picking a different field
    order for no reason.
    """
    if not GEM_ID_RE.match(entry_id):
        raise IdRefused(f"entry id {entry_id!r} fails the gem id grammar")
    if not NAME_KEY_RE.match(name_key):
        raise IdRefused(f"nameKey {name_key!r} fails the gem nameKey grammar gem.<kebab-body>")
    if not name:
        raise IdRefused("name must be non-empty")
    if not family_id.startswith("atom."):
        raise IdRefused(f"family {family_id!r} is not an atom.* reference")
    if power_band not in POWER_BAND_ROTATION:
        raise IdRefused(f"powerBand {power_band!r} is outside this module's proven rotation "
                        f"{POWER_BAND_ROTATION}")
    if affinity_element is not None and affinity_element == registries.load_omni_element_id():
        # `element` legitimately includes omni (the `elements+omni` variant generator), but
        # `affinityElement` is a socket affinity and must always be concrete -- item-seed-regen
        # cause 8b/3 (GemAffinityNotConcrete): the caller must omit affinityElement (None) rather
        # than forward an omni element pick into it.
        raise IdRefused(
            f"affinityElement {affinity_element!r} is omni, not a concrete element; pass None to "
            f"omit it instead of forwarding the element pick verbatim")

    entry: dict = {
        "id": entry_id,
        "nameKey": name_key,
        "name": name,
        "family": family_id,
    }
    if element is not None:
        entry["element"] = element
    entry["powerBand"] = power_band
    if affinity_element is not None:
        entry["affinityElement"] = affinity_element
    entry["iconKey"] = icon_key(name_key)
    entry["tags"] = list(tags)
    return entry
