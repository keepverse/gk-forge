"""Tests for A-S7 `coverage-assignment` (spec-coverage-assignment.md, action-corpus program).

    python -m pytest gk-forge/tools/seedsmith/tests/test_coverage_assignment.py -v

Model-free throughout -- no transport import anywhere in this module or the one it tests.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.actions.coverage_assignment.derive import (  # noqa: E402
    MissingForcedEnablerError, assign_required_families, load_current_usage,
    sort_population_by_usage, splice_payoff_enablers, usage_counts_from_report,
)
from seedsmith.adapters.actions.vocab import load_family_ids  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
USAGE_REPORTS_DIR = REPO_ROOT / "docs" / "research" / "action-corpus"
ACTIONS_ROOT = REPO_ROOT / "data" / "seed" / "actions"
PLAN_PATH = ACTIONS_ROOT / "_briefs" / "round-1.json"
PAIRINGS_PATH = ACTIONS_ROOT / "pairings.json"
FAMILY_IDS = load_family_ids()


def _brief(brief_id: str, *, role: str = "none", paired_payoff_family=None, forced_enabler=None,
          allowed=None, forbidden=()) -> dict:
    return {
        "briefId": brief_id,
        "pairing": {"role": role, "pairedPayoffFamily": paired_payoff_family,
                   "forcedEnabler": forced_enabler},
        "pool": {"allowedAtomFamilies": list(allowed or FAMILY_IDS), "forbiddenAtomFamilies": list(forbidden)},
    }


class UsageCountsFromReportTests(unittest.TestCase):
    def test_never_used_families_default_to_zero_not_absent(self) -> None:
        report = {"allTime": {"counts": {"atom.a": 5}, "neverUsed": ["atom.b", "atom.c"]}}
        counts = usage_counts_from_report(report)
        self.assertEqual(counts["atom.a"], 5)
        self.assertEqual(counts["atom.b"], 0)
        self.assertEqual(counts["atom.c"], 0)

    def test_a_never_used_family_already_in_counts_is_not_overwritten(self) -> None:
        # Defensive: neverUsed should never actually overlap with a nonzero count, but setdefault
        # (not assignment) is what makes that a non-issue even if it somehow did.
        report = {"allTime": {"counts": {"atom.a": 5}}, "allTime_extra": None}
        report["allTime"]["neverUsed"] = ["atom.a"]
        counts = usage_counts_from_report(report)
        self.assertEqual(counts["atom.a"], 5)


class LoadCurrentUsageTests(unittest.TestCase):
    def test_no_report_directory_returns_empty_map_not_an_error(self, ) -> None:
        empty = load_current_usage(REPO_ROOT / "does" / "not" / "exist")
        self.assertEqual(empty, {})

    def test_the_real_committed_report_loads_for_real(self) -> None:
        counts = load_current_usage(USAGE_REPORTS_DIR)
        self.assertIsInstance(counts, dict)
        self.assertGreater(len(counts), 0)
        self.assertIn("atom.chill-punisher", counts)  # a real, currently 0-usage family


class SortPopulationByUsageTests(unittest.TestCase):
    def test_two_zero_usage_families_break_the_tie_by_id(self) -> None:
        ordered = sort_population_by_usage(["atom.z", "atom.a"], {})
        self.assertEqual(ordered, ["atom.a", "atom.z"])

    def test_a_used_family_sorts_after_an_unused_one_regardless_of_id(self) -> None:
        ordered = sort_population_by_usage(["atom.a", "atom.z"], {"atom.a": 5})
        self.assertEqual(ordered, ["atom.z", "atom.a"])

    def test_sort_is_stable_and_deterministic_across_two_calls(self) -> None:
        ids = ["atom.q", "atom.b", "atom.m", "atom.a"]
        counts = {"atom.q": 2, "atom.b": 2, "atom.m": 0}
        self.assertEqual(sort_population_by_usage(ids, counts), sort_population_by_usage(ids, counts))

    def test_duplicate_ids_in_the_input_are_deduped(self) -> None:
        ordered = sort_population_by_usage(["atom.a", "atom.a", "atom.b"], {})
        self.assertEqual(ordered, ["atom.a", "atom.b"])


class PairingBriefRequirementTests(unittest.TestCase):
    def test_payoff_brief_requires_its_own_payoff_family(self) -> None:
        entries = [_brief("b1", role="payoff", paired_payoff_family="atom.chill-punisher")]
        out = assign_required_families(entries, usage_counts={}, family_ids=FAMILY_IDS)
        self.assertEqual(out["b1"], ["atom.chill-punisher"])

    def test_enabler_brief_requires_its_own_forced_enabler(self) -> None:
        entries = [_brief("b1", role="enabler", paired_payoff_family="atom.chill-punisher",
                          forced_enabler="atom.freezing")]
        out = assign_required_families(entries, usage_counts={}, family_ids=FAMILY_IDS)
        self.assertEqual(out["b1"], ["atom.freezing"])

    def test_an_enabler_brief_missing_forced_enabler_is_refused_by_name(self) -> None:
        entries = [_brief("b1", role="enabler", paired_payoff_family="atom.chill-punisher",
                          forced_enabler=None)]
        with self.assertRaises(MissingForcedEnablerError) as ctx:
            assign_required_families(entries, usage_counts={}, family_ids=FAMILY_IDS)
        self.assertIn("b1", str(ctx.exception))
        self.assertIn("forcedEnabler", str(ctx.exception))

    def test_pairing_briefs_never_consume_the_round_robin_cursor(self) -> None:
        """A payoff/enabler brief's required family comes from its own pairing data, not the
        rotation -- proven by checking the NEXT none-role brief still gets population[0], not
        population[1] (i.e. the pairing brief didn't silently advance the cursor)."""
        entries = [
            _brief("b1", role="payoff", paired_payoff_family="atom.chill-punisher"),
            _brief("b2", role="none"),
        ]
        least_used = sort_population_by_usage(FAMILY_IDS, {})[0]
        out = assign_required_families(entries, usage_counts={}, family_ids=FAMILY_IDS)
        self.assertEqual(out["b2"], [least_used])


class RoundRobinTests(unittest.TestCase):
    def test_none_role_briefs_advance_a_global_cursor_never_per_subject(self) -> None:
        population = sort_population_by_usage(FAMILY_IDS, {})
        entries = [_brief(f"b{i}", role="none") for i in range(5)]
        out = assign_required_families(entries, usage_counts={}, family_ids=FAMILY_IDS)
        for i in range(5):
            self.assertEqual(out[f"b{i}"], [population[i]])

    def test_every_population_member_is_covered_within_one_population_length(self) -> None:
        population = sort_population_by_usage(FAMILY_IDS, {})
        entries = [_brief(f"b{i}", role="none") for i in range(len(population))]
        out = assign_required_families(entries, usage_counts={}, family_ids=FAMILY_IDS)
        assigned = {v[0] for v in out.values() if v}
        self.assertEqual(assigned, set(population))

    def test_the_rotation_wraps_around_past_the_population_length(self) -> None:
        population = sort_population_by_usage(FAMILY_IDS, {})
        entries = [_brief(f"b{i}", role="none") for i in range(len(population) + 3)]
        out = assign_required_families(entries, usage_counts={}, family_ids=FAMILY_IDS)
        self.assertEqual(out["b0"], out[f"b{len(population)}"])

    def test_a_forbidden_candidate_is_skipped_never_assigned(self) -> None:
        population = sort_population_by_usage(FAMILY_IDS, {})
        least_used = population[0]
        entries = [_brief("b0", role="none", forbidden=[least_used])]
        out = assign_required_families(entries, usage_counts={}, family_ids=FAMILY_IDS)
        self.assertNotEqual(out["b0"], [least_used])
        self.assertEqual(out["b0"], [population[1]])

    def test_an_all_conflict_fixture_degrades_to_empty_never_raises(self) -> None:
        small_population = ["atom.only-one"]
        entries = [_brief("b0", role="none", forbidden=["atom.only-one"])]
        out = assign_required_families(entries, usage_counts={}, family_ids=small_population)
        self.assertEqual(out["b0"], [])

    def test_rerun_with_identical_inputs_is_byte_identical(self) -> None:
        entries = [_brief(f"b{i}", role="none") for i in range(10)]
        a = assign_required_families(entries, usage_counts={"atom.might": 3}, family_ids=FAMILY_IDS)
        b = assign_required_families(entries, usage_counts={"atom.might": 3}, family_ids=FAMILY_IDS)
        self.assertEqual(a, b)


class RealDataProofTests(unittest.TestCase):
    """SS9's own real-data integration proof -- zero model calls, real committed evidence."""

    def test_every_real_never_used_family_is_covered_within_the_first_pass(self) -> None:
        usage_counts = load_current_usage(USAGE_REPORTS_DIR)
        if not usage_counts:
            self.skipTest("no real FC1 usage report committed in this checkout")
        never_used = {f for f, c in usage_counts.items() if c == 0}
        self.assertTrue(never_used, "the real report should name at least one never-used family")

        population = sort_population_by_usage(FAMILY_IDS, usage_counts)
        entries = [_brief(f"b{i}", role="none") for i in range(len(population))]
        out = assign_required_families(entries, usage_counts=usage_counts, family_ids=FAMILY_IDS)
        assigned = {v[0] for v in out.values() if v}
        missing = never_used - assigned
        self.assertEqual(missing, set(),
                         f"real never-used families never assigned within one full pass: {missing}")


class PayoffExclusionTests(unittest.TestCase):
    """G1 (2026-09-12): the non-pairing round-robin must never require a payoff key, because only a
    `role: payoff` brief carries a matching enabler and species-scope briefs are never pairing briefs.
    Measured before the fix: 74 live anchors required `atom.rot-punisher` with no possible enabler."""

    PAYOFFS = ("atom.rot-punisher", "atom.chill-punisher")

    def test_round_robin_never_assigns_a_payoff_key(self) -> None:
        population = [f for f in FAMILY_IDS if f not in self.PAYOFFS]
        entries = [_brief(f"b{i}", role="none") for i in range(len(FAMILY_IDS) * 2)]
        out = assign_required_families(entries, usage_counts={}, family_ids=FAMILY_IDS,
                                      payoff_families=self.PAYOFFS)
        assigned = {v[0] for v in out.values() if v}
        self.assertEqual(assigned & set(self.PAYOFFS), set(),
                         "a payoff key reached a role:none brief")
        self.assertEqual(assigned, set(population))

    def test_a_pairing_brief_still_names_its_payoff_key(self) -> None:
        entry = {"briefId": "b0", "pairing": {"role": "payoff",
                                              "pairedPayoffFamily": "atom.rot-punisher"}}
        out = assign_required_families([entry], usage_counts={}, family_ids=FAMILY_IDS,
                                       payoff_families=self.PAYOFFS)
        self.assertEqual(out["b0"], ["atom.rot-punisher"])

    def test_default_payoff_set_is_backward_compatible(self) -> None:
        entries = [_brief(f"b{i}", role="none") for i in range(len(FAMILY_IDS))]
        with_default = assign_required_families(entries, usage_counts={}, family_ids=FAMILY_IDS)
        population = sort_population_by_usage(FAMILY_IDS, {})
        self.assertEqual(with_default["b0"], [population[0]])


class RealPlanPayoffTests(unittest.TestCase):
    """G1 against the REAL committed plan: no `role: none` brief requires a payoff key, and both
    payoff keys stay covered through their own pairing briefs (the fix loses no coverage)."""

    def test_no_real_none_brief_requires_a_payoff_key(self) -> None:
        if not PLAN_PATH.is_file() or not PAIRINGS_PATH.is_file():
            self.skipTest("real plan/pairings not present in this checkout")
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        pairings = json.loads(PAIRINGS_PATH.read_text(encoding="utf-8"))
        payoffs = set(pairings)
        offenders = [e["briefId"] for e in plan["entries"]
                     if (e.get("pairing") or {}).get("role") == "none"
                     and set(e.get("requiredFamilies") or ()) & payoffs]
        self.assertEqual(offenders, [], f"{len(offenders)} role:none briefs require a payoff key")

    def test_real_payoff_keys_stay_covered_by_pairing_briefs(self) -> None:
        if not PLAN_PATH.is_file() or not PAIRINGS_PATH.is_file():
            self.skipTest("real plan/pairings not present in this checkout")
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        pairings = json.loads(PAIRINGS_PATH.read_text(encoding="utf-8"))
        covered = {e["pairing"]["pairedPayoffFamily"] for e in plan["entries"]
                   if (e.get("pairing") or {}).get("role") == "payoff"}
        self.assertEqual(covered, set(pairings),
                         "every payoff key must be required by a real pairing brief")


class SplicePayoffEnablersTests(unittest.TestCase):
    """G2 (2026-09-12): a model-picked payoff key gains its enabler deterministically, so an accepted
    species row can never carry a payoff with no same-anchor enabler."""

    TABLE = {"atom.rot-punisher": ["atom.venomous", "atom.withering", "atom.bloodletting"]}

    def test_payoff_pick_gains_its_first_allowed_enabler(self) -> None:
        out = splice_payoff_enablers(
            ["atom.rot-punisher", "atom.might"], pairing_table=self.TABLE,
            allowed_atom_families=["atom.might", "atom.withering", "atom.venomous"])
        self.assertIn("atom.venomous", out)
        self.assertEqual(out, sorted(out))

    def test_existing_enabler_is_not_duplicated(self) -> None:
        out = splice_payoff_enablers(
            ["atom.rot-punisher", "atom.withering"], pairing_table=self.TABLE,
            allowed_atom_families=["atom.withering"])
        self.assertEqual(out, ["atom.rot-punisher", "atom.withering"])

    def test_no_allowed_enabler_adds_nothing(self) -> None:
        out = splice_payoff_enablers(
            ["atom.rot-punisher"], pairing_table=self.TABLE,
            allowed_atom_families=["atom.might"])
        self.assertEqual(out, ["atom.rot-punisher"])

    def test_non_payoff_input_is_unchanged(self) -> None:
        out = splice_payoff_enablers(["atom.might", "atom.swift"], pairing_table=self.TABLE,
                                     allowed_atom_families=["atom.might", "atom.swift"])
        self.assertEqual(out, ["atom.might", "atom.swift"])

    def test_deterministic(self) -> None:
        args = (["atom.rot-punisher"],)
        kwargs = dict(pairing_table=self.TABLE, allowed_atom_families=["atom.withering"])
        self.assertEqual(splice_payoff_enablers(*args, **kwargs),
                         splice_payoff_enablers(*args, **kwargs))


if __name__ == "__main__":
    unittest.main()
