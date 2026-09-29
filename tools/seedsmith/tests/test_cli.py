"""Tests for seedsmith.report.cli (tasks/seedsmith-todo.md, S1).

    python -m pytest gk-forge/tools/seedsmith/tests/test_cli.py -v
    python -m seedsmith check --adapter stub tests/fixtures/clean && echo OK   # (from gk-forge/tools/seedsmith/)
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.report.cli import (  # noqa: E402
    EXIT_CANNOT_RUN,
    EXIT_CLEAN,
    EXIT_GAP,
    main,
)


def test_retry_blocked_ledger_preserves_authored_and_marks_duplicate_feedback():
    from seedsmith.report.cli import _retry_blocked_ledger

    ledger, feedback = _retry_blocked_ledger({
        "authored": {"attempts": 1},
        "blocked": {"outcome": "blocked", "defects": ["schema mismatch"]},
        "duplicate": {"outcome": "escalated", "defects": ["duplicate name 'Ash' "]},
    })
    assert set(ledger) == {"authored"}
    assert feedback == {"duplicate"}

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class ExitCodeTests(unittest.TestCase):
    def test_clean_fixture_exits_zero(self) -> None:
        self.assertEqual(main(["check", "--adapter", "stub", str(FIXTURES / "clean")]),
                         EXIT_CLEAN)

    def test_broken_fixture_exits_one(self) -> None:
        self.assertEqual(main(["check", "--adapter", "stub", str(FIXTURES / "broken")]),
                         EXIT_GAP)

    def test_unreadable_corpus_exits_two_distinct_from_gap(self) -> None:
        code = main(["check", "--adapter", "stub", str(FIXTURES / "unreadable")])
        self.assertEqual(code, EXIT_CANNOT_RUN)
        self.assertNotEqual(code, EXIT_GAP)

    def test_unknown_adapter_exits_two(self) -> None:
        code = main(["check", "--adapter", "does-not-exist", str(FIXTURES / "clean")])
        self.assertEqual(code, EXIT_CANNOT_RUN)

    def test_gate_flag_never_fails_while_nothing_is_promoted(self) -> None:
        # Every metric ships gates=False for the whole of W1 (spec-metrics.md §4) — --gate
        # against the broken fixture must therefore exit clean, not 1, until something is
        # deliberately promoted.
        code = main(["check", "--adapter", "stub", "--gate", str(FIXTURES / "broken")])
        self.assertEqual(code, EXIT_CLEAN)


class JsonOutputTests(unittest.TestCase):
    def test_json_output_matches_findings_and_carries_schema_version(self, ) -> None:
        import tempfile
        out_path = Path(tempfile.mkdtemp()) / "out.json"
        code = main(["check", "--adapter", "stub", "--json", str(out_path),
                    str(FIXTURES / "broken")])
        self.assertEqual(code, EXIT_GAP)

        data = json.loads(out_path.read_text(encoding="utf-8"))
        # NOT_MEASURED findings from numerics-dependent metrics (no NumericsContext for the
        # stub adapter run) are expected alongside the one real GAP — isolate the GAP explicitly
        # rather than assert a total count that grows every time a new metric is registered.
        gap_findings = [f for f in data if f["severity"] == "gap"]
        self.assertEqual(len(gap_findings), 1)
        self.assertEqual(gap_findings[0]["metric"], "Coverage/EmptyPartition")
        self.assertEqual(gap_findings[0]["subject"], "b")
        self.assertEqual(data[0]["schemaVersion"], 1)


class MetricFilterTests(unittest.TestCase):
    def test_metric_filter_runs_only_the_named_metric(self) -> None:
        # Only one metric exists in S1, but the --metric flag's plumbing (registry.get by id,
        # empty selection safety) is proven here rather than left for a later wave to discover
        # broken.
        code = main(["check", "--adapter", "stub", "--metric", "Coverage/EmptyPartition",
                    str(FIXTURES / "clean")])
        self.assertEqual(code, EXIT_CLEAN)

    def test_unknown_metric_id_runs_nothing_not_an_error(self) -> None:
        code = main(["check", "--adapter", "stub", "--metric", "Does/NotExist",
                    str(FIXTURES / "broken")])
        self.assertEqual(code, EXIT_CLEAN)  # nothing ran, so nothing found a GAP


def test_actions_check_uses_domain_loader_and_excludes_round_scratch(capsys):
    """The actions loader excludes `_rounds/`, whose ids intentionally overlap committed seeds."""
    live_actions = Path(__file__).resolve().parents[3] / "data" / "seed" / "actions"
    assert main(["check", "--adapter", "actions", "--metric", "Actions/Loader",
                 str(live_actions)]) == EXIT_CLEAN
    assert "could not load corpus" not in capsys.readouterr().err


if __name__ == "__main__":
    unittest.main()


# ---- `seedsmith creatures` (added 2026-09-01) -------------------------------------------------------
#
# ⛔ Two of the audit's own `Verify` lines named commands that did not exist:
# `python -m seedsmith creatures motifs` (G1.3) and
# `python -m seedsmith creatures generate --kind commander-effect` (G4.3). Both FAILED when actually
# executed during the final-proof pass — the real entrypoints were reachable only as
# `python -m seedsmith.adapters.creatures.<module>`. Same defect D1.4 already caught once ("the real
# CLI — `report` from the spec's own example doesn't exist"). Fixed by making the documented claim
# true, per P6's own precedent, rather than editing the Verify line down to match.


def test_creatures_subcommand_is_registered_with_both_verbs():
    from seedsmith.report.cli import build_parser

    parser = build_parser()
    for argv in (["creatures", "motifs"], ["creatures", "themes"],
                 ["creatures", "theme-refresh"],
                 ["creatures", "generate", "--kind", "commander-effect"]):
        args = parser.parse_args(argv)
        assert args.command == "creatures"
        assert callable(args.func)


def test_theme_refresh_public_command_reads_the_complete_roster(capsys):
    """A stale theme snapshot must be repairable through the documented CLI, not a private module path."""
    from seedsmith.report.cli import EXIT_CLEAN, main

    assert main(["creatures", "themes", "--dry-run"]) == EXIT_CLEAN
    report = json.loads(capsys.readouterr().out)
    assert report["dryRun"] is True
    # Contract: every species input produced a theme. The roster size is a reading, so assert the
    # relationship and let the scale print (validation-ssot.md).
    assert report["inputs"] > 0
    assert report["inputs"] == report["themes"]


def test_species_item_plan_refuses_when_theme_coverage_is_stale(capsys):
    """A missing registration must stop the walk instead of looking like a smaller plan."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from seedsmith.adapters.items.setgen import themes as themes_mod
    from seedsmith.report.cli import EXIT_CANNOT_RUN, main

    stale = SimpleNamespace(species=904, themes=903, uncovered=("new-creature",), orphaned=())
    with patch.object(themes_mod, "coverage_report", return_value=stale):
        assert main(["items", "generate", "--kind", "set", "--population", "species",
                     "--dry-run"]) == EXIT_CANNOT_RUN
    assert "theme registry is stale" in capsys.readouterr().err


def test_creatures_requires_a_verb():
    """`seedsmith creatures` alone must be a usage error, not a silent no-op."""
    import pytest

    from seedsmith.report.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["creatures"])


def test_creatures_generate_refuses_a_kind_with_no_generator():
    from seedsmith.report.cli import EXIT_CANNOT_RUN, build_parser

    args = build_parser().parse_args(["creatures", "generate", "--kind", "aspect"])
    assert args.func(args) == EXIT_CANNOT_RUN, (
        "an unbuilt kind must refuse loudly — `aspect` is blocked on another program (plan §D-F2), "
        "and silently generating nothing would read as success")


def test_importing_the_cli_does_not_require_langgraph():
    """⛔ Load-bearing. `creatures generate` pulls in the workflow package, and `langgraph` is an
    OPTIONAL extra — the measurement half of seedsmith must keep running on a base install
    (verified live: 470 passed with the extra absent). A top-level import in `cli.py` would make
    plain `seedsmith check` fail for every base-install user.

    Asserted by reading the module source rather than by import success, because this test process
    has langgraph installed and would pass either way."""
    from pathlib import Path

    import seedsmith.report.cli as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    top_level = [ln for ln in source.splitlines()
                 if ln.startswith(("import ", "from ")) and "langgraph" in ln]
    assert top_level == [], f"cli.py imports langgraph at module level: {top_level}"
    assert "generate_commander_effects" not in source.split("def cmd_creatures")[0], (
        "the generator must be imported inside cmd_creatures, not at module scope")


# ---- --pipeline as an execution-scope flag (2026-09-04, creature-corpus-self-heal B1) --------------
#
# Real bug found live: `rerun --pipeline kit-shape --species Peashooter,SunFlower,WallNut` silently
# did a FULL 8-pipeline reclassification of all 3 (49 calls, not the expected 3) — `--species` won
# the old if-elif chain and `--pipeline`'s own value was discarded entirely rather than narrowing
# execution for the selected species.

def _selector_args(**overrides):
    import argparse
    ns = argparse.Namespace(species="", side="", family="", pipeline="", basis="",
                            unresolved=False, stale=False)
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def test_pipeline_alone_selects_and_scopes():
    from seedsmith.report.cli import _selector_from_args
    assert _selector_from_args(_selector_args(pipeline="kit-shape")) == {
        "kind": "pipeline", "pipeline": "kit-shape"}


def test_species_plus_pipeline_selects_those_species_and_scopes_execution():
    from seedsmith.report.cli import _selector_from_args
    selector = _selector_from_args(_selector_args(species="Peashooter,SunFlower", pipeline="kit-shape"))
    assert selector == {"kind": "species", "species": ["Peashooter", "SunFlower"], "pipeline": "kit-shape"}


def test_species_alone_never_carries_a_pipeline_key():
    from seedsmith.report.cli import _selector_from_args
    selector = _selector_from_args(_selector_args(species="Peashooter"))
    assert "pipeline" not in selector


# ---------------------------------------------------------------------------------------------
# `seedsmith numerics rebalance` — the command tier-bands.v1.json's own `_meta.rebalance` line
# has always named, and which did not exist until item-content T10 (affix-draw-coverage).
# ---------------------------------------------------------------------------------------------

def test_set_pairs_parse_the_meta_documented_key_grammar():
    from seedsmith.report.cli import _parse_set_pairs
    assert _parse_set_pairs(["channelWeight.might=0.85", "baseShare=0.036"]) == {
        "channelWeight.might": 0.85, "baseShare": 0.036}


def test_a_set_key_that_is_neither_baseshare_nor_a_channel_weight_is_refused():
    from seedsmith.report.cli import _parse_set_pairs
    import pytest
    with pytest.raises(ValueError):
        _parse_set_pairs(["opWeight.More=0.55"])
    with pytest.raises(ValueError):
        _parse_set_pairs(["channelWeight.might"])


def test_rebalance_with_no_overrides_refuses_rather_than_publishing_a_noop(capsys):
    assert main(["numerics", "rebalance"]) == EXIT_CANNOT_RUN
    assert "refusing a no-op publish" in capsys.readouterr().out


def test_rebalance_is_dry_by_default_and_reports_what_would_move(capsys):
    assert main(["numerics", "rebalance", "--set", "channelWeight.might=0.85"]) == EXIT_CLEAN
    out = capsys.readouterr().out
    assert "~ might: 1000‰ -> 850‰" in out
    assert "nothing written" in out


def test_the_shipped_tuning_file_authors_a_weight_for_every_affix_family(capsys):
    """T10's acceptance re-stated as a CLI-level check: a rebalance that adds nothing means the
    shipped corpus is already fully weighted, so `FamilyExpansion` refuses none at its first
    gate."""
    import json
    from seedsmith.numerics import TierBands
    from seedsmith.numerics.tier_bands_io import TUNING_DIR

    weighted = set(TierBands.load("latest").channel_weight_permille)
    for path in sorted((TUNING_DIR.parent / "affix-families").glob("*.json")):
        if path.name.startswith("_"):
            continue
        for entry in json.loads(path.read_text(encoding="utf-8"))["entries"]:
            fid = entry["id"]
            stem = fid[len("atom."):] if fid.startswith("atom.") else fid
            assert stem in weighted, f"{fid} has no authored channelWeight — undrawable"
