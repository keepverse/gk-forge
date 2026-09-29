"""seedsmith.workflow.graphs.species_effects — T5.3 (`species-effects`, creature-seed module 15).
Thin wiring only, the first REAL consumer of `container_authoring.py`'s shared shape (T5.0) —
matching `commander_effect.py`'s own code style, per this module's own spec.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ...adapters.creatures.effects.prompts import (
    SYSTEM_PROMPT,
    affix_ids_are_known,
    build_brief,
    build_context,
    fixed_core_within_band,
)
from ...adapters.creatures.effects.schema import SPECIES_EFFECTS_SCHEMA
from ...pipeline.llm_caller import LlmCallerConfig
from .container_authoring import ContainerAuthoringSpec, build_container_authoring_graph, state_for_container

__all__ = ["load_shape_tuning", "spec_for_species", "state_for_species", "build_species_effects_graph"]

TUNING_DIR = Path(__file__).resolve().parents[5] / "data" / "tuning"


def load_shape_tuning(version: "int | str" = 1) -> dict:
    path = TUNING_DIR / f"creature-species-effects.v{int(version)}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def spec_for_species(
    *, eligible_families: "tuple[str, ...]", rarity_bands: "tuple[str, ...]", tag_set: "tuple[str, ...]",
) -> ContainerAuthoringSpec:
    return ContainerAuthoringSpec(
        id="species-effects",
        system_prompt=SYSTEM_PROMPT,
        schema=SPECIES_EFFECTS_SCHEMA,
        eligible_families=eligible_families,
        rarity_bands=rarity_bands,
        tag_set=tag_set,
        build_brief=build_brief,
        validators=(fixed_core_within_band, affix_ids_are_known),
    )


def state_for_species(spec: ContainerAuthoringSpec, anchor: dict, *, shape_tuning: "dict[str, Any] | None" = None) -> dict:
    """Folds `anchor`'s own context (rarity, elements, aptitudes, posture, resources, family, traits,
    lore — deliberately NOT `threatBand`, spec §2) plus the fixed-core band FOR THIS SPECIES' OWN
    RARITY into the state `container_authoring.py`'s shared skeleton runs on."""
    context = build_context(anchor)
    shape = shape_tuning or load_shape_tuning()
    context["fixedCoreBand"] = shape["fixedCoreBandByRarity"].get(context["rarity"])
    return state_for_container(spec, anchor, context=context)


def build_species_effects_graph(
    spec: ContainerAuthoringSpec,
    *,
    on_persist: "Callable[[str, dict], None] | None" = None,
    config: LlmCallerConfig | None = None,
    call: "Callable[..., str] | None" = None,
    checkpointer: "Any | None" = None,
):
    return build_container_authoring_graph(
        spec, on_persist=on_persist, config=config, call=call, checkpointer=checkpointer)
