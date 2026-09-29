"""seedsmith.adapters.items.setgen.schema — the closed-enum output schema, audit_schema-clean by
construction.

⛔ P1, unamended: **the model writes identity, deterministic code writes magnitude.** The model picks
which capability, which stat families, which member roles, the name and the flavour. It never emits a
number — and that is enforced mechanically, by `pipeline.model.audit_schema`, which
`Pipeline.__post_init__` runs at CONSTRUCTION. A numeric field cannot reach a model call at all.

⚠ `pieces` is the one place a number is legal, and only as a closed enum. Written as a bare
`{"type": "integer"}` the schema is rejected before the first call. Said in the schema, not in a
comment — which is why `threshold_pieces` reads its enum from `distribute.threshold_ladder` rather
than repeating it: which piece counts a set may carry is one fact, and a second copy here is where
it goes stale. It did: the enum offered `{2,3,4,6}` while the ladder derived `(2,4)`, and the first
real batch lost all three sets to it.

⚠ Two field names the deny-list would refuse, and how this schema avoids them rather than
allow-listing its way past them: `tier` (a magnitude by convention) never appears — tiers come from
`numerics`; and `cost` never appears — a charm's AP cost is DERIVED from its class.
"""
from __future__ import annotations

from typing import Any

from .distribute import capability_family_ids, legal_set_stat_pool, threshold_ladder
from .roles import HYBRID_CORE_ROLES
from .tuning import SetCharmGenTuning
from .vocab import Vocabulary

#: The exact spelling `audit_schema` allows: an enum of numbers is a vocabulary, not an invention.
#: Built from tuning so the schema and the distributor cannot disagree about what is legal.
def threshold_pieces(tuning: SetCharmGenTuning,
                     ladder: "tuple[int, ...] | None" = None) -> "dict[str, Any]":
    """The `pieces` node. `ladder` narrows the enum to the counts THIS set can carry.

    ⚠ **Offering the whole `legalThresholdPieces` vocabulary was a real defect** (module 13
    defect 3, 2026-09-06): the enum said `{2,3,4,6}` and the brief said *"the piece counts"*, while
    `distribute.threshold_ladder` derived `(2, 4)` from the member count and refused everything
    else. All three sets in the first real batch picked 3 and were refused. The ladder is the
    single fact; the enum reads it.
    """
    return {"type": "integer", "enum": list(ladder if ladder is not None
                                            else tuning.legal_threshold_pieces)}


def _identity_fields() -> "dict[str, Any]":
    """⛔ `nameKey` deliberately removed from here, 2026-09-08 — this schema no longer asks the
    model for it at all. Two independent real-call findings converge on the same fix:
    `trees/nodegen`'s own 2026-09-06 finding (`_derive_unique_name_key`'s docstring) found the
    model repeatedly falls back to a generic templated key decoupled from its own `name` choice;
    this program's own incident, the same day `maxLength` was added below as a mitigation, found a
    WORSE failure mode on the identical field — a quantized model (reproduced on two different
    models) degenerating into a repeated-token loop that burned the full `max_tokens` budget on
    garbage, with the `maxLength`/`pattern` constraints both silently unenforced by LM Studio's
    grammar sampler. `nameKey` is pure mechanical derivation from `name` (`set.<slug-of-name>` /
    `charm.<slug-of-name>`, `seedfile.py`'s own `_derive_unique_name_key`) — there is no
    information in it the model could add, and no validation value in asking for it that
    `_identity_fields`'s own removal doesn't already close by construction: with
    `additionalProperties: false` on every schema that embeds this, the model cannot legally emit
    a `nameKey` key at all, not merely "is discouraged from" one.

    `type` is `["string", "null"]`, not a bare `"string"` — see `set_schema`'s own docstring for
    why every optional field in this whole module got the same treatment 2026-09-08.
    """
    return {
        "name": {"type": ["string", "null"], "minLength": 3, "maxLength": 48},
        "flavor": {"type": ["string", "null"], "minLength": 8, "maxLength": 400},
    }


def _blocked() -> "dict[str, Any]":
    return {
        "type": ["string", "null"],
        "description": "Set this INSTEAD of the content fields if the brief cannot be satisfied — "
                       "say why. A blocked answer writes nothing and is reported, not retried "
                       "forever.",
    }


def set_schema(tuning: SetCharmGenTuning, *, vocabulary: Vocabulary,
               frames: "tuple[str, ...]" = ("humanoid", "plant"),
               member_count: "int | None" = None) -> "dict[str, Any]":
    """The `set` output schema. Identity only — every magnitude is resolved afterwards.

    `capability.family` and threshold `families[]` are closed enums from `vocabulary`, filtered
    by `legal_set_stat_pool` so D14 / More-op atoms cannot be sampled then refused by distribute.
    """
    ladder = threshold_ladder(tuning, member_count or tuning.typical_members)
    cap_families = list(capability_family_ids(vocabulary))
    if not cap_families:
        raise ValueError("set_schema requires a non-empty capability vocabulary")
    stat_ids: list[str] = []
    for pick in legal_set_stat_pool(vocabulary, tuning):
        if pick.pick_id not in stat_ids:
            stat_ids.append(pick.pick_id)
        if pick.family not in stat_ids:
            stat_ids.append(pick.family)
    if not stat_ids:
        raise ValueError("set_schema requires a non-empty legal set-stat pool")
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "flavor", "blocked", "capability", "members", "thresholds"],
        "properties": {
            **_identity_fields(),
            "blocked": _blocked(),
            "capability": {
                "type": ["object", "null"],
                "additionalProperties": False,
                "required": ["family", "variant"],
                "properties": {
                    "family": {"type": "string", "enum": cap_families,
                               "description": "one capability family id from the brief's closed "
                                              "list — a non-stat.* kind (ssot-sets §3.2)"},
                    "variant": {"type": ["string", "null"],
                                "description": "only for a family the brief marks as element-"
                                               "generated; null otherwise"},
                },
            },
            "members": {
                "type": ["array", "null"],
                "minItems": 2,
                "maxItems": tuning.max_roles,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["role", "frame"],
                    "properties": {
                        "role": {"type": "string", "enum": list(HYBRID_CORE_ROLES)},
                        "frame": {"type": "string", "enum": list(frames)},
                    },
                },
            },
            "thresholds": {
                "type": ["array", "null"],
                "minItems": len(ladder),
                "maxItems": len(ladder),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["pieces", "families"],
                    "properties": {
                        "pieces": threshold_pieces(tuning, ladder),
                        "families": {
                            "type": ["array", "null"],
                            "minItems": 1,
                            "maxItems": 3,
                            "items": {"type": "string", "enum": stat_ids,
                                      "description": "a distributor-legal stat family id from "
                                                     "the brief's closed list"},
                        },
                    },
                },
            },
        },
    }


def charm_schema(tuning: SetCharmGenTuning) -> "dict[str, Any]":
    """The `charm` output schema.

    `charmClass` is an enum and `apCost` is absent on purpose: the cost is derived from the class
    (ssot-charms §3.4), and a model asked for both would eventually disagree with itself. `axis`
    reuses the five power categories the family library already uses — no new vocabulary.

    ⛔ Every field `required` + nullable, same 2026-09-08 fix as `set_schema` — see that
    docstring for the live-model evidence. `drawback` stays genuinely optional in MEANING (most
    charms have none) even though it is now structurally `required`: `null` is exactly "no
    drawback," which is what an absent key meant before.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "flavor", "blocked", "charmClass", "axis", "frameHint", "families",
                    "drawback"],
        "properties": {
            **_identity_fields(),
            "blocked": _blocked(),
            "charmClass": {"type": ["string", "null"],
                           "enum": [c.id for c in tuning.charm_classes] + [None]},
            "axis": {"type": ["string", "null"],
                     "enum": ["offense", "survivability", "control", "utility", "economy", None]},
            "frameHint": {"type": ["string", "null"], "enum": ["any", "humanoid", "plant", None]},
            "families": {
                "type": ["array", "null"],
                "minItems": 1,
                "maxItems": 2,
                "items": {"type": "string",
                          "description": "an always-on Flat family id from the brief's closed "
                                         "list — never Increased, never More (ssot-charms §3.4)"},
            },
            "drawback": {
                "type": ["object", "null"],
                "additionalProperties": False,
                "required": ["family"],
                "properties": {
                    "family": {"type": "string",
                               "description": "signet only: the authored negative atom's family"},
                },
            },
        },
    }
