"""seedsmith.adapters.items.milestonegen.schema — closed vocabularies + the model's answer schema.

Three closed vocabularies, each transcribed from real, currently-shipped sources and cited:

- `STAT_MODIFY_OPS` — the real op vocabulary `stat.modify` atoms accept, per `AtomKindRegistry.cs`
  (see `__init__.py`'s module docstring for the full citation). `Override` is deliberately absent —
  it is the one op the real consumer refuses at bind time.
- `PRIMARY_CHANNELS` — a mirror of `FusionRpg.Core.Stats.StatChannels.All`
  (`gk-core/src/FusionRpg.Core/Stats/ModifierOp.cs:69-75`), the exact 23 Unity-mapped channel strings
  `stat.modify`'s own `ParamDef("channel", ..., Vocabulary: () => PrimaryChannels)` validates
  against (`AtomKindRegistry.cs:498-499`, `AtomKindRegistry.PrimaryChannels = Stats.StatChannels.All`
  at line 83). There is no JSON export of that C# array to read programmatically — same situation
  `adapters.items.channels` already documents for `BattleRuleset`'s formulas — so this is a literal
  transcription, not a re-derivation, and `test_enhancement_milestones_gen.py` pins it against the
  literal C# source text so a future channel added there is caught by a failing test rather than a
  silent drift.
- `TAG_VOCAB` — the tag vocabulary the real shipped corpus already uses (`offensive`, `defensive`,
  `utility` — every one of the ten `enh.*` entries' own `tags` array uses exactly one of these three).

`CHANNEL_TUNING` is this generator's OWN closed subset of `PRIMARY_CHANNELS` — the channels it is
willing to offer a model for a NEW enhancement milestone, each mapped to the op and powerBand code
resolves deterministically (P1: the model picks `channel`, never `op`/`powerBand`). It is a strict
subset by design (some primary channels — `zombieSpeed`, `attackCountdown`, and the like — belong to
the zombie/board side of the ladder, not a plant-facing enhancement milestone), not the full 23.
"""
from __future__ import annotations

from typing import Any

#: `AtomKindRegistry.cs:349-357`, doc comment at line 517: "Ops are Flat|Increased|More — effects
#: cannot emit Override". PascalCase — the literal on-disk casing every existing entry already uses.
STAT_MODIFY_OPS: "tuple[str, ...]" = ("Flat", "Increased", "More")

#: `Override` is explicitly illegal for `stat.modify` (`AtomKindRegistry.Validate`, case-insensitive
#: match) — kept as a named constant so a test can assert it is never offered or emitted, not just
#: absent from `STAT_MODIFY_OPS` by omission.
ILLEGAL_STAT_MODIFY_OP = "Override"

#: `FusionRpg.Core.Stats.StatChannels.All` (`ModifierOp.cs:69-75`), transcribed verbatim, declaration
#: order preserved. 23 entries — 11 since E16, 12 more since E38, per that array's own doc comment.
PRIMARY_CHANNELS: "tuple[str, ...]" = (
    "hp", "maxHp", "atk", "defense", "arm1", "arm1Max", "arm2", "arm2Max",
    "attackInterval", "produceInterval", "zombieSpeed",
    "plantShield", "attackCountdown", "attackSpeedAdder", "produceCountdown", "plantSpeed",
    "plantMoveSpeed", "plantLevel", "shootingLevel", "armorFlat", "takeDmgMultiplier",
    "zombieSpeedCurrent", "zombieOriginSpeed",
)

#: The real shipped corpus's own tag vocabulary (`milestones.json`'s ten entries use exactly these
#: three, one each).
TAG_VOCAB: "tuple[str, ...]" = ("offensive", "defensive", "utility")

#: The real shipped corpus's own `powerBand` vocabulary (`milestones.json`'s ten entries use exactly
#: these four values). No formal C# enum backs this field yet (grepped, none found) — these are the
#: values the real data itself already commits to.
POWER_BANDS: "tuple[str, ...]" = ("trivial", "low", "medium", "high")

#: This generator's own offered channel set: a strict subset of `PRIMARY_CHANNELS`, each mapped to
#: the `(op, powerBand)` code resolves deterministically once the model picks the channel — P1's
#: "model writes identity, code writes magnitude" applied to op/powerBand as well as to any number.
#: Every value pair here is drawn from `STAT_MODIFY_OPS` / `POWER_BANDS` respectively (asserted by a
#: test), so a typo here cannot mint an entry the real consumer would reject.
CHANNEL_TUNING: "dict[str, tuple[str, str]]" = {
    "maxHp": ("Flat", "medium"),
    "hp": ("Flat", "low"),
    "atk": ("Flat", "medium"),
    "defense": ("Flat", "medium"),
    "arm1": ("Flat", "medium"),
    "arm2": ("Flat", "medium"),
    "armorFlat": ("Flat", "medium"),
    "plantShield": ("Flat", "high"),
    "attackSpeedAdder": ("Increased", "low"),
    "plantMoveSpeed": ("Increased", "low"),
}

#: `stat.modify` is the only kind this generator authors against today (mirrors
#: `affix-families-gen`'s own per-kind scoping discipline). `shield.grant` entries exist in the real
#: corpus (`enh.003`) but this generator does not mint new ones — different param shape
#: (`element`/`trigger`, no `channel`/`op` at all), out of this pass's scope.
KIND_ID = "stat.modify"


def channel_vocab() -> "tuple[str, ...]":
    """The channels a NEW milestone may pick, in stable sorted order (so a schema built twice is
    byte-identical regardless of dict insertion order)."""
    return tuple(sorted(CHANNEL_TUNING))


def answer_schema(*, channels: "tuple[str, ...] | None" = None,
                   tags: "tuple[str, ...] | None" = None) -> "dict[str, Any]":
    """The model's own answer schema. Deliberately narrow: `name`, `flavor`, `channel`, `tags` —
    never `op`, `powerBand`, `id`, `nameKey` or `runtimeFamily`, all of which `emit.py` derives.

    `name` carries a pattern requiring the `"Enhancement "` prefix every one of the ten real entries
    already uses (`"Enhancement Vigor"`, `"Enhancement Edge"`, ...) — the convention this module's
    own id/nameKey/runtimeFamily minting depends on (`emit.slug_from_name` strips exactly this
    prefix), enforced in the schema rather than discovered as a mint-time failure.
    """
    channel_enum = list(channels if channels is not None else channel_vocab())
    tag_enum = list(tags if tags is not None else TAG_VOCAB)
    if not channel_enum:
        raise ValueError("no channels offered — CHANNEL_TUNING must not be empty")
    if not tag_enum:
        raise ValueError("no tags offered — TAG_VOCAB must not be empty")
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {
            "name": {
                "type": "string",
                "minLength": len("Enhancement X"),
                "maxLength": 64,
                "pattern": r"^Enhancement [A-Z][A-Za-z]*$",
                "description": "Must start with 'Enhancement ' followed by one capitalized word, "
                               "matching every existing entry's own naming convention.",
            },
            "flavor": {
                "type": "string",
                "minLength": 8,
                "maxLength": 400,
                "description": "One or two sentences of mechanical flavor — no number, no tier, no "
                               "magnitude; those are resolved after the answer, from tuning data.",
            },
            "channel": {
                "type": "string",
                "enum": channel_enum,
                "description": "The real stat channel this milestone touches — op and powerBand "
                               "are resolved from this choice, never authored directly.",
            },
            "tags": {
                "type": "array",
                "minItems": 1,
                "maxItems": len(tag_enum),
                "items": {"type": "string", "enum": tag_enum},
            },
            "blocked": {
                "type": "string",
                "description": "Set this INSTEAD of the content fields if no legal channel fits "
                               "the theme — say why. A blocked answer writes nothing.",
            },
        },
    }


def schema_field_names(schema: "dict[str, Any]") -> "tuple[str, ...]":
    """Every property name in the schema — for a test asserting `op`/`powerBand`/`id`/`nameKey`/
    `runtimeFamily` are ABSENT (P1: the model never authors them)."""
    return tuple(sorted(schema.get("properties", {})))
