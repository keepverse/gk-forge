"""Tests for `usage-direction`'s pure weight function (FC3, spec-usage-direction.md,
roster-balance program). Model-free; no transport stub needed anywhere in this file.

    python -m pytest gk-forge/tools/seedsmith/tests/test_usage_direction_weights.py -v
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402

import pytest  # noqa: E402

from seedsmith.adapters.actions.usage_direction.weights import (  # noqa: E402
    CEILING_WEIGHT_MILLI, CUE_LABEL, FLOOR_WEIGHT_MILLI, latest_usage_report_path, render_cue,
    target_share_milli, weight_milli, weights_for, weights_from_usage_report,
)
from seedsmith.adapters.actions.generate_usage_stats import REPO_ROOT, REPORT_DIR  # noqa: E402

POP = 98


class TestTargetShare:
    def test_target_share_matches_hand_computation(self):
        assert target_share_milli(98) == 1000 // 98

    def test_target_share_requires_a_positive_population(self):
        with pytest.raises(ValueError):
            target_share_milli(0)


class TestWeightMilli:
    def test_a_zero_usage_family_gets_the_ceiling_weight(self):
        usage = {"atom.a": 100}  # SOME usage exists overall, just none for this family
        w = weight_milli("atom.never-used", usage, population_size=POP)
        assert w == CEILING_WEIGHT_MILLI

    def test_a_family_at_or_above_target_share_gets_the_floor_never_negative(self):
        usage = {"atom.a": 50, "atom.b": 50}  # atom.a is 50% of all usage, way above 1/98 target
        w = weight_milli("atom.a", usage, population_size=POP)
        assert w == FLOOR_WEIGHT_MILLI
        assert w >= 0

    def test_weight_is_monotonic_in_the_deficit(self):
        # more usage -> smaller deficit -> smaller (or equal) weight
        usage = {"atom.a": 1, "atom.b": 5, "atom.c": 0}
        wa = weight_milli("atom.a", usage, population_size=POP)
        wb = weight_milli("atom.b", usage, population_size=POP)
        wc = weight_milli("atom.c", usage, population_size=POP)
        assert wc >= wa >= wb

    def test_zero_total_usage_returns_the_floor_for_everyone(self):
        # no history at all yet -- nobody is "underused" relative to nothing
        assert weight_milli("atom.a", {}, population_size=POP) == FLOOR_WEIGHT_MILLI

    def test_weight_never_exceeds_the_ceiling(self):
        usage = {"atom.a": 1000}
        w = weight_milli("atom.never-used", usage, population_size=POP)
        assert w <= CEILING_WEIGHT_MILLI

    def test_weight_is_a_per_mille_integer_never_a_float(self):
        usage = {"atom.a": 3, "atom.b": 7}
        w = weight_milli("atom.c", usage, population_size=POP)
        assert isinstance(w, int)


class TestWeightsFor:
    def test_weights_for_covers_every_requested_family(self):
        weights = weights_for(["atom.a", "atom.b", "atom.c"], {"atom.a": 10}, population_size=POP)
        assert set(weights) == {"atom.a", "atom.b", "atom.c"}

    def test_weights_for_is_deterministic(self):
        usage = {"atom.a": 3, "atom.b": 1}
        w1 = weights_for(["atom.b", "atom.a"], usage, population_size=POP)
        w2 = weights_for(["atom.a", "atom.b"], usage, population_size=POP)
        assert w1 == w2


class TestRenderCue:
    def test_an_underused_family_gets_the_legible_cue(self):
        weights = {"atom.a": CEILING_WEIGHT_MILLI}
        assert render_cue("atom.a", weights) == CUE_LABEL

    def test_a_well_served_family_gets_no_cue(self):
        weights = {"atom.a": FLOOR_WEIGHT_MILLI}
        assert render_cue("atom.a", weights) is None

    def test_an_unweighted_family_gets_no_cue(self):
        assert render_cue("atom.unknown", {}) is None

    def test_the_cue_never_contains_a_number(self):
        weights = {"atom.a": CEILING_WEIGHT_MILLI}
        cue = render_cue("atom.a", weights)
        assert cue is not None
        assert not any(ch.isdigit() for ch in cue)


# ---------------------------------------------------------------------------------------------
# Checkpoint C3 — the honest zero-cost proof: mechanism correctness against FC1's real report.
# NOT a claim that model behavior changes (that needs a real run, see roster-balance-todo.md's
# own "Deferred" section) -- only that real never-used/concentrated families get the weight they
# should, computed from real, committed, already-verified-byte-identical data.
# ---------------------------------------------------------------------------------------------

class TestRealUsageReportIntegration:
    @staticmethod
    def _load_real_report():
        import json
        path = latest_usage_report_path(REPORT_DIR)
        assert path is not None, "no FC1 usage report found under docs/research/action-corpus/"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_every_real_never_used_family_gets_the_ceiling_weight_against_FC1s_real_report(self):
        report = self._load_real_report()
        never_used = report["allTime"]["neverUsed"]
        assert len(never_used) > 0, "expected real never-used families in the committed report"
        weights = weights_from_usage_report(report)
        for family in never_used:
            assert weights[family] == CEILING_WEIGHT_MILLI, family

    def test_the_real_top_10_concentrated_families_get_the_floor_weight(self):
        report = self._load_real_report()
        counts = report["allTime"]["counts"]
        top10 = sorted(counts, key=lambda f: counts[f], reverse=True)[:10]
        weights = weights_from_usage_report(report)
        for family in top10:
            assert weights[family] == FLOOR_WEIGHT_MILLI, family

    def test_computing_weights_twice_from_the_same_report_produces_identical_weights(self):
        report = self._load_real_report()
        assert weights_from_usage_report(report) == weights_from_usage_report(report)

    def test_latest_usage_report_path_is_none_when_no_reports_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert latest_usage_report_path(Path(tmp)) is None
