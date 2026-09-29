"""The `fusion-recipe-propose` proposal shape (creature-seed module 17, spec-fusion-recipe-generator.md
§2). One resolved recipe candidate for ONE deficit output per call — matching `classify-pipelines`'
own one-judgement-per-call shape, never a batch.
"""
from __future__ import annotations


def build_fusion_proposal_schema(output_species_id: str, candidate_ids: "list[str]") -> dict:
    """Consumable directly as an LM Studio `response_format` schema, same convention as
    `anchor/schema.py`'s `build_anchor_schema`. `inputA`/`inputB` are constrained to the SAME
    bounded candidate pool the prompt shows (spec §2's own closed-enum discipline, mirroring
    `anchor-contract`) — the model can never propose a species it was never shown. `speciesId` is
    pinned to a single-value enum so a malformed or confused answer (echoing the wrong output) is
    caught mechanically rather than trusted. `candidate_ids` must already be the caller's bounded
    nearest-2-3-populated-rungs-below pool — this function does no bounding itself, it only turns
    a pool into an enum.
    """
    if len(candidate_ids) < 2:
        raise ValueError(f"fusion proposal schema needs at least 2 candidates, got {len(candidate_ids)}")

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "FusionRecipeProposal",
        "type": "object",
        "properties": {
            "speciesId": {
                "type": "string",
                "enum": [output_species_id],
                "description": "Echo back the exact output species id you were asked about — always this exact value.",
            },
            "inputA": {
                "type": "string",
                "enum": list(candidate_ids),
                "description": "One of the two candidates that fuse into the output. Must be a real id from the shown candidate list.",
            },
            "inputB": {
                "type": "string",
                "enum": list(candidate_ids),
                "description": "The other candidate that fuses into the output. Must differ from inputA.",
            },
            "reason": {
                "type": "string",
                "description": "One-sentence rationale for this pairing. Logged, never gates anything.",
            },
        },
        "required": ["speciesId", "inputA", "inputB", "reason"],
        "additionalProperties": False,
    }
