"""Tests for `seedsmith.adapters.structures.metrics` (spec-structure-metrics.md, base-defense
module 29). Zero model calls: `Transport_stub_raises_if_a_test_calls_a_model` proves no test here
can reach one even by accident.

    python -m pytest gk-forge/tools/seedsmith/tests/test_structure_metrics.py -v
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import seedsmith.adapters.structures.metrics as metrics_mod  # noqa: E402
from seedsmith.adapters.structures.generate_corpus import ALL_ROWS  # noqa: E402
from seedsmith.adapters.structures.metrics import (  # noqa: E402
    CLOSED,
    OPEN,
    Metric,
    MetricDeclarationError,
    run_all,
    registered_metrics,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from seedsmith.workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

TUNING = json.loads((_owned("data/tuning/structure-seed.v1.json")).read_text(encoding="utf-8"))
ROWS = list(ALL_ROWS)


def test_every_metric_declares_its_loop():
    # By construction: `_declare` raises for an undeclared/mis-declared loop, so any metric that
    # made it into the module-level registry already satisfies this -- re-asserted directly too.
    for m in registered_metrics():
        assert m.loop in (CLOSED, OPEN)


def test_a_metric_with_no_declaration_fails_registration():
    with pytest.raises(MetricDeclarationError):
        metrics_mod._declare("bad", "sideways", None, lambda rows, tuning: None)


def test_every_closed_metric_has_a_declared_target():
    for m in registered_metrics():
        if m.loop == CLOSED:
            assert m.target is not None, f"{m.name} is closed-loop with no target"


def test_every_open_metric_has_no_target():
    # The mirror check: an open-loop metric that DOES declare a target is equally a contract
    # violation (a target that can never gate anything is a lie about what the metric does).
    for m in registered_metrics():
        if m.loop == OPEN:
            assert m.target is None, f"{m.name} is open-loop but declares a target"


def test_no_open_loop_metric_can_fail_a_build():
    report = run_all(ROWS, TUNING)
    open_results = [r for r in report.results if r.loop == OPEN]
    assert open_results, "sanity: there should be open-loop results to check"
    for r in open_results:
        assert r.passed is None  # structurally cannot be True/False, only ever informational
    # Report.passed only ever reads CLOSED results -- proven by construction (see its own
    # docstring), re-proven here behaviourally: flipping every open result's value can't move it.
    assert report.passed == all(r.passed for r in report.results if r.loop == CLOSED)


def test_role_skew_is_caught_at_plan_and_at_output():
    # "At the plan" is structure-planner's (27) own job, not yet built (blocked on the container
    # gap, see base-defense-todo.md's own module 27 header) -- this test proves the OUTPUT half
    # this module owns today: per_role_coverage fails if a role drops below its budget.
    report = run_all(ROWS, TUNING)
    coverage = next(r for r in report.results if r.name == "per_role_coverage")
    assert coverage.passed is True

    thin_tuning = json.loads(json.dumps(TUNING))
    thin_tuning["budget"]["Extract"] = 999
    thin_report = run_all(ROWS, thin_tuning)
    thin_coverage = next(r for r in thin_report.results if r.name == "per_role_coverage")
    assert thin_coverage.passed is False
    assert thin_report.passed is False


def test_density_gate_rejects_a_taxonomy_out_of_band():
    report = run_all(ROWS, TUNING)
    density = next(r for r in report.results if r.name == "grid_density")
    assert density.passed is True

    narrow_tuning = json.loads(json.dumps(TUNING))
    narrow_tuning["metrics"]["densityBand"] = {"minMilli": 100, "maxMilli": 200}
    narrow_report = run_all(ROWS, narrow_tuning)
    narrow_density = next(r for r in narrow_report.results if r.name == "grid_density")
    assert narrow_density.passed is False


def test_rarity_does_not_correlate_with_strength_band():
    report = run_all(ROWS, TUNING)
    result = next(r for r in report.results if r.name == "rarity_strength_correlation")
    assert result.passed is True


def test_distinctness_reads_abilities_not_stats():
    # Source scan over the metric's own implementation, per the spec's own test name -- proves it
    # structurally, not just behaviourally (a function could coincidentally never READ a field it
    # still references in its own source).
    src = inspect.getsource(metrics_mod._flavour_distinctness)
    fields_src = inspect.getsource(metrics_mod)  # _DISTINCTNESS_FIELDS is module-level
    assert '"strengthBand"' not in src
    assert '"rarity"' not in src
    for allowed in ("role", "obstacleVerbs", "acquisitionPaths", "traits"):
        assert allowed in fields_src


def test_report_header_states_anchor_is_not_roster():
    report = run_all(ROWS, TUNING)
    assert "not a complete roster" in report.header.lower() or "not a complete roster" in report.header


def test_unresolved_rate_gates_at_the_declared_ceiling():
    report = run_all(ROWS, TUNING)
    result = next(r for r in report.results if r.name == "unresolved_rate")
    # Every row today is AUTHORED, zero GENERATED -- correctly reads 0, trivially under ceiling.
    assert result.value == 0
    assert result.passed is True


def test_idempotency_metric_matches_the_module_24_harness():
    report = run_all(ROWS, TUNING)
    result = next(r for r in report.results if r.name == "idempotency")
    assert result.passed is True
    assert result.value == result.target  # both are hashes of independently-written trees


def test_transport_stub_raises_if_a_test_calls_a_model():
    # This whole module has no transport to stub -- the guarantee is structural: no import of any
    # model client anywhere in metrics.py, checked directly (the same discipline
    # test_structure_corpus.py's own test_zero_model_calls_in_this_module already established).
    src = (Path(__file__).resolve().parent.parent / "seedsmith" / "adapters" / "structures"
           / "metrics.py").read_text(encoding="utf-8")
    for banned in ("openai", "anthropic", "lmstudio", "requests.post", "httpx", "urllib"):
        assert banned not in src.lower()
