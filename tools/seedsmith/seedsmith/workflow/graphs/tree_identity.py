"""passive-tree's own tree-identity stage (`seedsmith-content-standard`, Task 17,
spec-passive-tree-identity-content.md §5). Thin wiring only, matching `species_codex.py`'s own
shape exactly — no `StateGraph(` call of its own, only `build_generation_graph`.
"""
from __future__ import annotations

from typing import Any, Callable

from ...adapters.trees.identity.prompts import (
    TREE_IDENTITY_SYSTEM_PROMPT, build_identity_brief, build_identity_context,
)
from ...adapters.trees.identity.schemas import TREE_IDENTITY_RESPONSE_SCHEMA, tree_identity_defects
from ...pipeline.llm_caller import LlmCallerConfig
from ..nodes.generate import make_generate_node
from ..nodes.persist import make_persist_node
from ..nodes.validate import make_validate_node
from ..state import new_state
from .base import build_generation_graph

__all__ = ["build_tree_identity_graph", "state_for_tree_identity", "TREE_IDENTITY_VALIDATORS",
          "tree_identity_content_is_clean"]


def tree_identity_content_is_clean(draft: "dict[str, Any]", context: "dict[str, Any]") -> "list[str]":
    """Run as a validator so a defect becomes a REPAIR prompt, not a silent accept — mirrors
    `codex_summary_content_is_clean`'s own contract exactly."""
    return tree_identity_defects(draft.get("name", ""), draft.get("description", ""))


TREE_IDENTITY_VALIDATORS = (tree_identity_content_is_clean,)


def build_tree_identity_graph(
    *,
    on_persist: "Callable[[str, dict], None] | None" = None,
    config: LlmCallerConfig | None = None,
    call: "Callable[..., str] | None" = None,
    checkpointer: "Any | None" = None,
):
    """`call` is injected so a test — or `--dry-run` — can prove zero model calls happen, the same
    contract every graph in this program already honours."""
    return build_generation_graph(
        generate=make_generate_node(
            system=TREE_IDENTITY_SYSTEM_PROMPT, schema=TREE_IDENTITY_RESPONSE_SCHEMA,
            config=config, call=call),
        validate=make_validate_node(TREE_IDENTITY_VALIDATORS),
        persist=make_persist_node(on_persist),
        checkpointer=checkpointer,
    )


def state_for_tree_identity(subject_id: str, tree_id: str, category: str,
                            branches: "list[str]", sample_nodes: "list[tuple[str, str]]") -> dict:
    """Renders the brief via `build_identity_brief` — never assembled ad hoc at the call site,
    mirroring `state_for_species_codex`'s own discipline."""
    context = build_identity_context(tree_id, category, branches, sample_nodes)
    brief = build_identity_brief(context)
    return new_state(subject_id, brief=brief, context=context)
