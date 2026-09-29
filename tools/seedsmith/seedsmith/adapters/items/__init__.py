"""seedsmith.adapters.items — the real item feature, wired to `gk-data/packs/fusion/data/seed/items/`.

Confirmed fresh 2026-08-23 against the live corpus and `gk-forge/tools/ItemSeedValidator`'s own
`--list-partitions` output (not carried over from an earlier session's numbers, which had
drifted — see `_registry_snapshot/allocated_partitions.json`'s docstring): **121 files, 1,430
entries, 126 allocated partitions, 9 currently empty.**
"""
from __future__ import annotations

from .channels import build_channels
from .kinds import KINDS
from .registries import (
    COMMANDER_ROLE,
    HYBRID_FRAME_EXCLUDED_ROLES,
    load_versions,
    load_vocabularies,
)
from ..base import Dimension, KindSpec, RegistrySet


def _applies_to(field_name: str) -> frozenset[str]:
    return frozenset(k.kind for k in KINDS if field_name in k.required or field_name in k.optional)


class ItemsAdapter:
    def kinds(self) -> "list[KindSpec]":
        return list(KINDS)

    def dimensions(self) -> "list[Dimension]":
        vocab = load_vocabularies()
        return [
            Dimension(id="role", values=tuple(sorted(vocab["role"])), field="role",
                     applies_to=_applies_to("role")),
            Dimension(id="frame", values=tuple(sorted(vocab["frame"])), field="frame",
                     applies_to=_applies_to("frame")),
            Dimension(id="band", values=tuple(sorted(vocab["band"])), field="band",
                     applies_to=_applies_to("band")),
            Dimension(id="powerBand", values=tuple(sorted(vocab["powerBand"])),
                     field="powerBand", applies_to=_applies_to("powerBand")),
            Dimension(id="element", values=tuple(sorted(vocab["element"])), field="element",
                     applies_to=_applies_to("element")),
            Dimension(id="rarity", values=tuple(sorted(vocab["rarity"])), field="rarity",
                     applies_to=_applies_to("rarity")),
            # "class" deliberately NOT exposed as a pairwise dimension yet: its 28 real values
            # (registries.py's `class_values`) are frame- AND role-restricted per rung
            # (classes.v1.json's classLadders[ladder][frame][i].roles), which legal_combinations
            # does not encode. Exposing it today would report every (dimension, class) pair a
            # rung's own roles/frame don't reach as a false hole — measured directly: doing so
            # produced 100%-missing findings for band×class/frame×class/role×class, the exact
            # "confidently wrong" trap spec-analytics §2.2 warns about. `registries().vocabularies
            # ["class"]` still carries the correct vocabulary for whatever DOES need it (e.g. a
            # future closed-vocabulary check on the field itself).
        ]

    def legal_combinations(self):
        def _legal(dim_a: str, val_a: str, dim_b: str, val_b: str) -> bool:
            paired = {dim_a: val_a, dim_b: val_b}
            if set(paired) == {"role", "frame"}:
                role, frame = paired["role"], paired["frame"]
                if frame == "hybrid" and (role in HYBRID_FRAME_EXCLUDED_ROLES
                                          or role == COMMANDER_ROLE):
                    return False
            return True
        return _legal

    def registries(self) -> RegistrySet:
        return RegistrySet(vocabularies=load_vocabularies(), versions=load_versions())

    def channels(self):
        return list(build_channels())
