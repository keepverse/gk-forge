"""seedsmith.adapters.items.affixfamgen.schema — the closed-enum answer schema.

⛔ Same discipline as `setgen/schema.py`: identity only, every magnitude resolved afterwards by
`seedsmith.numerics`. `pipeline.model.audit_schema` (run by `brief.AffixFamilyBrief.__post_init__`)
is the mechanical proof this file cannot regress into offering a bare number — this module's own
job is just to make sure that proof always has something to check, by never being imported without
also being audited.

⚠ Two field names the `MAGNITUDE_DENY_NAMES` deny-list would refuse on sight, and how this schema
avoids them: `tier` never appears (tiers come from `numerics`, exactly like `setgen/schema.py`'s
own note); `powerBand` is NOT on the deny list (it is a closed enum of category words, the same
"author writes this INSTEAD of a magnitude" role `bands.v1.json` itself documents) and is kept as
the field name real shipped families already use, rather than inventing a different spelling to
dodge a check it does not trigger.

`op`'s enum is built from the FREE `(channel, op)` pairs still available in the partition — never
the full `opvocab.legal_ops` set alone — so constrained decoding cannot re-sample a taken pair.

⛔ `nameKey` is not asked of the model (2026-09-09): derived in `emit.assemble_entry` from `name`,
same incident class as `setgen/schema.py`'s 2026-09-08 removal.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from seedsmith.pipeline.run import validate_against_schema

from . import opvocab

#: `naming.v1.json`'s own family-id rule: a NEW family's `word` is "the agent's own free choice of
#: a short mechanical identifier (NOT a display word)". Enforced here as a pattern, not just prose:
#: lowercase kebab, 2-24 chars, matching the shipped `word` tokens already seen (`hardening`,
#: `riveting`, `life-graft`'s own `graft`, `fixation`, `truesight`).
WORD_PATTERN = r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$"
_NAME_KEY_SLUG_RE = re.compile(r"[^a-z0-9]+")


def derive_name_key(name: str) -> str:
    """`affix.<slug>` — mechanical transform of `name`; never asked of the model."""
    slug = _NAME_KEY_SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return f"affix.{slug or 'family'}"


def _identity_fields() -> "dict[str, Any]":
    """`name` / `displayTemplate` only — `nameKey` is derived in emit (setgen 2026-09-08 precedent).

    `type` is `["string", "null"]` so every content key can stay `required` while a `blocked`
    answer still satisfies the grammar (setgen live-model fix, 2026-09-08).
    """
    return {
        "name": {"type": ["string", "null"], "minLength": 3, "maxLength": 48},
        "displayTemplate": {"type": ["string", "null"], "minLength": 3, "maxLength": 160},
    }


def _blocked() -> "dict[str, Any]":
    return {
        "type": ["string", "null"],
        "description": "Set this INSTEAD of the content fields if the brief cannot be satisfied — "
                       "say why. A blocked answer writes nothing and is reported, not retried "
                       "forever. When blocked is a non-empty string, every other field must be null.",
    }


def _nullable_string_enum(values: "tuple[str, ...]", *, description: str = "") -> "dict[str, Any]":
    node: "dict[str, Any]" = {
        "type": ["string", "null"],
        "enum": list(values) + [None],
    }
    if description:
        node["description"] = description
    return node


def affix_family_schema(
        kind_id: str, *,
        free_pairs: "tuple[tuple[str, str], ...]",
        roles: "tuple[str, ...]",
        tags: "tuple[str, ...]",
        power_bands: "tuple[str, ...]",
        channels: "tuple[str, ...] | None" = None) -> "dict[str, Any]":
    """The `affix-family` answer schema for ONE partition + ONE declared `kindId`.

    `free_pairs` is the mechanically free `(channel, op)` set from `brief.free_channel_ops` —
    the only pairs constrained decoding may sample. The legacy `channels=` kwarg remains only so
    older call sites that passed partition channels without free pairs fail loudly when free_pairs
    is empty; prefer always passing `free_pairs`.
    """
    del channels  # superseded by free_pairs; kept in signature for call-site migration clarity
    if not free_pairs:
        raise ValueError(
            "affix_family_schema requires at least one free (channel, op) pair — "
            "call free_channel_ops first and skip the model when empty")
    if not roles:
        raise ValueError("affix_family_schema requires at least one legal role")
    if not tags:
        raise ValueError("affix_family_schema requires at least one legal tag")
    if not power_bands:
        raise ValueError("affix_family_schema requires at least one legal powerBand")

    free_channels = tuple(sorted({c for c, _ in free_pairs}))
    pair_tokens = tuple(f"{c}|{o}" for c, o in free_pairs)

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "displayTemplate", "blocked", "word", "channelOp",
                     "roles", "tags", "powerBand"],
        "properties": {
            **_identity_fields(),
            "blocked": _blocked(),
            "word": {
                "type": ["string", "null"],
                "pattern": WORD_PATTERN,
                "minLength": 2,
                "maxLength": 24,
                "description": "a short MECHANICAL identifier, never a display word — the "
                               "family id is minted as atom.{stem}-{word}",
            },
            "channelOp": _nullable_string_enum(
                pair_tokens,
                description=(
                    f"exactly one free (channel|op) still open in this partition "
                    f"(channels with free slots: {', '.join(free_channels)})")),
            "roles": {
                "type": ["array", "null"],
                "minItems": 1,
                "maxItems": len(roles),
                "items": {"type": "string", "enum": list(roles)},
            },
            "tags": {
                "type": ["array", "null"],
                "minItems": 1,
                "maxItems": len(tags),
                "items": {"type": "string", "enum": list(tags)},
            },
            "powerBand": _nullable_string_enum(power_bands),
        },
    }


def _is_blocked(answer: Mapping[str, Any]) -> bool:
    blocked = answer.get("blocked")
    return isinstance(blocked, str) and bool(blocked.strip())


def validate_answer(answer: Mapping[str, Any], schema: Mapping[str, Any], *,
                    channel_ops: "Mapping[str, tuple[str, ...]] | None" = None,
                    kind_id: str | None = None,
                    free_pairs: "tuple[tuple[str, str], ...] | None" = None) -> "list[str]":
    """Validate an affix answer locally, including the live partition's occupied mechanics."""
    defects = validate_against_schema(answer, schema)

    if _is_blocked(answer):
        # Content keys must be null / absent — same XOR as setgen blocked answers.
        for key, value in answer.items():
            if key == "blocked":
                continue
            if value is not None:
                defects.append(
                    f"a blocked answer must null out content fields; {key!r} is {value!r}")
        return defects

    # Content path: blocked must be null/absent; identity + mechanics present.
    if answer.get("blocked") not in (None, ""):
        defects.append("field 'blocked' must be null when authoring content")

    required = ("name", "displayTemplate", "word", "roles", "tags", "powerBand")
    for name in required:
        value = answer.get(name)
        if value is None or value == "":
            defects.append(f"missing required content field {name!r}")

    channel, op = _resolve_channel_op(answer)
    if channel is None or op is None:
        defects.append("missing required free pair — set channelOp (or channel+op) to a free token")
        return defects

    try:
        canonical = opvocab.canonical_op(kind_id or "", op)
    except ValueError as error:
        defects.append(str(error))
        return defects

    if free_pairs is not None and (channel, canonical) not in free_pairs:
        defects.append(
            f"(channel={channel!r}, op={canonical!r}) is not in the free-pair set for this brief")
    elif channel_ops is not None and canonical in channel_ops.get(channel, ()):
        defects.append(
            f"partition already ships (channel={channel!r}, op={canonical!r}); choose a free pair")
    return defects


def _resolve_channel_op(answer: Mapping[str, Any]) -> "tuple[str | None, str | None]":
    """Prefer joint `channelOp`; fall back to separate channel/op for hand-authored answers."""
    token = answer.get("channelOp")
    if isinstance(token, str) and "|" in token:
        channel, _, op = token.partition("|")
        if channel and op:
            return channel, op
    channel = answer.get("channel")
    op = answer.get("op")
    if isinstance(channel, str) and isinstance(op, str):
        return channel, op
    return None, None
