"""Tests for seedsmith.adapters.creatures.anchor.derive (spec-classify-pipelines.md §4).

T2.11's own real 20-species run (2026-09-02) crashed on `clamp_variant_count` the first time a
species' `rarity` vote landed on the documented "two repairs, then unresolved" outcome
(spec-classify-pipelines.md §4) — `derive.py` had never been exercised against that real, anticipated
case before this file existed.
"""
from __future__ import annotations

from seedsmith.adapters.creatures.anchor.derive import (
    clamp_variant_count,
    derive_posture,
    derive_pure,
    derive_rank,
    load_aptitude_fallback,
    load_rank_grid,
    load_rarity_power_fallback,
    resolve_secondary_element_from_fusion_lineage,
    resolve_threat_band,
    resolve_unresolved_aptitude,
    resolve_unresolved_rarity,
    resolve_unresolved_threat_band,
)
from seedsmith.adapters.creatures.anchor.schema import RARITY, THREAT_BAND
from seedsmith.adapters.creatures.power.bands import ThreatTuning, classify, rung_for_score, score
from seedsmith.adapters.creatures.power.model import PowerSeed


def test_truncates_to_the_bands_high_end():
    # sprout: [1, 1] — three offered variants, keep only the model's own first one.
    assert clamp_variant_count(["normal", "ancient", "mutated"], "sprout") == ["normal"]


def test_extends_to_the_bands_low_end_deterministically():
    # fused: [2, 3] — one offered variant, extend with the lowest-ordinal missing one twice run
    # over the same input must extend identically.
    once = clamp_variant_count(["ancient"], "fused")
    twice = clamp_variant_count(["ancient"], "fused")
    assert once == twice
    assert len(once) == 2
    assert "ancient" in once


def test_dedupes_before_clamping():
    assert clamp_variant_count(["normal", "normal"], "sprout") == ["normal"]


def test_unresolved_rarity_passes_variants_through_unclamped():
    # The real bug: rarity's own vote can legitimately land on "unresolved" (two failed repairs,
    # spec §4) — there is no band to clamp against, so this must not crash and must not guess a
    # band. The model's own (deduped) variants pass through as-is.
    result = clamp_variant_count(["normal", "ancient", "normal"], "unresolved")
    assert result == ["normal", "ancient"]


def test_an_unknown_rarity_also_passes_through_rather_than_crashing():
    # Any value absent from the tuning bands (not just the literal "unresolved" string) hits the
    # same no-band-to-clamp-against case — defensive against a future rarity added to the enum
    # before the tuning file catches up, not just the one known string.
    result = clamp_variant_count(["normal"], "not-a-real-rarity")
    assert result == ["normal"]


def test_derive_posture_matches_the_real_catalog_for_a_known_aptitude():
    assert derive_posture("Might") in ("Force", "Finesse", "Bastion")


def test_derive_pure_true_when_no_secondary():
    assert derive_pure("Might", "none") is True


def test_derive_pure_true_when_both_aptitudes_share_a_posture():
    # Might and Fortitude are both Force (schema.py's own APTITUDE_POSTURE).
    assert derive_posture("Might") == derive_posture("Fortitude") == "Force"
    assert derive_pure("Might", "Fortitude") is True


def test_derive_pure_false_when_aptitudes_differ_in_posture():
    # Might is Force, Ferocity is Bastion.
    assert derive_posture("Might") != derive_posture("Ferocity")
    assert derive_pure("Might", "Ferocity") is False


def test_derive_posture_unresolved_aptitude_propagates_rather_than_crashing():
    # The second real bug from the same T2.11 run: aptitudePrimary can itself land on
    # "unresolved" the same way rarity can — a posture cannot be derived from it.
    assert derive_posture("unresolved") == "unresolved"


def test_derive_pure_false_when_primary_aptitude_is_unresolved():
    assert derive_pure("unresolved", "none") is False
    assert derive_pure("unresolved", "Ferocity") is False


def test_derive_pure_false_when_secondary_aptitude_is_unresolved():
    assert derive_pure("Might", "unresolved") is False


# ---- resolve_unresolved_threat_band (2026-09-04, creature-corpus-self-heal F1) ---------------------

def test_a_resolved_threat_band_passes_through_unchanged():
    tuning = ThreatTuning.load()
    value, was_deterministic = resolve_unresolved_threat_band("tyrant", tuning=tuning)
    assert value == "tyrant"
    assert was_deterministic is False


def test_unresolved_threat_band_resolves_to_the_real_sanctioned_default():
    tuning = ThreatTuning.load()
    value, was_deterministic = resolve_unresolved_threat_band("unresolved", tuning=tuning)
    # The exact value the real, committed creature-threat.v1.json names — never invented here.
    assert value == tuning.threshold_for_rung(tuning.inferred_default_rung).id
    assert was_deterministic is True


# ---- resolve_threat_band (threat-band-fill T3: score first, then the sanctioned default) -------


def _observed_seed(toughness: int, damage: int) -> PowerSeed:
    return PowerSeed(
        side="plant", type_id=1, basis="observed", toughness=toughness, damage=damage,
        text_toughness=None, text_damage=None, shot_count=None, interval_ms=None,
        disagreement_toughness=False, disagreement_damage=False)


def test_a_resolved_threat_band_is_authored_not_recomputed():
    tuning = ThreatTuning.load()
    value, provenance = resolve_threat_band("tyrant", _observed_seed(300, 20), tuning=tuning)
    assert (value, provenance) == ("tyrant", "authored")


def test_a_scoreable_seed_is_scored_never_defaulted():
    tuning = ThreatTuning.load()
    seed = _observed_seed(300, 20)
    value, provenance = resolve_threat_band("unresolved", seed, tuning=tuning)
    assert provenance == "scored"
    # The rung `classify` itself computes from this exact seed — the resolver must agree with
    # the scorer, never invent its own answer.
    assert value == classify(seed, tuning).id
    assert value == rung_for_score(score(300, 20, tuning), tuning).id


def test_an_unscorable_basis_falls_to_the_sanctioned_default():
    tuning = ThreatTuning.load()
    inferred = PowerSeed(
        side="plant", type_id=1, basis="inferred", toughness=None, damage=None,
        text_toughness=None, text_damage=None, shot_count=None, interval_ms=None,
        disagreement_toughness=False, disagreement_damage=False)
    value, provenance = resolve_threat_band("unresolved", inferred, tuning=tuning)
    assert provenance == "default"
    assert value == tuning.threshold_for_rung(tuning.inferred_default_rung).id


def test_a_missing_seed_falls_to_the_sanctioned_default():
    tuning = ThreatTuning.load()
    value, provenance = resolve_threat_band("unresolved", None, tuning=tuning)
    assert provenance == "default"
    assert value == tuning.threshold_for_rung(tuning.inferred_default_rung).id


def test_a_missing_field_fills_exactly_like_a_vote_split():
    tuning = ThreatTuning.load()
    seed = _observed_seed(300, 20)
    value, provenance = resolve_threat_band(None, seed, tuning=tuning)
    assert provenance == "scored"
    assert value == classify(seed, tuning).id


def test_an_unresolved_aptitude_fills_from_the_real_fallback_table():
    default = load_aptitude_fallback()
    assert resolve_unresolved_aptitude("unresolved", default=default) == (default, True)
    assert resolve_unresolved_aptitude("Might", default=default) == ("Might", False)


def test_a_BLANK_aptitude_is_treated_exactly_like_the_unresolved_sentinel():
    """Measured 2026-10-04: 41 real entries carried `aptitudePrimary: ""`, written by a `resolve_vote`
    that could not tell three non-answers from three agreements.

    `resolve_vote` now refuses to resolve a blank to a value, so no NEW blank is produced — but the
    41 already written predate that, and a resolver that recognised only the literal `"unresolved"`
    would strand them permanently: the same defect the three-unresolved fix exists to close, reached
    by a different spelling. Blank and `"unresolved"` are the same statement ("no answer came back").

    FAIL-BEFORE: `("", )` was returned unchanged with `was_deterministic=False`, so
    `creatures run fix-unresolved` reported 0 fixes and the 41 entries could not be closed at all.
    """
    default = load_aptitude_fallback()
    for blank in ("", "   ", "\t\n"):
        assert resolve_unresolved_aptitude(blank, default=default) == (default, True), repr(blank)
    # A real answer is still passed through untouched — this is not "anything falsy is unresolved".
    assert resolve_unresolved_aptitude("Agility", default=default) == ("Agility", False)


def test_the_fusion_lineage_resolver_treats_an_ABSENT_secondary_as_no_secondary():
    """`fix-secondary-from-fusion` reads `entry.get("elementSecondary", "none")`, so an ABSENT key
    already arrives here as `"none"` — but 88 real entries had no key at all, and the resolver's own
    guard (`not in ("none", "")`) treated `None` as "already real" and returned it untouched. An
    absent value, `""`, and the literal `"none"` are one statement: no secondary element recorded.

    FAIL-BEFORE: `resolve_secondary_element_from_fusion_lineage(None, "fire",
    input_a_element="ice", input_b_element="fire")` returned `(None, False)`.
    """
    from seedsmith.adapters.creatures.anchor.derive import (
        resolve_secondary_element_from_fusion_lineage as lineage,
    )

    # Exactly one parent differs from the output's primary -> that parent is the real signal.
    for empty in (None, "", "none", "unresolved"):
        assert lineage(empty, "fire", input_a_element="ice", input_b_element="fire") == ("ice", True)
    # Both parents agree with the output: real evidence this species is single-typed, not a gap.
    assert lineage(None, "fire", input_a_element="fire", input_b_element="fire")[1] is False
    # Two disagreeing parents: neither can be trusted, so it is left unresolved, never guessed.
    assert lineage(None, "fire", input_a_element="ice", input_b_element="air")[1] is False
    # An already-real value is never overwritten.
    assert lineage("light", "fire", input_a_element="ice", input_b_element="dark") == (
        "light", False)


# ---- resolve_unresolved_rarity (2026-09-07, creature-corpus-self-heal Phase H, owner-directed) -----
#
# Rarity is this game's OWN mechanism, not an almanac/PvZ property — when the identity pipeline's
# vote never converges, the owner's direction is "stronger species are rarer, fall back to a
# deterministic engine" rather than leave it unresolved forever. The fallback reuses threatBand's
# own already-validated power banding (creature-threat.v1.json) via a rank-preserving correspondence
# (creature-rarity-power-fallback.v1.json), never a second independent curve.

def test_a_resolved_rarity_passes_through_unchanged():
    mapping = load_rarity_power_fallback()
    value, was_deterministic = resolve_unresolved_rarity("fused", "tyrant", mapping=mapping)
    assert value == "fused"
    assert was_deterministic is False


def test_unresolved_rarity_resolves_from_a_resolved_threat_band():
    mapping = load_rarity_power_fallback()
    value, was_deterministic = resolve_unresolved_rarity("unresolved", "calamity", mapping=mapping)
    # calamity is threat rung 10, the top — the committed mapping names its rarity explicitly.
    assert value == mapping["calamity"]
    assert value == "almanac"
    assert was_deterministic is True


def test_unresolved_rarity_stays_unresolved_when_threat_band_has_no_signal_either():
    mapping = load_rarity_power_fallback()
    value, was_deterministic = resolve_unresolved_rarity("unresolved", "unresolved", mapping=mapping)
    assert value == "unresolved"
    assert was_deterministic is False


def test_rarity_power_fallback_is_a_rank_preserving_bijection_over_both_closed_ladders():
    from seedsmith.adapters.creatures.anchor.schema import RARITY, THREAT_BAND

    mapping = load_rarity_power_fallback()
    assert set(mapping.keys()) == set(THREAT_BAND)
    assert set(mapping.values()) == set(RARITY)
    # Rank-preserving: the Nth-weakest threat band maps to the Nth-least-rare rarity.
    assert [mapping[t] for t in THREAT_BAND] == list(RARITY)


# ---- resolve_unresolved_aptitude (2026-09-07, creature-corpus-self-heal Phase I, owner-directed) ---
#
# No real signal exists for aptitude (measured: F≈1.34 over the species with a computable score,
# and 10 of the 11 real unresolved species have no computable score at all) — this is a flat,
# undisguised invented default, not a derivation, on the owner's own explicit direction.

def test_a_resolved_aptitude_passes_through_unchanged():
    value, was_deterministic = resolve_unresolved_aptitude("Bulwark", default="Onslaught")
    assert value == "Bulwark"
    assert was_deterministic is False


def test_unresolved_aptitude_resolves_to_the_flat_default():
    value, was_deterministic = resolve_unresolved_aptitude("unresolved", default="Onslaught")
    assert value == "Onslaught"
    assert was_deterministic is True


def test_aptitude_fallback_names_a_real_aptitude():
    from seedsmith.adapters.creatures.anchor.schema import APTITUDES

    default = load_aptitude_fallback()
    assert default in APTITUDES


# ---- resolve_secondary_element_from_fusion_lineage --------------------------------------------

def test_a_real_secondary_passes_through_unchanged():
    value, was_fixed = resolve_secondary_element_from_fusion_lineage(
        "fire", "earth", input_a_element="earth", input_b_element="fire")
    assert value == "fire"
    assert was_fixed is False


def test_input_b_supplies_a_clean_secondary_when_input_a_matches_the_output():
    value, was_fixed = resolve_secondary_element_from_fusion_lineage(
        "none", "air", input_a_element="air", input_b_element="earth")
    assert value == "earth"
    assert was_fixed is True


def test_input_a_supplies_a_clean_secondary_when_it_is_the_one_that_differs():
    value, was_fixed = resolve_secondary_element_from_fusion_lineage(
        "none", "air", input_a_element="fire", input_b_element="air")
    assert value == "fire"
    assert was_fixed is True


def test_both_parents_matching_the_output_is_real_signal_not_a_gap():
    value, was_fixed = resolve_secondary_element_from_fusion_lineage(
        "none", "light", input_a_element="light", input_b_element="light")
    assert value == "none"
    assert was_fixed is False


def test_both_parents_differing_and_disagreeing_is_left_unresolved():
    value, was_fixed = resolve_secondary_element_from_fusion_lineage(
        "none", "light", input_a_element="earth", input_b_element="dark")
    assert value == "none"
    assert was_fixed is False


def test_missing_lineage_data_is_left_unresolved_rather_than_guessed():
    value, was_fixed = resolve_secondary_element_from_fusion_lineage(
        "none", "fire", input_a_element=None, input_b_element=None)
    assert value == "none"
    assert was_fixed is False


# ---- derive_rank (spec-species-rank.md §1/§2, creature-seed Task 3) --------------------------------
#
# A DERIVED anchor field: deterministic code over the resolved (threatBand, rarity) pair through the
# 10x10 grid in gk-core/data/tuning/creature-rank.v1.json. Nothing votes on it and no model authors it, and
# rank is identity only — it gates and displays, it never prices, scales or contests.

def test_derive_rank_returns_the_grid_cell_for_a_resolved_pair():
    from seedsmith.adapters.creatures.anchor.schema import RANK

    grid = load_rank_grid()
    for threat_band in THREAT_BAND:
        for rarity in RARITY:
            value = derive_rank(threat_band, rarity)
            assert value == grid[(threat_band, rarity)]
            assert value in RANK


def test_derive_rank_propagates_unresolved_on_either_axis():
    # Assumption 4: skip, don't fabricate. An unresolved input never reaches the table.
    assert derive_rank("unresolved", "fused") == "unresolved"
    assert derive_rank("warden", "unresolved") == "unresolved"
    # An ABSENT field is the same semantic category as a vote split — 721 of 906 real anchors
    # carried no threatBand when this was measured (2026-09-20).
    assert derive_rank(None, "fused") == "unresolved"
    assert derive_rank("warden", None) == "unresolved"
    assert derive_rank("", "") == "unresolved"


def test_derive_rank_never_crashes_on_a_pair_outside_the_closed_vocabularies():
    # The grid's own coverage is asserted at load, so this branch only fires for an ANCHOR carrying
    # a value outside the closed vocabulary — reported, never a reason to abort a corpus run.
    assert derive_rank("not-a-rung", "fused") == "unresolved"
    assert derive_rank("warden", "not-a-rarity") == "unresolved"


def test_the_rank_grid_covers_every_pair_of_the_two_declaring_ladders():
    grid = load_rank_grid()
    assert len(grid) == len(THREAT_BAND) * len(RARITY)
    assert set(grid.keys()) == {(t, r) for t in THREAT_BAND for r in RARITY}
    # Every cell holds a real rank id from the closed vocabulary — never a second vocabulary.
    assert set(grid.values()) <= set(RARITY)
    # v1 ships diagonal-by-default: a cell's rank is its own column's rarity rung, so the threat row
    # changes nothing until a balance pass authors an off-diagonal divergence.
    assert all(rank == rarity for (_t, rarity), rank in grid.items())


def test_the_rank_grid_is_a_pure_function_of_its_two_inputs():
    # Determinism is the contract Task 4's byte-identical rerun rests on.
    assert derive_rank("warden", "fused") == derive_rank("warden", "fused")
    assert load_rank_grid() == load_rank_grid()
