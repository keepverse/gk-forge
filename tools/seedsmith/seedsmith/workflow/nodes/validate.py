"""The validate node — runs the deterministic (tier-2) battery. NO model, NO LangGraph."""
from __future__ import annotations

from typing import Any, Callable, Sequence

__all__ = ["validate_node", "make_validate_node"]

Validator = Callable[[dict, dict], "list[str]"]


def make_validate_node(validators: "Sequence[Validator]"):
    """Compose validators into a node. Each returns a list of defect strings naming the field AND
    the offending value, because those strings become the repair prompt."""

    def validate_node(state: dict) -> dict:
        draft = state.get("draft")
        context: "dict[str, Any]" = state.get("context") or {}
        if not isinstance(draft, dict):
            return {"defects": ["response was not a JSON object"]}
        defects: "list[str]" = []
        for v in validators:
            defects.extend(v(draft, context))
        return {"defects": defects}

    return validate_node


validate_node = make_validate_node(())
