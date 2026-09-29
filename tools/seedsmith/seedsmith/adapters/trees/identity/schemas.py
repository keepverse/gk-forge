"""seedsmith.adapters.trees.identity.schemas — the response schema for a passive tree's own
display name + description (`seedsmith-content-standard`, Task 17,
spec-passive-tree-identity-content.md §3).

Mirrors `adapters.trees.species.schemas`'s own `CODEX_SUMMARY_RESPONSE_SCHEMA`/
`codex_summary_defects` shape exactly — same two content rules (no digit, no channel-id-shaped
token), generalized from one field to two, never a new pattern invented.
"""
from __future__ import annotations

import re
from typing import Any

from ....pipeline.model import BLOCKED_FIELD

TREE_NAME_MAX_LENGTH = 40
TREE_DESCRIPTION_MAX_LENGTH = 160

#: Identical to `species/schemas.py`'s own `_CHANNEL_ID_PATTERN`/`_DIGIT_PATTERN` — the same real
#: content-level defects a generated sentence can smuggle regardless of which field it's in.
_CHANNEL_ID_PATTERN = re.compile(r"\b[a-z][a-z0-9-]+(?:\.[a-z][a-z0-9-]+){1,}\b")
_DIGIT_PATTERN = re.compile(r"\d")


def _text_defects(field: str, text: str) -> "list[str]":
    defects: "list[str]" = []
    if _DIGIT_PATTERN.search(text):
        defects.append(f"{field} contains a digit: {text!r}")
    match = _CHANNEL_ID_PATTERN.search(text)
    if match:
        defects.append(f"{field} contains a channel-id-shaped token {match.group()!r}: {text!r}")
    return defects


def tree_identity_defects(name: str, description: str) -> "list[str]":
    """Both fields checked against the SAME two content rules `codex_summary_defects` already
    proved for a single field — returns an empty list when both are clean, the same pure-reporter
    contract every content-level check in this program follows."""
    return _text_defects("name", name) + _text_defects("description", description)


def _blocked_field() -> "dict[str, Any]":
    return {
        "type": "string",
        "description": "The exact empty string when you WERE able to answer — the normal case. "
                       "Do NOT put a real answer here; set this INSTEAD of the content fields if "
                       "the brief cannot be satisfied, and say why.",
    }


#: `audit_schema(TREE_IDENTITY_RESPONSE_SCHEMA)` must return `[]` — proven by this module's own
#: test, mirroring `species/schemas.py`'s own test for `CODEX_SUMMARY_RESPONSE_SCHEMA`.
TREE_IDENTITY_RESPONSE_SCHEMA: "dict[str, Any]" = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "description", BLOCKED_FIELD],
    "properties": {
        "name": {
            "type": "string", "minLength": 1, "maxLength": TREE_NAME_MAX_LENGTH,
            "description": "A short, evocative display name for this passive skill tree (2-4 "
                           "words). Never a number. Never a stat name, channel id, or mechanics "
                           "term by its game name.",
        },
        "description": {
            "type": "string", "minLength": 1, "maxLength": TREE_DESCRIPTION_MAX_LENGTH,
            "description": "ONE sentence: what kind of build this tree REWARDS, in the player's "
                           "own words, grounded in the tree's own already-written trait names/"
                           "flavor text. Never a number. Never a stat name, channel id, or "
                           "mechanics term by its game name.",
        },
        BLOCKED_FIELD: _blocked_field(),
    },
}
