"""seedsmith.corpus — the typed graph. Knows nothing about items (spec-foundation §1): no role,
no frame, no rung band, no drop table appears anywhere in this package.
"""
from __future__ import annotations

from .model import Corpus, CorpusLoadError, Edge, Entry

__all__ = ["Corpus", "CorpusLoadError", "Edge", "Entry"]
