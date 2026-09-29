"""The generate node — the only node that calls a model (spec-workflow-runtime.md §2.1)."""
from __future__ import annotations

import json
from typing import Any, Callable

from ...pipeline.llm_caller import LlmCallerConfig, call_model, extract_json

__all__ = ["generate_node", "make_generate_node"]

#: Structural constant, not a tunable (spec-workflow-runtime.md §2.3). Matches
#: `spec-pipeline.md` §3.6's existing budget: 1 initial attempt + 2 heals.
MAX_ATTEMPTS = 3


def make_generate_node(
    *,
    system: str,
    schema: "dict[str, Any] | None" = None,
    config: LlmCallerConfig | None = None,
    call: "Callable[..., str] | None" = None,
):
    """Build a generate node. The model call is INJECTED (`call`) so tests never reach the network.

    A repair pass re-prompts with the NAMED defects appended — a bare retry teaches the model
    nothing (`spec-pipeline.md` §3.6). `schema` turns on constrained decoding (G0.3), which makes
    a malformed-shape response unsampleable rather than merely detected.
    """
    caller = call or call_model

    def generate_node(state: dict) -> dict:
        user = state.get("brief", "")
        defects = state.get("defects") or []
        if defects:
            user += ("\n\nYour previous attempt was REJECTED for:\n"
                     + "\n".join(f"- {d}" for d in defects)
                     + "\nFix exactly these.")
        raw = caller(system, user, config=config, schema=schema)
        try:
            draft = json.loads(raw)
        except json.JSONDecodeError:
            try:
                draft = extract_json(raw)   # defense-in-depth; schema portability is not guaranteed
            except Exception:
                draft = None
        return {"draft": draft, "attempts": int(state.get("attempts", 0)) + 1}

    return generate_node


#: Default instance for callers that inject everything at graph-build time.
generate_node = make_generate_node(system="You generate structured game content.")
