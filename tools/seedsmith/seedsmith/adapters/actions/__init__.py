"""seedsmith.adapters.actions — the `action-corpus` program's adapter, wired to
`gk-data/packs/fusion/data/seed/actions/` (spec-corpus-loader.md, module A-C1).

Structured the same way as `adapters/items` (the smaller of the two existing real adapters, per
this module's own build instructions): `kinds.py` for the ten `KindSpec`s, `vocab.py` for the
closed vocabularies transcribed from the C# code of record plus the ones read fresh from data,
`load.py` for the load algorithm (spec §3) built entirely on `corpus.model`'s own `Corpus.load` /
`Corpus.add` / `discover_edges` primitives.
"""
from __future__ import annotations

from .kinds import KINDS
from .load import Finding, LoadResult, load_committed
from .vocab import (
    ACTION_KINDS,
    AREA_SHAPES,
    CATEGORIES,
    PAIRING_ROLES,
    RELATIONS,
    SCOPES,
    STATUSES,
    TAGS,
    TARGET_MODES,
    load_accepted_family_ids,
    load_family_map_keys,
    load_pairing_keys,
)
from ..base import Channel, Dimension, KindSpec, RegistrySet

__all__ = ["ActionsAdapter", "Finding", "LoadResult", "load_committed"]


def _applies_to(field_name: str) -> "frozenset[str]":
    return frozenset(k.kind for k in KINDS if field_name in k.required or field_name in k.optional)


class ActionsAdapter:
    def kinds(self) -> "list[KindSpec]":
        return list(KINDS)

    def dimensions(self) -> "list[Dimension]":
        return [
            Dimension(id="category", values=tuple(sorted(CATEGORIES)), field="category",
                     applies_to=_applies_to("category")),
            Dimension(id="targetMode", values=tuple(sorted(TARGET_MODES)), field="targetMode",
                     applies_to=_applies_to("targetMode")),
            Dimension(id="areaShape", values=tuple(sorted(AREA_SHAPES)), field="areaShape",
                     applies_to=_applies_to("areaShape")),
            Dimension(id="relation", values=tuple(sorted(RELATIONS)), field="relation",
                     applies_to=_applies_to("relation")),
            Dimension(id="scope", values=tuple(sorted(SCOPES)), field="scope",
                     applies_to=_applies_to("scope")),
            Dimension(id="pairingRole", values=tuple(sorted(PAIRING_ROLES)), field="pairingRole",
                     applies_to=_applies_to("pairingRole")),
            Dimension(id="kindHint", values=tuple(sorted(ACTION_KINDS)), field="kindHint",
                     applies_to=_applies_to("kindHint")),
        ]

    def legal_combinations(self):
        def _legal(dim_a: str, val_a: str, dim_b: str, val_b: str) -> bool:
            paired = {dim_a: val_a, dim_b: val_b}
            if set(paired) == {"targetMode", "areaShape"} and paired["targetMode"] != "area":
                # ActionTargetSpec.Shape is `Area`-only ("`Area` only", ActionTargetSpec.cs:86) —
                # an areaShape value paired with any other target mode is not a real combination,
                # the same real-rule-not-invented-example discipline `items`/`creatures` document for
                # their own one illegal pair (base.py's own warning: a `LegalityFn` returning
                # `True` unconditionally turns every real illegal pair into a permanent false
                # Coverage finding).
                return False
            return True
        return _legal

    def registries(self) -> RegistrySet:
        return RegistrySet(
            vocabularies={
                "kind": ACTION_KINDS, "category": CATEGORIES, "tag": TAGS,
                "targetMode": TARGET_MODES, "areaShape": AREA_SHAPES, "relation": RELATIONS,
                "status": STATUSES, "scope": SCOPES, "pairingRole": PAIRING_ROLES,
                "atomFamily": load_accepted_family_ids(), "pairingKey": load_pairing_keys(),
                "familyMapKey": load_family_map_keys(),
            },
            versions={},
        )

    def channels(self) -> "list[Channel]":
        # Deliberately empty, same reasoning `adapters/creatures` states for itself (§2.6): constraint
        # 1 — "an atom names a POOL; element, tier and cell resolve at layer 4, per player, at roll
        # time" — so a generated action-seed carries no magnitude at all, only pool references.
        # `numerics` is consumed only via `adapter.channels()`; an empty list makes "never a
        # number" structural for this feature rather than a rule someone has to remember.
        return []
