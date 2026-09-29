"""Tests for seedsmith.adapters.creatures.anchor.{permute,vote} (spec-option-permutation.md,
creature-seed module 6)."""
from __future__ import annotations

from seedsmith.adapters.creatures.anchor.permute import order_for
from seedsmith.adapters.creatures.anchor.vote import (
    VOTED_FIELDS,
    SetVoteResult,
    VoteRecord,
    VoteResult,
    disagreement_rate,
    resolve_set_vote,
    resolve_vote,
)

ELEMENTS = ["fire", "ice", "air", "earth", "light", "dark"]


def test_same_species_same_order_across_runs():
    a = order_for("peashooter", "elementPrimary", 0, ELEMENTS)
    b = order_for("peashooter", "elementPrimary", 0, ELEMENTS)
    assert a == b


def test_three_samples_have_three_distinct_orders():
    orders = [order_for("peashooter", "elementPrimary", i, ELEMENTS) for i in range(3)]
    assert orders[0] != orders[1]
    assert orders[1] != orders[2]
    assert orders[0] != orders[2]


def test_different_species_get_different_orders():
    a = order_for("peashooter", "elementPrimary", 0, ELEMENTS)
    b = order_for("sunflower", "elementPrimary", 0, ELEMENTS)
    assert a != b


def test_order_is_a_permutation_never_drops_or_duplicates():
    order = order_for("peashooter", "elementPrimary", 0, ELEMENTS)
    assert sorted(order) == sorted(ELEMENTS)
    assert len(order) == len(ELEMENTS)


def test_different_fields_on_same_species_get_different_orders():
    a = order_for("peashooter", "elementPrimary", 0, ELEMENTS)
    b = order_for("peashooter", "aptitudePrimary", 0, ELEMENTS)
    assert a != b


# --- vote resolution -------------------------------------------------------------------------


def test_unanimous_vote_is_high_confidence():
    r = resolve_vote(["fire", "fire", "fire"])
    assert r == VoteResult(value="fire", confidence="high", minority=None)


def test_two_one_split_records_the_minority():
    r = resolve_vote(["fire", "fire", "ice"])
    assert r.value == "fire"
    assert r.confidence == "split"
    assert r.minority == "ice"


def test_three_way_split_is_unresolved_not_first():
    r = resolve_vote(["fire", "ice", "air"])
    assert r.value is None
    assert r.confidence == "unresolved"
    assert r.minority is None


def test_resolve_vote_requires_exactly_three():
    import pytest
    with pytest.raises(ValueError):
        resolve_vote(["fire", "ice"])


def test_vote_set_is_exactly_the_six_named_fields():
    # attackTempo joined 2026-09-04 (creature-corpus-self-heal C1, owner-approved) — kit-shape was the
    # one pipeline never wired into voting, and the real corpus audit found exactly the collapse
    # that predicts (attackTempo entropy 0.00 across 833 real species).
    assert VOTED_FIELDS == frozenset({
        "elementPrimary", "aptitudePrimary", "rarity", "threatBand", "deployMode", "attackTempo",
    })
    assert len(VOTED_FIELDS) == 6


def test_disagreement_rate_is_reported_per_field_and_side():
    records = [
        VoteRecord("p1", "plant", "elementPrimary", resolve_vote(["fire", "fire", "fire"])),
        VoteRecord("p2", "plant", "elementPrimary", resolve_vote(["fire", "fire", "ice"])),
        VoteRecord("z1", "zombie", "elementPrimary", resolve_vote(["fire", "ice", "air"])),
        VoteRecord("z2", "zombie", "elementPrimary", resolve_vote(["fire", "fire", "fire"])),
    ]
    rates = disagreement_rate(records)
    assert rates["elementPrimary"]["plant"] == 0.5   # 1 of 2 disagreed
    assert rates["elementPrimary"]["zombie"] == 0.5  # 1 of 2 disagreed


def test_disagreement_rate_zero_when_everything_unanimous():
    records = [
        VoteRecord("p1", "plant", "rarity", resolve_vote(["chaff", "chaff", "chaff"])),
        VoteRecord("p2", "plant", "rarity", resolve_vote(["sprout", "sprout", "sprout"])),
    ]
    rates = disagreement_rate(records)
    assert rates["rarity"]["plant"] == 0.0


# ---------------------------------------------------------------------------------------------
# resolve_set_vote -- per-MEMBER majority for set-valued fields (added 2026-09-05, SMOKE BATCH
# criterion 2). `resolve_vote` stays the scalar path and is unchanged; these pin the extension.
# ---------------------------------------------------------------------------------------------

def test_set_vote_unanimous_is_high_and_keeps_every_member():
    r = resolve_set_vote([["a", "b"], ["b", "a"], ["a", "b"]])
    assert r.values == ("a", "b")
    assert r.confidence == "high"
    assert r.minority == ()


def test_set_vote_partial_overlap_resolves_instead_of_discarding_a_unanimous_member():
    # THE case the scalar path could not express: flattened to "a|b"/"a|c"/"a|d" this was a
    # 1-1-1 unresolved, throwing away a 3/3 agreement on `a`.
    r = resolve_set_vote([["a", "b"], ["a", "c"], ["a", "d"]])
    assert r.values == ("a",)
    assert r.confidence == "split"
    assert r.minority == ("b", "c", "d")
    assert r.tally["a"] == 3


def test_set_vote_needs_two_samples_for_a_member_never_one():
    r = resolve_set_vote([["a", "solo"], ["a", "b"], ["a", "b"]])
    assert r.values == ("a", "b")
    assert "solo" not in r.values


def test_set_vote_fully_disjoint_is_unresolved_and_value_is_none():
    r = resolve_set_vote([["a"], ["b"], ["c"]])
    assert r.values == ()
    assert r.confidence == "unresolved"
    assert r.value is None


def test_set_vote_a_failed_sample_still_counts_against_the_threshold():
    # Two real samples agreeing out of three is a majority (2 >= 2) -- but the denominator stays
    # three, so it is a `split`, never `high`.
    r = resolve_set_vote([["a"], ["a"], None])
    assert r.values == ("a",)
    assert r.confidence == "split"


def test_set_vote_two_failed_samples_cannot_resolve():
    r = resolve_set_vote([["a"], None, None])
    assert r.confidence == "unresolved"
    assert r.value is None


def test_set_vote_value_and_minority_key_read_like_the_scalar_result():
    r = resolve_set_vote([["b", "a"], ["a", "b"], ["a", "c"]])
    assert r.value == "a|b"
    assert r.minority_key == "c"


def test_set_vote_requires_exactly_the_declared_sample_count():
    try:
        resolve_set_vote([["a"], ["a"]])
    except ValueError:
        return
    raise AssertionError("resolve_set_vote must refuse a wrong sample count")


def test_scalar_resolve_vote_is_untouched_by_the_extension():
    # The extension must not change the scalar path any existing caller depends on.
    assert resolve_vote(["x", "x", "x"]) == VoteResult(value="x", confidence="high", minority=None)
    assert resolve_vote(["x", "y", "z"]).confidence == "unresolved"
