"""species-effects' own constrained-decoding schema (T5.3, spec-species-effects.md §3, §6).

The model picks WHICH affix families this species is eligible for, an affinity ordinal per pick
(`core` / `likely` / `occasional`), and the container's eligibility tags — nothing numeric. A weight,
a tier, a magnitude or a `pool_rolls` count would violate spec §6's "the seed holds no numbers at
all"; `additionalProperties: False` throughout makes a stray numeric field unsampleable, not merely
detected (G0.3), and `no_numeric_field_survives_the_audit` proves it mechanically over real drafts.
"""
from __future__ import annotations

from typing import Any

AFFINITIES = ("core", "likely", "occasional")

SPECIES_EFFECTS_SCHEMA: "dict[str, Any]" = {
    "type": "object",
    "properties": {
        "eligibleAffixes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "affixId": {"type": "string"},
                    "affinity": {"type": "string", "enum": list(AFFINITIES)},
                },
                "required": ["affixId", "affinity"],
                "additionalProperties": False,
            },
        },
        "eligibilityTags": {
            "type": "object",
            "properties": {
                "requireTags": {"type": "array", "items": {"type": "string"}},
                "anyOfTags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["requireTags", "anyOfTags"],
            "additionalProperties": False,
        },
    },
    "required": ["eligibleAffixes", "eligibilityTags"],
    "additionalProperties": False,
}
