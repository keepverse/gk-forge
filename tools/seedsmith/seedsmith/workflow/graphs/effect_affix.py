"""`affix-authoring` (effect-pipeline module 9, spec-affix-authoring.md). Thin wiring only,
matching `creature_anchor.py`'s own shape exactly (A6's own warning: a second pipeline SHAPE here
would be the fork this program's own reused-machinery discipline exists to prevent) — this module
carries no `StateGraph(` call of its own, only `build_generation_graph`.
"""
from __future__ import annotations

from typing import Any, Callable

from ...adapters.effects.affix.prompts import (
    AFFIX_SCHEMA,
    SYSTEM_PROMPT,
    build_brief,
    build_context,
    bundle_has_at_least_two_refs,
    refs_are_known_atoms,
)
from ...pipeline.llm_caller import LlmCallerConfig
from ..nodes.generate import make_generate_node
from ..nodes.persist import make_persist_node
from ..nodes.validate import make_validate_node
from ..state import new_state
from .base import build_generation_graph

__all__ = ["build_affix_authoring_graph", "state_for_affix", "AFFIX_VALIDATORS"]

#: spec §4's own testing-table rows — a bad bundle (unknown ref, too-small bundle) is a repair
#: prompt, never a silent pass.
AFFIX_VALIDATORS = (refs_are_known_atoms, bundle_has_at_least_two_refs)


def state_for_affix(
    subject_id: str, eligible_atoms: "list[str]", *, theme_hint: str = "",
) -> dict:
    """Renders the brief via `build_brief` — never assembled ad hoc at the call site, the same
    discipline `creature_anchor.py`'s own `state_for_pipeline` already established."""
    context = build_context(eligible_atoms, theme_hint=theme_hint)
    brief = build_brief(context)
    return new_state(subject_id, brief=brief, context=context)


def build_affix_authoring_graph(
    *,
    on_persist: "Callable[[str, dict], None] | None" = None,
    config: LlmCallerConfig | None = None,
    call: "Callable[..., str] | None" = None,
    checkpointer: "Any | None" = None,
):
    """`call` is injected (never imported directly) so a test — or `--dry-run` — can prove zero
    model calls happen by handing in a raising stub, the same contract every graph in this program
    already honours."""
    return build_generation_graph(
        generate=make_generate_node(system=SYSTEM_PROMPT, schema=AFFIX_SCHEMA, config=config, call=call),
        validate=make_validate_node(AFFIX_VALIDATORS),
        persist=make_persist_node(on_persist),
        checkpointer=checkpointer,
    )
