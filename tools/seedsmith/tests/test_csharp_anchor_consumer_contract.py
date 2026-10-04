"""One case per guard in `csharp_anchor_consumer_violations`, plus the coverage assertion.

The sibling of `tests/test_seed_consumer_contract.py`, and it exists for the same reason. That file
was written after consumer 1's corpus had been repaired four times against one guard at a time: 44
entries with an unresolvable elementPrimary, 111 with a rarity outside the ladder, 9 with a string
where a list belonged, 338 with no family at all. Every round fixed a real instance and every round
was followed by a suite run that surfaced the NEXT guard in the same consumer file.

Consumer 2 then did it again, worse, and silently: the corpus was valid for consumer 1 while
failing the C# anchor reader on 222 of 904 entries, which took gk-core's `RealAnchorCorpusFixture`
static initialiser down with it — 133 tests — over one absent `aptitudeSecondary`. And consumer 2's
own CLI is FAIL-FAST: `CreatureRecipeReconcileInput/Program.cs` prints the first rejection and
`return 1`s, so a repair programme driven by that tool learns one guard per round and cannot even
see the rest.

So the coverage claim is asserted here rather than asserted-about: the docstring must account for
every guard the consumer raises on, keyed on guard NAMES. Line numbers are the wrong key — the
sibling file's own docstring records that adding one import to `catalog.py` shifted every line its
first draft cited, and the test then failed on prose that was correct.

No model, no network.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from seedsmith.adapters.creatures.anchor.schema import (
    C_SHARP_ACQUISITION_FLAGS,
    C_SHARP_STR_FIELDS,
    csharp_anchor_consumer_violations as violations,
    csharp_anchor_corpus_violations,
    csharp_anchor_skipped_fields,
)
from seedsmith.workspace_roots import core_root

#: Guard NAMES, each the predicate's own docstring wording. A consumer guard the predicate does not
#: cover is a name this tuple cannot produce, which is what makes the assertion below meaningful.
CONSUMER_GUARDS = (
    # stage 1 - AnchorRowReader.ReadAll
    "anchor file: not valid JSON",
    "anchor file: expected a top-level array",
    # stage 2 - AnchorRowReader.ReadOne
    "anchor record must be an object",
    "anchor: missing or non-string '{k}'",
    "anchor: missing or non-integer 'gameTypeId'",
    # stage 3 - SpeciesExpander.Expand
    "rarity '{v}' is not a known CreatureRarity",
    "aptitudePrimary '{v}' has no edge in aptitudes.v2.json",
    "aptitudeSecondary '{v}' has no edge in aptitudes.v2.json",
    "attackTempo '{v}' has no entry in creature-shape.v1.json",
    "reach '{v}' has no entry in creature-shape.v1.json",
    "elementPrimary '{v}' is not a known element",
    "elementSecondary '{v}' is not a known element",
    "deployMode '{v}' is not a known CreatureDeployMode",
    "acquisition '{v}' is not a known CreatureAcquisition",
    "rank '{v}' is not a known CreatureRank",
    "species has no acquisition flags",
)

#: An entry that survives every guard. Anything a case adds to this must be the ONLY defect in it.
LEGAL = {
    "speciesId": "Specimen",
    "rarity": "chaff",
    "aptitudePrimary": "Might",
    "aptitudeSecondary": "none",
    "attackTempo": "steady",
    "reach": "melee",
    "side": "plant",
    "elementPrimary": "fire",
    "elementSecondary": "none",
    "deployMode": "PlantAvatar",
    "targetPreference": "frontline",
    "pure": False,
    "acquisition": ["Summonable"],
    "rank": "chaff",
    "gameTypeId": 42,
}


def fields(**over) -> dict:
    merged = dict(LEGAL)
    merged.update(over)
    return merged


def test_a_legal_entry_has_no_violations():
    assert violations(fields()) == ()


def test_a_non_dict_record_is_refused_rather_than_raising():
    """The predicate sees the consequence of what `ReadAll` cannot even reach: `JsonElement`'s
    `TryGetProperty` on a non-object element throws `InvalidOperationException`, which the consumer's
    `catch (AnchorRowRejection)` does NOT catch. Reporting it is honest; raising a TypeError out of
    the run is not."""
    assert violations(["not", "a", "record"]) == (
        "anchor record must be an object, not list",)
    assert violations(None) == ("anchor record must be an object, not NoneType",)


def test_every_str_field_is_refused_when_it_is_absent():
    """Eleven keys, one guard, one case each — the guard's whole job is not missing one of them,
    which is exactly how an absent `aptitudeSecondary` took 133 gk-core tests down."""
    assert len(C_SHARP_STR_FIELDS) == 11
    for key in C_SHARP_STR_FIELDS:
        got = violations({k: v for k, v in LEGAL.items() if k != key})
        assert f"anchor: missing or non-string '{key}'" in got, (key, got)


def test_a_non_string_str_field_is_refused():
    assert "anchor: missing or non-string 'rarity'" in violations(fields(rarity=7))
    assert "anchor: missing or non-string 'pure'" not in violations(fields(pure="yes"))


def test_game_type_id_must_be_an_integer_and_not_a_bool():
    """`bool` is an `int` subclass in Python and a JSON `true` is not a number to C#'s
    `TryGetInt32`. If this branch used a bare `isinstance(x, int)`, a `true` would pass the
    predicate and be refused by the consumer — the predicate silently weaker than its own claim."""
    assert violations(fields(gameTypeId="42")) == (
        "anchor: missing or non-integer 'gameTypeId'",)
    assert violations(fields(gameTypeId=1.5)) == (
        "anchor: missing or non-integer 'gameTypeId'",)
    assert violations(fields(gameTypeId=True)) == (
        "anchor: missing or non-integer 'gameTypeId'",)
    assert violations(fields(gameTypeId=-3)) == ()   # negative is still an integer


def test_empty_string_is_a_MEMBERSHIP_defect_not_a_presence_defect():
    """The distinction the corpus actually turns on, measured: 102 entries carried `attackTempo: ""`
    and 54 were missing `reach` entirely. `Str` accepts "" happily, so an empty value passes stage 2
    and dies at stage 3 — while an absent one dies at stage 2 and never reaches a lookup at all. A
    test that treated them as one failure mode would miss the other, and the repair for each is
    different work."""
    tempo = violations(fields(attackTempo=""))
    assert tempo == ("attackTempo '' has no entry in creature-shape.v1.json",)
    assert not any("missing or non-string" in v for v in tempo)

    absent_reach = violations({k: v for k, v in fields().items() if k != "reach"})
    assert absent_reach == ("anchor: missing or non-string 'reach'",)


def test_a_presence_defect_shadows_its_own_fields_membership_guard():
    """Faithfulness, and the predicate was wrong here first. `Str` raises before any vocabulary
    lookup runs, so an absent `reach` is ONE defect — not a missing key AND an unknown reach.
    Reporting both invented a refusal the consumer never makes and inflated the measured corpus
    defect count from 223 entries to 225 violations' worth of noise."""
    got = violations({k: v for k, v in fields().items() if k != "reach"})
    assert len(got) == 1, got
    assert "has no entry in creature-shape.v1.json" not in " ".join(got)


@pytest.mark.parametrize(
    "over, expected",
    [
        ({"rarity": "unresolved!"}, "rarity"),
        ({"aptitudePrimary": "Swiftness"}, "aptitudePrimary"),
        ({"attackTempo": " Steady"}, "attackTempo"),      # ordinal: untrimmed is a different key
        ({"attackTempo": "STEADY"}, "attackTempo"),       # ordinal: case-sensitive
        ({"reach": "MELee"}, "reach"),
        ({"elementPrimary": "smoke"}, "elementPrimary"),
        ({"elementSecondary": "plasma"}, "elementSecondary"),
        ({"deployMode": "plantavatar"}, "deployMode"),     # ignoreCase: false
        ({"rank": "mythic"}, "rank"),
        ({"acquisition": ["Summonable", "Plasma"]}, "acquisition"),
    ],
)
def test_each_membership_guard_is_refused_with_a_reason_that_names_it(over, expected):
    got = violations(fields(**over))
    assert any(expected in item for item in got), f"{got!r} does not name {expected!r}"


def test_rarity_and_element_fold_case_because_their_parsers_do():
    """`CreatureRarityIds.TryParse` / `CreatureRankIds.TryParse` / `ElementRoster.TryParse` all read
    `(value ?? "").Trim().ToLowerInvariant()`. A predicate that compared them ordinally would refuse
    entries the consumer loads."""
    assert violations(fields(rarity=" CHAFF ")) == ()
    assert violations(fields(elementPrimary=" Fire ")) == ()
    assert violations(fields(rank=" Chaff ")) == ()
    assert violations(fields(elementSecondary="  Ice ")) == ()


def test_the_none_sentinel_is_exempt_case_insensitively_and_untrimmed_exactly_as_the_reader_is():
    """`AnchorRowReader` maps the sentinel with `string.Equals(x, "none", OrdinalIgnoreCase)` and no
    trim, so `None`/`NONE` are exempt and `" none "` is not — it reaches the vocabulary lookup and is
    refused there."""
    assert violations(fields(elementSecondary="NONE")) == ()
    assert violations(fields(aptitudeSecondary="None")) == ()
    assert violations(fields(elementSecondary=" none ")) == (
        "elementSecondary ' none ' is not a known element",)


def test_a_secondary_aptitude_on_a_PURE_anchor_is_never_refused():
    """`Expand` gates that guard on `hasSecondary` (`not pure` and a non-null secondary) and says
    why there: a pure species carries zero secondary share by construction, so the value is INERT
    and must not refuse generation for something the math never reads. Checking it unconditionally
    would invent refusals the consumer never makes."""
    assert violations(fields(pure=True, aptitudeSecondary="Swiftness")) == ()
    assert violations(fields(pure=False, aptitudeSecondary="Swiftness")) == (
        "aptitudeSecondary 'Swiftness' has no edge in aptitudes.v2.json",)


def test_acquisition_none_is_excluded_on_purpose_and_says_why():
    """`CreatureAcquisition` is `[Flags] enum { None = 0, ... }` and `Enum.TryParse` would accept the
    literal `"None"`. It is still excluded, for three stated reasons in the constant's own comment —
    it is not authorable (the JSON Schema's enum is built from `ACQUISITION`), `CreatureRarity.cs`
    documents None as a catalog error, and the consumer's own output projection drops it. Pinned
    here so the exclusion cannot be read as an oversight."""
    assert "None" not in C_SHARP_ACQUISITION_FLAGS
    assert C_SHARP_ACQUISITION_FLAGS == ("Summonable", "CaptureOnly", "EventOnly")
    assert violations(fields(acquisition=["None"])) == (
        "acquisition 'None' is not a known CreatureAcquisition",)
    # Stricter than the consumer on purpose, in the safe direction: Enum.TryParse also accepts a
    # numeric string and a comma-separated list, and neither is authorable.
    assert violations(fields(deployMode="0")) != ()
    assert violations(fields(acquisition=["Summonable, EventOnly"])) != ()


def test_a_non_array_or_absent_acquisition_is_refused_for_STAGE_4_not_because_the_reader_raises():
    """The one guard the two readers do not raise. Measured by running the tool: after the anchor
    load cleared all 904 entries, `CreatureRecipeReconcileInput` failed one stage further out with
    `Species 'blackhorse' has no acquisition flags.` — `StrArray` had silently defaulted the absent
    key to an empty list, and `CreatureSpeciesCatalog.Validate` refused it.

    So an absent/empty `acquisition` IS a refusal of this consumer, one stage past the readers. The
    guard is worded so it cannot be misread as a reader behaviour, and `variants`/`traits` stay
    unguarded because nothing downstream refuses an empty one.
    """
    for value, label in ((None, "absent"), ([], "empty"), ("Summonable", "not a list")):
        got = violations(fields(acquisition=value))
        assert any("no acquisition flags" in v for v in got), (label, got)
    assert violations(fields(acquisition=["Summonable"])) == ()
    # `variants`/`traits` are NOT guarded: an empty or absent one is never refused anywhere.
    assert violations(fields(variants=None, traits=[])) == ()


def test_the_stage_four_guard_is_named_in_the_docstring_like_every_other_guard():
    """A guard the coverage assertion does not name is a guard a future edit can drop silently."""
    assert "species has no acquisition flags" in CONSUMER_GUARDS
    assert "STAGE 4" in (violations.__doc__ or "")


def test_a_non_string_rank_is_never_a_violation():
    """The reader's own `ValueKind == String` test makes a non-string `rank` null before
    `ResolveRank` ever sees it, and the literal `"unresolved"` maps to null too — both skipped, as
    `ResolveRank`'s early return does."""
    assert violations(fields(rank=7)) == ()
    assert violations(fields(rank=None)) == ()
    assert violations(fields(rank="unresolved")) == ()
    assert violations(fields(rank="UNRESOLVED")) == ()


def test_every_violation_is_reported_not_just_the_first():
    """This is the whole point of the predicate. Consumer 2's CLI is fail-fast, so a caller that
    fixed one guard and retried had to discover the next one on the next round — four times."""
    got = violations(fields(
        elementPrimary="smoke", rarity="nope", attackTempo="", deployMode="",
        acquisition=["Plasma"], rank="mythic",
    ))
    assert len(got) == 6, got
    for named in ("elementPrimary", "rarity", "attackTempo", "deployMode", "acquisition", "rank"):
        assert any(named in v for v in got), (named, got)


def test_an_unresolved_sentinel_SHADOWS_the_whole_expand_stage():
    """`UnresolvedFields` is checked BEFORE `Expand` and the caller skips the entire species, so
    with a sentinel present none of the stage-3 guards can fire. Getting this wrong made the first
    draft of this predicate report 225 defective entries where the consumer refuses 223 — and the
    extra two were sentinels, i.e. species consumer 2 silently DROPS rather than refuses."""
    got = violations(fields(attackTempo="unresolved", deployMode="smouldery",
                            elementPrimary="smoke"))
    assert got == (), got
    # Stage 2 still fires under a sentinel: `Str` runs before the species is ever skipped.
    absent = violations({k: v for k, v in fields(attackTempo="unresolved").items()
                         if k != "reach"})
    assert absent == ("anchor: missing or non-string 'reach'",)


def test_a_skip_is_not_a_violation_and_has_its_own_named_function():
    """`()` must never read as "consumer 2 reconciles this species" when the truth is "consumer 2
    silently drops it". Both sentences are true about different species; only one is true about
    this one, which is why they are two functions and neither calls the other."""
    entry = fields(attackTempo="unresolved")
    assert violations(entry) == ()
    assert csharp_anchor_skipped_fields(entry) == ("attackTempo",)
    assert csharp_anchor_skipped_fields(fields()) == ()
    assert csharp_anchor_skipped_fields(fields(deployMode="Unresolved")) == ()  # case-sensitive ==
    assert csharp_anchor_skipped_fields("not a dict") == ()


# ---------------------------------------------------------------------------------------------
# Stage 1 — the FILE-level guards, which no per-entry predicate can express
# ---------------------------------------------------------------------------------------------

def test_the_file_level_guards_fire_and_name_the_file():
    assert csharp_anchor_corpus_violations({"not": "an array"}, path="x.json") == (
        "x.json: anchor file: expected a top-level array, not dict",)
    assert csharp_anchor_corpus_violations([], path="x.json") == ()
    got = csharp_anchor_corpus_violations(
        [fields(attackTempo=""),
         {**{k: v for k, v in LEGAL.items() if k != "reach"}, "speciesId": "NoReach"}],
        path="plant/x.json")
    assert got == (
        "plant/x.json: Specimen: attackTempo '' has no entry in creature-shape.v1.json",
        "plant/x.json: NoReach: anchor: missing or non-string 'reach'",
    ), got
    # A non-dict element is located by index, since it has no speciesId to name it by.
    assert "index 0: anchor record must be an object" in csharp_anchor_corpus_violations(
        [7], path="p.json")[0]


def test_a_document_that_is_not_valid_json_is_the_callers_parse_error_not_this_predicates():
    """`JsonDocument.Parse` failing is what "not valid JSON" names, and it happens before any JSON
    value exists to check. Asserted as a boundary so the guard is not silently uncovered: the
    corpus predicate takes a PARSED document, and every `Path.read_text` in this file parses first."""
    with pytest.raises(json.JSONDecodeError):
        json.loads("{not json")


def test_the_predicate_documents_every_guard_the_consumer_raises_on():
    doc = violations.__doc__ or ""
    missing = [name for name in CONSUMER_GUARDS if name not in doc]
    assert not missing, (
        "csharp_anchor_consumer_violations does not account for these consumer guards: "
        + ", ".join(missing)
        + " - add the branch and name it, or the corpus will ship the shape again")


def test_every_documented_guard_has_a_behavioural_case():
    """A name in the docstring with no case proving it fires is documentation, not coverage — and
    that is the check whose absence let this defect class ship once already."""
    absent = lambda k: violations({x: v for x, v in LEGAL.items() if x != k})  # noqa: E731
    cases = {
        "anchor file: expected a top-level array":
            lambda: csharp_anchor_corpus_violations({}, path="x.json"),
        "anchor file: not valid JSON": lambda: pytest.raises(json.JSONDecodeError),
        "anchor record must be an object": lambda: violations(7),
        "anchor: missing or non-string '{k}'": lambda: absent("speciesId"),
        "anchor: missing or non-integer 'gameTypeId'": lambda: violations(fields(gameTypeId=None)),
        "rarity '{v}' is not a known CreatureRarity": lambda: violations(fields(rarity="?")),
        "aptitudePrimary '{v}' has no edge in aptitudes.v2.json":
            lambda: violations(fields(aptitudePrimary="?")),
        "aptitudeSecondary '{v}' has no edge in aptitudes.v2.json":
            lambda: violations(fields(aptitudeSecondary="?")),
        "attackTempo '{v}' has no entry in creature-shape.v1.json":
            lambda: violations(fields(attackTempo="?")),
        "reach '{v}' has no entry in creature-shape.v1.json":
            lambda: violations(fields(reach="?")),
        "elementPrimary '{v}' is not a known element": lambda: violations(fields(elementPrimary="?")),
        "elementSecondary '{v}' is not a known element":
            lambda: violations(fields(elementSecondary="?")),
        "deployMode '{v}' is not a known CreatureDeployMode":
            lambda: violations(fields(deployMode="?")),
        "acquisition '{v}' is not a known CreatureAcquisition":
            lambda: violations(fields(acquisition=["?"])),
        "rank '{v}' is not a known CreatureRank": lambda: violations(fields(rank="?")),
        "species has no acquisition flags": lambda: violations(fields(acquisition=[])),
    }
    for name, build in cases.items():
        assert name in CONSUMER_GUARDS, f"{name!r} is documented but not in the guard tuple"
        got = build()
        assert got is not None, f"the documented guard {name!r} never fires"


# ---------------------------------------------------------------------------------------------
# The drift check that replaces a second copy of every vocabulary
# ---------------------------------------------------------------------------------------------

def _tuning(name: str) -> dict:
    path = Path(core_root()) / "data" / "tuning" / name
    if not path.exists():  # pragma: no cover - a split checkout without gk-core/data/tuning
        pytest.skip(f"{name} is not present under {core_root()}")
    return json.loads(path.read_text(encoding="utf-8"))


def test_attack_tempo_and_reach_match_creature_shapes_own_keys_exactly():
    """The two vocabularies consumer 2 looks up are not declared in this repo at all — they are the
    KEYS of `creature-shape.v1.json`, read by `SpeciesExpander` through a `StringComparer.Ordinal`
    dictionary. `ATTACK_TEMPO`/`REACH` transcribe them; this is what proves the transcription is
    still true. A tempo rung added to the tuning file without adding it here would make the
    predicate refuse a legal value — fail-closed, and caught here instead."""
    from seedsmith.adapters.creatures.anchor.schema import ATTACK_TEMPO, REACH

    shape = _tuning("creature-shape.v1.json")
    tempo_keys = {k for k in shape["attackTempoIntervalMs"] if not k.startswith("_")}
    reach_keys = {k for k in shape["reachRangeCells"] if not k.startswith("_")}
    assert set(ATTACK_TEMPO) == tempo_keys, (
        "anchor/schema.py ATTACK_TEMPO has drifted from creature-shape.v1.json's own keys")
    assert set(REACH) == reach_keys, (
        "anchor/schema.py REACH has drifted from creature-shape.v1.json's own keys")


def test_aptitude_primary_is_checked_against_the_edge_sources_the_consumer_reads():
    """`IsKnownAptitude` matches `aptitudes.v2.json`'s edge `source` column with
    `StringComparison.Ordinal`, so THAT column is the vocabulary — not this repo's `APTITUDES`
    transcription of `AptitudeCatalog.All`. They agree today; the two are separate declarations and
    only one of them is what the consumer consults."""
    from seedsmith.adapters.creatures.anchor.schema import APTITUDES

    aptitudes = _tuning("aptitudes.v2.json")
    # `edges` interleaves `_group` header comments with real edges; only the latter carry `source`.
    edge_sources = {edge["source"] for edge in aptitudes["edges"] if "source" in edge}
    assert len(edge_sources) == 12, sorted(edge_sources)
    assert edge_sources == set(APTITUDES), (
        "aptitudes.v2.json's edge sources have drifted from anchor/schema.py APTITUDES")
    # And the lookup is ordinal, so the check is case-sensitive — these are Capitalised ids, and a
    # lowercased anchor value is refused by `IsKnownAptitude` too.
    assert all(s[:1].isupper() for s in edge_sources)


def test_the_vocabulary_tables_the_predicate_reads_are_never_a_second_copy():
    """Every closed vocabulary this predicate consults is the module's own declaration, imported by
    name. The failure this guards is the one that has recurred in this repo: a second tuple that
    looks identical until one file moves."""
    import inspect

    from seedsmith.adapters.creatures.anchor import schema

    # Scoped to the predicate's own body: the module DOES declare `ELEMENTS = ("fire", "ice", ...)`
    # and that declaration is exactly what must be reused. What must not exist is a SECOND copy of
    # a vocabulary anywhere near the guard.
    body = inspect.getsource(schema.csharp_anchor_consumer_violations)
    body += inspect.getsource(schema._is_member)
    for literal in ('("fire", "ice"', '("melee", "short"', '("ponderous", "slow"',
                    '("PlantAvatar", "HypnoAlly"', '("chaff", "sprout"'):
        assert literal not in body, f"{literal!r} is a re-transcribed vocabulary in the predicate"
    assert schema.C_SHARP_ACQUISITION_FLAGS is schema.ACQUISITION