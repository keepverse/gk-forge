"""seedsmith.adapters.registry — name -> adapter mapping, so `report.cli` never hardcodes which
feature adapters exist. S2 adds `"items"` here and nowhere else in `report`.
"""
from __future__ import annotations

from ._stub import StubAdapter
from .actions import ActionsAdapter
from .creatures import CreaturesAdapter
from .dungeon import DungeonAdapter
from .items import ItemsAdapter

ADAPTERS: "dict[str, type]" = {
    "stub": StubAdapter,
    "items": ItemsAdapter,
    "creatures": CreaturesAdapter,
    "actions": ActionsAdapter,
    "dungeon": DungeonAdapter,
}


def resolve_adapter(name: str):
    cls = ADAPTERS.get(name)
    if cls is None:
        raise KeyError(name)
    return cls()


def known_adapter_names() -> list[str]:
    return sorted(ADAPTERS)
