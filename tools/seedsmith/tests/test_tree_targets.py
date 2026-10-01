"""Tests for seedsmith.adapters.trees.targets (task A2, tasks/passive-tree-todo.md).

    python -m pytest gk-forge/tools/seedsmith/tests/test_tree_targets.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dataclasses
from seedsmith.workspace_roots import core_root  # noqa: E402

from seedsmith.adapters.trees.targets import (  # noqa: E402
    PassiveTreeTargetsError,
    load,
    missing_thresholds,
)


def write(root: Path, doc: dict) -> Path:
    path = root / "targets.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def base_doc() -> dict:
    """A minimal, structurally complete document — every test mutates a copy of this."""
    return {
        "version": 1,
        "quotas": {
            "aptitude": {"weightScheme": "uniform"},
            "nodeClass": {"weightsMilli": [500, 500], "_order": ["mechanism", "magnitude"]},
            "exclusionForm": {
                "weightsMilli": [450, 450, 100],
                "_order": ["reroute", "precedence", "nullification"],
            },
        },
        "legitimateSkew": {"rows": []},
        "exclusion": {"targetShareMilli": 20},
        "speciesUniqueAffixMin": 8,
        "sampling": {
            "tier2SampleSize": 60,
            "tier3AdditionalSampleSize": 30,
            "acceptanceLadder": [
                {"rejectsIn60": 0, "upperBoundPermille95": 48, "verdict": "accept"},
            ],
        },
        "gates": {
            "cellOccupancy": {"medianMax": 2},
            "quotaDrift": {"toleranceUnits": 1},
            "mechanismRamp": {"deepestTierShareMilli": 1000},
            "exclusionRate": {"maxSharePermille": 30},
            "nearDuplicateRate": {"maxSharePermille": 5},
            "unresolvedCount": {"maxSharePermille": 50},
        },
    }


class LiveTargetsTests(unittest.TestCase):
    def test_the_live_shipped_file_loads_cleanly(self) -> None:
        targets = load()  # default path: data/tuning/passive-tree-targets.v2.json
        self.assertEqual(targets.exclusion_target_share_milli, 20)
        self.assertEqual(targets.species_unique_affix_min, 8)
        self.assertEqual(targets.cell_occupancy_median_max, 2)
        self.assertEqual(targets.unresolved_count_max_share_permille, 50)
        self.assertEqual(missing_thresholds(targets), [])

    def test_the_live_file_has_no_missing_thresholds(self) -> None:
        # spec-tree-language.md §7 gate 5: "every gate has a threshold" — asserted against the real
        # shipped file, not only a synthetic fixture.
        targets = load()
        self.assertEqual(missing_thresholds(targets), [],
                         "every PassiveTree gate this module claims must resolve to a number")


class MissingKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())

    def test_a_missing_top_level_key_is_refused_naming_it(self) -> None:
        doc = base_doc()
        del doc["speciesUniqueAffixMin"]
        path = write(self.root, doc)
        with self.assertRaises(PassiveTreeTargetsError) as ex:
            load(path)
        self.assertIn("speciesUniqueAffixMin", str(ex.exception))

    def test_a_missing_nested_gate_key_is_refused_naming_it(self) -> None:
        doc = base_doc()
        del doc["gates"]["unresolvedCount"]
        path = write(self.root, doc)
        with self.assertRaises(PassiveTreeTargetsError) as ex:
            load(path)
        self.assertIn("unresolvedCount", str(ex.exception))
        self.assertIn("maxSharePermille", str(ex.exception))


class LegitimateSkewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())

    def test_empty_skew_rows_load_cleanly(self) -> None:
        path = write(self.root, base_doc())
        targets = load(path)
        self.assertEqual(targets.legitimate_skew_rows, ())

    def test_a_skew_row_without_a_why_is_refused(self) -> None:
        doc = base_doc()
        doc["legitimateSkew"]["rows"] = [
            {"axis": "element", "member": "earth", "weightMilli": 1500, "_why": ""}
        ]
        path = write(self.root, doc)
        with self.assertRaises(PassiveTreeTargetsError) as ex:
            load(path)
        self.assertIn("_why", str(ex.exception))

    def test_a_skew_row_with_a_stated_why_loads_cleanly(self) -> None:
        doc = base_doc()
        doc["legitimateSkew"]["rows"] = [
            {"axis": "element", "member": "earth", "weightMilli": 1500,
             "_why": "D32's worked example — earth roughly 1.5x uniform"}
        ]
        path = write(self.root, doc)
        targets = load(path)
        self.assertEqual(len(targets.legitimate_skew_rows), 1)
        self.assertEqual(targets.legitimate_skew_rows[0].axis, "element")


class GateThresholdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())

    def test_a_gate_removed_entirely_fails_the_strict_loader_naming_it(self) -> None:
        # The strict load path (gate 4, "the target file is complete") catches this before
        # missing_thresholds() ever runs — `_require` refuses on the missing nested key.
        doc = base_doc()
        del doc["gates"]["nearDuplicateRate"]
        path = write(self.root, doc)
        with self.assertRaises(PassiveTreeTargetsError) as ex:
            load(path)
        self.assertIn("nearDuplicateRate", str(ex.exception))

    def test_missing_thresholds_lists_a_gate_left_unresolved_on_an_already_parsed_object(self) -> None:
        # Gate 5 ("every gate has a threshold") is a SEPARATE, softer check from gate 4's strict
        # completeness — it exists to protect against a future GATING_METRICS entry added without
        # a matching load()/_require wire-up, which the strict loader alone cannot catch (a
        # dataclass field can't go missing through `_require`, but a newly-added GATING_METRICS
        # key with no matching attribute name can). Exercised directly on a hand-built object, since
        # `load()` itself can never produce one with a None threshold.
        targets = load()  # start from a fully valid, loaded object
        broken = dataclasses.replace(targets, near_duplicate_rate_max_share_permille=None)
        missing = missing_thresholds(broken)
        self.assertEqual(missing, ["PassiveTree/NearDuplicate"])

    def test_a_fully_loaded_object_never_has_a_missing_threshold(self) -> None:
        self.assertEqual(missing_thresholds(load()), [])


class QuotaShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())

    def test_nodeClass_weights_must_sum_to_1000(self) -> None:
        doc = base_doc()
        doc["quotas"]["nodeClass"]["weightsMilli"] = [500, 400]
        path = write(self.root, doc)
        with self.assertRaises(PassiveTreeTargetsError) as ex:
            load(path)
        self.assertIn("1000", str(ex.exception))

    def test_exclusionForm_must_carry_exactly_three_forms(self) -> None:
        doc = base_doc()
        doc["quotas"]["exclusionForm"]["weightsMilli"] = [500, 500]
        doc["quotas"]["exclusionForm"]["_order"] = ["reroute", "precedence"]
        path = write(self.root, doc)
        with self.assertRaises(PassiveTreeTargetsError):
            load(path)

    def test_nullification_weight_must_be_non_zero(self) -> None:
        # D40: "nullification: 0" is explicitly superseded — all three forms must be reachable.
        doc = base_doc()
        doc["quotas"]["exclusionForm"]["weightsMilli"] = [500, 500, 0]
        path = write(self.root, doc)
        with self.assertRaises(PassiveTreeTargetsError) as ex:
            load(path)
        self.assertIn("nullification", str(ex.exception))

    def test_no_axis_lists_its_own_registry_driven_members(self) -> None:
        # A2's own acceptance bar: aptitude/trigger/element/status/channelFamily are registry-driven,
        # so the shipped file must carry a scheme marker for them, never a hardcoded member array —
        # a thirteenth aptitude (or an 8th status, etc.) must change the grid by construction alone
        # (spec-tree-language.md §4.3's own worked example names aptitude explicitly).
        live_root = core_root() / "data" / "tuning"
        raw = (live_root / "passive-tree-targets.v2.json").read_text(encoding="utf-8")
        doc = json.loads(raw)
        for axis in ("aptitude", "trigger", "element", "status", "channelFamily"):
            self.assertIn("weightScheme", doc["quotas"][axis],
                          f"{axis} must declare a scheme, not a member-keyed weight table")
            self.assertNotIn("weightsMilli", doc["quotas"][axis],
                             f"{axis} must not carry a literal per-member weights array")

    def test_aptitude_axis_loads_as_its_own_field(self) -> None:
        # Added 2026-09-06: spec-tree-language.md §4.3 names aptitude in the same "no axis lists its
        # own members" clause as element/status, but spec-tree-plan.md's own quota-axis table omits
        # it entirely (six rows, not seven) — a spec gap, closed here rather than silently dropped.
        targets = load()
        self.assertEqual(targets.aptitude_weight_scheme, "uniform")


if __name__ == "__main__":
    unittest.main()
