"""seedsmith.adapters — the feature seam (spec-foundation §2).

Everything item-shaped lives behind `SeedAdapter`. The core (`corpus`, `metrics`, `report`) never
imports `adapters.items` directly — only through the protocol in `base.py`.
"""
from __future__ import annotations

from .base import Channel, Dimension, KindSpec, LegalityFn, RegistrySet, SeedAdapter, Unit

__all__ = [
    "Channel", "Dimension", "KindSpec", "LegalityFn", "RegistrySet", "SeedAdapter", "Unit",
]
