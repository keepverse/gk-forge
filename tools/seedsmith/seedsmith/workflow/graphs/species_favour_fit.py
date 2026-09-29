"""species-tree's own favour-fit stage (task J8, spec-species-tree.md §3.1 step 3). Thin wiring
only, matching `effect_affix.py`/`species_codex.py`'s own shape exactly.

No extra validators beyond the schema itself: `favour_fit_schema`'s own per-call `enum` already
makes every out-of-quota answer structurally unsampleable (gate 8's own "quota conformance is
unsampleable, not merely rejected" pattern) — there is no further content rule to check the way
`codex_summary_content_is_clean` checks free text, so this stage's validator list is legitimately
empty, the same as `workflow/nodes/validate.py`'s own `validate_node = make_validate_node(())`
default.
"""
from __future__ import annotations

from typing import Any, Callable

from ...adapters.trees.species.plan import FavourCell
from ...adapters.trees.species.prompts import (
    FAVOUR_FIT_SYSTEM_PROMPT,
    build_favour_fit_brief,
    build_favour_fit_context,
)
from ...adapters.trees.species.roster import SpeciesAnchor
from ...adapters.trees.species.schemas import favour_fit_schema
from ...pipeline.llm_caller import LlmCallerConfig
from ..nodes.generate import make_generate_node
from ..nodes.persist import make_persist_node
from ..nodes.validate import make_validate_node
from ..state import new_state
from .base import build_generation_graph

__all__ = ["build_species_favour_fit_graph", "state_for_species_favour_fit", "FAVOUR_FIT_VALIDATORS"]

FAVOUR_FIT_VALIDATORS: "tuple" = ()


def build_species_favour_fit_graph(
    *, alternate_keys: "list[str]",
    on_persist: "Callable[[str, dict], None] | None" = None,
    config: LlmCallerConfig | None = None,
    call: "Callable[..., str] | None" = None,
    checkpointer: "Any | None" = None,
):
    """`alternate_keys` is THIS call's own offered alternates — the schema's enum is built fresh
    per graph, never a shared mutable constant (`schemas.favour_fit_schema`'s own per-call
    discipline, `two_calls_never_alias_one_enum`)."""
    return build_generation_graph(
        generate=make_generate_node(
            system=FAVOUR_FIT_SYSTEM_PROMPT, schema=favour_fit_schema(alternate_keys),
            config=config, call=call),
        validate=make_validate_node(FAVOUR_FIT_VALIDATORS),
        persist=make_persist_node(on_persist),
        checkpointer=checkpointer,
    )


def state_for_species_favour_fit(
    subject_id: str, anchor: SpeciesAnchor, offered: FavourCell, alternates: "list[FavourCell]",
) -> dict:
    context = build_favour_fit_context(anchor, offered, alternates)
    brief = build_favour_fit_brief(context)
    return new_state(subject_id, brief=brief, context=context)
