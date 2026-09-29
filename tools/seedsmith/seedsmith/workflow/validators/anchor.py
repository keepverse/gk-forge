"""Cross-field validators for the creature species anchor (spec-classify-pipelines.md §4, Q12:
"reject and repair, naming the conflict"). Same `(draft, context) -> list[str]` shape every other
validator in this package uses — `make_validate_node` composes them without change.

Three of the six rules in §4 are deliberately NOT here: `pure-flag` and `variant-count` are
post-processing (`anchor/derive.py`), and `family-open` is a no-op by construction. A validator
that never finds a defect would be dead code, not documentation.
"""
from __future__ import annotations

from typing import Any, Mapping

from ...adapters.creatures.anchor.schema import APTITUDE_POSTURE

__all__ = ["posture_resource", "element_distinct", "acquisition_nonzero"]


def posture_resource(draft: Mapping[str, Any], context: Mapping[str, Any]) -> "list[str]":
    """`posture` is derived from the already-decided `aptitudePrimary` (passed in `context` by the
    run orchestrator, since pipeline 3 runs before pipeline 7). A Bastion creature whose
    `resourceProfile` omits `poise` is incoherent — Bastion IS the guard posture, and poise pays
    for guarding (resource-hub-ssot.md, class-system `poise-resource`)."""
    aptitude_primary = context.get("aptitudePrimary")
    if not aptitude_primary or aptitude_primary not in APTITUDE_POSTURE:
        return []  # not yet decided, or an invalid upstream value — nothing to check against here
    posture = APTITUDE_POSTURE[aptitude_primary]
    resource_profile = draft.get("resourceProfile")
    if posture == "Bastion" and isinstance(resource_profile, list) and "poise" not in resource_profile:
        return [
            f"resourceProfile {resource_profile!r} omits 'poise', but this species' posture is "
            f"Bastion (derived from aptitudePrimary={aptitude_primary!r}) — every Bastion "
            f"creature's kit must include poise, since Bastion IS the guard posture and poise "
            f"pays for guarding"
        ]
    return []


def element_distinct(draft: Mapping[str, Any], context: Mapping[str, Any]) -> "list[str]":
    """`elementSecondary` may not equal the already-decided `elementPrimary`. `none` is always a
    legal, encouraged answer (spec §4)."""
    element_primary = context.get("elementPrimary")
    element_secondary = draft.get("elementSecondary")
    if not element_primary or element_secondary in (None, "none"):
        return []
    if element_secondary == element_primary:
        return [
            f"elementSecondary={element_secondary!r} equals elementPrimary={element_primary!r} — "
            f"a secondary element must be genuinely different from the primary, or 'none' if this "
            f"species is pure"
        ]
    return []


def acquisition_nonzero(draft: Mapping[str, Any], context: Mapping[str, Any]) -> "list[str]":
    """`CreatureAcquisition.None` is a catalog error (`CreatureRarity.cs:11` — `[Flags] enum
    CreatureAcquisition { None = 0, ... }`, and `CreatureSpeciesCatalog`'s own validation already throws
    on it). `acquisition` must name at least one real flag."""
    acquisition = draft.get("acquisition")
    if not acquisition:
        return [
            "acquisition is empty — every species needs at least one of Summonable/CaptureOnly/"
            "EventOnly; a species with no acquisition flag is a catalog error"
        ]
    return []
