"""seedsmith.workflow.graphs.container_authoring — T5.0 (`shared-authoring-shape`, seed-to-concrete
plan). The ONE parameterised container-authoring pipeline shape `species-effects` (creature-seed T5.3)
and `affix-authoring` (effect-pipeline T7.1) both consume, extracted BEFORE either exists.

⛔ **Found by audit:** an earlier draft of this plan asserted this shape would be shared only in
T7.2, *after* T5.3 had already built its own — which is exactly the fork this module exists to
prevent. Extraction precedes first use here, not a second use elsewhere.

Thin wiring only, matching `creature_anchor.py`'s own shape (a parameterised spec object feeding
`build_generation_graph`) — this module carries NO feature-specific prompt, schema, or brief-building
knowledge. Everything domain-specific is a field on `ContainerAuthoringSpec`, supplied by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from ...pipeline.llm_caller import LlmCallerConfig
from ..nodes.generate import make_generate_node
from ..nodes.persist import make_persist_node
from ..nodes.validate import make_validate_node
from ..state import new_state
from .base import build_generation_graph

__all__ = ["ContainerAuthoringSpec", "state_for_container", "build_container_authoring_graph"]


@dataclass(frozen=True)
class ContainerAuthoringSpec:
    """Everything one container-authoring pipeline needs, parameterised over the exact four inputs
    the plan's own acceptance line names: anchor inputs, eligible families, rarity bands, and a tag
    set (`eligibility-tags`, T5.2's own `EligibilityRule` axis — the tag set an authored container
    may declare). Mirrors `PipelineSpec` (`adapters/creatures/anchor/prompts.py`) one layer up: a system
    prompt, a JSON schema for constrained decoding (G0.3 — a malformed shape becomes unsampleable,
    not merely detected), and a `build_brief` callable the caller supplies. This module never
    assembles a prompt itself — the same "never ad hoc at the call site" discipline
    `creature_anchor.py`'s own `state_for_pipeline` doc comment states for anchor classification.
    """
    id: str
    system_prompt: str
    schema: "dict[str, Any]"
    eligible_families: "tuple[str, ...]"
    rarity_bands: "tuple[str, ...]"
    tag_set: "tuple[str, ...]"
    build_brief: "Callable[[dict, dict], str]"        # (anchor_inputs, context) -> brief text
    validators: "Sequence[Callable[[dict, dict], list]]" = field(default_factory=tuple)


def state_for_container(
    spec: ContainerAuthoringSpec, anchor_inputs: dict, *, context: "dict[str, Any] | None" = None,
) -> dict:
    """Folds the spec's own parameters into the context every brief sees, then renders the brief via
    the SPEC's own `build_brief` — never assembled ad hoc at the call site, so a prompt change in one
    caller's spec never has to be re-derived at a second."""
    ctx = dict(context or {})
    ctx.setdefault("eligibleFamilies", list(spec.eligible_families))
    ctx.setdefault("rarityBands", list(spec.rarity_bands))
    ctx.setdefault("tagSet", list(spec.tag_set))
    brief = spec.build_brief(anchor_inputs, ctx)
    subject_id = anchor_inputs.get("id") or anchor_inputs.get("speciesId") or spec.id
    return new_state(subject_id, brief=brief, context=ctx)


def build_container_authoring_graph(
    spec: ContainerAuthoringSpec,
    *,
    on_persist: "Callable[[str, dict], None] | None" = None,
    config: LlmCallerConfig | None = None,
    call: "Callable[..., str] | None" = None,
    checkpointer: "Any | None" = None,
):
    """Wires `spec` into the shared `generate -> validate -> route -> persist/escalate` skeleton —
    no new control flow. `call` is injected (never imported directly), the same seam
    `creature_anchor.py`'s own graph builder uses, so a test — or `--dry-run` — can prove zero model
    calls happen by handing in a raising stub."""
    return build_generation_graph(
        generate=make_generate_node(system=spec.system_prompt, schema=spec.schema, config=config, call=call),
        validate=make_validate_node(spec.validators),
        persist=make_persist_node(on_persist),
        checkpointer=checkpointer,
    )
