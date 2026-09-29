"""seedsmith.adapters.trees.nodegen.schema — the §6.3 response schema, `audit_schema`-clean by
construction (task H1, spec-tree-language.md §2.1, §6.3, §7 gates 1 and 8).

⛔ **P1, this program's own wording (§2.1): "the language stage can never move a balance number" is
not a policy in this document. It is an unsampleable state, enforced by shipped code.** This module
reuses the SHARED guard rather than forking a program-local copy: `pipeline.model.MAGNITUDE_DENY_NAMES`
already contains `tier`, `rung`, `duration`, `chance`, `cost`, `weight`, `damage`, `hp`, `atk`, plus
any name ending `Milli` — exactly the list §2.1 cites by line number — and `pipeline.model.Pipeline`
already runs `audit_schema` from `__post_init__`, i.e. at construction, before a single field of this
schema is filled. `build_pipeline` below is this module's own construction site: the same act every
other seedsmith pipeline performs, so a numeric field added here fails the exact same way a numeric
field added to `items/setgen/schema.py` or `combogen/schema.py` already does.

Unlike `items/setgen`'s program-specific widened list (`adapters/creatures/anchor/audit.py`'s own
`MAGNITUDE_DENY_NAMES`), this schema needs no widened deny-list of its own: none of its seven
required fields (`affixIds`, `affinity`, `exclusion.form`, `exclusion.propertyKeys`, `name`,
`nameKey`, `flavor`) plus the one open-loop field (`rationale`) collide with the shared floor, and
adding one that did would be a P1 violation worth its own review, not a name to allow-list past.

⭐ **Gate 8 — quota conformance is unsampleable, not merely rejected.** `affixIds.items.enum` and
`exclusion.propertyKeys.items.enum` ship EMPTY in the constant below — deliberately, mirroring
`family_propose/prompts.py:63-66` and `items/setgen/schema.py`'s own `threshold_pieces` — and only
`schema_for_call` fills them, from the caller's own permitted subset, `deepcopy`d per call so two
calls in the same process never alias one another's enum (`two_calls_never_alias_one_enum`, spec
Testing strategy). `audit_schema(NODE_RESPONSE_SCHEMA)` therefore audits the SHAPE, never one call's
own snapshot of a quota cell — the same split every other `*_propose` schema in this repo draws.

⚠ **`rationale` — a spec ambiguity resolved here, stated plainly.** §2's ownership table lists
`rationale` as AUTHORED/FREE, "Review queue only. An OPEN-loop field may never gate" — but §6.3's
own illustrative JSON block does not list it among the seven schema properties. Resolved default:
`rationale` IS a schema property, OPTIONAL (never in `required`, never gating), exactly the shape
`pipeline.open_loop.audit_open_loop_schema`'s `VERDICT_FIELD_NAMES` floor already protects against
for a different reason — a free-text field that never becomes a pass/fail is not a P1 hazard, and
omitting it from the schema would silently drop the one place a model can say *why* it picked what
it picked, which the review queue (H2/H6) reads. If a later task finds §6.3's omission was instead
deliberate, dropping this property is a one-line change here, not a redesign.
"""
from __future__ import annotations

import copy
from typing import Any, Callable, Mapping, Sequence

from ....pipeline.model import BLOCKED_FIELD, MAGNITUDE_DENY_NAMES, Pipeline, audit_schema

__all__ = [
    "AFFINITY_VALUES",
    "EXCLUSION_FORMS",
    "NAME_KEY_PATTERN",
    "FLAVOR_MAX_LENGTH",
    "NODE_RESPONSE_SCHEMA",
    "schema_for_call",
    "build_pipeline",
]

#: §6.3's own three affinity ordinals — never a weight, per §2's own row ("a model cannot be
#: trusted with `weight: 40` but can reliably say an effect is *core* to a node").
AFFINITY_VALUES: "tuple[str, ...]" = ("core", "likely", "occasional")

#: §6.3's `exclusion.form` enum. `nullification` stays IN the enum per D40 (§5.2) — the discipline
#: moved from "keep it out of the enum" to "print it loudly on both sides", never to removing the
#: rung. This constant is the SHAPE; §5's ladder order (reroute -> precedence -> nullification) is
#: `exclusion.py`'s concern, not this schema's.
EXCLUSION_FORMS: "tuple[str, ...]" = ("none", "reroute", "precedence", "nullification")

NAME_KEY_PATTERN = r"^tree\.node\.[a-z0-9-]+$"
FLAVOR_MAX_LENGTH = 140


def _identity_fields() -> "dict[str, Any]":
    return {
        "name": {
            "type": "string", "minLength": 1, "maxLength": 64,
            "description": "The node's own name. It is NOT the tree's name, and it is NOT a "
                           "sentence — no mechanics, no number.",
        },
        "nameKey": {
            # ⛔ maxLength added 2026-09-08: same class of gap as setgen/schema.py's nameKey (a
            # real incident there) — `pattern` alone is not enforced at decode time, so without a
            # length bound this field was unconstrained during generation. `tree.node.` (10 chars)
            # plus `name`'s own 64-char budget as a kebab slug, with headroom.
            "type": "string", "pattern": NAME_KEY_PATTERN, "maxLength": 96,
            "description": "Lowercase-kebab key, `tree.node.<slug>`. It is NOT free text and it "
                           "is NOT the node id — the plan already minted that. Derive <slug> from "
                           "the `name` you just chose above (e.g. name \"Primal Surge\" -> slug "
                           "\"primal-surge\") — never a generic template like \"branch-depth-01\", "
                           "which is not unique and will collide with a different node's own name.",
        },
        "flavor": {
            "type": "string", "maxLength": FLAVOR_MAX_LENGTH,
            "description": "One line under the name. It is NOT a rules description: never say "
                           "what the node does mechanically, and never write a number.",
        },
    }


def _blocked_field() -> "dict[str, Any]":
    return {
        "type": "string",
        "description": "The exact empty string when you WERE able to author the node — the "
                       "normal case. Do NOT put a real answer here; set this INSTEAD of the "
                       "content fields if the brief cannot be satisfied, and say why.",
    }


def _rationale_field() -> "dict[str, Any]":
    # OPTIONAL, never in `required`: §2's own row — "Review queue only. An OPEN-loop field may
    # never gate — metrics/registry.py:17-21 refuses to register one with gates=True." Kept out of
    # `required` is how a schema keeps a field from ever becoming load-bearing for a pass/fail.
    return {
        "type": "string", "maxLength": 280,
        "description": "OPTIONAL. Why you chose what you chose — review queue only, never "
                       "checked mechanically and never a reason to reject this node. Leave it "
                       "empty if you have nothing to add.",
    }


#: The §6.3 response schema. Both enum arrays below ship EMPTY — filled only by `schema_for_call`,
#: per call, from that call's own permitted subset (gate 8). `audit_schema(NODE_RESPONSE_SCHEMA)`
#: must return `[]`; `test_schema_no_numeric_field` (this module's test) proves it, and proves the
#: converse by mutating a copy.
NODE_RESPONSE_SCHEMA: "dict[str, Any]" = {
    "type": "object",
    "additionalProperties": False,
    "required": ["affixIds", "affinity", "exclusion", "name", "nameKey", "flavor", BLOCKED_FIELD],
    "properties": {
        "affixIds": {
            "type": "array", "minItems": 1, "maxItems": 3,
            "items": {"type": "string", "enum": []},  # FILLED PER CALL — gate 8
            "description": "The effects this node grants. Pick only from the list. This is NOT "
                           "a description of the node — never invent an id.",
        },
        "affinity": {
            "type": "array", "minItems": 1, "maxItems": 3,
            "items": {"type": "string", "enum": list(AFFINITY_VALUES)},
            "description": "How central each chosen effect is, in the same order as `affixIds` "
                           "and the same length. This is NOT a strength and NOT a weight.",
        },
        "exclusion": {
            "type": "object",
            "additionalProperties": False,
            "required": ["form", "propertyKeys"],
            "properties": {
                "form": {
                    "type": "string", "enum": list(EXCLUSION_FORMS),
                    "description": "The exclusion ladder rung. `none` is NOT a placeholder to "
                                   "fill in later — it is the normal case, and most nodes never "
                                   "leave it.",
                },
                "propertyKeys": {
                    "type": "array",
                    "items": {"type": "string", "enum": []},  # FILLED PER CALL — gate 8
                    "description": "The properties this node's effect conflicts with. This is "
                                   "NOT a node id, and it never names one — an exclusion keys on "
                                   "a property.",
                },
            },
            "description": "Only when this node's effect genuinely conflicts with a listed "
                           "property. It is NOT a way to make the node stronger, and it never "
                           "names another node. `nullification` is the last resort and must say "
                           "which side wins (in `printedText`, composed afterwards).",
        },
        **_identity_fields(),
        "rationale": _rationale_field(),
        BLOCKED_FIELD: _blocked_field(),
    },
}


def schema_for_call(permitted_affix_ids: "Sequence[str]",
                    permitted_property_keys: "Sequence[str]",
                    exclusion_forms: "Sequence[str] | None" = None) -> "dict[str, Any]":
    """A per-call COPY of `NODE_RESPONSE_SCHEMA` with all three enums filled from one node's own
    (already permuted) quota cell — never mutates the shared constant. `deepcopy`d so two calls in
    the same process never alias each other's enum (`family_propose/prompts.py:150-160`'s own
    rule, reused verbatim).

    `exclusion_forms` (2026-09-11) is the `exclusionForm` axis's §4.2 step-6 narrowing: the ONE
    value the node's own quota cell allocated (or that value plus `none` — a `none`-allocated cell
    passes `("none",)` and a designated cell passes `(form, "none")`), narrowed here so the schema
    enum says what the cell says. Optional-with-default so every existing caller keeps compiling;
    the real caller (`run.py`) passes it per cell.

    Neither argument is validated for non-emptiness here: an empty `permitted_affix_ids` is
    `UnsatisfiableCell` territory (`quota.py`'s job, held rather than widened), and forcing that
    refusal to happen twice — once here, once there — would just be two places that can disagree.
    """
    schema = copy.deepcopy(NODE_RESPONSE_SCHEMA)
    schema["properties"]["affixIds"]["items"]["enum"] = list(permitted_affix_ids)
    schema["properties"]["exclusion"]["properties"]["propertyKeys"]["items"]["enum"] = \
        list(permitted_property_keys)
    if exclusion_forms is not None:
        schema["properties"]["exclusion"]["properties"]["form"]["enum"] = list(exclusion_forms)
    return schema


def build_pipeline(schema: "Mapping[str, Any]", *, metric: str = "PassiveTree/NodeLanguage",
                   scope: str = "tree-language",
                   gate: "Callable[[Mapping[str, Any]], Sequence[str]] | None" = None,
                   on_persist: "Callable[[str, Mapping[str, Any]], None] | None" = None) -> Pipeline:
    """Constructs the `Pipeline` this stage's schema is actually audited THROUGH (gate 1: "ValueError
    at construction — before any call", `Pipeline.__post_init__` -> `audit_schema`).

    `gate`/`on_persist` default to inert placeholders — **H2's job is the real gate runner**
    (`run_g1`/`run_g2`, persist-time re-gate, §7 gates 6-14); this function exists so gate 1 is
    provable end-to-end today (`Pipeline(schema=...)` raising `ValueError` on a numeric field) without
    waiting on H2's wiring. Passing a real `gate`/`on_persist` later needs no change here.
    """
    return Pipeline(
        metric=metric, scope=scope, schema=schema,
        gate=gate or (lambda _response: ()),
        on_persist=on_persist or (lambda _subject_id, _response: None),
    )


# `audit_schema`/`MAGNITUDE_DENY_NAMES` are re-exported for the sibling modules and tests that need
# to name them without importing `pipeline.model` directly a second way.
__all__ += ["audit_schema", "MAGNITUDE_DENY_NAMES"]
