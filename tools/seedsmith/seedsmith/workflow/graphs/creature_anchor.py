"""The eight `classify-pipelines` graphs (creature-seed module 7, spec-classify-pipelines.md).

Thin wiring only, matching `commander_effect.py`'s own shape — this is the ONE other module that
imports LangGraph for creature content, and node bodies carry all the pipeline-specific knowledge.
"""
from __future__ import annotations

from typing import Any, Callable

from ...adapters.creatures.anchor.prompts import (
    PIPELINES,
    PipelineSpec,
    SpeciesLore,
    threat_audit_spec_for_basis,
)
from ...pipeline.llm_caller import LlmCallerConfig
from ..nodes.generate import make_generate_node
from ..nodes.persist import make_persist_node
from ..nodes.validate import make_validate_node
from ..state import new_state
from ..validators.anchor import acquisition_nonzero, element_distinct, posture_resource
from .base import build_generation_graph

__all__ = [
    "build_pipeline_graph", "build_all_pipeline_graphs",
    "state_for_pipeline", "spec_for", "PIPELINE_VALIDATORS",
]

#: Which validators apply to which pipeline (spec §4) — only the pipelines whose OUTPUT a
#: cross-field rule can actually judge get one; the rest run with an empty tuple, which is a real,
#: intentional "nothing to check here" rather than an omission.
PIPELINE_VALIDATORS: "dict[str, tuple]" = {
    "element-secondary": (element_distinct,),
    "kit-shape": (posture_resource,),
    "deployment": (acquisition_nonzero,),
}


def spec_for(pipeline_id: str, *, basis: "str | None" = None) -> PipelineSpec:
    if pipeline_id == "threat-audit":
        return threat_audit_spec_for_basis(basis or "observed")
    return PIPELINES[pipeline_id]


def state_for_pipeline(pipeline_id: str, lore: SpeciesLore, *, context: "dict[str, Any] | None" = None,
                       basis: "str | None" = None) -> dict:
    """Renders the brief via the pipeline's own `build_brief` — never assembled ad hoc at the
    call site, so a prompt change in `prompts.py` reaches every consumer identically."""
    spec = spec_for(pipeline_id, basis=basis)
    ctx = dict(context or {})
    brief = spec.build_brief(lore, ctx)
    state = new_state(lore.species_id, brief=brief, context=ctx)
    return state


def build_pipeline_graph(
    pipeline_id: str,
    *,
    basis: "str | None" = None,
    on_persist: "Callable[[str, dict], None] | None" = None,
    config: LlmCallerConfig | None = None,
    call: "Callable[..., str] | None" = None,
    checkpointer: "Any | None" = None,
):
    """One of the eight graphs. `call` is injected (never imported directly) so a test — or
    `--dry-run` — can prove zero model calls happen by handing in a raising stub."""
    spec = spec_for(pipeline_id, basis=basis)
    validators = PIPELINE_VALIDATORS.get(pipeline_id, ())
    return build_generation_graph(
        generate=make_generate_node(system=spec.system_prompt, schema=spec.schema, config=config, call=call),
        validate=make_validate_node(validators),
        persist=make_persist_node(on_persist),
        checkpointer=checkpointer,
    )


def build_all_pipeline_graphs(**kwargs) -> "dict[str, Any]":
    """One compiled graph per pipeline id — `threat-audit` is built once per call since its shape
    depends on `basis` (kwargs may include `basis=` for that one)."""
    return {pid: build_pipeline_graph(pid, **kwargs) for pid in PIPELINES}
