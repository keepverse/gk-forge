"""Terminal nodes. `escalate` exists so exhausting the retry budget is an OUTCOME, never a silent
give-up (spec-workflow-runtime.md §2.3 — 'not stopping' is 28.1% of field-observed agent failures)."""
from __future__ import annotations

from typing import Any, Callable

__all__ = ["persist_node", "escalate_node", "make_persist_node"]


def make_persist_node(on_persist: "Callable[[str, dict], None] | None" = None):
    """`on_persist` is injected rather than imported so a run can be proven to write NOTHING —
    which is how the escalate path is asserted without touching a filesystem."""

    def persist_node(state: dict) -> dict:
        draft = state.get("draft")
        if on_persist is not None and isinstance(draft, dict):
            on_persist(state.get("subject_id", ""), draft)
        return {"outcome": "persisted"}

    return persist_node


persist_node = make_persist_node()


def escalate_node(state: dict) -> dict:
    """Writes nothing, deliberately."""
    return {"outcome": "escalated"}
