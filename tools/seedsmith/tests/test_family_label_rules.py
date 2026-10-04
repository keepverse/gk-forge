"""Tests for `creatures/family/label_rules.py` — the predicate behind "a family label must group
something, because it becomes an action namespace key".

**What these tests assert, and why it is not a count.** Per `docs/architecture/validation-ssot.md` §1
a guardrail validates a contract and closed enums, never a population count: the corpus grows every
time a species ships, so a pinned 509 would fail for the corpus doing its job and the "fix" would be
to edit the number. Every assertion here is therefore an invariant — the five classes partition the
vocabulary, every rejected class holds at most one species, no species resolves to an empty family
set, every derived id is a legal namespace key — which holds whatever the corpus grows to.

The synthetic fixtures build a candidate set that contains a known instance of each class, so each
test names the defect it exists to catch rather than asserting that "the current data looks right".

No model, no network. The corpus half is read-only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from seedsmith.adapters.creatures.family.consolidate import FamilyCandidateInput, consolidate
from seedsmith.adapters.creatures.family.label_rules import (
    CLASS_A,
    CLASS_B,
    CLASS_C,
    CLASS_D,
    CLASS_E,
    CLASS_NAMES,
    FALLBACK_FIELD,
    REJECTED_CLASSES,
    camel_tokens,
    census,
    classify_family,
    classify_vocabulary,
    derive_vetted_assignments,
    fallback_family,
    identity_echo_of,
    is_placeholder_label,
    rejected_labels,
    walk_back_head,
)
from seedsmith.ladders import normalize_family_key
from seedsmith.workspace_roots import content_root


def C(species_id: str, label: str) -> FamilyCandidateInput:
    return FamilyCandidateInput(species_id=species_id, label=label, native_label=label, basis="text")


def ids_of(candidates) -> "dict[str, str]":
    """Authored label -> the family id `consolidate` gives it, for these candidates.

    **Why the tests never hardcode a family id.** `consolidate` owns the mapping from a label to an
    id, and it is free to change it — its head-noun merge is corroborated by the candidate set, so
    the same label can reduce to `nut` in one corpus and stay `nut-shooter` in another. A test that
    spelled `headed` or `entry` would therefore be asserting `consolidate`'s behaviour while claiming
    to test this module, and would fail for a change that is none of its business. Every assertion
    below names the label it means and looks the id up.
    """
    out: "dict[str, str]" = {}
    for family_id, record in consolidate(candidates).families.items():
        for label in (record.get("nativeLabels") or []):
            out[str(label)] = family_id
    return out


def class_of(candidates, label: str) -> str:
    """The class `label`'s consolidated id receives, for this candidate set."""
    family_id = ids_of(candidates)[label]
    return classify_vocabulary(candidates)[family_id].klass


def species_root() -> Path:
    return content_root() / "data" / "seed" / "creatures" / "species"


def load_committed_records() -> "list[dict]":
    """Every committed species record, read exactly as `catalog.load_live_records` shapes them."""
    out: "list[dict]" = []
    seen: "set[str]" = set()
    for path in sorted(species_root().rglob("*.json")):
        if path.name == "_index.json":
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for entry in (payload if isinstance(payload, list) else [payload]):
            if not isinstance(entry, dict):
                continue
            raw = entry.get("speciesId")
            sid = str(raw).strip().lower()
            if not sid or sid in seen:
                continue
            seen.add(sid)
            out.append({**entry, "speciesId": sid})
    assert out, f"{species_root()} yielded no species records — the corpus half is not a no-op"
    return out


# =================================================================================================
# Class A — placeholder-derived
# =================================================================================================


def test_placeholder_label_is_recognised():
    assert is_placeholder_label("placeholder entry")
    assert is_placeholder_label("unnamed plant")
    assert not is_placeholder_label("explosive-fungus")


def test_a_family_fed_only_by_placeholder_labels_is_class_a():
    """`placeholder entry` is the corpus's own instance: it holds exactly one species."""
    candidates = [C("refrash", "placeholder entry")]
    assert class_of(candidates, "placeholder entry") == CLASS_A
    assert classify_vocabulary(candidates)[ids_of(candidates)["placeholder entry"]].rejected


def test_one_placeholder_label_among_many_real_ones_does_not_condemn_the_family():
    """The guard on the guard.

    `plant` is fed by ~200 real labels AND by `placeholder plant` / `unnamed plant`. A test that
    asked "does ANY feeding label carry a placeholder?" would classify `plant` — a 391-member family,
    the largest in the corpus — as an artefact and delete it. The class is A only when EVERY feeding
    label is a placeholder.

    The bare `plant` label is load-bearing and the precondition is asserted below rather than
    assumed: without a label that stands for the family on its own, `consolidate` may legitimately
    keep `explosive plant` and `unnamed plant` as two separate ids, and then there is no shared
    family for the question to arise in — the fixture would pass against the `any()` mutant for the
    wrong reason. That is not hypothetical: it is what this test did before the precondition was
    asserted, and the mutation control caught it.
    """
    labels = ["plant", "explosive plant", "defensive plant", "unnamed plant", "placeholder plant"]
    candidates = [C(f"s{i}", label) for i, label in enumerate(labels)]
    verdicts = classify_vocabulary(candidates)
    plant_id = ids_of(candidates)["explosive plant"]

    feeding = verdicts[plant_id].raw_labels
    assert set(feeding) == set(labels), f"the fixture no longer builds one shared family: {feeding}"
    assert any(is_placeholder_label(v) for v in feeding), "no placeholder label reaches the family"
    assert any(not is_placeholder_label(v) for v in feeding), "no real label reaches the family"

    assert verdicts[plant_id].klass != CLASS_A
    assert not verdicts[plant_id].rejected


# =================================================================================================
# Class B — identity echo
# =================================================================================================


def test_camel_tokens_splits_the_games_own_humps():
    assert camel_tokens("PeaMine") == ["pea", "mine"]
    assert camel_tokens("GnomeZombie2") == ["gnome", "zombie", "2"]
    assert camel_tokens("UltimatePaperZombie") == ["ultimate", "paper", "zombie"]


def test_a_name_initial_is_class_b():
    """`ultimate Professor Z` reduces to `z`. The corpus's own instance.

    Asserted on `classify_family` rather than through `consolidate`, because class B is a relation
    between an ID and the species' own name — it is decided on the id, and no other module's choice
    of id can change the answer.
    """
    assert identity_echo_of("z", "UltimatePaperZombie") == "name-initial"
    verdict = classify_family("z", raw_labels=["ultimate Professor Z"],
                              species=["UltimatePaperZombie"], group_size=1)
    assert verdict.klass == CLASS_B
    assert verdict.rejected


def test_an_id_echo_is_class_b():
    assert identity_echo_of("cattail", "CattailGirl") == "id-echo"
    assert identity_echo_of("plant", "Peashooter") is None
    verdict = classify_family("cattail", raw_labels=["cattail"],
                              species=["HypnoCattailGirl"], group_size=1)
    assert verdict.klass == CLASS_B


def test_the_id_echo_needs_the_committed_casing():
    """`hypnocattailgirl` is ONE token and `HypnoCattailGirl` is three. A caller that hands the
    canonical lower-cased id to the echo test gets a silent `None` and a class B that only ever
    catches name-initials — a detector that looks present and is not."""
    assert identity_echo_of("cattail", "HypnoCattailGirl") == "id-echo"
    assert identity_echo_of("cattail", "hypnocattailgirl") is None


def test_the_derivation_carries_the_committed_casing_into_the_echo_test():
    """`derive_vetted_assignments` must not lose the humps by canonicalising the id it passes on."""
    report = derive_vetted_assignments([{
        "speciesId": "HypnoCattailGirl", "family": ["cattail"], FALLBACK_FIELD: "zombie",
    }])
    verdicts = report.verdicts
    echoed = [v for v in verdicts.values() if v.klass == CLASS_B]
    assert echoed, "the committed casing never reached identity_echo_of"
    assert echoed[0].species == ("HypnoCattailGirl",)


def test_a_name_echo_that_groups_several_species_is_legitimate():
    """`squash` is `Squash`'s own name AND a real seven-member family. Grouping is the rule, not
    provenance — dropping it would delete a family the next squash belongs to."""
    verdict = classify_family("squash", raw_labels=["squash", "melon squash"],
                              species=["squash", "squashpumpkin", "squashkelp", "squashnut"],
                              group_size=4)
    assert verdict.klass != CLASS_B
    assert not verdict.rejected


# =================================================================================================
# Class C — walk-back artefact
# =================================================================================================


def test_walk_back_head_reports_only_a_promoted_modifier():
    assert walk_back_head("two-headed-shooter") == "headed"
    assert walk_back_head("fragile-body") is None      # `body` is already the last token
    assert walk_back_head("nut") is None


def test_a_walk_back_artefact_is_class_c():
    candidates = [C("lanternsplit", "two-headed-shooter")]
    assert class_of(candidates, "two-headed-shooter") == CLASS_C
    assert classify_vocabulary(candidates)[ids_of(candidates)["two-headed-shooter"]].rejected


def test_a_walk_back_that_groups_several_species_is_legitimate():
    """`nut-shooter` promotes `nut` past the generic `shooter` and that is CORRECT — `nut` is a
    36-member family. A test that flagged every forced walk-back would delete `nut`, `shroom` (48),
    `ranged` (23) and `shooter` itself. This is the mutant that makes the naive version wrong."""
    candidates = [C(f"nut{i}", "nut-shooter") for i in range(4)]
    verdicts = classify_vocabulary(candidates)
    nut_id = ids_of(candidates)["nut-shooter"]
    assert verdicts[nut_id].klass != CLASS_C
    assert verdicts[nut_id].group_size == 4


# =================================================================================================
# The partition itself
# =================================================================================================


def test_the_five_classes_partition_the_vocabulary():
    """`classify_family` is total and single-valued, and every declared class is reachable.

    A class with no case here is a branch nothing exercises, which is how a predicate rots into
    one that reports 0 for a class it should never report. Driven through `classify_family` because
    that is the decision itself — the ids are given, so nothing depends on how `consolidate` chose
    them.
    """
    cases = [
        ("entry", ["placeholder entry"], ["refrash"], 1, CLASS_A),
        ("z", ["ultimate Professor Z"], ["UltimatePaperZombie"], 1, CLASS_B),
        ("headed", ["two-headed-shooter"], ["lanternsplit"], 1, CLASS_C),
        ("aloe", ["aloe"], ["lotusaloes"], 1, CLASS_D),
        ("nut", ["nut", "defensive nut"], ["wallnut", "tallnut"], 2, CLASS_E),
    ]
    seen: "set[str]" = set()
    for family_id, raw_labels, species, group_size, expected in cases:
        verdict = classify_family(family_id, raw_labels=raw_labels, species=species,
                                  group_size=group_size)
        assert verdict.klass == expected, f"{family_id}: {verdict.klass} != {expected} ({verdict.reason})"
        seen.add(verdict.klass)
    assert seen == set(CLASS_NAMES)


def test_every_class_name_has_a_human_readable_name():
    for klass, name in CLASS_NAMES.items():
        assert name and name.islower() and " " not in name, klass


def test_census_counts_every_id_exactly_once():
    candidates = [C("refrash", "placeholder entry"), C("wallnut", "nut"), C("tallnut", "nut")]
    verdicts = classify_vocabulary(candidates)
    counted = census(verdicts)
    assert sum(counted.values()) == len(verdicts)
    assert counted[CLASS_A] == 1 and counted[CLASS_E] == 1


def test_only_a_b_and_c_are_rejected():
    """D is an under-populated real category and E is a family that groups. Neither is a defect, and
    refusing either would delete vocabulary the corpus still needs."""
    assert REJECTED_CLASSES == frozenset({CLASS_A, CLASS_B, CLASS_C})
    assert CLASS_D not in REJECTED_CLASSES and CLASS_E not in REJECTED_CLASSES


def test_every_rejected_class_holds_at_most_one_species():
    """The rule, asserted over whatever the corpus currently holds: a rejected id is rejected
    BECAUSE it groups nothing, so an id that groups two species must never be in a rejected class."""
    verdicts = classify_vocabulary([
        C("a", "placeholder entry"), C("b", "ultimate Professor Z"), C("c", "two-headed-shooter"),
        C("d", "nut-shooter"), C("e", "defensive-nut"), C("f", "wall-nut"),
    ])
    for verdict in verdicts.values():
        if verdict.rejected:
            assert verdict.group_size <= 1, f"{verdict.family_id} is rejected but groups " \
                                            f"{verdict.group_size} species"


def test_classification_is_a_pure_function_of_the_candidate_set():
    candidates = [C("a", "placeholder entry"), C("b", "nut-shooter"), C("c", "defensive-nut")]
    assert classify_vocabulary(candidates) == classify_vocabulary(candidates)


# =================================================================================================
# Rejecting the labels
# =================================================================================================


def test_rejected_labels_keeps_the_kept_candidates_and_reports_why():
    candidates = [C("refrash", "placeholder entry"), C("wallnut", "nut"), C("tallnut", "nut")]
    verdicts = classify_vocabulary(candidates)
    kept, refused = rejected_labels(candidates, verdicts)
    assert sorted(c.label for c in kept) == ["nut", "nut"]
    assert refused == {ids_of(candidates)["placeholder entry"]: ["placeholder entry"]}


# =================================================================================================
# The deterministic fallback
# =================================================================================================


def record(**over) -> dict:
    base = {"speciesId": "Refrash", "family": ["placeholder entry"], FALLBACK_FIELD: "plant"}
    base.update(over)
    return base


def test_the_fallback_is_the_species_own_committed_taxonomy():
    assert fallback_family({"speciesId": "X", FALLBACK_FIELD: "plant"}) == "plant"
    assert fallback_family({"speciesId": "X", FALLBACK_FIELD: " Zombie "}) == "zombie"


def test_the_fallback_never_returns_an_empty_or_illegal_key():
    """It goes through the consumer's own `normalize_family_key`, so the result is a legal action
    namespace key by construction rather than by a second normalisation."""
    key = fallback_family({"speciesId": "X", FALLBACK_FIELD: "Bone Wall"})
    assert key == normalize_family_key(key) and key


def test_the_fallback_fails_closed_by_name_when_there_is_no_taxonomy():
    with pytest.raises(ValueError, match="fall back to"):
        fallback_family({"speciesId": "X", FALLBACK_FIELD: "  "})
    with pytest.raises(ValueError, match="fall back to"):
        fallback_family({"speciesId": "X"})


def test_a_species_whose_every_label_is_an_artefact_resolves_to_the_fallback():
    report = derive_vetted_assignments([record()])
    assert report.assignments == {"refrash": ["plant"]}
    assert report.fell_back == ("refrash",)


def test_a_species_with_no_family_field_at_all_resolves_instead_of_raising():
    """The property behind removing the loader's `has no family` raise: an empty family set is
    resolved, never raised, because raising turns one cosmetic label into a whole-corpus load
    failure."""
    report = derive_vetted_assignments([
        {"speciesId": "EmptyOne", "family": [], FALLBACK_FIELD: "zombie"},
        {"speciesId": "BlankOne", "family": ["", "   "], FALLBACK_FIELD: "zombie"},
        {"speciesId": "AbsentOne", FALLBACK_FIELD: "zombie"},
    ])
    assert report.assignments == {"absentone": ["zombie"], "blankone": ["zombie"],
                                  "emptyone": ["zombie"]}
    assert report.fell_back == ("absentone", "blankone", "emptyone")


def test_the_fallback_only_fires_when_the_filter_emptied_the_set():
    report = derive_vetted_assignments([
        record(family=["placeholder entry", "nut"]),
    ])
    assert report.assignments == {"refrash": ["nut"]}
    assert report.fell_back == ()


def test_the_fallback_is_repeatable():
    one = derive_vetted_assignments([record()])
    two = derive_vetted_assignments([record()])
    assert one.assignments == two.assignments
    assert one.fell_back == two.fell_back


# =================================================================================================
# Over the committed corpus — read-only
# =================================================================================================


@pytest.fixture(scope="module")
def corpus_report():
    return derive_vetted_assignments(load_committed_records())


def test_no_class_abc_id_survives_into_the_derived_output(corpus_report):
    """The whole point of the change, asserted on the corpus rather than on a fixture: an id this
    module calls an artefact can never come out of the derivation."""
    derived = {f for families in corpus_report.assignments.values() for f in families}
    leaked = sorted(
        f for f in derived
        if f in corpus_report.verdicts and corpus_report.verdicts[f].klass in REJECTED_CLASSES)
    assert leaked == [], f"artefact family ids reached the derived output: {leaked}"


def test_no_species_resolves_to_an_empty_family_set(corpus_report):
    """The invariant `catalog.derive_live_family_assignments` turns into a hard load failure."""
    empty = sorted(sid for sid, families in corpus_report.assignments.items() if not families)
    assert empty == [], f"species with no family at all: {empty}"


def test_every_species_in_the_corpus_is_still_assigned(corpus_report):
    ids = {r["speciesId"] for r in load_committed_records()}
    assert set(corpus_report.assignments) == ids


def test_every_derived_id_is_a_legal_action_namespace_key(corpus_report):
    for species_id, families in corpus_report.assignments.items():
        for family in families:
            assert normalize_family_key(family) == family, f"{species_id}: {family!r}"


def test_the_fallback_only_ever_uses_committed_vocabulary(corpus_report):
    """A fallback id is a family the corpus already groups by, so the fallback adds no new key to
    the action namespace."""
    derived = {f for families in corpus_report.assignments.values() for f in families}
    for species_id in corpus_report.fell_back:
        for family in corpus_report.assignments[species_id]:
            assert family in derived


def test_the_derivation_is_deterministic_over_the_corpus():
    records = load_committed_records()
    first = derive_vetted_assignments(records)
    second = derive_vetted_assignments(records)
    assert first.assignments == second.assignments
    assert first.fell_back == second.fell_back
    assert first.refused == second.refused


def test_census_covers_the_whole_committed_vocabulary(corpus_report):
    counted = census(corpus_report.verdicts)
    assert sum(counted.values()) == len(corpus_report.verdicts)
    assert set(counted) == set(CLASS_NAMES)
