"""Tests for `seedsmith metrics --coverage` (tasks/seedsmith-todo.md, S7).

    python -m pytest gk-forge/tools/seedsmith/tests/test_metrics_coverage_cli.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.combogen import tuning as tuning_mod  # noqa: E402
from seedsmith.corpus import Corpus, Entry  # noqa: E402
from seedsmith.metrics import Ctx, Severity  # noqa: E402
from seedsmith.metrics.appendix_a import AppendixARow, coverage_report  # noqa: E402
from seedsmith.metrics.coverage import HostRoleDiversityMetric  # noqa: E402
from seedsmith.report.cli import EXIT_CLEAN, EXIT_GAP, main  # noqa: E402


def _combination(entry_id: str, shape: str, host_role: "str | None") -> Entry:
    data = {"id": entry_id, "shape": shape}
    if host_role is not None:
        data["hostRole"] = host_role
    return Entry(id=entry_id, kind="combination", partition=f"combinations/{shape}",
                 path=f"combinations/{entry_id}.json", data=data)


class _FakeMetric:
    def __init__(self, id_, covers):
        self.id = id_
        self.covers = covers


class CoverageReportTests(unittest.TestCase):
    def test_every_w1_scope_row_currently_registered_is_claimed(self) -> None:
        # This is the acceptance criterion itself: run it against the REAL registry, not a fake
        # one, so a future metric that forgets to declare `covers` is caught immediately.
        code = main(["metrics", "--coverage"])
        self.assertEqual(code, EXIT_CLEAN)

    def test_an_in_scope_row_with_no_covering_metric_is_unclaimed_not_hidden(self) -> None:
        rows = (AppendixARow(99, "a hypothetical missing check", "TestFamily", True),)
        import seedsmith.metrics.appendix_a as appendix_a_module
        original = appendix_a_module.ROWS
        appendix_a_module.ROWS = rows
        try:
            report = coverage_report([])
            self.assertEqual(len(report["unclaimed"]), 1)
            self.assertEqual(report["unclaimed"][0].number, 99)
        finally:
            appendix_a_module.ROWS = original

    def test_an_out_of_scope_row_with_no_covering_metric_is_a_known_gap_not_unclaimed(self) -> None:
        rows = (AppendixARow(100, "planner work, W2", "Feasibility", False),)
        import seedsmith.metrics.appendix_a as appendix_a_module
        original = appendix_a_module.ROWS
        appendix_a_module.ROWS = rows
        try:
            report = coverage_report([])
            self.assertEqual(report["unclaimed"], [])
            self.assertEqual(len(report["known_gap"]), 1)
        finally:
            appendix_a_module.ROWS = original

    def test_a_claimed_row_lists_the_covering_metric_id(self) -> None:
        rows = (AppendixARow(101, "d", "F", True),)
        import seedsmith.metrics.appendix_a as appendix_a_module
        original = appendix_a_module.ROWS
        appendix_a_module.ROWS = rows
        try:
            metric = _FakeMetric("Family/Thing", ("appendix-a:101",))
            report = coverage_report([metric])
            self.assertEqual(len(report["claimed"]), 1)
            row, ids = report["claimed"][0]
            self.assertEqual(row.number, 101)
            self.assertEqual(ids, ["Family/Thing"])
        finally:
            appendix_a_module.ROWS = original


class HostRoleDiversityTests(unittest.TestCase):
    """strain-splice-host SSH2.7: `Coverage/HostRoleDiversity` is a READING, never a gate.

    A test that pins today's host-role shares guards nothing — it fails the day content ships, and
    its "fix" is to bump the number (validation-ssot's rule). What is asserted here is the
    ENVELOPE: every entry lands in exactly one bucket per shape, the buckets are the offered set
    plus "no role" plus any stale pin, the reading is reproducible from the same input, and nothing
    it reports is ever GAP.
    """

    #: A role id no tuning revision will ever offer. Named for what it is, so the out-of-offered
    #: bucket is exercised without depending on which ceilings the shipped file happens to carry.
    NEVER_OFFERED = "fixture-never-offered-role"

    @staticmethod
    def _offered() -> "tuple[str, ...]":
        return tuning_mod.load().host_roles()

    def _corpus(self) -> Corpus:
        corpus = Corpus()
        for entry in (
            _combination("combo.strain-a", "strain", "armament-primary"),
            _combination("combo.strain-b", "strain", "armament-primary"),
            _combination("combo.strain-c", "strain", "core-guard"),
            _combination("combo.strain-d", "strain", None),
            _combination("combo.strain-e", "strain", self.NEVER_OFFERED),
            _combination("combo.splice-a", "splice", None),
            _combination("combo.splice-b", "splice", "core-guard"),
        ):
            corpus.add(entry)
        return corpus

    def test_host_role_diversity_is_a_reading_not_a_gate(self) -> None:
        metric = HostRoleDiversityMetric()
        self.assertFalse(metric.gates)
        findings = metric.run(Ctx(corpus=self._corpus(), adapter=None))
        self.assertTrue(findings)
        # Never GAP: a plain `check` prints this reading without failing it.
        self.assertTrue(all(f.severity is Severity.NOTE for f in findings),
                        [(f.subject, f.severity) for f in findings])

        by_shape: "dict[str, list]" = {}
        for finding in findings:
            by_shape.setdefault(finding.evidence["shape"], []).append(finding)
        self.assertEqual({"splice", "strain"}, set(by_shape))
        for shape, rows in by_shape.items():
            totals = {r.evidence["entries"] for r in rows}
            self.assertEqual(1, len(totals), f"{shape} rows disagree about the denominator")
            # The envelope: the entry counts sum to the shape's own population, exactly once each.
            self.assertEqual(next(iter(totals)),
                             sum(r.evidence["pinned"] for r in rows), shape)

        # Every offered role is printed, even at zero — "the helm is never chosen" is the reading.
        strain_roles = {r.evidence["hostRole"] for r in by_shape["strain"]}
        self.assertTrue(set(self._offered()) <= strain_roles)
        self.assertIn(None, strain_roles)          # the "no role" bucket
        stale = next(r for r in by_shape["strain"]
                     if r.evidence["hostRole"] == self.NEVER_OFFERED)
        self.assertFalse(stale.evidence["offered"])   # visible, and still never a GAP
        self.assertEqual(1, stale.evidence["pinned"])

        # Reproducible from the same input, byte for byte.
        again = metric.run(Ctx(corpus=self._corpus(), adapter=None))
        self.assertEqual([f.to_dict() for f in findings], [f.to_dict() for f in again])


if __name__ == "__main__":
    unittest.main()
