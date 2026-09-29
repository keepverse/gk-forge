"""Thin wiring for the commander-effect generator (G4.2) — no new control flow.

The only module in this feature that imports LangGraph, per the seam (spec-workflow-runtime §2.1).
"""
from __future__ import annotations

from typing import Any, Callable

from ...adapters.creatures.commander_effect import (
    COMMANDER_EFFECT_SCHEMA,
    SYSTEM_PROMPT,
    VALIDATORS,
)
from ...pipeline.llm_caller import LlmCallerConfig
from ..nodes.generate import make_generate_node
from ..nodes.persist import make_persist_node
from ..nodes.validate import make_validate_node
from .base import build_generation_graph

__all__ = ["build_commander_effect_graph"]


def build_commander_effect_graph(
    *,
    on_persist: "Callable[[str, dict], None] | None" = None,
    config: LlmCallerConfig | None = None,
    call: "Callable[..., str] | None" = None,
    checkpointer: "Any | None" = None,
):
    """Constrained decoding is on by default (`schema=`), so a malformed shape is unsampleable
    rather than merely detected (G0.3)."""
    return build_generation_graph(
        generate=make_generate_node(system=SYSTEM_PROMPT, schema=COMMANDER_EFFECT_SCHEMA,
                                    config=config, call=call),
        validate=make_validate_node(VALIDATORS),
        persist=make_persist_node(on_persist),
        checkpointer=checkpointer,
    )
