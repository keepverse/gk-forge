"""Tests for seedsmith.adapters.creatures.power.bands (spec-threat-band.md, creature-seed module 4)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from seedsmith.adapters.creatures.power.bands import (
    ThreatTuning,
    UnoccupiedRung,
    classify,
    histogram,
    rung_for_score,
    score,
)
from seedsmith.adapters.creatures.power.model import PowerSeed
from seedsmith.ladders import RARITY_LADDER

BANDS_SRC = Path(__file__).parents[1] / "seedsmith" / "adapters" / "creatures" / "power" / "bands.py"

# The rarity ladder's declaring read (tier-propagation-contract T-2) — the ladder threat-band's
# own vocabulary must never rhyme with it (Q11). Referenced, never re-transcribed.
RARITY_WORDS = set(RARITY_LADDER)


@pytest.fixture(scope="module")
def tuning() -> ThreatTuning:
    return ThreatTuning.load(1)


def seed(basis: str, toughness: "int | None" = None, damage: "int | None" = None) -> PowerSeed:
    return PowerSeed(
        side="plant", type_id=1, basis=basis, toughness=toughness, damage=damage,
        text_toughness=None, text_damage=None, shot_count=None, interval_ms=None,
        disagreement_toughness=False, disagreement_damage=False)


def test_no_threshold_literal_in_code(tuning: ThreatTuning):
    """Scans the actual AST — real code constants, never text inside a docstring or comment —
    for every distinctive threshold value the tuning table carries. `0`/`1`/`1000`/`6` are
    excluded: they are structural (the "no signal" default, the loader's own default version arg,
    the divide-by-1000-once rule, and the `parents[]` depth to the repo root), not balance
    numbers, and 0 coincides with rung 1's own `thetaOffset` — a real ambiguity, not a bug in this
    check. Every other threshold value is distinctive enough that finding it in code is real
    evidence of a hardcoded threshold."""
    structural_allowlist = {0, 1, 1000, 6}
    forbidden = set()
    for t in tuning.thresholds:
        if t.max_score is not None:
            forbidden.add(t.max_score)
        forbidden.add(t.theta_offset)
    forbidden -= structural_allowlist

    tree = ast.parse(BANDS_SRC.read_text(encoding="utf-8"))
    code_ints = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, int) and not isinstance(node.value, bool)
    }
    leaked = forbidden & code_ints
    assert not leaked, f"threshold literals hardcoded in bands.py's code: {leaked} — they must live only in tuning"


def test_rung_is_monotonic_in_score(tuning: ThreatTuning):
    scores = [0, 6, 12, 13, 24, 25, 120, 432, 720, 4920, 4921, 1_000_000]
    rungs = [rung_for_score(s, tuning).rung for s in scores]
    assert rungs == sorted(rungs), "a higher score must never yield a lower rung"


def test_boundary_scores_land_on_the_named_rung(tuning: ThreatTuning):
    for t in tuning.thresholds:
        if t.max_score is None:
            continue
        # exactly at the boundary
        assert rung_for_score(t.max_score, tuning).rung == t.rung
        # one below the boundary — still this rung (unless it's rung 1's own floor of 0)
        if t.max_score > 0:
            assert rung_for_score(t.max_score - 1, tuning).rung <= t.rung
        # one above the boundary — the next rung up
        next_rung = rung_for_score(t.max_score + 1, tuning).rung
        assert next_rung == t.rung + 1


def test_single_signal_uses_full_weight(tuning: ThreatTuning):
    # A species with only toughness observed must not score half of what a same-magnitude
    # damage-only species scores — the missing signal is absent, not zero-weighted twice.
    toughness_only = score(1000, None, tuning)
    damage_only = score(None, 1000, tuning)
    assert toughness_only == 1000 * tuning.toughness_milli // 1000
    assert damage_only == 1000 * tuning.damage_milli // 1000
    both_present_double_counted_wrongly = 1000 * (tuning.toughness_milli + tuning.damage_milli) // 1000 // 2
    # neither single-signal score is silently halved relative to its own full weight
    assert toughness_only != both_present_double_counted_wrongly or tuning.toughness_milli == tuning.damage_milli


def test_no_word_shared_between_the_two_ladders(tuning: ThreatTuning):
    threat_words = {t.id for t in tuning.thresholds}
    assert threat_words.isdisjoint(RARITY_WORDS), \
        f"shared words: {threat_words & RARITY_WORDS}"
    assert len(threat_words) == 10


def test_blocked_does_not_become_rung_one(tuning: ThreatTuning):
    # classify() only handles observed/stated; blocked/inferred return None from classify() and
    # must be routed by the CALLER to inferred_default_rung, never silently to rung 1.
    assert classify(seed("blocked"), tuning) is None
    assert classify(seed("inferred"), tuning) is None
    assert tuning.inferred_default_rung != 1


def test_observed_and_stated_classify_to_a_real_rung(tuning: ThreatTuning):
    result = classify(seed("observed", toughness=300, damage=20), tuning)
    assert result is not None
    assert 1 <= result.rung <= 10

    result_stated = classify(seed("stated", toughness=4000, damage=None), tuning)
    assert result_stated is not None


def test_theta_offset_survives_long_roundtrip(tuning: ThreatTuning):
    long_max = 9_223_372_036_854_775_807
    for t in tuning.thresholds:
        assert 0 <= t.theta_offset <= 40
        # every offset must itself survive being added into a long-typed Theta without overflow
        assert t.theta_offset + long_max // 2 < long_max


def test_histogram_reports_empty_rungs(tuning: ThreatTuning):
    # only rung 1 and rung 10 occupied — every rung in between must still appear, at zero.
    rungs_seen = [1, 1, 10]
    h = histogram(rungs_seen, tuning)
    assert len(h) == 10
    assert h["nuisance"] == 2
    assert h["calamity"] == 1
    for t in tuning.thresholds:
        if t.id not in ("nuisance", "calamity"):
            assert h[t.id] == 0


def test_tuning_loads_from_real_committed_file():
    # No fixture stand-in — this is the actual gk-core/data/tuning/creature-threat.v1.json this module ships.
    t = ThreatTuning.load(1)
    assert t.version == 1
    assert len(t.thresholds) == 10
    assert t.thresholds[-1].max_score is None
    assert t.thresholds[0].rung == 1
