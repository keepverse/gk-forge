"""Tests for A-S7's CLI entrypoint, `generate_coverage_assignment.py`
(spec-coverage-assignment.md SS7). Model-free.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.actions import generate_coverage_assignment as gen_mod  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_PLAN_PATH = REPO_ROOT / "data" / "seed" / "actions" / "_briefs" / "round-1.json"
REAL_USAGE_DIR = REPO_ROOT / "docs" / "research" / "action-corpus"


def _write_plan(tmp_dir: Path, entries: list) -> Path:
    doc = {"schemaVersion": 1, "kind": "action-brief", "_meta": {}, "entries": entries}
    path = tmp_dir / "plan.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


class WrongKindRefusalTests(unittest.TestCase):
    def test_a_non_action_brief_envelope_is_refused_naming_the_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            path.write_text(json.dumps({"kind": "action-review", "entries": []}), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                gen_mod.regenerate(plan_path=path, write=False)
            self.assertIn("action-review", str(ctx.exception))


class DryRunTests(unittest.TestCase):
    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            entries = [{"briefId": "b1", "pairing": {"role": "none"},
                       "pool": {"allowedAtomFamilies": [], "forbiddenAtomFamilies": []}}]
            plan_path = _write_plan(tmp_path, entries)
            before = plan_path.read_text(encoding="utf-8")
            summary = gen_mod.regenerate(plan_path=plan_path, usage_reports_dir=tmp_path / "no-reports",
                                         write=False)
            after = plan_path.read_text(encoding="utf-8")
            self.assertEqual(before, after)
            self.assertFalse(summary["written"])


class RealRunTests(unittest.TestCase):
    def test_real_run_preserves_every_existing_brief_field_byte_identical(self) -> None:
        """A-S7 is ADDITIVE: re-running it changes `requiredFamilies` (and nothing else) on every
        brief. `requiredFamilies` is stripped from BOTH sides — comparing the freshly assigned value
        against a previously assigned one would assert "the assignment never changes", which is not
        the contract and is false the moment the payoff-exclusion rule (G1, 2026-09-12) or the usage
        report moves. The contract is: every OTHER field survives untouched."""
        if not REAL_PLAN_PATH.is_file():
            self.skipTest("round-1.json not yet generated in this checkout")
        original = json.loads(REAL_PLAN_PATH.read_text(encoding="utf-8"))
        original_entries = copy.deepcopy(original["entries"])

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.json"
            gen_mod.regenerate(plan_path=REAL_PLAN_PATH, usage_reports_dir=REAL_USAGE_DIR,
                              plan_out_path=out_path, write=True)
            updated = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(len(updated["entries"]), len(original_entries))
        by_id = {e["briefId"]: e for e in updated["entries"]}
        for original_entry in original_entries:
            updated_entry = by_id[original_entry["briefId"]]
            self.assertIn("requiredFamilies", updated_entry)
            without_new = {k: v for k, v in updated_entry.items() if k != "requiredFamilies"}
            original_without = {k: v for k, v in original_entry.items() if k != "requiredFamilies"}
            self.assertEqual(without_new, original_without,
                             f"{original_entry['briefId']}: a field other than requiredFamilies moved")

    def test_omitted_usage_report_dir_falls_back_to_the_real_default(self) -> None:
        if not REAL_PLAN_PATH.is_file():
            self.skipTest("round-1.json not yet generated in this checkout")
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.json"
            summary = gen_mod.regenerate(plan_path=REAL_PLAN_PATH, plan_out_path=out_path, write=True)
        self.assertTrue(summary["usageReportUsed"], "the real committed FC1 report should be found")

    def test_no_usage_report_directory_still_produces_an_assignment(self) -> None:
        if not REAL_PLAN_PATH.is_file():
            self.skipTest("round-1.json not yet generated in this checkout")
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.json"
            summary = gen_mod.regenerate(plan_path=REAL_PLAN_PATH,
                                         usage_reports_dir=Path(tmp) / "does-not-exist",
                                         plan_out_path=out_path, write=True)
        self.assertFalse(summary["usageReportUsed"])
        self.assertGreater(summary["totalBriefs"], 0)


if __name__ == "__main__":
    unittest.main()
