"""seedsmith.adapters.actions.kinds — the ten `action-corpus` KindSpecs (spec-corpus-loader.md §2).

Only `action-seed`'s shape is specified by this module's own spec (§3 step 4) — `required` /
`optional` / `reference_fields` transcribed verbatim, post the F7 correction (`atomPools` ->
`atomFamilies`, `enablesStatus` -> `pairedPayoffFamily`, `pairingRole` moved into `required`
because `none` is a value, never an omission). The other nine kinds are owned by whichever module
writes them (A-S1/A-S2/A-S3/A-S5/A-S6/A-T1/A-S0) — this loader only needs their `id_pattern` so
`discover_edges` can record a reference TO one of their ids, so their `required`/`optional` stay at
the common `{id}` floor. Same discipline as `adapters/items/kinds.py`'s `_undefined()` helper for a
kind with no authored shape yet (there: `attribute`; here: nine of the ten).

`id_pattern` is a PER-KIND field, not one shared pattern for the whole adapter (the spec's own F
correction, from review): a single `action.`-only pattern would silently drop every cross-kind edge
for the other nine kinds, because `Corpus.discover_edges` only records an edge where the id_pattern
it was CALLED WITH matches (`corpus/model.py:154`) — and `load.load_committed` calls it once per
kind (§2: "discover_edges is called once per kind with that kind's pattern").
"""
from __future__ import annotations

import re

from ..base import KindSpec

ACTION_SEED_REQUIRED = frozenset({
    "id", "scope", "category", "rungBand", "targetMode", "relation", "atomFamilies", "pairingRole",
})
ACTION_SEED_OPTIONAL = frozenset({
    "scopeKey", "areaShape", "tags", "kindHint", "structureAxes", "pairedPayoffFamily",
    "motifsUsed", "name",
    # ⚠ `description` was here from 2026-09-08 to 2026-10-05 and is RETIRED — it was declared as
    # "the AUTHORED English text `descriptionKey` will eventually resolve to", on the items'
    # `flavor`/`flavorKey` precedent. It was never that: nothing resolved it. `ActionRow` has no
    # `Description` field (it carries `DescriptionKey` and nothing else), `ActionCorpusBriefJson`
    # parses `descriptionKey` and never a `description` element, and the player-visible sentence
    # resolves through `ItemCard.GrantedActionLines` → `LookupString(a.DescriptionKey)` against
    # `gk-content/content/display/en.json`. Measured before removal: 181 rows carried it, 25 of
    # those keys exist in the display catalog, and NONE of the 25 matched its catalog row — the
    # corpus contradicted the text a player reads, in 25 places, while being unread in all 181.
    # The prose belongs to gk-content, which is where `innate_picker/derive.py`'s own comment on
    # `descriptionKey` already said it lands. `descriptionKey` is untouched and still required by
    # `ActionCorpusBriefJson.Parse`.
    #
    # The committed corpus is rewritten by `migrate_retired_description.py` (`--check` is the CI
    # gate) — never by hand.
})
ACTION_SEED_REFERENCES = frozenset({"atomFamilies", "pairedPayoffFamily", "scopeKey"})


def _seed(kind: str, directory: str, pattern: str) -> KindSpec:
    return KindSpec(kind=kind, directory=directory, namespace=kind,
                    required=ACTION_SEED_REQUIRED, optional=ACTION_SEED_OPTIONAL,
                    id_pattern=re.compile(pattern), reference_fields=ACTION_SEED_REFERENCES)


def _unspecified(kind: str, directory: str, pattern: str) -> KindSpec:
    # Shape owned by the writer named in the module docstring — only `id` is asserted here, same
    # as `items.kinds._undefined`.
    return KindSpec(kind=kind, directory=directory, namespace=kind,
                    required=frozenset({"id"}), optional=frozenset(),
                    id_pattern=re.compile(pattern))


KINDS: "tuple[KindSpec, ...]" = (
    _seed("action-seed", "",
         r"^action\.(general\.[0-9]{3,}|(family|species)\.[a-z0-9_-]+\.[0-9]{3,})$"),
    _unspecified("action-brief", "_briefs",
                r"^brief\.(general|family|species)\.[a-z0-9_-]+\.[0-9]{3,}$"),
    _unspecified("action-reject", "_rounds", r"^reject\.[a-z0-9_.-]+$"),
    _unspecified("action-review", "_rounds", r"^review\.[a-z0-9_.-]+$"),
    _unspecified("action-coverage", "_reports", r"^(cell|target)\.[a-z0-9_.-]+$"),
    _unspecified("action-innate", "", r"^innate\.[a-z0-9_-]+$"),
    _unspecified("action-type-weights", "_generated", r"^weights\.(species|family)\.[a-z0-9_-]+$"),
    _unspecified("action-role-lean", "_generated", r"^lean\.[a-z0-9_-]+$"),
    _unspecified("action-characteristic-pool", "_generated", r"^pool\.[a-z0-9_-]+$"),
    # A manifest entry, not an entry graph (§2's table: "(none) — a manifest entry, not an entry
    # graph") — no `id_pattern`, so `load.load_committed` skips it when calling `discover_edges`.
    KindSpec(kind="action-config", directory="", namespace="action-config"),
)

assert len(KINDS) == 10, "action-corpus-map.md §4 names ten model-free-relevant kinds (nine writers + config)"
assert len({k.kind for k in KINDS}) == 10, "duplicate kind id in this port"
