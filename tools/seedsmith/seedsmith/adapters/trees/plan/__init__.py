"""seedsmith.adapters.trees.plan — tree-plan, Stage 1 of the passive-tree generator (task B1,
spec-tree-plan.md). Deterministic, no model calls. Emits topology, the tier ladder, the budget
column, the shape archetype, the property vocabulary and per-node ids for one tree.

`python -m seedsmith trees plan --emit` per the spec's own Commands section — the CLI wiring lands
alongside `emit.py`.
"""
from __future__ import annotations
