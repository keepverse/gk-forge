"""The shared generation skeleton (spec-workflow-runtime.md §2.2-§2.3).

    START -> generate -> validate -> route -> { persist | generate | escalate } -> END

⛔ **Bounded three independent ways**, because failing to terminate is the single largest
field-observed agent failure class (28.1%: step repetition 15.7% + unaware of termination 12.4%):

  1. `attempts` in state, checked by `route_after_validate`
  2. LangGraph's own `recursion_limit` — a backstop if the routing function is ever wrong
  3. a terminal `escalate` node — exhausting the budget is an OUTCOME, never a silent give-up

There is no unbounded `while` anywhere in this module.
"""
from __future__ import annotations

from typing import Any, Callable, Literal

from langgraph.graph import END, START, StateGraph

from ..nodes.generate import MAX_ATTEMPTS
from ..nodes.persist import escalate_node
from ..state import RECURSION_LIMIT, GenerationState

__all__ = ["build_generation_graph", "route_after_validate", "RECURSION_LIMIT"]

# RECURSION_LIMIT is defined in `..state` (engine-free) and re-exported here for callers that
# already import the graph layer. Stop #2 of three: it fires only when routing is itself broken —
# exactly the bug it exists to catch, and which a test exercises.


def route_after_validate(state: dict) -> Literal["persist", "generate", "escalate"]:
    """Stop #1. Clean -> persist. Defective and budget remains -> repair. Budget spent -> escalate."""
    if not state.get("defects"):
        return "persist"
    if int(state.get("attempts", 0)) >= MAX_ATTEMPTS:
        return "escalate"
    return "generate"


def build_generation_graph(
    *,
    generate: "Callable[[dict], dict]",
    validate: "Callable[[dict], dict]",
    persist: "Callable[[dict], dict]",
    escalate: "Callable[[dict], dict]" = escalate_node,
    checkpointer: "Any | None" = None,
):
    """Wire the four injected nodes. Nothing here knows what is being generated — the kind-specific
    knowledge lives entirely in the node bodies the caller supplies."""
    g = StateGraph(GenerationState)
    g.add_node("generate", generate)
    g.add_node("validate", validate)
    g.add_node("persist", persist)
    g.add_node("escalate", escalate)

    g.add_edge(START, "generate")
    g.add_edge("generate", "validate")
    g.add_conditional_edges("validate", route_after_validate,
                            {"persist": "persist", "generate": "generate", "escalate": "escalate"})
    g.add_edge("persist", END)
    g.add_edge("escalate", END)
    return g.compile(checkpointer=checkpointer)
