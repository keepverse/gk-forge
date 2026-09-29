"""Tests for seedsmith.adapters.creatures.power (spec-power-parse.md, creature-seed module 3)."""
from __future__ import annotations

from pathlib import Path

import pytest

from seedsmith.adapters.creatures.power.model import MagnitudeOverflow, PowerSeed
from seedsmith.adapters.creatures.power.parse import (
    basis_histogram,
    disagreements,
    parse_flavor_text,
    parse_power_seed,
)

FIXTURES = Path(__file__).parent / "fixtures" / "power_text"


def fixture(name: str) -> str:
    """Real captured text, copied verbatim from gk-data/packs/fusion/data/seed/creatures/_dump/almanac/*.json — never a
    hand-written approximation (spec's own testing-strategy rule)."""
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- basis precedence -----------------------------------------------------------------------


def test_observed_beats_stated():
    # 寒冰菇 (plant 10): structured hp=300, attack=0. Text says "伤害：20" — a real disagreement
    # in the corpus (spec §2: "A disagreement is recorded, not resolved here").
    seed = parse_power_seed(
        side="plant", type_id=10, stats_observed=True, hp=300, attack=0,
        flavor_text=fixture("plant_0010_disagreement.txt"))
    assert seed.basis == "observed"
    assert seed.toughness == 300
    assert seed.damage == 0
    assert seed.text_damage == 20
    assert seed.disagreement_damage is True
    assert seed.disagreement_toughness is False


def test_bullet_damage_prefix_still_matches_via_substring_search():
    # 豌豆射手僵尸 (zombie 100): text reads "子弹伤害：20" — the substring "伤害：20" must still
    # match, because .search (not .match/.fullmatch) is used throughout this module.
    seed = parse_power_seed(
        side="zombie", type_id=100, stats_observed=True, hp=270, attack=50,
        flavor_text=fixture("zombie_0100_bullet_damage.txt"))
    assert seed.basis == "observed"
    assert seed.toughness == 270
    assert seed.damage == 50
    assert seed.text_damage == 20
    assert seed.text_toughness == 270
    assert seed.disagreement_damage is True     # 20 != 50
    assert seed.disagreement_toughness is False  # 270 == 270


def test_text_only_is_stated_not_inferred():
    # 坚果 (plant 3): not stats_observed, but "韧性：4000" parses.
    seed = parse_power_seed(
        side="plant", type_id=3, stats_observed=False, hp=None, attack=None,
        flavor_text=fixture("plant_0003_toughness.txt"))
    assert seed.basis == "stated"
    assert seed.toughness == 4000
    assert seed.damage is None


def test_inferred_when_text_exists_but_no_number_parses():
    # 睡莲 (plant 12): real text, no "伤害"/"韧性" line at all.
    seed = parse_power_seed(
        side="plant", type_id=12, stats_observed=False, hp=None, attack=None,
        flavor_text=fixture("plant_0012_inferred.txt"))
    assert seed.basis == "inferred"
    assert seed.toughness is None
    assert seed.damage is None


def test_no_text_and_no_stats_is_blocked():
    seed = parse_power_seed(
        side="plant", type_id=246, stats_observed=False, hp=None, attack=None, flavor_text="")
    assert seed.basis == "blocked"
    assert seed.toughness is None
    assert seed.damage is None

    seed_none = parse_power_seed(
        side="plant", type_id=247, stats_observed=False, hp=None, attack=None, flavor_text=None)
    assert seed_none.basis == "blocked"


# --- the parse itself, real fixtures ------------------------------------------------------


def test_damage_shot_count_and_interval_all_extracted_together():
    # 三线射手 (plant 14): "伤害：20×3/1.5秒" — damage, shot count, and interval in one line.
    parsed = parse_flavor_text(fixture("plant_0014_dmg_shots_interval.txt"))
    assert parsed["damage"] == 20
    assert parsed["shot_count"] == 3
    assert parsed["interval_ms"] == 1500


def test_interval_is_milliseconds_integer():
    # 豌豆射手 (plant 0): "伤害：20/1.5秒" -> 1500, never 1.5.
    parsed = parse_flavor_text(fixture("plant_0000_dmg_interval.txt"))
    assert parsed["damage"] == 20
    assert parsed["interval_ms"] == 1500
    assert isinstance(parsed["interval_ms"], int)


def test_damage_without_shots_or_interval():
    # 樱桃炸弹 (plant 2): "伤害：1800（灰烬）" — no ×N, no /N秒.
    parsed = parse_flavor_text(fixture("plant_0002_damage_only.txt"))
    assert parsed["damage"] == 1800
    assert parsed["shot_count"] is None
    assert parsed["interval_ms"] is None
    assert parsed["toughness"] is None


def test_half_width_and_full_width_colons_both_parse():
    # The real corpus (all 904 species, checked 2026-09-01) contains only full-width "：" —
    # zero half-width examples exist today. This tests the pattern's own tolerance for the ASCII
    # form directly rather than claiming corpus representativeness for a shape that does not (yet)
    # occur in captured text; the two real fixtures above already cover the full-width form that
    # is actually in the corpus.
    full = parse_flavor_text("伤害：20/1.5秒")
    half = parse_flavor_text("伤害:20/1.5秒")
    assert full["damage"] == half["damage"] == 20
    assert full["interval_ms"] == half["interval_ms"] == 1500


# --- overflow -----------------------------------------------------------------------------


def test_out_of_range_magnitude_raises():
    with pytest.raises(MagnitudeOverflow):
        PowerSeed(
            side="plant", type_id=1, basis="observed",
            toughness=2 ** 63,  # one past the C# long max
            damage=1, text_toughness=None, text_damage=None,
            shot_count=None, interval_ms=None,
            disagreement_toughness=False, disagreement_damage=False)


def test_in_range_magnitude_does_not_raise():
    seed = PowerSeed(
        side="plant", type_id=1, basis="observed",
        toughness=9_223_372_036_854_775_807, damage=1,
        text_toughness=None, text_damage=None, shot_count=None, interval_ms=None,
        disagreement_toughness=False, disagreement_damage=False)
    assert seed.toughness == 9_223_372_036_854_775_807


# --- histogram / disagreement report -------------------------------------------------------


def test_basis_histogram_and_disagreements():
    seeds = [
        parse_power_seed(side="plant", type_id=0, stats_observed=True, hp=300, attack=20,
                          flavor_text=fixture("plant_0000_dmg_interval.txt")),
        parse_power_seed(side="plant", type_id=3, stats_observed=False, hp=None, attack=None,
                          flavor_text=fixture("plant_0003_toughness.txt")),
        parse_power_seed(side="plant", type_id=12, stats_observed=False, hp=None, attack=None,
                          flavor_text=fixture("plant_0012_inferred.txt")),
        parse_power_seed(side="plant", type_id=246, stats_observed=False, hp=None, attack=None,
                          flavor_text=""),
        parse_power_seed(side="plant", type_id=10, stats_observed=True, hp=300, attack=0,
                          flavor_text=fixture("plant_0010_disagreement.txt")),
    ]
    hist = basis_histogram(seeds)
    assert hist == {"observed": 2, "stated": 1, "inferred": 1, "blocked": 1}

    dis = disagreements(seeds)
    assert len(dis) == 1
    assert dis[0].type_id == 10
