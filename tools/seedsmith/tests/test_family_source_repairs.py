"""The family-label SOURCE repairs of 2026-10-04: the placeholder gate, the corroboration-gated
head-noun merge, and the deterministic family fallback.

Every case here is a shape that reached the committed corpus. None of them is hypothetical: the
`ARTEFACT_HEADS` names are the real labels the live 904-species seed carries, and the fallback cases
are the real species whose only family was one of them.
"""
from __future__ import annotations

import pytest

from seedsmith.adapters.creatures.family.consolidate import (
    FamilyCandidateInput,
    attested_grouping_terms,
    canonical_key,
    consolidate,
    head_noun,
    merge_corroborated,
    normalize,
)
from seedsmith.adapters.creatures.family.fallback import (
    SIDE_WORDS,
    family_label_is_artefact,
    resolve_unresolved_family,
)

#: Labels whose head-noun merge would DISCARD a term the corpus already groups by. This is the whole
#: rule: a provable loss. `undead` is a family 30+ species land on; `fauna` is a category noun
#: nothing else uses, and `undead fauna` was throwing the first away to keep the second.
REFUSED_MERGES = {
    "undead fauna": "undead-fauna",
    "undead-fauna": "undead-fauna",
}

#: Merges `_GENERIC_SUFFIXES` exists for (§2.1 rule 2). Losing any of these splits a real family, so
#: they are the control that proves the refusal is a refusal and not a demolition — and four
#: pre-existing `test_family_consolidate.py` cases are the ones that caught the wider version.
KEPT_MERGES = {
    "wall-nut": "nut", "tall-nut": "nut", "defensive-nut": "nut",
    "nut-type": "nut", "ice-attackers": "ice", "fire-based": "fire", "chomper-kin": "chomper",
    "nut-kin": "nut", "sun-producers": "sun", "cryo-botanical": "botanical",
    "fragile-body": "body", "two-headed-shooter": "headed",
    "magical-planthybrid": "planthybrid",
}

CURATED = frozenset({"nut", "pea", "corn", "bucket", "ice", "garlic", "cherry", "sun", "hypno",
                     "cactus", "sunflower", "fruit", "fire", "light", "double", "dolls", "chomper",
                     "base", "line", "academic", "afflicted", "alchemical"})


def _candidate(species_id: str, label: str) -> FamilyCandidateInput:
    return FamilyCandidateInput(species_id=species_id, label=label,
                                native_label=label, basis="text")


# ---------------------------------------------------------------------------------------------
# The corroboration gate
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("label, kept", sorted(REFUSED_MERGES.items()))
def test_a_merge_that_would_discard_a_corroborated_family_term_is_refused(label, kept):
    """The one refusal, stated as the loss it prevents: `undead` is a family 30+ species land on,
    `fauna` is a category noun nothing else uses, and the merge was throwing the first away."""
    # The corpus states `undead` is a family by authoring the bare label; `fauna` it never does.
    attested = attested_grouping_terms([_candidate("a", "undead"), _candidate("b", label)])
    assert "undead" in attested and "fauna" not in attested
    assert merge_corroborated(label, {}, attested) == kept


@pytest.mark.parametrize("label, head", sorted(KEPT_MERGES.items()))
def test_every_undecidable_merge_is_left_exactly_as_spec_section_2_1_left_it(label, head):
    """The control, and it is the important one.

    `cryo-botanical` -> `botanical`, `fragile-body` -> `body`, `two-headed-shooter` -> `headed` and
    `magical-planthybrid` -> `planthybrid` are all still emitted, because deciding otherwise needs to
    know that `botanical`/`body`/`headed` are not family terms, and nothing in this tree knows what a
    word means. The wider version of this rule was built, broke four pre-existing
    `test_family_consolidate.py` cases, and did not even fix these — this parameterisation is what
    says so, so the next reader does not rebuild it.

    `wall-nut` -> `nut` is here for the same reason: a three-candidate corpus corroborates nothing,
    and refusing every uncorroborated head splits a family that has been one since 2026-08-31.
    """
    attested = attested_grouping_terms([_candidate("s", "nut"), _candidate("t", label)])
    assert merge_corroborated(label, {}, attested) == head


def test_a_curated_registry_term_is_read_as_corroboration():
    """`wall-nut` -> `nut` in a corpus where `nut` is the curated family and nothing authored it
    bare — the second committed source, and the one that makes the control above hold on the live
    904-species corpus rather than only on a three-candidate fixture."""
    attested = attested_grouping_terms([_candidate("s", "wall-nut")])
    assert "nut" not in attested
    assert merge_corroborated("undead fauna", {}, attested | {"undead"}) == "undead-fauna"


def test_a_synonym_still_wins_over_the_refusal():
    """§2.1 rule 3 is a human override and must not be second-guessed by a corroboration test."""
    attested = frozenset({"undead"})
    syn = {"shambler": "lurcher", "armor-plated": "shell"}
    assert merge_corroborated("shambler", syn, attested) == "lurcher"
    assert merge_corroborated("armor-plated", syn, attested) == "shell"


def test_canonical_key_is_unchanged_for_a_caller_with_no_corpus():
    """`canonical_key` keeps its original behaviour; the gate is additive and lives in
    `consolidate`/`merge_corroborated`. A caller holding one label and no corpus cannot tell a
    family term from a category noun, and this function does not pretend otherwise."""
    assert canonical_key("cryo-botanical", {}) == "botanical"
    assert canonical_key("wall-nut", {}) == "nut"


def test_consolidate_is_still_a_pure_function_of_its_inputs():
    """§2.1's byte-identical claim, which a corpus-wide gate could have broken by introducing order
    dependence. Two runs over the same candidates in two different input orders must agree."""
    cands = [_candidate("beta", "undead fauna"), _candidate("alpha", "wall-nut"),
             _candidate("gamma", "undead"), _candidate("delta", "tall-nut")]
    one = consolidate(cands, established_terms=CURATED)
    two = consolidate(list(reversed(cands)), established_terms=CURATED)
    assert one.assignments == two.assignments
    assert one.families == two.families
    assert one.assignments["alpha"] == ["nut"]              # the §2.1 merge, intact
    assert one.assignments["beta"] == ["undead-fauna"]     # the refusal, applied


# ---------------------------------------------------------------------------------------------
# The deterministic fallback
# ---------------------------------------------------------------------------------------------

#: The eleven species whose ONLY family was an artefact, the artefact they held, the real grouping
#: each resolves to, and the committed signal that decides it. A derivation nobody can trace is a
#: derivation nobody can trust, so the source is part of the fixture rather than the message.
FALLBACK_CASES = [
    # species, artefact held, committed name tokens, resolved, curated?, source
    ("boatimp", "mech-watercraft", ("boat", "imp"), "imp", False,
     "head-most name word another species groups by"),
    ("bucketplant", "crafting-material", ("bucket", "plant"), "bucket", True,
     "curated families.v1.json id"),
    ("icecorn", "cryo-botanical", ("ice", "corn"), "corn", True,
     "curated id, HEAD-most of the two curated matches — `ice` is the modifier"),
    ("minisnowmonster", "undead-fauna", ("mini", "snow", "monster"), "snow", False,
     "head `monster` groups nothing; the next word `snow` groups 7"),
    ("nuclearsquash", "nuclear-botanical", ("nuclear", "squash"), "squash", False,
     "head-most corroborated name word"),
    ("nutblover", "botanical-talisman", ("nut", "blover"), "nut", True,
     "curated id, not the head `blover`"),
    ("nuttorch", "pyro-botanical", ("nut", "torch"), "nut", True,
     "curated id, not the head `torch`"),
    ("peablover", "projectile-symbiote", ("pea", "blover"), "pea", True,
     "curated id, not the head `blover`"),
    ("peamine", "explosive-legume", ("pea", "mine"), "pea", True,
     "curated id, not the head `mine` — `mine` is an attested label and still the wrong answer"),
    ("peapuff", "sprout-fungi", ("pea", "puff"), "pea", True,
     "curated id, not the head `puff`"),
    ("penguinzombie", "undead-avian", ("penguin", "zombie"), "penguin", False,
     "`zombie` is a SIDE word; `penguin` is grouped by SuperPenguinZombie"),
]

#: The world the fallback reads. `botanical` groups 4 species and is still an artefact, because
#: "does it bucket more than one thing" is not the only question — it also has to BE a family.
OWNERS = {
    "nut": {"nut_a", "nut_b"}, "pea": {"pea_a", "pea_b"}, "corn": {"corn_a", "corn_b"},
    "snow": {"snow_a", "snow_b"}, "squash": {"squash_a", "squash_b"}, "imp": {"imp_a", "imp_b"},
    "torch": {"torch_a"}, "mine": {"mine_a"}, "blover": {"blover_a"},
    "penguin": {"superpenguinzombie"},
    # `botanical` groups FOUR species and is still an artefact, because every one of those four is
    # here only because it is the species under test — which is exactly why the artefact test
    # subtracts the species itself. Two of the eleven held it; the other nine held their own.
    "botanical": {"icecorn", "nuclearsquash", "nuttorch", "peanut"},
}


@pytest.mark.parametrize("species, artefact, tokens, expected, curated, source", FALLBACK_CASES)
def test_each_artefact_only_species_resolves_to_a_real_grouping(
        species, artefact, tokens, expected, curated, source):
    """Acceptance: every one of the eleven, and the committed signal that decides it."""
    assert (expected in CURATED) is curated, \
        f"{species}: the fixture claims this came from {'curated' if curated else 'the corpus'}"
    families, was_deterministic = resolve_unresolved_family(
        [artefact], species_id=species, name_tokens=tokens,
        curated_terms=CURATED, key_owners=OWNERS,
    )
    assert families == [expected], f"{species}: expected {expected!r}, source was {source}"
    assert was_deterministic is True, f"{species}: a fallback that fired must say so"


def test_the_fallback_never_invents_a_family_it_cannot_source():
    """A species whose name words are all side words, all uncorroborated, or all uncurated keeps
    EXACTLY what it had. `aloe` is a real taxon of one species and must come through this untouched —
    a fallback that guesses here is worse than no fallback, because a wrong family is a wrong family
    forever and a missing one is visible."""
    for species, families, tokens in [
        ("aloe", ["aloe"], ("aloe",)),
        ("bucket_zombie_side", ["present"], ("present", "zombie")),
    ]:
        assert resolve_unresolved_family(
            families, species_id=species, name_tokens=tokens,
            curated_terms=CURATED, key_owners={"present": {"other"}},
        ) == (families, False)


def test_the_fallback_does_not_fire_when_one_family_is_already_real():
    """Multi-membership is the corpus's own escape hatch: a species holding one real grouping plus
    one artefact keeps both. Only an ALL-artefact species is repaired."""
    assert resolve_unresolved_family(
        ["nut", "botanical"], species_id="x", name_tokens=("pea",),
        curated_terms=CURATED, key_owners=OWNERS,
    ) == (["nut", "botanical"], False)


def test_a_placeholder_label_is_an_artefact_even_when_other_species_land_on_it():
    """The artefact test is the disjunction of its three clauses, and the placeholder clause comes
    first: no amount of corroboration makes `unnamed plant` a family term."""
    owners = {"unnamed-plant": {"a", "b", "c"}}
    assert family_label_is_artefact(
        "unnamed-plant", key_owners=owners, species_id="a") is True
    assert family_label_is_artefact(
        "nut", key_owners=OWNERS, species_id="nut_a") is False


def test_a_species_is_never_the_reason_its_own_family_looks_corroborated():
    """The per-species set difference. `penguin` is grouped by exactly one other species, which is a
    grouping of two; a species must not be able to corroborate itself into looking like a family."""
    owners = {"solo": {"solo"}}
    assert family_label_is_artefact("solo", key_owners=owners, species_id="solo") is True
    assert family_label_is_artefact("solo", key_owners=owners, species_id="other") is False


def test_the_side_words_are_excluded_by_name_not_by_size():
    """`plant` and `zombie` are the two largest family keys in the corpus and neither is a family —
    they are the SIDE. A size test would pick them; this is why the exclusion is by name."""
    assert SIDE_WORDS == {"plant", "zombie"}
    for side in SIDE_WORDS:
        assert resolve_unresolved_family(
            ["artefact"], species_id="s", name_tokens=(side,),
            curated_terms=CURATED, key_owners={side: {"a", "b", "c"}},
        ) == (["artefact"], False)
