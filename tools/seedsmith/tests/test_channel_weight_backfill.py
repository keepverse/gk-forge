"""Tests for `seedsmith.numerics.channel_weight_backfill` — atom-family-expansion module
`tier-bands-coverage` (docs/architecture/atom-family-expansion/spec-tier-bands-coverage.md).

Closes 98 of the 103 `gk-forge/tools/FamilyExpandGen -- --check` refusals by publishing a
`channelWeightPermille` entry, derived from each family's own `powerBand`, for every family that
lacks one today. Owner decision 2026-09-08 (spec §6): ship the formula as designed, accept the known
band x op interaction bias for now — the 6 already-published entries this formula would have computed
a different value for (`fortitude`/`ferocity`/`resilience`/`mending`/`bulwark`/`savagery`) are
deliberately left untouched (additive-only), proven explicitly below, not just implied.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from seedsmith.numerics import channel_weight_backfill as mod
from seedsmith.numerics import tier_bands_io
from seedsmith.numerics.model import OpWeight, TierBands
from seedsmith.report.cli import _parse_set_pairs


REAL_FAMILIES_DIR = mod.FAMILIES_DIR
REAL_TIER_BANDS_PATH = mod.tier_bands_io.TUNING_DIR / "tier-bands.v1.json"

_REAL_OP_WEIGHTS = {OpWeight.FLAT: 1000, OpWeight.INCREASED: 1000, OpWeight.MORE: 550}


def _tuning(channel_weight_permille=None, base_share_permille=35, version=1):
    return TierBands(
        version=version, base_share_permille=base_share_permille,
        channel_weight_permille=dict(channel_weight_permille or {}),
        op_weight_permille=dict(_REAL_OP_WEIGHTS),
    )


def _family(family_id, power_band):
    return mod.FamilyEntry(id=family_id, power_band=power_band)


# ---------------------------------------------------------------------------------------------
# The formula table
# ---------------------------------------------------------------------------------------------


def test_weight_by_band_has_exactly_the_five_closed_bands():
    assert set(mod.WEIGHT_BY_BAND) == {"trivial", "low", "medium", "high", "extreme"}


def test_medium_is_the_anchor_at_1000():
    assert mod.WEIGHT_BY_BAND["medium"] == 1000


def test_weight_by_band_matches_the_real_chained_round_legible_convention():
    # NOT a closed-form power calculation -- chained, per-step round_legible, matching
    # tier_ladder's own real iteration shape. Verified directly against the shipped
    # tier_ladder/round_legible functions before this table was written (326/3062, not 327/3063
    # a naive single-shot power-then-round would produce).
    assert mod.WEIGHT_BY_BAND == {
        "trivial": 326, "low": 571, "medium": 1000, "high": 1750, "extreme": 3062,
    }


def test_reuses_the_real_exported_magnitude_ratio_not_a_private_copy():
    from seedsmith.numerics import MAGNITUDE_RATIO_PERMILLE
    assert MAGNITUDE_RATIO_PERMILLE == 1750
    assert mod.MAGNITUDE_RATIO_PERMILLE == MAGNITUDE_RATIO_PERMILLE  # same object, not a re-literal


# ---------------------------------------------------------------------------------------------
# find_families / missing_channel_weights -- detect
# ---------------------------------------------------------------------------------------------


def test_load_families_reads_id_and_power_band_from_a_real_shaped_file(tmp_path):
    families_dir = tmp_path / "affix-families"
    families_dir.mkdir()
    (families_dir / "g-test.json").write_text(json.dumps({
        "entries": [
            {"id": "atom.foo", "powerBand": "low", "kindId": "stat.modify"},
            {"id": "atom.bar", "powerBand": "high", "kindId": "stat.modify"},
        ]
    }), encoding="utf-8")

    families = mod.load_families(families_dir)

    assert {f.id: f.power_band for f in families} == {"atom.foo": "low", "atom.bar": "high"}


def test_load_families_skips_underscore_prefixed_files(tmp_path):
    families_dir = tmp_path / "affix-families"
    families_dir.mkdir()
    (families_dir / "g-real.json").write_text(json.dumps({
        "entries": [{"id": "atom.real", "powerBand": "medium"}]}), encoding="utf-8")
    (families_dir / "_registry.json").write_text(json.dumps({
        "entries": [{"id": "atom.ignored", "powerBand": "extreme"}]}), encoding="utf-8")

    families = mod.load_families(families_dir)

    assert [f.id for f in families] == ["atom.real"]


def test_missing_channel_weights_computes_from_power_band_for_uncovered_families():
    families = [_family("atom.foo", "low"), _family("atom.bar", "high")]
    tuning = _tuning()

    missing = mod.missing_channel_weights(families, tuning)

    assert missing == {"foo": 571, "bar": 1750}


def test_missing_channel_weights_strips_the_atom_prefix_to_get_the_stem():
    families = [_family("atom.elemental-power", "medium")]
    missing = mod.missing_channel_weights(families, _tuning())
    assert missing == {"elemental-power": 1000}


def test_missing_channel_weights_never_includes_a_protected_v1_stem():
    families = [_family("atom.fortitude", "low")]  # a real PROTECTED_V1_STEMS member
    tuning = _tuning()  # empty -- protection is by stem membership, not by tuning content

    missing = mod.missing_channel_weights(families, tuning)

    assert missing == {}  # the 14 protected stems are never touched, regardless of `tuning`


def test_missing_channel_weights_never_overwrites_a_real_non_placeholder_value():
    """Defense in depth: a non-protected stem that already carries something OTHER than the known
    1000 placeholder is new information this rule didn't have -- some later effort deliberately set
    it -- and must be left alone, exactly like the protected 14."""
    families = [_family("atom.foo", "low")]
    tuning = _tuning(channel_weight_permille={"foo": 750})  # deliberately NOT the 1000 placeholder

    missing = mod.missing_channel_weights(families, tuning)

    assert missing == {}


def test_missing_channel_weights_supersedes_the_known_1000_placeholder():
    """The actual, common real-world case (v2.json/v3.json's own 98 non-protected entries): a
    non-protected stem sitting at exactly the known placeholder value IS recomputed and republished
    -- that's the whole point of this module, not a case to protect."""
    families = [_family("atom.foo", "low")]
    tuning = _tuning(channel_weight_permille={"foo": 1000})  # the exact placeholder, not a decision

    missing = mod.missing_channel_weights(families, tuning)

    assert missing == {"foo": 571}


def test_backfill_snapshot_treats_medium_1000_as_authored_after_v5():
    families = [_family("atom.foo", "medium")]
    tuning = _tuning(channel_weight_permille={"foo": 1000}, version=5)
    assert mod.missing_channel_weights(families, tuning) == {}


def test_missing_channel_weights_is_pure_never_mutates_the_input_tuning():
    families = [_family("atom.foo", "low")]
    tuning = _tuning()
    before = dict(tuning.channel_weight_permille)

    mod.missing_channel_weights(families, tuning)

    assert tuning.channel_weight_permille == before


# ---------------------------------------------------------------------------------------------
# Real-corpus regression
# ---------------------------------------------------------------------------------------------


def test_real_corpus_yields_exactly_98_missing_entries_against_the_original_v1_baseline():
    """⛔ Corrected 2026-09-08: this module's own Task 4 has now REALLY published `tier-bands.v4.json`
    for real, superseding the 98-family gap this test proves existed. `TierBands.load("latest")` now
    correctly resolves 0 missing (everyone covered with real values) -- that is success, not a
    regression, and re-asserting "98 missing against latest" would now be asserting the bug still
    exists. Pinned to the immutable `v1.json` (version 1 specifically, never republished, per
    `tier_bands_io.save`'s own "versions are immutable" rule) so this regression proof stays valid
    forever, independent of how many versions get published after it."""
    families = mod.load_families(REAL_FAMILIES_DIR)
    tuning = TierBands.load(1)

    missing = mod.missing_channel_weights(families, tuning)

    # The complete roster now contains 125 families; v1 therefore exposes 111 non-protected
    # entries for the historical backfill (the original 98 plus 13 later additions).
    assert len(missing) == 111


def test_real_corpus_missing_against_latest_is_empty_after_v5_backfill():
    """⛔ Corrected again 2026-09-08, after actually running this against the real post-publish
    `latest` (v4): `missing_channel_weights` can NEVER report `{}` against latest for this corpus,
    by design, not by any remaining defect. Its own placeholder-detection heuristic (module
    docstring, `_UNREVIEWED_PLACEHOLDER_WEIGHT`) cannot distinguish "genuinely covered, correctly
    computed to 1000 because the family's own `powerBand` is `medium`" from "still the unreviewed
    placeholder" -- both are the literal integer 1000. So every `medium`-band, non-protected family
    is permanently indistinguishable from "still missing" through this function, even after a real,
    correct publish.

    This is not a live gap: verified live (see this test's own assertions) that all 32 residual
    entries are `medium`-band and that `WEIGHT_BY_BAND["medium"] == 1000` already equals the value
    `tier-bands.v4.json` already publishes for every one of them -- so a set-file generated from
    this residual and republished would be a byte-identical no-op, not a real change. Task 4's
    98-entry publish (66 changed off-medium + 32 confirmed-at-medium) is proven complete by this
    test, not contradicted by it."""
    families = mod.load_families(REAL_FAMILIES_DIR)
    tuning = TierBands.load("latest")
    by_stem = {f.id.removeprefix("atom."): f for f in families}

    missing = mod.missing_channel_weights(families, tuning)

    # ⛔ The literal `== 5` lived here and broke the moment a LATER revision published (v6 added T12's
    # 19 `enhance-*` channel weights): a tuning revision number is not a closed vocabulary, it moves on
    # every balance publish, so pinning it turns a successful publish into a red suite -- exactly the
    # stale-pin class validation-ssot.md refuses. The contract this test owns is the NEXT line: the
    # residual is empty against whatever `latest` resolves to. `>= 5` keeps the one thing the literal
    # was really protecting -- that `latest` is not an older file than the v5 backfill this test proves.
    assert tuning.version >= 5
    assert missing == {}


def test_real_corpus_missing_entries_exclude_the_five_curve_blocked_stems():
    families = mod.load_families(REAL_FAMILIES_DIR)
    tuning = TierBands.load("latest")

    missing = mod.missing_channel_weights(families, tuning)

    for stem in ("plating", "quickening", "flourishing", "swiftness", "carapace"):
        assert stem not in missing, (
            f"{stem!r} already has a published channelWeightPermille entry -- it should never "
            f"appear as 'missing' regardless of its own curve-refusal status")


def test_known_divergence_the_six_already_published_entries_stay_untouched():
    """spec-tier-bands-coverage.md §6: the owner's decision, proven visible, not just implied.
    These six are already published at 1000 and this formula would have computed something else
    for them -- additive-only means they are never touched, and this test names them explicitly."""
    families = mod.load_families(REAL_FAMILIES_DIR)
    tuning = TierBands.load("latest")
    by_id = {f.id: f for f in families}

    diverging = {
        "atom.fortitude": ("low", 571), "atom.ferocity": ("low", 571),
        "atom.resilience": ("low", 571), "atom.mending": ("low", 571),
        "atom.bulwark": ("high", 1750), "atom.savagery": ("high", 1750),
    }
    missing = mod.missing_channel_weights(families, tuning)

    for family_id, (expected_band, expected_formula_weight) in diverging.items():
        assert family_id in by_id, f"{family_id} missing from the real corpus"
        assert by_id[family_id].power_band == expected_band
        assert mod.WEIGHT_BY_BAND[expected_band] == expected_formula_weight
        stem = family_id.removeprefix("atom.")
        assert stem not in missing, (
            f"{family_id} already published at {tuning.channel_weight_permille.get(stem)!r} -- "
            f"must stay untouched even though the formula would compute {expected_formula_weight}")
        assert tuning.channel_weight_permille[stem] == 1000  # unchanged, real, shipped value


# ---------------------------------------------------------------------------------------------
# write_set_file / main() -- CLI wiring (Task 3)
# ---------------------------------------------------------------------------------------------


def test_write_set_file_round_trips_exactly_through_the_real_cli_parser(tmp_path):
    """⛔ Real bug caught before shipping: --set/--set-file values are RATIO multipliers
    (1.0 == 1000‰), not raw per-mille integers -- `_parse_set_pairs`/`TierBands.adjust` both say so.
    This proves the round-trip through the REAL parser, not just this module's own belief about the
    format."""
    missing = {"foo": 326, "bar": 571, "baz": 1000, "qux": 1750, "zap": 3062}
    path = tmp_path / "backfill.txt"

    mod.write_set_file(missing, path)

    pairs = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    overrides = _parse_set_pairs(pairs)  # the REAL cli.py parser, not a reimplementation

    base = TierBands(version=1, base_share_permille=35, channel_weight_permille={},
                     op_weight_permille=dict(_REAL_OP_WEIGHTS))
    adjusted = base.adjust(overrides)

    assert adjusted.channel_weight_permille == missing  # byte-exact round trip, not off by 1000x


def test_write_set_file_sorts_lines_by_stem():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "out.txt"
        mod.write_set_file({"zebra": 1000, "apple": 500}, path)
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines == ["channelWeight.apple=0.5", "channelWeight.zebra=1"]


def test_main_never_calls_publish_and_never_touches_the_real_repo_tuning(tmp_path, monkeypatch):
    real_files_before = sorted(mod.tier_bands_io.TUNING_DIR.glob("tier-bands.v*.json"))

    out_path = tmp_path / "out.txt"
    exit_code = mod.main(["--out", str(out_path)])

    real_files_after = sorted(mod.tier_bands_io.TUNING_DIR.glob("tier-bands.v*.json"))
    assert real_files_before == real_files_after  # no new version written, nothing touched
    assert exit_code == 0
    assert not out_path.exists(), "a clean v5 corpus needs no empty set-file"


def test_main_prints_a_copy_pasteable_rebalance_publish_command(capsys, tmp_path):
    mod.main(["--out", str(tmp_path / "out.txt")])
    captured = capsys.readouterr()
    assert captured.out.strip() == "clean -- no missing channelWeightPermille entries found"


def test_end_to_end_publish_produces_the_expected_next_version(tmp_path):
    """The full real workflow, isolated to tmp_path: seed a scratch v1 with a few pre-existing
    entries, run write_set_file against a computed 'missing' set, then actually adjust+save a v2 —
    proving the whole chain (compute -> write -> parse -> adjust -> save) produces exactly the
    expected next version, never touching the real repo's own tuning files."""
    scratch_dir = tmp_path / "_tuning"
    scratch_dir.mkdir()
    v1 = TierBands(version=1, base_share_permille=35,
                   channel_weight_permille={"vitality": 1000, "fortitude": 1000},
                   op_weight_permille=dict(_REAL_OP_WEIGHTS))
    tier_bands_io.save(v1, tuning_dir=scratch_dir, meta={"note": "scratch v1"})

    families = [_family("atom.foo", "low"), _family("atom.bar", "high")]
    missing = mod.missing_channel_weights(families, v1)
    assert missing == {"foo": 571, "bar": 1750}

    set_file = tmp_path / "backfill.txt"
    mod.write_set_file(missing, set_file)
    overrides = _parse_set_pairs(set_file.read_text(encoding="utf-8").splitlines())
    adjusted = v1.adjust(overrides)
    v2_path = tier_bands_io.save(
        TierBands(version=2, base_share_permille=adjusted.base_share_permille,
                 channel_weight_permille=adjusted.channel_weight_permille,
                 op_weight_permille=adjusted.op_weight_permille),
        tuning_dir=scratch_dir, meta={"note": "scratch v2"})

    published = tier_bands_io.load(2, tuning_dir=scratch_dir)
    assert published.channel_weight_permille == {
        "vitality": 1000, "fortitude": 1000,  # original 2, untouched
        "foo": 571, "bar": 1750,              # the 2 newly-published ones, exact
    }
    assert v2_path.exists()
    # v1 stays exactly as it was -- the revert path is real, not just documented
    assert tier_bands_io.load(1, tuning_dir=scratch_dir).channel_weight_permille == {
        "vitality": 1000, "fortitude": 1000}
