"""seedsmith.adapters.creatures.family.schema — the family-extraction response schema
(spec-family-extract.md §2.3, §2.5).

A response covers ONE BATCH. `candidates` holds an entry per (creature, label) pair the model
proposed — a creature may appear zero, one or several times (multi-membership, owner 2026-08-31); a
creature that appears zero times is `blocked` (§2.3), and `blocked` is therefore represented by
ABSENCE from this array, never by a per-candidate flag, because there is nothing to attach a flag
to. `basis` here is only ever `text` or `name` for exactly that reason — `blocked` never appears as
a candidate value.

`speciesId` on each candidate is what lets the caller reject a label for a creature that was never in
the batch (§6's own test row) without trusting the model to have stayed in scope.
"""
from __future__ import annotations

from ....pipeline.model import BLOCKED_FIELD

CANDIDATE_SCHEMA: dict = {
    "type": "object",
    "required": ["speciesId", "label", "nativeLabel", "basis"],
    "properties": {
        "speciesId": {"type": "string"},
        "label": {"type": "string"},          # English, kebab-case — what consolidation merges on
        "nativeLabel": {"type": "string"},    # as read — never merges, carried for display/audit
        "basis": {"type": "string", "enum": ["text", "name"]},  # "blocked" = absent from the array
    },
}

FAMILY_EXTRACTION_SCHEMA: dict = {
    "type": "object",
    "required": ["candidates"],
    "properties": {
        "candidates": {"type": "array", "items": CANDIDATE_SCHEMA},
        BLOCKED_FIELD: {"type": "boolean"},
        "reason": {"type": "string"},
    },
}
