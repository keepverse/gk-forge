"""The species anchor schema (creature-seed module 2, spec-anchor-contract.md). Twenty-two keys for
eighteen design variables — `speciesId`, `gameTypeId`, `pure` and `speciesKind` are bookkeeping the
ideal doc's count did not include, per §2 (`speciesKind` added 2026-09-17 by R-CS4). **The anchor
holds no numbers at all** except the one allow-listed identifier (`gameTypeId`), which is what makes
`audit.py`'s numeric audit mechanical rather than a judgement call.
"""
from __future__ import annotations

from typing import Any

from .descriptions import DESCRIPTIONS
from seedsmith.ladders import RARITY_LADDER as _RARITY_LADDER
from seedsmith.ladders import carries_no_identity, carries_placeholder, normalize_family_key
from seedsmith.ladders import THREAT_BAND as _THREAT_BAND

# Real, shipped vocabularies — never invented here. Sources:
#   ELEMENTS      gk-core/src/FusionRpg.Core/Combat/Element/ElementTable.cs:125-130
#   APTITUDES     gk-core/src/FusionRpg.Core/Stats/Aptitudes/Aptitude.cs (AptitudeCatalog.All)
#   POSTURES      gk-core/src/FusionRpg.Core/Stats/Aptitudes/Aptitude.cs (enum Posture)
#   DEPLOY_MODE   gk-core/src/FusionRpg.Core/Creatures/CreatureRarity.cs (enum CreatureDeployMode)
#   ACQUISITION   gk-core/src/FusionRpg.Core/Creatures/CreatureRarity.cs (enum CreatureAcquisition, [Flags])
#   RARITY        gk-data/packs/fusion/data/seed/rarity/ladder.v1.json (ten-rung ladder, creatures adopted 2026-09-01)
#   THREAT_BAND   gk-core/data/tuning/creature-threat.v1.json (creature-seed module 4)
# Both are READ from their declaring files via seedsmith.ladders (tier-propagation-contract
# T-2) — never re-transcribed here.
#   VARIANTS      docs/architecture/creature-seed-ideal.md:274 (owner Q17)
#   RESOURCES     resource-hub-ssot.md — six actor resources incl. poise
#   SPECIES_KIND  creature-seed-ideal.md R-CS4 (owner, 2026-09-17) — declared below, code-owned

ELEMENTS = ("fire", "ice", "air", "earth", "light", "dark")

APTITUDES = (
    "Might", "Fortitude", "Vigor", "Onslaught",
    "Agility", "Composure", "Pierce", "Focus",
    "Bulwark", "Retribution", "Precision", "Ferocity",
)

# aptitude id -> posture, ported verbatim from AptitudeCatalog.All so `posture` derives correctly.
APTITUDE_POSTURE = {
    "Might": "Force", "Fortitude": "Force", "Vigor": "Force", "Onslaught": "Force",
    "Agility": "Finesse", "Composure": "Finesse", "Pierce": "Finesse", "Focus": "Finesse",
    "Bulwark": "Bastion", "Retribution": "Bastion", "Precision": "Bastion", "Ferocity": "Bastion",
}

POSTURES = ("Force", "Finesse", "Bastion")
THREAT_BAND = _THREAT_BAND
RARITY = _RARITY_LADDER
# The rank ladder mirrors the rarity ladder 1:1, row for row (spec-species-rank.md Assumption 1,
# owner-confirmed) — so it IS the rarity ladder's declaring read, never a retyped tuple
# (tier-propagation-contract T-2). `gk-core/data/tuning/creature-rank.v1.json` carries its own `ranks`
# table and the C# `CreatureRank` enum is the runtime vocabulary; all three must agree, and the
# C# loader + this module's own derive tests are what fail loudly if they drift.
RANK = _RARITY_LADDER
DEPLOY_MODE = ("PlantAvatar", "HypnoAlly")
ACQUISITION = ("Summonable", "CaptureOnly", "EventOnly")
VARIANTS = ("normal", "ancient", "mutated", "corrupted", "blessed", "cursed", "shiny")
RESOURCES = ("hp", "stamina", "hunger", "spirit", "qi", "poise")
BASIS = ("observed", "stated", "inferred", "blocked")

#: What a corpus ROW is, as opposed to what the creature on it is like (creature-seed R-CS4,
#: owner-ruled 2026-09-17: "just make closed enum for it"). A CLOSED vocabulary the code owns and a
#: human changes by review — the mirror image of the species roster itself, which is a derived
#: POPULATION and must never become an enum.
#:
#:   creature  a real creature whose `gameTypeId` resolves to a real PlantType/ZombieType member
#:   mimic     a real creature that deliberately BORROWS a lawn type id it does not natively own.
#:             R-CS2 exists so the corpus stays open to authored content: enforcing native
#:             resolution would refuse a new special species for the crime of being new. A borrowed
#:             id keeps spawn/render/dump joins working and makes the borrowing explicit and
#:             inspectable rather than an absence somebody later reads as a bug.
#:   excluded  NOT a creature. Never spawn, never draw, never count as roster. A positive statement
#:             about what the row is FOR (nothing, deliberately) — R-CS3 ruled marking over
#:             deleting because "a deleted id is untracked, and an untracked id can be silently
#:             re-used or re-derived."
#:
#: `mimic` implies `creature`; there is no meaningful excluded mimic, which is why R-CS2's id
#: provenance and R-CS3's what-is-this-row collapse into ONE enum rather than two axes.
#: Deliberately SEPARATE from BASIS: `basis: blocked` means "no text to derive power from" and a
#: real creature can legitimately be blocked — a different statement from "not a creature."
SPECIES_KIND = ("creature", "mimic", "excluded")
ATTACK_TEMPO = ("ponderous", "slow", "steady", "quick", "flurry")
REACH = ("melee", "short", "long", "siege")
TARGET_PREFERENCE = ("frontline", "backline", "swarm", "elite", "structure", "indiscriminate")

# Ownership level per field (spec §1). A field with no entry here is a contract defect.
OWNERSHIP = {
    "side": "CAPTURED", "speciesId": "CAPTURED", "gameTypeId": "CAPTURED",
    "elementPrimary": "CLASSIFIED", "elementSecondary": "CLASSIFIED",
    "aptitudePrimary": "CLASSIFIED", "aptitudeSecondary": "CLASSIFIED",
    "posture": "DERIVED", "pure": "DERIVED",
    "threatBand": "CLASSIFIED", "rarity": "CLASSIFIED",
    "rank": "DERIVED",
    "deployMode": "CLASSIFIED", "acquisition": "CLASSIFIED",
    "variants": "CLASSIFIED", "resourceProfile": "CLASSIFIED",
    "basis": "DERIVED", "speciesKind": "DERIVED",
    "family": "CLASSIFIED", "traits": "CLASSIFIED",
    "attackTempo": "CLASSIFIED", "reach": "CLASSIFIED", "targetPreference": "CLASSIFIED",
}

# The model authors CLASSIFIED fields only — CAPTURED is echoed from the dump, DERIVED is
# computed by code (never let the model author posture/pure/basis/speciesKind — boundaries).
CLASSIFIED_FIELDS = frozenset(k for k, v in OWNERSHIP.items() if v == "CLASSIFIED")
DERIVED_FIELDS = frozenset(k for k, v in OWNERSHIP.items() if v == "DERIVED")

# The one legal integer field — an identifier, never a magnitude (spec §4).
ALLOWLISTED_INTEGER_FIELDS = frozenset({"gameTypeId"})


def _desc(field: str) -> str:
    try:
        return DESCRIPTIONS[field]
    except KeyError:
        raise KeyError(f"anchor field {field!r} has no description in descriptions.py") from None


def _enum_prop(field: str, values: "tuple[str, ...]", *, nullable: bool = False) -> dict:
    enum_values = list(values) + (["none"] if nullable else [])
    return {"type": "string", "enum": enum_values, "description": _desc(field)}


def _flag_array_prop(field: str, values: "tuple[str, ...]") -> dict:
    return {
        "type": "array",
        "items": {"type": "string", "enum": list(values)},
        "minItems": 1,
        "uniqueItems": True,
        "description": _desc(field),
    }


def _open_array_prop(field: str) -> dict:
    return {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 1,
        "description": _desc(field),
    }


def build_anchor_schema() -> dict:
    """The resolved JSON Schema for one species anchor. Consumable directly as an LM Studio
    `response_format: {"type": "json_schema", "json_schema": {"schema": build_anchor_schema()}}`.
    """
    properties: "dict[str, Any]" = {
        "side": {"type": "string", "enum": ["plant", "zombie"], "description": _desc("side")},
        "speciesId": {"type": "string", "description": _desc("speciesId")},
        # The one allow-listed integer — captured, an identifier, never arithmetic (spec §4).
        "gameTypeId": {"type": "integer", "description": _desc("gameTypeId")},

        "elementPrimary": _enum_prop("elementPrimary", ELEMENTS),
        "elementSecondary": _enum_prop("elementSecondary", ELEMENTS, nullable=True),

        "aptitudePrimary": _enum_prop("aptitudePrimary", APTITUDES),
        "aptitudeSecondary": _enum_prop("aptitudeSecondary", APTITUDES, nullable=True),

        "posture": _enum_prop("posture", POSTURES),
        "pure": {"type": "boolean", "description": _desc("pure")},

        "threatBand": _enum_prop("threatBand", THREAT_BAND),
        "rarity": _enum_prop("rarity", RARITY),
        "rank": _enum_prop("rank", RANK),

        "deployMode": _enum_prop("deployMode", DEPLOY_MODE),
        "acquisition": _flag_array_prop("acquisition", ACQUISITION),

        "variants": _flag_array_prop("variants", VARIANTS),
        "resourceProfile": _flag_array_prop("resourceProfile", RESOURCES),

        "basis": _enum_prop("basis", BASIS),
        "speciesKind": _enum_prop("speciesKind", SPECIES_KIND),

        "family": _open_array_prop("family"),
        "traits": _open_array_prop("traits"),

        "attackTempo": _enum_prop("attackTempo", ATTACK_TEMPO),
        "reach": _enum_prop("reach", REACH),
        "targetPreference": _enum_prop("targetPreference", TARGET_PREFERENCE),
    }

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "CreatureSpeciesAnchor",
        "type": "object",
        "properties": properties,
        "required": sorted(properties.keys()),
        "additionalProperties": False,
    }


def seed_consumer_violations(fields: "dict[str, object]") -> "tuple[str, ...]":
    """Every shape `characteristic_pool.catalog` refuses on the live-seed load path, as one
    predicate.

    Transcribed from that module's own raise statements, which is the only place the contract
    is knowable from. Named by GUARD rather than by line, deliberately: an earlier version of this
    docstring carried the line numbers and they were stale within the same edit that added them,
    because moving one import in catalog.py shifted every one of them. A citation that rots on an
    unrelated edit is not evidence of coverage, and this repo already has a guard for that class of
    drift; the fix is to not write the citation.

        species record must be an object    speciesId present
        speciesId unique                     dir non-empty
        speciesId is a string               elementPrimary in six
        elementSecondary in six              rarity in the ladder
        traits is a list                     a family label normalizes
        family is a list                    family has a live label
        family label asserts an identity     family label is loadable

    The last row is the only one NOT transcribed from a `raise` in the consumer, and it is
    deliberate: it is a SOURCE-side refusal, which is the whole point of it. The consumer
    (`characteristic_pool/catalog.py`) cannot see the defect — `normalize_family_key` maps
    `placeholder entry` to the perfectly loadable key `entry`, and maps `unnamed plant` to `plant`,
    which is one of the two largest buckets in the corpus. Both are artefacts and both load
    without complaint, so a predicate transcribed from the consumer's raise set can never refuse
    them. Measured 2026-10-04 over the 904 live records: 2 labels carry a capture-placeholder token
    and 6 more assert that no identity was captured, for 8 label occurrences the consumer accepts.

    The list is this long because the corpus was repaired four times against one guard at a
    time - 44 entries with an unresolvable elementPrimary, 111 with a rarity outside the
    ladder, 9 with a string where a list belongs, 338 with no family at all - and each round was
    followed by a suite run that surfaced the NEXT guard in the same file. A runner checking
    one field and a validator enumerating one field are the same mistake at two layers.

    Returns human-readable violations; an empty tuple means the entry is loadable. The family
    branch calls the shared leaf's `normalize_family_key` so this check cannot drift from the
    consumer's own normalisation.
    """
    out: "list[str]" = []
    species_id = fields.get("speciesId")
    if species_id is None:
        out.append("speciesId is absent")
        return tuple(out)
    if not isinstance(species_id, str):
        out.append(f"speciesId is {type(species_id).__name__}, not a string")
        return tuple(out)

    primary = fields.get("elementPrimary")
    if (primary.lower() if isinstance(primary, str) else "") not in ELEMENTS:
        out.append(f"elementPrimary {primary!r} is not one of {list(ELEMENTS)}")

    secondary = fields.get("elementSecondary")
    secondary_id = (secondary.lower()
                    if isinstance(secondary, str) and secondary.lower() != "none" else None)
    # Only the literal 'none' (or an absent field) is exempt - an EMPTY string is not, which
    # is why an entry carrying '' reached the loader and raised. Mirrors L165 exactly.
    if secondary_id is not None and secondary_id not in ELEMENTS:
        out.append(f"elementSecondary {secondary!r} is not one of {list(ELEMENTS)}")

    rarity = fields.get("rarity")
    if (rarity.lower() if isinstance(rarity, str) else "") not in _RARITY_LADDER:
        out.append(f"rarity {rarity!r} is not one of the ten rungs")

    if not isinstance(fields.get("traits", []), list):
        out.append(f"traits is {type(fields.get('traits')).__name__}, not a list")

    families = fields.get("family", [])
    if isinstance(families, str):
        families = [families]
    if not isinstance(families, list):
        out.append(f"family is {type(fields.get('family')).__name__}, not a list")
    else:
        labels = sorted({str(label).strip() for label in families if str(label).strip()})
        if not labels:
            out.append("family has no live label")
        else:
            # normalize_family_key RAISES on a label that normalizes to nothing rather than returning
            # an empty key - that is the consumer's own contract, and it is the definition this check
            # has to agree with. Catching the raise keeps ONE normalisation in the tree; recomputing
            # the key here would be the second implementation that could drift from the consumer.
            dead = []
            for label in labels:
                try:
                    normalize_family_key(label)
                except ValueError:
                    dead.append(label)
            if dead:
                out.append(f"family label(s) {dead} normalize to an empty key")
            # The SOURCE-side refusal the consumer structurally cannot make (see the docstring's
            # table). Both predicates come from the shared leaf so this gate and `theme_enrich`'s
            # flavour check read one definition, and reported per label so a caller repairing one
            # bad label is told exactly which one it was.
            assert_no_identity = sorted(
                label for label in labels
                if carries_placeholder(label) or carries_no_identity(label))
            if assert_no_identity:
                out.append(
                    f"family label(s) {assert_no_identity} assert no captured identity "
                    f"(placeholder / unnamed / unknown / unspecified / unidentified)")
    return tuple(out)


# =================================================================================================
# Consumer 2 — the C# anchor reader: `AnchorRowReader.ReadOne` + `SpeciesExpander.Expand`
# =================================================================================================
#
# A SIBLING of `seed_consumer_violations`, never an extension of it. Two different consumers read the
# same corpus and they do NOT accept the same entries: consumer 1 is the Python
# `characteristic_pool/catalog.py` live-seed loader, consumer 2 is the C# `AnchorRowReader` /
# `SpeciesExpander` pair that every C# anchor tool and the `RealAnchorCorpusFixture` test family go
# through (`gk-forge/tools/CreatureRecipeReconcileInput/Program.cs` is one caller;
# `gk-core/tests/FusionRpg.Core.Tests/Delve/Encounter/RealAnchorCorpusFixture.cs` is another, and it
# is the fixture whose static initialiser took 133 gk-core tests down).
#
# Merging the two sets would be wrong twice over: consumer 1's predicate would start refusing entries
# consumer 1 loads today (it does NOT care about `reach` or `targetPreference` at all), and
# `tests/test_seed_consumer_contract.py` pins consumer 1's docstring to consumer 1's exact raise set
# as its coverage assertion — widening that docstring silently destroys the assertion that keeps
# consumer 1 honest. Two consumers, two predicates, two tests.
#
# Every closed vocabulary consumer 2 checks is declared in THIS module, so nothing below is
# re-transcribed. `tests/test_csharp_anchor_consumer_contract.py` asserts each one against the file
# the C# side actually loads (`aptitudes.v2.json` edge sources, `creature-shape.v1.json` keys), which
# is the drift check that replaces a second copy: if `creature-shape.v1.json` gains a tempo rung and
# `ATTACK_TEMPO` does not, that test fails rather than the predicate quietly refusing a legal value.

#: The literal one-word sentinel both optional-secondary fields use for "no secondary". The C# reader
#: maps it to null with a case-INSENSITIVE, untrimmed comparison (`AnchorRow.cs`'s
#: `string.Equals(x, "none", StringComparison.OrdinalIgnoreCase)`), so `None`/`NONE` are equally exempt
#: and a value with surrounding whitespace is NOT.
C_SHARP_NONE_SENTINEL = "none"

#: The same sentinel, named for the WRITER rather than the reader. `build_anchor_schema` appends it
#: to exactly the two optional-secondary vocabularies (`_enum_prop(..., nullable=True)`), so it is a
#: declared MEMBER of those vocabularies — a legal answer, not a failure marker. An ABSENT key on one
#: of those two fields means the very same thing the sentinel means, so a generator that declines to
#: answer should write this rather than write nothing. Declared here beside
#: `C_SHARP_NONE_SENTINEL` so the reader's spelling and the writer's are visibly one value.
DECLARED_NULL = C_SHARP_NONE_SENTINEL

#: The eleven anchor keys `AnchorRowReader.ReadOne` reads through its `Str` helper, which raises
#: `anchor: missing or non-string '{key}'` for anything that is not a JSON string. `StrArray` (the other
#: three keys) is deliberately NOT here - see the docstring of `csharp_anchor_consumer_violations`.
C_SHARP_STR_FIELDS = (
    "speciesId", "rarity", "aptitudePrimary", "aptitudeSecondary",
    "attackTempo", "reach", "side", "elementPrimary", "elementSecondary",
    "deployMode", "targetPreference",
)

#: `ACQUISITION` plus the one C#-legal member this module's authoring contract deliberately omits.
#:
#: `CreatureAcquisition` is `[Flags] enum { None = 0, Summonable = 1, CaptureOnly = 2, EventOnly = 4 }`
#: and `SpeciesExpander` parses each flag with `Enum.TryParse(ignoreCase: false)`, so the literal
#: `"None"` WOULD parse without raising. It is still excluded here, on purpose and not by oversight:
#:
#:   1. `None` is not AUTHORABLE. `_flag_array_prop` builds the authoring JSON Schema's enum straight
#:      from `ACQUISITION`, so no rerun of `deployment` can emit `"None"` - a guard against an
#:      unreachable state is a guard that can only ever block a hand-edit.
#:   2. `None` is already a catalog error by this repo's own ruling, stated twice: `CreatureRarity.cs`
#:      documents "A species with None is a catalog error", and
#:      `workflow/validators/anchor.py::acquisition_nonzero` refuses an empty acquisition for the same
#:      reason. Consumer 2 is simply not where that is enforced.
#:   3. The consumer's own output projection drops it: `AcquisitionFlags` in
#:      `CreatureRecipeReconcileInput/Program.cs` filters `CreatureAcquisition.None` out before
#:      emitting, so accepting it here would only move the problem downstream.
#:
#: Excluding it is therefore stricter than consumer 2, in the safe direction: everything this flags,
#: consumer 2 either refuses outright or should never have been handed. The same over-approximation
#: covers `Enum.TryParse`'s numeric and comma-separated forms (`"2"`, `"Summonable, EventOnly"`), which
#: also parse in C# and are equally unauthorable - and a bare digit in a closed enum field is exactly
#: the numeric-smuggling shape `anchor/audit.py` exists to catch.
C_SHARP_ACQUISITION_FLAGS = ACQUISITION

#: The classification pipeline's own literal `"unresolved"`, which `SpeciesExpander.UnresolvedFields`
#: reports and the caller SKIPS on before calling `Expand`. A skip is not a raise, so it is NOT a
#: violation — and because the caller skips the whole species on ANY one of these five fields, one
#: sentinel shadows every `Expand` guard for that entry. See `csharp_anchor_skipped_fields`.
C_SHARP_UNRESOLVED_SENTINEL = "unresolved"

#: The five fields `SpeciesExpander.UnresolvedFields` inspects, in its own order.
C_SHARP_SKIP_FIELDS = ("rarity", "aptitudePrimary", "elementPrimary", "attackTempo", "deployMode")


def _folded(value: object) -> str:
    """`value` trimmed and lower-cased — how `CreatureRarityIds.TryParse`, `CreatureRankIds.TryParse`
    and `ElementRoster.TryParse` all read their argument (`(value ?? "").Trim().ToLowerInvariant()`)."""
    return value.strip().lower() if isinstance(value, str) else ""


def _ordinal(value: object) -> str:
    """`value` verbatim — how the `attackTempo`/`reach` lookup (`StringComparer.Ordinal` over
    `creature-shape.v1.json`) and the `aptitudePrimary` edge match (`StringComparison.Ordinal`) read
    theirs. Neither trims, neither folds case: `" steady"` and `"steady"` are different keys."""
    return value if isinstance(value, str) else ""


def _is_member(value: object, vocabulary: "tuple[str, ...]", *, folded: bool) -> bool:
    read = _folded if folded else _ordinal
    return read(value) in vocabulary


def _str_or_report(fields: "dict", key: str, out: "list[str]") -> "str | None":
    """The `AnchorRowReader.Str` guard for one key: report `anchor: missing or non-string '{key}'`
    unless the value is a JSON string.

    Returns the value, or `None` when the guard fired. That `None` is load-bearing and is why this
    is sequencing rather than short-circuiting: the consumer raises at `Str` and NEVER reaches any
    later guard on the same field, so a second complaint about the same value would be reporting a
    refusal the consumer does not make — `reach: absent` is ONE defect, not a missing field AND an
    unknown reach. Every field is still checked, and every field's guards are still evaluated
    whenever the consumer would actually evaluate them.
    """
    value = fields.get(key)
    if not isinstance(value, str):
        out.append(f"anchor: missing or non-string '{key}'")
        return None
    return value


def csharp_anchor_consumer_violations(fields: "object") -> "tuple[str, ...]":
    """Every shape the C# anchor consumer refuses, as ONE predicate — the sibling of
    `seed_consumer_violations`, and every guard evaluated with no short-circuit across guards,
    because this consumer's own CLI is fail-fast: `CreatureRecipeReconcileInput/Program.cs` prints
    the first rejection and `return 1`s, abandoning the rest of the load. That is precisely why an
    earlier repair programme cost four serial rounds against this consumer, each round discovering
    the next guard. Collapsing it back to one pass is the entire point of this function.

    Transcribed by GUARD NAME, never by line number, for the reason `seed_consumer_violations`'s
    docstring gives: line citations rotted inside the very edit that added them, and
    `test_csharp_anchor_consumer_contract.py` asserts the coverage against these names.

    -- STAGE 1: `AnchorRowReader.ReadAll` (file level, so NOT expressible per entry; see
       `csharp_anchor_corpus_violations`, which does check them) --------------------------

        anchor file: not valid JSON
        anchor file: expected a top-level array

    -- STAGE 2: `AnchorRowReader.ReadOne` -------------------------------------------------

        anchor record must be an object       every element of the top-level array is a JSON object
        anchor: missing or non-string '{k}'   for EACH of the eleven C_SHARP_STR_FIELDS
        anchor: missing or non-integer 'gameTypeId'

    -- STAGE 3: `SpeciesExpander.Expand` (only reached when stage 2 passed for every field) ------

        rarity '{v}' is not a known CreatureRarity
        aptitudePrimary '{v}' has no edge in aptitudes.v2.json
        aptitudeSecondary '{v}' has no edge in aptitudes.v2.json
        attackTempo '{v}' has no entry in creature-shape.v1.json
        reach '{v}' has no entry in creature-shape.v1.json
        elementPrimary '{v}' is not a known element
        elementSecondary '{v}' is not a known element
        deployMode '{v}' is not a known CreatureDeployMode
        acquisition '{v}' is not a known CreatureAcquisition
        rank '{v}' is not a known CreatureRank

    -- THE TWO ORDERING RULES THAT KEEP THE THREE STAGES HONEST ------------------------------
    Both are faithful to the consumer's own control flow, and both were measured against the corpus
    rather than assumed — the first draft of this function got both wrong and each one invented
    violations that `CreatureRecipeReconcileInput.exe` never reports.

    1. A `Str` guard shadows its own field's stage-3 guard (`_str_or_report` says why). This is the
       difference between the two defect modes the corpus actually contains: `attackTempo: ""` is
       present-and-wrong and fails ONLY at the membership lookup, while `reach` absent fails ONLY at
       presence. Empty string is not exempt from either — `Str` accepts "" happily — so the two
       vocabularies of failure stay distinct in the wording, and a caller fixing one has different
       work from a caller fixing the other.
    2. ONE `UnresolvedFields` sentinel shadows the WHOLE stage 3, because the caller skips the entire
       species before `Expand` is called. Reported separately by `csharp_anchor_skipped_fields`, and
       deliberately NOT a violation: refusing it would be refusing an entry consumer 2 silently
       drops, which is a real defect of a different kind (a lost species, not a rejected file).

    -- STAGE 4: `CreatureSpeciesCatalog.Validate`, reached by `CreatureRecipeReconcileInput` --------
    Only the stages this tool actually RUNS are listed, and that set was measured by running it
    rather than assumed. Clearing `AnchorRowReader`/`SpeciesExpander` alone was enough to load all
    904 entries, and the tool then failed one stage further out on this:

        species has no acquisition flags        `acquisition` present, a list, and non-empty

    `acquisition` is absent on 301 of the 904 real entries and `StrArray` silently defaults it to an
    empty list, so it survives every stage above and is refused HERE — `CreatureRarity.cs`'s own "a
    species with None is a catalog error" made concrete. It is the one guard here the two readers do
    not raise, and it is present because the tool's exit code is the acceptance measurement: a
    predicate that stopped at stage 3 would report 0 while the tool still exited non-zero, which is
    precisely the failure mode this predicate exists to prevent.

    -- CONSIDERED AND DELIBERATELY NOT GUARDS ----------------------------------------------
    Named here so a reader can tell an omission from an oversight:

        `StrArray`'s `variants` and `traits` still default silently to an EMPTY list and nothing
            downstream refuses an empty one, so they stay unguarded. `acquisition` left that list
            precisely because stage 4 does refuse it.
        `AnchorRowReader`'s `threatBand`, `pure` and `speciesKind`, and a NON-STRING `rank`, all
            degrade to null/false and never raise.
        `speciesId`, `side` and `targetPreference` are presence-guarded and nothing more — `Expand`
            reads none of them through a vocabulary, so a present-but-unknown value is not a defect
            at these stages.
        `Enum.TryParse` also accepts a numeric string and a comma-separated flag list, and trims its
            argument. See `C_SHARP_ACQUISITION_FLAGS` for why this predicate stays strict there.

    Returns human-readable violations; an empty tuple means the entry survives every guard. Never
    raises on a malformed value: a bad row must become a refusal, not a `TypeError` out of the run.
    """
    if not isinstance(fields, dict):
        return (f"anchor record must be an object, not {type(fields).__name__}",)

    out: "list[str]" = []

    # ---- STAGE 2: presence and shape -------------------------------------------------------
    values: "dict[str, str | None]" = {
        key: _str_or_report(fields, key, out) for key in C_SHARP_STR_FIELDS
    }
    game_type_id = fields.get("gameTypeId")
    # `bool` is an int in Python and a JSON `true` is not a number to C#'s TryGetInt32, so exclude it
    # explicitly rather than let `isinstance` quietly disagree with the consumer.
    if isinstance(game_type_id, bool) or not isinstance(game_type_id, int):
        out.append("anchor: missing or non-integer 'gameTypeId'")

    # ---- STAGE 3: only if the consumer would actually get there ------------------------------
    # `UnresolvedFields` is checked BEFORE stage 3, not after, because it is what decides whether
    # stage 3 happens at all.
    if any(fields.get(key) == C_SHARP_UNRESOLVED_SENTINEL for key in C_SHARP_SKIP_FIELDS):
        return tuple(out)

    def _member_guard(key: str, vocabulary: "tuple[str, ...]", complaint: str, *,
                      folded: bool) -> None:
        value = values.get(key)
        if value is not None and not _is_member(value, vocabulary, folded=folded):
            out.append(complaint.format(value=repr(value)))

    # Folded reading: the three TryParse switch statements trim and lower-case their argument.
    _member_guard("rarity", RARITY, "rarity {value} is not a known CreatureRarity", folded=True)
    _member_guard(
        "elementPrimary", ELEMENTS, "elementPrimary {value} is not a known element", folded=True)

    # Ordinal reading: `string.Equals(e.Source, family, Ordinal)`, and `StringComparer.Ordinal` over
    # `creature-shape.v1.json`'s own table. Neither trims, neither folds case.
    _member_guard(
        "aptitudePrimary", APTITUDES,
        "aptitudePrimary {value} has no edge in aptitudes.v2.json", folded=False)
    _member_guard(
        "attackTempo", ATTACK_TEMPO,
        "attackTempo {value} has no entry in creature-shape.v1.json", folded=False)
    _member_guard(
        "reach", REACH, "reach {value} has no entry in creature-shape.v1.json", folded=False)
    _member_guard(
        "deployMode", DEPLOY_MODE,
        "deployMode {value} is not a known CreatureDeployMode", folded=False)

    # ---- the two secondary fields: same `Str` guard, then their own null mapping ---------------
    # The reader maps the `none` sentinel to null with a case-INSENSITIVE, UNTRIMMED comparison, so
    # `None`/`NONE` are exempt and a value with surrounding whitespace is not.
    element_secondary = values.get("elementSecondary")
    if element_secondary is not None and \
            element_secondary.lower() != C_SHARP_NONE_SENTINEL and \
            not _is_member(element_secondary, ELEMENTS, folded=True):
        out.append(f"elementSecondary {element_secondary!r} is not a known element")

    # `Expand` gates the secondary-apptitude edge check on `hasSecondary` — `not pure` AND a
    # non-null secondary — and says why in a comment there: a pure species carries zero secondary
    # share by construction, so a garbage `aptitudeSecondary` on a pure anchor is INERT and must not
    # refuse generation for a value the math never reads. Mirroring the gate is the whole fidelity
    # question on this field; checking it unconditionally would invent refusals.
    aptitude_secondary = values.get("aptitudeSecondary")
    if aptitude_secondary is not None and fields.get("pure") is not True and \
            aptitude_secondary.lower() != C_SHARP_NONE_SENTINEL and \
            not _is_member(aptitude_secondary, APTITUDES, folded=False):
        out.append(
            f"aptitudeSecondary {aptitude_secondary!r} has no edge in aptitudes.v2.json")

    # ---- acquisition: a flag ARRAY, each flag parsed on its own (stages 3 and 4) ----------------
    # Stage 3 parses each flag; stage 4 refuses the species outright when the array is empty.
    # `StrArray` makes absent, non-list and empty all the SAME thing — an empty array — so the guard
    # does too, via the `isinstance` normalisation rather than three separate branches. Absent is the
    # case that actually occurs (301 of 904 real entries), and it is the one a naive
    # `if isinstance(..., list)` guard silently misses.
    acquisition = fields.get("acquisition")
    flags = acquisition if isinstance(acquisition, list) else []
    if not flags:
        out.append("species has no acquisition flags — 'acquisition' is absent, not a list, or "
                   "empty (StrArray makes all three an empty array)")
    for flag in flags:
        # A non-string element can only come from a hand-edit: `StrArray` would have stringified
        # it to "" and then refused it at the enum parse, so refusing it here agrees.
        if not isinstance(flag, str) or not _is_member(
                flag, C_SHARP_ACQUISITION_FLAGS, folded=False):
            out.append(f"acquisition {flag!r} is not a known CreatureAcquisition")

    # ---- rank: gated on being a string at all, and on not being the `unresolved` sentinel ------
    # A non-string `rank` never reaches `ResolveRank` (the reader's own `ValueKind == String` test
    # makes it null), and the literal `"unresolved"` maps to null too — both skipped, exactly as
    # `ResolveRank`'s early return does.
    rank = fields.get("rank")
    if isinstance(rank, str) and rank.lower() != C_SHARP_UNRESOLVED_SENTINEL and \
            not _is_member(rank, RANK, folded=True):
        out.append(f"rank {rank!r} is not a known CreatureRank")

    return tuple(out)


def csharp_anchor_skipped_fields(fields: "object") -> "tuple[str, ...]":
    """The fields `SpeciesExpander.UnresolvedFields` reports — the classification pipeline's own
    literal `"unresolved"`, which its caller SKIPS on before calling `Expand`.

    Separate from `csharp_anchor_consumer_violations` on purpose, and the separation is the point: a
    skip is not a refusal. Folding the two together would either refuse entries consumer 2 loads
    today, or — worse, and much less visibly — let a caller read an empty violation tuple as "the C#
    side reconciles this species" when the truth is "the C# side silently drops it". Both sentences
    are true about different species, and only this one is true about this one.

    A caller that wants "will consumer 2 reconcile this species?" must ask BOTH functions. That is
    the reason they are separate and that is why neither calls the other.

    The comparison is an exact case-sensitive `==` in C#, which is why `"Unresolved"` is NOT a skip
    and IS refused by the sibling predicate as an unknown rarity.
    """
    if not isinstance(fields, dict):
        return ()
    return tuple(key for key in C_SHARP_SKIP_FIELDS
                 if fields.get(key) == C_SHARP_UNRESOLVED_SENTINEL)


def csharp_anchor_corpus_violations(document: object, *, path: str = "<corpus>") -> "tuple[str, ...]":
    """`AnchorRowReader.ReadAll`'s two file-level guards, plus the per-entry guard for every row.

    `csharp_anchor_consumer_violations` is per-entry, and `ReadAll`'s first two guards are about the
    FILE — a document that is not valid JSON, or is not a top-level array, never produces an entry to
    pass it. Checking them only in prose is how a shape that cannot reach the predicate stays
    unchecked, so they are checked here, where a corpus scan actually holds a whole document.

    `path` is quoted in every message so a scan over 464 files names the file, the way the consumer's
    own `Program.cs` does before it returns 1.
    """
    if not isinstance(document, list):
        return (f"{path}: anchor file: expected a top-level array, not "
                f"{type(document).__name__}",)
    out: "list[str]" = []
    for index, row in enumerate(document):
        for violation in csharp_anchor_consumer_violations(row):
            where = row.get("speciesId") if isinstance(row, dict) else None
            label = f"{where}" if isinstance(where, str) and where else f"index {index}"
            out.append(f"{path}: {label}: {violation}")
    return tuple(out)
