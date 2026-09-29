"""Shared fixture builder for the H1 nodegen tests. Not a test module itself (no `test_` prefix, so
pytest never collects it) — just the one place a synthetic, minimal-but-valid `tree-plan` document
gets built, so `plan_read`/`run`/`emit` tests do not each invent a slightly different fixture shape.

Deliberately synthetic rather than the real 1,560-node committed plan: H1's own tests exercise the
CONTRACT layer (does `plan_read` refuse a missing key, does `run.plan_run` skip a done subject),
which needs a small, fast, hand-shaped plan — not the live corpus B1 emits, which `test_tree_plan_*
.py` already exercises end to end for task B1's own acceptance.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def minimal_plan(tree_id: str = "fixture-tree", node_count: int = 4) -> "dict[str, Any]":
    nodes = []
    for i in range(node_count):
        branch = "offensive" if i % 2 == 0 else "defensive"
        tier = 1 + (i // 2)
        nodes.append({
            "id": f"skill.{tree_id}-{'off' if branch == 'offensive' else 'def'}-t{tier}-n{i}",
            "nodeKey": f"n{i}",
            "branch": branch,
            "tier": tier,
            "indexInTier": 0,
            "nodeClass": "mechanism" if i == 0 else "magnitude",
            "budgetShareMilli": 250,
            "budgetPoints": 25,
        })
    return {
        "schemaVersion": 1,
        "treeId": tree_id,
        "archetype": "broad-and-flat",
        "propertyVocabulary": {
            "posture": ["vanguard", "warden", "trickster"],
            "conversionState": ["converted", "unconverted"],
        },
        "mechNodesByTier": [1, 1, 0, 0, 0, 0, 0, 0, 0, 4],
        "nodes": nodes,
    }


def write_plan(seed_root: Path, tree_id: str = "fixture-tree", node_count: int = 4) -> Path:
    plan = minimal_plan(tree_id, node_count)
    path = seed_root / "passive-tree" / "plan" / f"{tree_id}.v1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return path


def raising_call(*args, **kwargs):
    """task H2's own offline transport stub (§7 gate 24) — the SAME pattern already used four times
    over in this repo (`test_classify_pipelines.py`, `test_family_propose.py`,
    `test_general_propose.py`, `test_signature_propose.py`): patch
    `seedsmith.pipeline.llm_caller.call_model` with this, and any test path that reaches a model
    fails loudly and immediately rather than hanging on a real HTTP call or returning a fake
    success. Shared here (rather than redefined per file, H1's own file did not yet need it) so
    every H2 test file in this directory imports the one copy."""
    raise AssertionError("a real model call was attempted — this test's transport must never be reached")
