"""seedsmith.adapters.trees.species.schemas — the response schemas task J8 needs beyond the shared
generic node schema (spec-species-tree.md §6, §7.1). Two schemas, both `audit_schema`-clean by
construction, matching `nodegen/schema.py`'s own "no numeric field, proven at `Pipeline.__post_init__`,
before a call is made" discipline exactly (reused, never forked):

- **`CODEX_SUMMARY_RESPONSE_SCHEMA`** — §6's own `codexSummary` field: AUTHORED, ≤140 chars, no
  numbers, no mechanics jargon. The schema audit (`audit_schema`) only proves the SHAPE carries no
  numeric field; it cannot see whether a GENERATED SENTENCE itself smuggles a digit or a channel id
  as prose (a schema has no opinion on string CONTENT). `codex_summary_defects` is the separate,
  content-level check §6's own Testing-strategy row names
  (`codexSummary_carries_no_number_and_no_channel_id`) — run on the model's own answer, after a call,
  never a substitute for the schema audit that runs before one.
- **`FAVOUR_FIT_RESPONSE_SCHEMA`** — §3.1 step 3's own brief contract: the stage receives ONE cell,
  its alternates, and the species' own lore, and answers ONE question — does the offered cell fit,
  and if not, which alternate does (or none of them)? The schema's own enum is filled PER CALL from
  that species' own offered options (gate 8's own "quota conformance is unsampleable, not merely
  rejected" pattern, `nodegen/schema.py`'s own `schema_for_call`), so the model can never answer with
  a cell that was not actually offered to it — the 166× fix, structural rather than validated after
  the fact.

The generic NODE schema itself is reused verbatim (`nodegen.schema.NODE_RESPONSE_SCHEMA`) — §1's own
table states species trees inherit the node record unchanged, so this module does not re-declare it.
"""
from __future__ import annotations

import re
from typing import Any, Sequence

from ....pipeline.model import BLOCKED_FIELD

CODEX_SUMMARY_MAX_LENGTH = 140

#: A conservative channel-id-shaped token: lowercase segments (each at least TWO characters, so a
#: single-letter abbreviation like "e.g." can never match) joined by dots, e.g. `combat.power.fire`
#: or `stat.modify` — the exact shape every real channel/atom kind id in this repo takes
#: (`docs/architecture/power/ssot-power-scale.md`'s own registry, `gk-data/packs/fusion/data/seed/atoms/**`). Caught and
#: fixed while writing this module's own tests: the first draft required only one character per
#: segment, so "e.g." false-positived as a channel id — `test_ordinary_punctuation_is_not_a_false_
#: positive` is what found it.
_CHANNEL_ID_PATTERN = re.compile(r"\b[a-z][a-z0-9-]+(?:\.[a-z][a-z0-9-]+){1,}\b")
_DIGIT_PATTERN = re.compile(r"\d")


def codex_summary_defects(text: str) -> "list[str]":
    """§6's own two content rules, checked against the GENERATED sentence itself (never the
    schema, which cannot see string content): no digit character anywhere, and no channel-id
    -shaped token. Returns an empty list when clean — the caller decides what an empty list means
    (accept the draw) the same way every other content-level check in this program stays a pure
    reporter rather than a raiser (`SpeciesUniquenessMetric`'s own "report, never crash" discipline).
    """
    defects: "list[str]" = []
    if _DIGIT_PATTERN.search(text):
        defects.append(f"codexSummary contains a digit: {text!r}")
    match = _CHANNEL_ID_PATTERN.search(text)
    if match:
        defects.append(f"codexSummary contains a channel-id-shaped token {match.group()!r}: {text!r}")
    return defects


def _blocked_field() -> "dict[str, Any]":
    return {
        "type": "string",
        "description": "The exact empty string when you WERE able to answer — the normal case. "
                       "Do NOT put a real answer here; set this INSTEAD of the content field if "
                       "the brief cannot be satisfied, and say why.",
    }


#: §6's own field. `audit_schema(CODEX_SUMMARY_RESPONSE_SCHEMA)` must return `[]` — proven by this
#: module's own test, mutating a copy to prove the converse too.
CODEX_SUMMARY_RESPONSE_SCHEMA: "dict[str, Any]" = {
    "type": "object",
    "additionalProperties": False,
    "required": ["codexSummary", BLOCKED_FIELD],
    "properties": {
        "codexSummary": {
            "type": "string", "minLength": 1, "maxLength": CODEX_SUMMARY_MAX_LENGTH,
            "description": "ONE sentence: what building into this bloodline REWARDS, in the "
                           "player's own words. Never a number. Never a stat name, channel id, or "
                           "mechanics term. Never a description of the CREATURE (that is the "
                           "anchor's own job) -- a description of the BUILD this species locks.",
        },
        BLOCKED_FIELD: _blocked_field(),
    },
}


def favour_fit_schema(alternate_keys: "Sequence[str]") -> "dict[str, Any]":
    """A per-call schema (never a shared mutable constant — the same `schema_for_call` discipline
    `nodegen/schema.py` already applies): `choice` is the offered cell OR one of its own alternates
    OR the literal `"none"` — never an open string, so an out-of-quota answer is unsampleable,
    matching §3.1 step 3's own contract exactly ("every option is already inside the quota").
    """
    enum = ["offered", *alternate_keys, "none"]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["choice", BLOCKED_FIELD],
        "properties": {
            "choice": {
                "type": "string", "enum": enum,
                "description": "\"offered\" if the primary cell fits this creature. Otherwise the "
                               "EXACT alternate key that fits instead. \"none\" if none of the "
                               "offered options fit -- never invent a different favour.",
            },
            BLOCKED_FIELD: _blocked_field(),
        },
    }
