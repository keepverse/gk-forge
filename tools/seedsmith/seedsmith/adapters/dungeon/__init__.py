"""seedsmith.adapters.dungeon — the party-dungeon feature (party-dungeon-map.md modules 1-2),
wired to `gk-data/packs/fusion/data/seed/dungeon/`. spec-dungeon-registries.md, spec-dungeon-seed-contract.md.

D1.5 landed `registries.py`. D1.6-D1.8 land here: the seven `KindSpec`s (`kinds.py`), their
schemas and ownership tables (`schema.py`), the §2 audit (`audit.py`), and this module's
`DungeonAdapter` — registered as `"dungeon"` in `adapters/registry.py` (D1.8).
"""
from __future__ import annotations

from .audit import run_audit
from .kinds import KINDS, MODEL_FREE_KINDS
from .registries import load_bands, load_room_kinds, load_vocabularies, load_versions
from .schema import ELEMENTS, OWNERSHIP_BY_KIND, SCHEMA_BUILDERS, build_schema
from ..base import Dimension, KindSpec, RegistrySet

#: The four room kinds every room's `climate` must be `none` on — every other kind admits any of
#: the six elements, plus `none` (a climate-blind archetype of that kind). This is §3.6's real
#: legality rule: without it, 24 of 77 (kind x climate) cells would be permanent false Coverage
#: positives (base.py's own warning against an always-True `legal_combinations`).
CLIMATE_NEUTRAL_ROOM_KINDS = frozenset({"rest", "merchant", "boss", "unknown"})


class DungeonAdapter:
    def kinds(self) -> "list[KindSpec]":
        return list(KINDS)

    def dimensions(self) -> "list[Dimension]":
        vocab = load_vocabularies()
        return [
            Dimension(id="roomKind", values=tuple(sorted(vocab["roomKind"])), field="kind",
                     applies_to=frozenset({"kind"})),
            Dimension(id="climate", values=tuple(sorted(ELEMENTS)) + ("none",), field="climate",
                     applies_to=frozenset({"climate"})),
            Dimension(id="formation", values=tuple(sorted(vocab["formation"])), field="formation",
                     applies_to=frozenset({"formation"})),
            Dimension(id="elementSpread", values=tuple(sorted(vocab["elementSpread"])), field="elementSpread",
                     applies_to=frozenset({"elementSpread"})),
        ]

    def legal_combinations(self):
        def _legal(dim_a: str, val_a: str, dim_b: str, val_b: str) -> bool:
            paired = {dim_a: val_a, dim_b: val_b}
            if set(paired) == {"roomKind", "climate"}:
                kind = paired["roomKind"]
                climate = paired["climate"]
                if kind in CLIMATE_NEUTRAL_ROOM_KINDS:
                    return climate == "none"
                return True  # the seven climate-bearing kinds legally admit any element, and `none`
            return True

        return _legal

    def registries(self) -> RegistrySet:
        return RegistrySet(vocabularies=load_vocabularies(), versions=load_versions())

    def channels(self):
        # Deliberately empty, same reasoning as creatures/items adapters carrying no dungeon-owned
        # magnitude: no seed file here carries a number (spec §"Numeric types") — every magnitude
        # is resolved by the consuming C# module from dungeon.v1.json/encounter.v1.json, never
        # authored or generated in a seed.
        return []

    def audit(self, kind: "str | None" = None):
        return run_audit(kind)


__all__ = ["DungeonAdapter", "KINDS", "MODEL_FREE_KINDS", "SCHEMA_BUILDERS", "OWNERSHIP_BY_KIND", "build_schema"]
