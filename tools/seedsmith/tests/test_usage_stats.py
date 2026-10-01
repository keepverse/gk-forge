"""Tests for `usage-stats` (FC1, spec-usage-stats.md, roster-balance program).

    python -m pytest gk-forge/tools/seedsmith/tests/test_usage_stats.py -v

Model-free throughout — this module never calls a model, so no test needs to stub a transport.
Determinism/shape/baseline tests run against the real, live repo data
(`data/seed/actions/_candidates/**` when this machine has run the pipeline, else the tracked
`gk-data/packs/fusion/data/seed/actions/_fixtures/**` minimal corpus -- see `derive._round_corpus_root`;
`gk-data/packs/fusion/data/seed/items/affix-families/*.json` either way), matching every prior action-corpus module's own
fixture discipline this session; synthetic in-memory rows are used for planted violations and the
counting-rule tests, so those do not depend on today's real rounds happening to contain a case that
exercises them.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402

import pytest  # noqa: E402

from seedsmith.adapters.actions.usage_stats.derive import (  # noqa: E402
    _round_corpus_root, build_report, canonical_dump, evenness, load_affix_family_ids,
    load_round_files, never_used, tally_usage, top_n_share,
)
from seedsmith.adapters.actions.generate_usage_stats import (  # noqa: E402
    REPO_ROOT, load_policy, verdict,
)
from seedsmith.workspace_roots import owned_path

POPULATION = frozenset({"atom.a", "atom.b", "atom.c", "atom.d"})


def make_row(*, outcome="accepted", atom_families=None):
    return {"outcome": outcome, "draft": {"atomFamilies": atom_families} if atom_families else {}}


# ---------------------------------------------------------------------------------------------
# Counting rule: one accepted row counts each family once, never once per occurrence.
# ---------------------------------------------------------------------------------------------

class TestTallyTests:
    def test_a_bundle_counts_each_family_once_never_by_repeat(self):
        rows = [make_row(atom_families=["atom.a", "atom.b"])]
        counts = tally_usage(rows)
        assert counts["atom.a"] == 1
        assert counts["atom.b"] == 1

    def test_unresolved_and_blocked_rows_never_contribute(self):
        rows = [
            make_row(outcome="unresolved", atom_families=["atom.a"]),
            make_row(outcome="blocked", atom_families=["atom.b"]),
            make_row(outcome="accepted", atom_families=["atom.c"]),
        ]
        counts = tally_usage(rows)
        assert counts["atom.a"] == 0
        assert counts["atom.b"] == 0
        assert counts["atom.c"] == 1

    def test_duplicate_families_within_one_draft_still_count_once(self):
        # a draft that (illegally) repeats a family in its own list must not double-count it
        rows = [make_row(atom_families=["atom.a", "atom.a"])]
        counts = tally_usage(rows)
        assert counts["atom.a"] == 1


# ---------------------------------------------------------------------------------------------
# Evenness over the FULL population, never only the families that appear.
# ---------------------------------------------------------------------------------------------

class TestEvennessTests:
    def test_evenness_is_computed_over_the_full_population_not_only_used_families(self):
        # 2 of 4 families used, evenly, 2 completely unused -- must NOT read as perfectly even.
        counts = {"atom.a": 10, "atom.b": 10}
        e = evenness(counts, POPULATION)
        assert 0.0 < e < 1.0
        # over just the used pair it WOULD be 1.0 -- confirm the population-wide answer differs
        assert e != evenness(counts, frozenset({"atom.a", "atom.b"}))

    def test_evenness_is_1_for_a_uniform_full_population(self):
        counts = {f: 5 for f in POPULATION}
        assert evenness(counts, POPULATION) == pytest.approx(1.0)

    def test_evenness_is_0_for_a_single_family_dominating(self):
        counts = {"atom.a": 100}
        assert evenness(counts, POPULATION) == pytest.approx(0.0)

    def test_a_family_with_zero_picks_pulls_evenness_down(self):
        full = {f: 5 for f in POPULATION}
        one_dead = {f: 5 for f in POPULATION if f != "atom.d"}
        assert evenness(one_dead, POPULATION) < evenness(full, POPULATION)


class TestTopShareTests:
    def test_top_n_share_of_zero_usage_is_zero(self):
        assert top_n_share({}, 10) == 0.0

    def test_top_n_share_matches_hand_computation(self):
        counts = {"atom.a": 6, "atom.b": 3, "atom.c": 1}
        assert top_n_share(counts, 2) == pytest.approx(9 / 10)


class TestNeverUsedTests:
    def test_never_used_families_are_named_individually(self):
        counts = {"atom.a": 1}
        assert never_used(counts, POPULATION) == ["atom.b", "atom.c", "atom.d"]

    def test_never_used_is_empty_when_everything_has_been_picked(self):
        counts = {f: 1 for f in POPULATION}
        assert never_used(counts, POPULATION) == []


# ---------------------------------------------------------------------------------------------
# Round-file loading: excludes model-experiment files, raises loudly on a corrupt file.
# ---------------------------------------------------------------------------------------------

class TestRoundLoadTests:
    def test_model_experiment_rounds_are_excluded_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "general").mkdir()
            (root / "general" / "round-1.json").write_text(
                json.dumps({"entries": [make_row(atom_families=["atom.a"])]}), encoding="utf-8")
            (root / "general" / "round-1-model-experiment.json").write_text(
                json.dumps({"entries": [make_row(atom_families=["atom.z"])]}), encoding="utf-8")
            loaded = load_round_files(root)
            all_rows = [r for _, rows in loaded["general"] for r in rows]
            families = {f for r in all_rows for f in (r.get("draft") or {}).get("atomFamilies", [])}
            assert "atom.z" not in families
            assert "atom.a" in families

    def test_an_unreadable_round_file_is_a_named_error_not_a_silent_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "general").mkdir()
            (root / "general" / "round-1.json").write_text("{not valid json", encoding="utf-8")
            with pytest.raises(ValueError, match="could not read"):
                load_round_files(root)

    def test_a_missing_scope_directory_is_legal_and_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = load_round_files(Path(tmp))
            assert loaded["general"] == []
            assert loaded["family"] == []
            assert loaded["signature"] == []


# ---------------------------------------------------------------------------------------------
# All-time vs latest-round: reported separately, demonstrably different when they diverge.
# ---------------------------------------------------------------------------------------------

class TestAllTimeVsLatestRoundTests:
    def test_all_time_and_latest_round_are_reported_separately_and_can_differ(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "seed" / "items" / "affix-families").mkdir(parents=True)
            (root / "data" / "seed" / "items" / "affix-families" / "g1.json").write_text(
                json.dumps({"entries": [{"id": "atom.a"}, {"id": "atom.b"}]}), encoding="utf-8")
            candidates = root / "data" / "seed" / "actions" / "_candidates"
            (candidates / "general").mkdir(parents=True)
            (candidates / "general" / "round-1.json").write_text(
                json.dumps({"entries": [make_row(atom_families=["atom.a"])]}), encoding="utf-8")
            (candidates / "general" / "round-2.json").write_text(
                json.dumps({"entries": [make_row(atom_families=["atom.b"])]}), encoding="utf-8")

            report = build_report(root).to_dict()
            assert report["allTime"]["counts"] == {"atom.a": 1, "atom.b": 1}
            assert report["latestRound"]["counts"] == {"atom.b": 1}
            assert report["latestRoundNumbers"]["general"] == 2


# ---------------------------------------------------------------------------------------------
# Policy: per-mille integers only, refused otherwise.
# ---------------------------------------------------------------------------------------------

class TestPolicyTests:
    def test_PLANTED_VIOLATION_a_float_threshold_in_the_tuning_file_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps({
                "minEvennessMilli": 0.85, "maxTop10SharePermille": 300, "minFamiliesUsedShare": 400,
            }), encoding="utf-8")
            with pytest.raises(ValueError, match="per-mille integer"):
                load_policy(path)

    def test_the_shipped_policy_loads_cleanly(self):
        policy = load_policy()
        assert isinstance(policy["minEvennessMilli"], int)
        assert isinstance(policy["maxTop10SharePermille"], int)
        assert isinstance(policy["minFamiliesUsedShare"], int)

    def test_verdict_fails_on_a_measured_gap_and_names_it(self):
        report = {"allTime": {"evennessMilli": 500, "top10SharePermille": 900, "familiesUsed": 10},
                 "populationSize": 100}
        policy = {"minEvennessMilli": 850, "maxTop10SharePermille": 300, "minFamiliesUsedShare": 400}
        v = verdict(report, policy)
        assert not v["pass"]
        assert len(v["findings"]) == 3

    def test_verdict_passes_when_every_axis_clears_its_floor_or_ceiling(self):
        report = {"allTime": {"evennessMilli": 950, "top10SharePermille": 100, "familiesUsed": 90},
                 "populationSize": 100}
        policy = {"minEvennessMilli": 850, "maxTop10SharePermille": 300, "minFamiliesUsedShare": 400}
        v = verdict(report, policy)
        assert v["pass"]
        assert v["findings"] == []


# ---------------------------------------------------------------------------------------------
# Which corpus the report reads: the runtime scratch dir, or the tracked fixture (SGC5-F1).
# ---------------------------------------------------------------------------------------------

class TestRoundCorpusRoot:
    """`derive._round_corpus_root`'s two branches, pinned. The runtime `_candidates/` dir is the
    actions pipeline's gitignored pre-acceptance scratch, so a fresh checkout has none and the report
    used to read an EMPTY corpus (SGC5-F1); the tracked fixture stands in for exactly that case and
    must never be MIXED INTO a real corpus, which is the double-count this class exists to prevent."""

    @staticmethod
    def _runtime_round(root: Path, scope: str, name: str, rows: "list[dict]") -> None:
        scope_dir = root / "data" / "seed" / "actions" / "_candidates" / scope
        scope_dir.mkdir(parents=True, exist_ok=True)
        (scope_dir / name).write_text(json.dumps({"entries": rows}), encoding="utf-8")

    def test_the_runtime_scratch_dir_wins_whenever_it_holds_a_real_round_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._runtime_round(root, "general", "round-1.json", [make_row(atom_families=["atom.a"])])
            assert _round_corpus_root(root) == root / "data" / "seed" / "actions" / "_candidates"
            # and the fixture's own candidate is therefore NOT counted alongside it
            assert "_fixtures" not in str(_round_corpus_root(root))

    def test_the_tracked_fixture_is_used_only_when_the_runtime_dir_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assert _round_corpus_root(root) == root / "data" / "seed" / "actions" / "_fixtures"

    def test_a_runtime_dir_holding_only_the_model_experiment_file_is_not_a_corpus(self):
        # `round-1-model-experiment.json` is excluded by name from every tally, so a dir holding only
        # it is empty for this module's purposes -- choosing it would report acceptedCount 0 and
        # silently drop the fixture that exists for exactly this case.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._runtime_round(root, "general", "round-1-model-experiment.json",
                                [make_row(atom_families=["atom.a"])])
            assert _round_corpus_root(root) == root / "data" / "seed" / "actions" / "_fixtures"

    def test_the_report_falls_back_to_the_fixture_and_counts_its_accepted_row(self):
        # the fixture root is a path UNDER the given repo root, so this pins the wiring end to end:
        # the report reads `_fixtures/`, counts only the accepted row, and reports round 1.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope_dir = root / "data" / "seed" / "actions" / "_fixtures" / "general"
            scope_dir.mkdir(parents=True)
            (scope_dir / "round-1.json").write_text(json.dumps({"entries": [
                make_row(atom_families=["atom.a"]), make_row(outcome="blocked")]}), encoding="utf-8")
            report = build_report(root).to_dict()
            assert report["acceptedCount"] == 1
            assert report["latestRoundNumbers"] == {"general": 1}


class TestTrackedWorkedExampleFixture:
    """The committed fixture's own contract (SGC5-F1): the pinned pair must stay a legal row -- an
    `accepted` candidate whose families are real affix families. Asserted as a join/membership, never
    as a population count (validation-ssot.md)."""

    FIXTURE = owned_path("data/seed/actions/_fixtures/general/round-1.json", REPO_ROOT)

    def test_the_fixture_is_tracked_content_with_the_pinned_accepted_candidate(self):
        doc = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        row = next(e for e in doc["entries"] if e["candidateId"] == "candidate.general.003")
        assert row["outcome"] == "accepted"
        assert row["briefId"] == "brief.general.general.004"

    def test_every_family_the_fixture_names_is_a_real_affix_family(self):
        doc = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        families = load_affix_family_ids(REPO_ROOT)
        picked = {f for e in doc["entries"] for f in (e["draft"].get("atomFamilies") or [])}
        assert picked and picked <= families


# ---------------------------------------------------------------------------------------------
# Determinism and the real corpus.
# ---------------------------------------------------------------------------------------------

class TestRealCorpusTests:
    def test_the_real_corpus_loads_and_reports_without_error(self):
        # Explicit acceptance value for the shared committed affix-family corpus (112 -> 125
        # after the owner's item-seed commits; nodegen's test_nodegen_vocab tracks the same
        # number, so the two stay in step).
        # `acceptedCount > 0` is the liveness half: it held only on a machine that had run the
        # actions pipeline (the round files are gitignored scratch) until the tracked fixture made
        # it hold on a fresh checkout too (SGC5-F1).
        report = build_report(REPO_ROOT).to_dict()
        assert report["populationSize"] == 125
        assert report["acceptedCount"] > 0

    def test_the_report_is_byte_identical_across_two_runs(self):
        a = canonical_dump(build_report(REPO_ROOT).to_dict())
        b = canonical_dump(build_report(REPO_ROOT).to_dict())
        assert a == b

    def test_load_affix_family_ids_finds_all_real_families(self):
        ids = load_affix_family_ids(REPO_ROOT)
        assert len(ids) == 125
        assert "atom.might" in ids
