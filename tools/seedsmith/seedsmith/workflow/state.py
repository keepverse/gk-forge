"""seedsmith.workflow.state — the contract between nodes (spec-workflow-runtime.md §2.2).

⛔ **This module imports nothing from LangGraph, and a test asserts that.** The seam is the
deliverable: node bodies and state must survive the workflow engine being replaced.

**Every field is bounded.** The documented failure mode is context-window overflow from
intermediate output accumulating across steps, so state carries ids and small structs — never a
message transcript. There is deliberately NO `messages: list` accumulator.
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict

__all__ = ["GenerationState", "Outcome", "OUTCOMES", "new_state", "RECURSION_LIMIT"]

Outcome = Literal["pending", "persisted", "escalated", "blocked"]
OUTCOMES: "frozenset[str]" = frozenset({"pending", "persisted", "escalated", "blocked"})


class GenerationState(TypedDict, total=False):
    """One subject's generation, start to finish.

    Bounded, precisely (audit S10): `subject_id`/`attempts`/`verified`/`outcome` are fixed-size;
    `brief` is bounded BY CONSTRUCTION — one subject's brief, assembled once and REPLACED on each
    pass, never appended to; `defects` is bounded by the retry limit; `draft` is one candidate.
    """
    subject_id: str
    brief: str
    context: "dict[str, Any]"      # motifs, anti-motifs, expression rule — read-only inputs
    draft: "dict[str, Any] | None"
    defects: "list[str]"
    attempts: int
    verified: bool
    outcome: Outcome


def new_state(subject_id: str, *, brief: str = "", context: "dict[str, Any] | None" = None) -> GenerationState:
    return GenerationState(
        subject_id=subject_id, brief=brief, context=dict(context or {}),
        draft=None, defects=[], attempts=0, verified=False, outcome="pending",
    )


#: Stop #2 of three (spec-workflow-runtime.md §2.3) — the engine-level backstop that fires only if
#: the routing function is itself wrong. Defined HERE, engine-free, so `runner.py` can read it
#: without importing LangGraph and breaking the seam.
RECURSION_LIMIT = 25
