"""species-tree's own codex-summary stage (task J8, spec-species-tree.md §6). Thin wiring only,
matching `effect_affix.py`'s own shape exactly (A6's own warning: a second pipeline SHAPE here
would be the fork this program's own reused-machinery discipline exists to prevent) — this module
carries no `StateGraph(` call of its own, only `build_generation_graph`.
"""
from __future__ import annotations

from typing import Any, Callable

from ...adapters.trees.species.prompts import CODEX_SYSTEM_PROMPT, build_codex_brief, build_codex_context
from ...adapters.trees.species.roster import SpeciesAnchor
from ...adapters.trees.species.plan import FavourCell
from ...adapters.trees.species.schemas import CODEX_SUMMARY_RESPONSE_SCHEMA, codex_summary_defects
from ...pipeline.llm_caller import LlmCallerConfig
from ..nodes.generate import make_generate_node
from ..nodes.persist import make_persist_node
from ..nodes.validate import make_validate_node
from ..state import new_state
from .base import build_generation_graph

__all__ = ["build_species_codex_graph", "state_for_species_codex", "CODEX_VALIDATORS",
          "codex_summary_content_is_clean"]


def codex_summary_content_is_clean(draft: "dict[str, Any]", context: "dict[str, Any]") -> "list[str]":
    """§6's own content rule, run as a validator so a defect becomes a REPAIR prompt (the same
    "defects become the repair prompt" contract `make_validate_node`'s own docstring states) rather
    than a silent accept — never a substitute for `codex_summary_defects` being callable on its own
    too (this module's own test calls it standalone for the unit-level proof)."""
    text = draft.get("codexSummary", "")
    return codex_summary_defects(text)


CODEX_VALIDATORS = (codex_summary_content_is_clean,)


def build_species_codex_graph(
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
        generate=make_generate_node(
            system=CODEX_SYSTEM_PROMPT, schema=CODEX_SUMMARY_RESPONSE_SCHEMA, config=config, call=call),
        validate=make_validate_node(CODEX_VALIDATORS),
        persist=make_persist_node(on_persist),
        checkpointer=checkpointer,
    )


def state_for_species_codex(subject_id: str, anchor: SpeciesAnchor, favour: FavourCell) -> dict:
    """Renders the brief via `build_codex_brief` — never assembled ad hoc at the call site, the
    same discipline `effect_affix.py`'s own `state_for_affix` already established."""
    context = build_codex_context(anchor, favour)
    brief = build_codex_brief(context)
    return new_state(subject_id, brief=brief, context=context)
