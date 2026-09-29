"""seedsmith.adapters.items.gemgen.brief — an unauthored affix family -> a brief.

Mirrors `setgen/brief.py`'s own discipline (no magnitude, no invented vocabulary, closed picks
inlined) but the shape is simpler: a gem does not carry a theme, a role list, or a threshold ladder —
it is one fixed container that grants ONE already-shipped effect family. So the only things this
brief ever asks a model to choose are the two genuinely creative fields, `name`/`nameKey`, plus,
only when the family has a per-element variant, which element this particular pick expresses.

Two things this module deliberately does NOT ask the model, and why:

- **`tags`** — a straight copy of the family's OWN authored, VALIDATED `tags` (read fresh from
  `gk-data/packs/fusion/data/seed/items/affix-families/*.json`). Asking the model to re-derive them risks a value that
  disagrees with the family's own combat-posture axis; the family already settled that question.
- **`powerBand`** — `emit.resolve_power_band`'s deterministic rotation. `entry-shapes.md` §1's own
  finding — "a gem's id slot number is load-bearing only for collision-safety, never for content" —
  applies exactly as well to which power-band rung a given batch position lands on.

**Which family a given subject gets is also decided by CODE, not the model** — see
`unauthored_families` below. A model choosing its own family from a big list is exactly the kind of
extra, uncontrolled degree of freedom `setgen`'s exemplar-dedup work already found expensive to
audit after the fact; here it is simply not offered.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import registries
from ..naming_grammar import NAMING_GRAMMAR_RULES
from ..setgen import vocab as setgen_vocab

#: Bumped 1->2 (item-seed-regen cause 3, 2026-09-20): now states naming.v1.json's naming grammar.
PROMPT_VERSION = "gem-gen/2"

#: `setgen/vocab.py`'s own docstring: "A family whose `variants` block says
#: `{"generate": "elements+omni"}` expands into one pick per element plus omni". This module treats
#: any such family as elemental and defers it out of the default flat-family pool
#: (`unauthored_families`) rather than emitting seven picks — one per element plus omni — for a
#: single batch slot; a partition that wants an elemental family is a deliberate, reviewed choice,
#: not this pool's default.
ELEMENT_VARIANT_GENERATOR = "elements+omni"


def is_elemental(family_row: dict) -> bool:
    variants = family_row.get("variants")
    return isinstance(variants, dict) and variants.get("generate") == ELEMENT_VARIANT_GENERATOR


#: Back-compat alias for call sites within this package that reach for the "private" spelling.
_is_elemental = is_elemental


def load_family_rows(directory: "Path | None" = None) -> "dict[str, dict]":
    """Every shipped affix-family row, keyed by id. Reuses `setgen.vocab.load_families` — the same
    glob-and-filter this program already proved at ~1,800-entry scale — rather than a second copy
    of the same read."""
    return {row["id"]: row for row in setgen_vocab.load_families(directory)}


def used_families(gems_dir: "Path | None" = None) -> "frozenset[str]":
    """Every `family` value already claimed by a shipped gem, read fresh from
    `gk-data/packs/fusion/data/seed/items/gems/*.json` on every call — never hardcoded, so a hand edit or a prior run's
    output is picked up on the very next call, matching `registries.py`'s own "read, never
    transcribe" discipline."""
    directory = gems_dir or (setgen_vocab.REPO_ROOT / "data" / "seed" / "items" / "gems")
    claimed: "set[str]" = set()
    if not directory.exists():
        return frozenset()
    for path in sorted(directory.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for entry in doc.get("entries", []):
            family = entry.get("family")
            if isinstance(family, str):
                claimed.add(family)
    return frozenset(claimed)


def unauthored_families(*, limit: "int | None" = None, gems_dir: "Path | None" = None,
                        family_rows: "dict[str, dict] | None" = None) -> "list[dict]":
    """The candidate pool for a NEW gem batch: every shipped affix-family whose id is not yet
    claimed by any gem entry, flat families only (elemental ones deferred, see `_is_elemental`),
    sorted by id so a rerun against unchanged on-disk state always proposes the same families in the
    same order — the id a family lands on is then only a function of ITS OWN position, never of
    iteration order over a dict. `limit` caps the result the way a partition's own batch size does;
    `None` returns the whole pool (used by tests that want to see everything still open)."""
    rows = family_rows if family_rows is not None else load_family_rows()
    claimed = used_families(gems_dir)
    pool = [rows[family_id] for family_id in sorted(rows)
           if family_id not in claimed and not _is_elemental(rows[family_id])]
    return pool if limit is None else pool[:limit]


def build_gem_brief(family_row: dict) -> str:
    """One gem, one already-selected family. `element` is offered only when the family is
    elemental — `unauthored_families`'s default pool never selects one, but the brief stays correct
    for a caller that hands it an elemental family directly (a deliberate, reviewed choice, per this
    module's own docstring)."""
    family_id = family_row["id"]
    family_name = family_row.get("name", family_id)
    elemental = _is_elemental(family_row)
    element_ask = ""
    if elemental:
        elements = sorted(registries.load_vocabularies()["element"])
        element_ask = (
            f"\n2. `element` — exactly one of: {', '.join(elements)}. This family has a per-element "
            f"variant, and this is which one THIS gem expresses.")
    return f"""Author ONE socket insert (a "gem") that grants the existing effect family
`{family_id}` ("{family_name}").

This is a fixed container: it does not invent a new effect, a magnitude, or a tier — it only needs a
name that fits what `{family_name}` already does.

Choose, and nothing else:
1. `name` and `nameKey` (`gem.<kebab-name>`, matching the name). Never reuse an existing shipped
   gem's name or nameKey.{element_ask}

{NAMING_GRAMMAR_RULES}

Never choose a number, a tier, a power band, or a tag — those are resolved after you answer.

If this family cannot carry a gem you would be happy to ship, set `blocked` and say why."""
