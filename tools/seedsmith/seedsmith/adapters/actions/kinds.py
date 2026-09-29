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
    # `description` (seedsmith-content-standard, content-completeness-actions, Task 8) — the
    # AUTHORED player-facing flavour text this domain never had a field for at all
    # (`spec-content-completeness-actions.md` §2: `candidate_assembly/derive.py`'s own 2026-09-04
    # comment flagged this exact split as "a real, separate, reviewed schema change... not
    # something to smuggle in here" — this is that reviewed change). Mirrors `items/kinds.py`'s
    # `flavor`/`flavorKey` pair exactly: `descriptionKey` (already minted, above, in
    # ACTION_SEED_OPTIONAL) is the stable i18n-ready identifier; `description` is the real English
    # text that identifier will eventually resolve to. Optional, not required, matching `name`'s
    # own optionality — the completeness *metric* (not the schema) is what reports a real gap.
    "description",
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
