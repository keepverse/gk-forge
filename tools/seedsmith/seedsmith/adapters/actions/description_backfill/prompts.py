"""seedsmith.adapters.actions.description_backfill.prompts — the model's own domain knowledge for
backfilling a real `description` onto an ALREADY-COMMITTED action-seed row.

Deliberately narrower than `general_propose/prompts.py`'s own flavour prompt (which designs a
brand-new action's identity from a role brief): this model never invents a name, a category, or
which atom families the action is built from — all three already exist and are handed back as
read-only context. Its only job is one line of in-world flavour text for content that already
shipped, which is why the system prompt below says "already been designed," not "design an action."
"""
from __future__ import annotations

from typing import Any, Mapping

__all__ = ["PROMPT_VERSION", "SCHEMA_VERSION", "SYSTEM_PROMPT", "DESCRIPTION_SCHEMA", "build_brief"]

#: Bumped whenever `SYSTEM_PROMPT`/`DESCRIPTION_SCHEMA`/`build_brief`'s own rendered shape changes
#: in a way that would make a previously-generated description worth reviewing again — the
#: `staleness_key` input this whole backfill exists to make comparable (spec-content-completeness-
#: core.md §4), matching every other adapter's own `PROMPT_VERSION` convention (e.g.
#: `general_propose/prompts.py`'s own module docstring names the same pattern for A-P1/A-P2/A-P3).
PROMPT_VERSION = "actions/description-backfill/1"

#: The `action-seed` schema version this generator was built against (`kinds.py`'s own
#: `ACTION_SEED_REQUIRED`/`ACTION_SEED_OPTIONAL`) — the second staleness-key input
#: `spec-content-completeness-core.md` §4 names alongside `prompt_version`.
SCHEMA_VERSION = "action-seed/1"

SYSTEM_PROMPT = (
    "You write ONE short line of in-world flavour text for an action in a plants-vs-zombies "
    "tactics game. The action has already been designed and named -- you are not choosing what it "
    "does, only describing what it feels like to see it happen. Never state a mechanical effect, "
    "a number, a duration, a chance, a range, or a cooldown: tables you never see decide every "
    "magnitude, the same rule this game's other content-generation prompts already use (see "
    "`adapters/actions/general_propose/prompts.py`'s own `SYSTEM_PROMPT`). Never restate the "
    "action's own name verbatim -- a description that just repeats the name teaches a player "
    "nothing new. Never invent a creature, element, or family beyond what the brief below already "
    "names."
)

DESCRIPTION_SCHEMA: "dict[str, Any]" = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": (
                "One line of in-world flavour text a player would read under this action's name, "
                "under 140 characters. NOT a rules description -- never a number, a duration, a "
                "chance, or a range. Do not restate the action's own name verbatim."
            ),
        },
    },
    "required": ["description"],
    "additionalProperties": False,
}


def build_brief(data: Mapping[str, Any]) -> str:
    """Render the read-only context the model sees. Every field here already exists on the
    committed row (`kinds.py`'s `ACTION_SEED_REQUIRED`/`ACTION_SEED_OPTIONAL`) -- this function
    invents nothing, it only selects and formats what `content_completeness.py`'s caller already
    has in hand, which is also exactly the text `pipeline.staleness.brief_hash` hashes."""
    families = ", ".join(data.get("atomFamilies") or []) or "(none)"
    scope = str(data.get("scope"))
    scope_key = data.get("scopeKey")
    if scope_key:
        scope = f"{scope} ({scope_key})"
    lines = [
        f"Action name: {data.get('name') or data.get('id')}",
        f"Category: {data.get('category')}",
        f"Relation: {data.get('relation')}",
        f"Target mode: {data.get('targetMode')}",
        f"Scope: {scope}",
        f"Built from atom families: {families}",
    ]
    return "\n".join(lines)
