"""Tests for `seedsmith.metrics.passive_tree`'s eight H4 metrics (spec-tree-language.md §7 gates
15-22, tasks/passive-tree-todo.md's H4 entry), plus task H5's three `tree-review` metrics
(spec-tree-review.md §4.1, §4.2, §7).

Every test builds a synthetic corpus with an INJECTED defect, per the todo's own Verification
line ("a 166x skew, a missing deep-tier mechanism, a duplicated name across 300 trees") — this
file is where those three fixtures live, plus one per remaining metric. `QuotaDrift`/
`MechanismRamp`/`CellOccupancy` lean on the REAL committed `might.v1.json` plan and the REAL
`passive-tree-targets.v2.json` (the same `plan_read.load("might")` / `tuning.load()` /
`quota.quota_for_plan(...)` triple `test_nodegen_quota.py`'s own H3 integration tests already use)
so a re-derivation defect is measured against real quota arithmetic, not a hand-tuned toy.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from seedsmith.adapters.trees.nodegen import exclusion as nodegen_exclusion
from seedsmith.adapters.trees.nodegen import plan_read, quota, tuning
from seedsmith.adapters.trees.species import plan as species_plan
from seedsmith.adapters.trees.targets import PassiveTreeTargets
from seedsmith.metrics.model import Ctx, Loop, Severity
from seedsmith.metrics.passive_tree import (
    ALL_PASSIVE_TREE_METRICS,
    CellOccupancyMetric,
    DeepMechanismValueMetric,
    ExclusionRateMetric,
    ExclusionResolvableMetric,
    ExclusionPresentationMetric,
    FavourDriftMetric,
    HiddenFileCountMetric,
    MechanismRampMetric,
    NameCollisionMetric,
    NearDuplicateMetric,
    PassiveTreePlanCtx,
    QuotaDriftMetric,
    SpeciesUniquenessMetric,
    TreeEqualValueMetric,
    UnresolvedCountMetric,
    check_bound_prices_honour_budget,
)
from seedsmith.metrics.registry import MetricRegistry, run_all


def _gap_findings(findings):
    return [f for f in findings if f.severity == Severity.GAP]


def _real_might_plan_and_targets():
    plan = plan_read.load("might")
    targets = tuning.load()
    return plan, targets


#: Genuinely lexically-distinct words (no two share enough 5-gram shingles to cross the exact-
#: Jaccard near-duplicate threshold) — `f"Node {node_id}"`-style names were tried first and FAILED
#: this exact requirement (two ids differing by one trailing digit are themselves a near-duplicate
#: pair by 5-gram Jaccard), which is real signal from this test file, not a fixture inconvenience:
#: it is exactly why `NearDuplicate` exists.
_DISTINCT_WORDS: "tuple[str, ...]" = (
    "Aardvark", "Basilisk", "Chimera", "Draconic", "Ember", "Falcon", "Griffin", "Hollowmere",
    "Ibex", "Jackal", "Kestrel", "Lynxhaven", "Mirage", "Nomadic", "Obelisk", "Phoenix", "Quartzite",
    "Ravenshade", "Sphinxrock", "Talonwing", "Umbra", "Vortexial", "Wyrmling", "Xenolith", "Yewbranch",
    "Zephyrus", "Anchorite", "Brambleheart", "Cinderfall", "Duskwalker", "Frostbite", "Glacialis",
    "Hearthstone", "Ironclad", "Jadewind", "Knightfall", "Lanternlight", "Moonshadow", "Nightbloom",
    "Oakenshield", "Pinewood", "Quicksilver", "Riverstone", "Stormcaller", "Thundercrag",
    "Underbrush", "Vinewhisper", "Willowmere", "Xylophage", "Zenithcall",
)


def _distinct_name(index: int) -> str:
    if index >= len(_DISTINCT_WORDS):
        raise ValueError(f"need a bigger word pool for index {index}")
    return _DISTINCT_WORDS[index]


def _clean_might_corpus():
    """The real `might` plan, a freshly re-derived quota assignment (so QuotaDrift/CellOccupancy
    start clean), and a synthetic-but-consistent `nodes_by_tree`/`outcomes_by_tree` built FROM that
    same plan — every node's `nodeClass` copied from the plan (so MechanismRamp starts clean too),
    every exclusion `none` (so ExclusionRate starts clean), every name lexically distinct (so
    NearDuplicate/NameCollision start clean), every outcome `accepted` (so UnresolvedCount starts
    clean)."""
    plan, targets = _real_might_plan_and_targets()
    cells = quota.quota_for_plan(plan, targets, category="primary")
    nodes = [
        {"id": n.node_id, "nodeClass": n.node_class, "name": _distinct_name(i),
         "nameKey": f"tree.node.{n.index_in_tier}-{n.tier}-{n.branch}",
         "exclusion": {"form": "none", "propertyKeys": [], "printedText": ""}}
        for i, n in enumerate(plan.nodes)
    ]
    outcomes = [{"nodeId": n.node_id, "outcome": "accepted"} for n in plan.nodes]
    return plan, targets, cells, nodes, outcomes


def _ctx_with(plan_ctx: PassiveTreePlanCtx) -> Ctx:
    return Ctx(corpus=None, adapter=None, passive_tree_plan=plan_ctx)


class QuotaDriftMetricTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan, self.targets, self.cells, _, _ = _clean_might_corpus()
        self.metric = QuotaDriftMetric()

    def _ctx(self, cells) -> Ctx:
        return _ctx_with(PassiveTreePlanCtx(
            plans=[self.plan.raw], archetypes=(), tier_count=10, unlock_first_points=0,
            unlock_step_points=0, reward_spread_max_ratio_milli=0, min_terminal_width=0,
            targets=self.targets, tree_plans=(self.plan,),
            quota_cells_by_tree={"might": cells}))

    def test_reports_not_measured_with_no_context(self) -> None:
        ctx = _ctx_with(PassiveTreePlanCtx(plans=[], archetypes=(), tier_count=10,
                                            unlock_first_points=0, unlock_step_points=0,
                                            reward_spread_max_ratio_milli=0, min_terminal_width=0))
        findings = self.metric.run(ctx)
        self.assertTrue(all(f.severity == Severity.NOT_MEASURED for f in findings))
        self.assertTrue(findings)

    def test_the_real_freshly_re_derived_corpus_has_no_drift(self) -> None:
        findings = self.metric.run(self._ctx(self.cells))
        self.assertEqual(_gap_findings(findings), [])
        self.assertTrue(findings)  # NOTE rows are still emitted, mirroring quota_drift_findings

    def test_a_166x_skew_is_caught_in_both_directions(self) -> None:
        """Force every node's `trigger` value to the SAME one id — a corpus-wide skew far past
        `toleranceUnits=1` on both the flooded value (huge overshoot) and every drained one
        (undershoot to zero) — the todo's own named '166x skew' fixture shape."""
        skewed = dict(self.cells)
        flood_value = next(iter(skewed.values())).trigger
        from dataclasses import replace
        skewed = {node_id: replace(cell, trigger=flood_value) for node_id, cell in skewed.items()}
        findings = self.metric.run(self._ctx(skewed))
        gaps = _gap_findings(findings)
        self.assertTrue(gaps, "a corpus-wide trigger skew must be caught")
        # the flooded value overshoots
        self.assertTrue(any(f.evidence["value"] == flood_value and f.evidence["driftUnits"] > 1
                            for f in gaps if f.evidence.get("axis") == "trigger"))
        # at least one other trigger value is starved to zero
        self.assertTrue(any(f.evidence["value"] != flood_value and f.evidence["driftUnits"] < -1
                            for f in gaps if f.evidence.get("axis") == "trigger"))

    def test_a_lying_declared_quota_annotation_does_not_prevent_catching_real_drift(self) -> None:
        """The acceptance bullet's own wording: 'catches a mutated brief because it re-derives
        rather than reads.' Simulated here as a bogus self-reported target embedded in the plan's
        own `raw` blob (the shape a 'declared quota' annotation would take) claiming everything is
        fine — this metric never reads that key at all, so real drift introduced alongside it is
        still caught exactly as if the lying annotation were never there."""
        from dataclasses import replace
        lying_raw = dict(self.plan.raw)
        lying_raw["_declaredQuota"] = {"trigger": {"anything": "the corpus is fine, trust me"}}
        lying_plan = replace(self.plan, raw=lying_raw)

        drifted = dict(self.cells)
        # corrupt one real node's assigned element away from what quota_for_plan would recompute
        some_id = next(iter(drifted))
        real_cell = quota.quota_for_plan(self.plan, self.targets, category="primary")[some_id]
        other_element = next(v for v in ("fire", "water", "earth", "omni")
                             if v != real_cell.element)
        drifted[some_id] = replace(real_cell, element=other_element)
        # push every other node needing that other_element hard enough to exceed tolerance
        bumped = 0
        for node_id, cell in list(drifted.items()):
            if node_id != some_id and cell.element == real_cell.element and bumped < 5:
                drifted[node_id] = replace(cell, element=other_element)
                bumped += 1

        ctx = _ctx_with(PassiveTreePlanCtx(
            plans=[lying_raw], archetypes=(), tier_count=10, unlock_first_points=0,
            unlock_step_points=0, reward_spread_max_ratio_milli=0, min_terminal_width=0,
            targets=self.targets, tree_plans=(lying_plan,),
            quota_cells_by_tree={"might": drifted}))
        findings = self.metric.run(ctx)
        gaps = _gap_findings(findings)
        self.assertTrue(gaps, "real drift must still be caught even beside a lying declaration")
        self.assertTrue(any(f.evidence.get("axis") == "element" for f in gaps))


class MechanismRampMetricTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan, self.targets, _, self.nodes, _ = _clean_might_corpus()
        self.metric = MechanismRampMetric()

    def _ctx(self, nodes) -> Ctx:
        return _ctx_with(PassiveTreePlanCtx(
            plans=[self.plan.raw], archetypes=(), tier_count=10, unlock_first_points=0,
            unlock_step_points=0, reward_spread_max_ratio_milli=0, min_terminal_width=0,
            tree_plans=(self.plan,), nodes_by_tree={"might": nodes}))

    def test_the_clean_corpus_matches_every_tier_exactly(self) -> None:
        findings = self.metric.run(self._ctx(self.nodes))
        self.assertEqual(_gap_findings(findings), [])

    def test_tiers_four_through_seven_all_carry_the_identical_target_and_still_pass_exactly(self) -> None:
        """`might` is broad-and-flat: mechNodesByTier[3:7] == [1, 1, 1, 1] — every one of these four
        tiers needs EXACTLY one mechanism node per branch, and the clean corpus already supplies
        exactly that; a threshold-shaped check risks conflating them (the acceptance bullet's own
        warning), an exact per-tier count does not."""
        self.assertEqual(list(self.plan.mech_nodes_by_tier[3:7]), [1, 1, 1, 1])
        findings = self.metric.run(self._ctx(self.nodes))
        tier_subjects = {f"{self.plan.tree_id}:{b}:t{t}"
                         for b in ("offensive", "defensive") for t in (4, 5, 6, 7)}
        self.assertFalse(any(f.subject in tier_subjects for f in _gap_findings(findings)))

    def test_a_missing_deep_tier_mechanism_is_caught(self) -> None:
        """The todo's own named fixture: flip one tier-10 node from mechanism to magnitude — the
        per-tier exact count must fire for that (tree, branch, tier)."""
        broken = [dict(n) for n in self.nodes]
        tier10_offensive = next(
            n for n in broken
            if any(pn.node_id == n["id"] and pn.tier == 10 and pn.branch == "offensive"
                  for pn in self.plan.nodes) and n["nodeClass"] == "mechanism")
        tier10_offensive["nodeClass"] = "magnitude"
        findings = self.metric.run(self._ctx(broken))
        gaps = _gap_findings(findings)
        self.assertTrue(any(f.subject == f"{self.plan.tree_id}:offensive:t10" for f in gaps))

    def test_the_deepest_tier_structural_check_fires_on_a_plan_that_disagrees_with_its_own_archetype(
        self,
    ) -> None:
        """The `mechNodes[tierCount] == w[tierCount]` special case (R-M1) is a check over the
        PLAN's own declared numbers, not the emitted corpus — a real plan never disagrees with
        itself here (B1 already guarantees it at build time), so proving this half fires needs a
        plan object that lies about it, not a corpus mutation."""
        from dataclasses import replace
        lying_target = list(self.plan.mech_nodes_by_tier)
        lying_target[-1] = lying_target[-1] - 1  # deepest tier now claims LESS than 100% mechanism
        lying_plan = replace(self.plan, mech_nodes_by_tier=tuple(lying_target))
        ctx = _ctx_with(PassiveTreePlanCtx(
            plans=[self.plan.raw], archetypes=(), tier_count=10, unlock_first_points=0,
            unlock_step_points=0, reward_spread_max_ratio_milli=0, min_terminal_width=0,
            tree_plans=(lying_plan,), nodes_by_tree={"might": self.nodes}))
        findings = self.metric.run(ctx)
        gaps = _gap_findings(findings)
        self.assertTrue(any(f.subject == f"{self.plan.tree_id}:deepest-tier" for f in gaps))

    def test_an_excess_mechanism_node_is_also_caught_not_only_a_shortfall(self) -> None:
        """A count, never a `>=` threshold: tier 1 targets ZERO mechanism nodes for `might` — one
        extra mechanism node there must be refused exactly as loudly as a missing one elsewhere."""
        broken = [dict(n) for n in self.nodes]
        tier1_offensive = next(
            n for n in broken
            if any(pn.node_id == n["id"] and pn.tier == 1 and pn.branch == "offensive"
                  for pn in self.plan.nodes))
        tier1_offensive["nodeClass"] = "mechanism"
        findings = self.metric.run(self._ctx(broken))
        gaps = _gap_findings(findings)
        self.assertTrue(any(f.subject == f"{self.plan.tree_id}:offensive:t1" for f in gaps))


class CellOccupancyMetricTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan, self.targets, self.cells, _, _ = _clean_might_corpus()
        self.metric = CellOccupancyMetric()

    def _ctx(self, cells) -> Ctx:
        return _ctx_with(PassiveTreePlanCtx(
            plans=[], archetypes=(), tier_count=10, unlock_first_points=0, unlock_step_points=0,
            reward_spread_max_ratio_milli=0, min_terminal_width=0, targets=self.targets,
            quota_cells_by_tree={"might": cells}))

    def test_reports_not_measured_with_no_cells(self) -> None:
        ctx = _ctx_with(PassiveTreePlanCtx(plans=[], archetypes=(), tier_count=10,
                                            unlock_first_points=0, unlock_step_points=0,
                                            reward_spread_max_ratio_milli=0, min_terminal_width=0,
                                            targets=self.targets))
        findings = self.metric.run(ctx)
        self.assertTrue(all(f.severity == Severity.NOT_MEASURED for f in findings))

    def test_the_real_corpus_median_is_reported(self) -> None:
        findings = self.metric.run(self._ctx(self.cells))
        self.assertEqual(len(findings), 1)
        self.assertIn("median", findings[0].message)

    def test_collapsing_every_node_onto_one_cell_is_a_gap(self) -> None:
        from dataclasses import replace
        first = next(iter(self.cells.values()))
        collapsed = {node_id: replace(first) for node_id in self.cells}
        findings = self.metric.run(self._ctx(collapsed))
        self.assertEqual(findings[0].severity, Severity.GAP)
        self.assertEqual(findings[0].evidence["cells"], 1)


class ExclusionRateMetricTests(unittest.TestCase):
    def setUp(self) -> None:
        self.targets = tuning.load()
        self.plan_stub = SimpleNamespace(
            tree_id="stub", property_vocabulary={"posture": ("vanguard", "warden", "trickster")})
        self.metric = ExclusionRateMetric()

    def _ctx(self, nodes) -> Ctx:
        return _ctx_with(PassiveTreePlanCtx(
            plans=[], archetypes=(), tier_count=10, unlock_first_points=0, unlock_step_points=0,
            reward_spread_max_ratio_milli=0, min_terminal_width=0, targets=self.targets,
            tree_plans=(self.plan_stub,), nodes_by_tree={"stub": nodes}))

    def _clean_none_node(self, node_id: str) -> dict:
        return {"id": node_id, "exclusion": {"form": "none", "propertyKeys": [], "printedText": ""}}

    def test_an_all_none_corpus_is_clean(self) -> None:
        nodes = [self._clean_none_node(f"n{i}") for i in range(50)]
        findings = self.metric.run(self._ctx(nodes))
        self.assertEqual(_gap_findings(findings), [])

    def test_a_correctly_composed_reroute_is_clean(self) -> None:
        keys = ("posture:vanguard",)
        text = nodegen_exclusion.compose_printed_text("reroute", keys, role="loser")
        nodes = [self._clean_none_node(f"n{i}") for i in range(49)]
        nodes.append({"id": "n49", "exclusion": {"form": "reroute", "propertyKeys": list(keys),
                                                  "printedText": text}})
        findings = self.metric.run(self._ctx(nodes))
        self.assertEqual(_gap_findings(findings), [])

    def test_a_missing_printed_text_is_a_gap(self) -> None:
        nodes = [self._clean_none_node(f"n{i}") for i in range(49)]
        nodes.append({"id": "n49", "exclusion": {"form": "reroute",
                                                  "propertyKeys": ["posture:vanguard"],
                                                  "printedText": ""}})
        findings = self.metric.run(self._ctx(nodes))
        gaps = _gap_findings(findings)
        self.assertTrue(any(f.evidence.get("code") == "MissingPrintedText" for f in gaps))

    def test_a_drifted_printed_text_is_a_gap(self) -> None:
        nodes = [self._clean_none_node(f"n{i}") for i in range(49)]
        nodes.append({"id": "n49", "exclusion": {"form": "reroute",
                                                  "propertyKeys": ["posture:vanguard"],
                                                  "printedText": "this is not the template"}})
        findings = self.metric.run(self._ctx(nodes))
        gaps = _gap_findings(findings)
        self.assertTrue(any(f.evidence.get("code") == "PrintedTextDrift" for f in gaps))

    def test_a_node_id_shaped_property_key_is_a_gap(self) -> None:
        nodes = [self._clean_none_node(f"n{i}") for i in range(49)]
        nodes.append({"id": "n49", "exclusion": {
            "form": "reroute", "propertyKeys": ["skill.might-off-t3-n1"],
            "printedText": "x"}})
        findings = self.metric.run(self._ctx(nodes))
        gaps = _gap_findings(findings)
        self.assertTrue(any(f.evidence.get("code") == "ExclusionFormDefect" for f in gaps))

    def test_a_rate_above_target_is_a_gap(self) -> None:
        """`exclusionRate.maxSharePermille` is 30 (3%) in the real targets file — well under half
        the corpus carrying an exclusion is a clear breach."""
        keys = ("posture:vanguard",)
        text = nodegen_exclusion.compose_printed_text("reroute", keys, role="loser")
        nodes = [{"id": f"n{i}", "exclusion": {"form": "reroute", "propertyKeys": list(keys),
                                               "printedText": text}}
                for i in range(10)]
        findings = self.metric.run(self._ctx(nodes))
        suite = [f for f in findings if f.subject == "(suite)"]
        self.assertEqual(suite[0].severity, Severity.GAP)


class ExclusionResolvableMetricTests(unittest.TestCase):
    def setUp(self) -> None:
        self.metric = ExclusionResolvableMetric()

    def test_reports_not_measured_and_names_the_atom_tag_registry_by_name(self) -> None:
        ctx = _ctx_with(PassiveTreePlanCtx(plans=[], archetypes=(), tier_count=10,
                                            unlock_first_points=0, unlock_step_points=0,
                                            reward_spread_max_ratio_milli=0, min_terminal_width=0))
        findings = self.metric.run(ctx)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.NOT_MEASURED)
        self.assertIn("atom-tag registry", findings[0].message)
        self.assertIn("§5.1", findings[0].message)

    def test_an_unknown_property_key_is_a_gap_once_a_registry_exists(self) -> None:
        plan_stub = SimpleNamespace(tree_id="stub")
        nodes = [{"id": "n1", "exclusion": {"form": "reroute", "propertyKeys": ["posture:vanguard"]}},
                {"id": "n2", "exclusion": {"form": "reroute", "propertyKeys": ["ghost:key"]}}]
        ctx = _ctx_with(PassiveTreePlanCtx(
            plans=[], archetypes=(), tier_count=10, unlock_first_points=0, unlock_step_points=0,
            reward_spread_max_ratio_milli=0, min_terminal_width=0,
            tree_plans=(plan_stub,), nodes_by_tree={"stub": nodes},
            atom_tag_registry={"posture:vanguard": True, "posture": True}))
        findings = self.metric.run(ctx)
        gaps = _gap_findings(findings)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].subject, "n2")


class ExclusionPresentationMetricTests(unittest.TestCase):
    """Task J3 (spec-tree-review.md §6.4 rule 2) — the ONE presentation-shaped unshippable
    condition that gates, unlike ExclusionRate's own rate. `gates = True` on the class itself is
    asserted directly; this metric is deliberately excluded from `ALL_PASSIVE_TREE_METRICS`'s own
    generation-time registry loop (see that tuple's own comment for the real, checked reason:
    §7.1's `assert_exactly_one_hard_gate` already owns `PassiveTree/UnresolvedCount` as the one
    generation-time hard gate; this is a review-time verdict concept instead), so these tests
    exercise the class directly, the same way `HiddenFileCountMetric`/`DeepMechanismValueMetric`
    (also excluded from that tuple, for their own reason) are tested above."""

    def setUp(self) -> None:
        self.plan_stub = SimpleNamespace(tree_id="stub")
        self.metric = ExclusionPresentationMetric()

    def _ctx(self, nodes) -> Ctx:
        return _ctx_with(PassiveTreePlanCtx(
            plans=[], archetypes=(), tier_count=10, unlock_first_points=0, unlock_step_points=0,
            reward_spread_max_ratio_milli=0, min_terminal_width=0,
            tree_plans=(self.plan_stub,), nodes_by_tree={"stub": nodes}))

    def test_the_metric_itself_gates(self) -> None:
        self.assertTrue(ExclusionPresentationMetric.gates)

    def test_a_none_form_node_is_not_a_member_nothing_to_present(self) -> None:
        nodes = [{"id": "n0", "exclusion": {"form": "none", "propertyKeys": [], "printedText": ""}}]
        findings = self.metric.run(self._ctx(nodes))
        self.assertEqual(_gap_findings(findings), [])
        self.assertIn("nothing to present", findings[0].message)

    def test_a_correctly_composed_nullification_is_clean(self) -> None:
        keys = ("posture:vanguard",)
        text = nodegen_exclusion.compose_printed_text("nullification", keys, role="loser")
        nodes = [{"id": "n0", "exclusion": {"form": "nullification", "propertyKeys": list(keys),
                                            "printedText": text}}]
        findings = self.metric.run(self._ctx(nodes))
        self.assertEqual(_gap_findings(findings), [])

    def test_a_well_presented_nullification_ships_never_wrongly_blocked(self) -> None:
        # J3's own 4th acceptance bullet, stated as a test so the withdrawn D40 narrowing (treating
        # nullification's mere existence as disqualifying) cannot creep back in: a well-presented
        # nullification passes this gate cleanly, the same as reroute/precedence would.
        keys = ("posture:vanguard", "conversionState:converted")
        text = nodegen_exclusion.compose_printed_text("nullification", keys, role="loser")
        nodes = [{"id": f"n{i}", "exclusion": {"form": "none", "propertyKeys": [], "printedText": ""}}
                for i in range(9)]
        nodes.append({"id": "n9", "exclusion": {"form": "nullification", "propertyKeys": list(keys),
                                                "printedText": text}})
        findings = self.metric.run(self._ctx(nodes))
        self.assertEqual(_gap_findings(findings), [])
        note = next(f for f in findings if f.severity != Severity.GAP)
        self.assertIn("1 exclusion(s) all present", note.message)

    def test_an_empty_printed_text_on_a_nullification_is_a_gap(self) -> None:
        nodes = [{"id": "n0", "exclusion": {"form": "nullification",
                                            "propertyKeys": ["posture:vanguard"], "printedText": ""}}]
        findings = self.metric.run(self._ctx(nodes))
        gaps = _gap_findings(findings)
        self.assertEqual(1, len(gaps))
        self.assertEqual("n0", gaps[0].subject)
        self.assertEqual("ExclusionPresentationDefect", gaps[0].evidence["code"])

    def test_a_drifted_printed_text_is_a_gap_naming_both_texts(self) -> None:
        nodes = [{"id": "n0", "exclusion": {"form": "reroute", "propertyKeys": ["posture:vanguard"],
                                            "printedText": "some hand-written drift"}}]
        findings = self.metric.run(self._ctx(nodes))
        gaps = _gap_findings(findings)
        self.assertEqual(1, len(gaps))
        self.assertIn("does not match the template", gaps[0].message)

    def test_precedence_and_reroute_are_also_covered_not_only_nullification(self) -> None:
        for form in ("reroute", "precedence"):
            with self.subTest(form=form):
                keys = ("posture:warden",)
                text = nodegen_exclusion.compose_printed_text(form, keys, role="loser")
                nodes = [{"id": "n0", "exclusion": {"form": form, "propertyKeys": list(keys),
                                                    "printedText": text}}]
                findings = self.metric.run(self._ctx(nodes))
                self.assertEqual(_gap_findings(findings), [])


class NearDuplicateMetricTests(unittest.TestCase):
    def setUp(self) -> None:
        self.targets = tuning.load()
        self.metric = NearDuplicateMetric()

    def _ctx(self, nodes) -> Ctx:
        return _ctx_with(PassiveTreePlanCtx(
            plans=[], archetypes=(), tier_count=10, unlock_first_points=0, unlock_step_points=0,
            reward_spread_max_ratio_milli=0, min_terminal_width=0, targets=self.targets,
            nodes_by_tree={"tree": nodes}))

    def test_a_corpus_of_distinct_names_is_clean(self) -> None:
        nodes = [{"id": f"n{i}", "name": _distinct_name(i)} for i in range(len(_DISTINCT_WORDS))]
        findings = self.metric.run(self._ctx(nodes))
        self.assertEqual(_gap_findings(findings), [])

    def test_two_near_duplicate_names_are_caught(self) -> None:
        nodes = [{"id": f"n{i}", "name": _distinct_name(i)} for i in range(len(_DISTINCT_WORDS) - 2)]
        nodes.append({"id": "nA", "name": "Ember Wardstone of the Deep"})
        nodes.append({"id": "nB", "name": "Ember Wardstone of the Deeps"})
        findings = self.metric.run(self._ctx(nodes))
        gaps = _gap_findings(findings)
        self.assertTrue(gaps)
        self.assertTrue(any(f.subject == "nA~nB" for f in findings))

    def test_exact_duplicate_names_are_not_double_counted_here(self) -> None:
        """Exact duplicates are NameCollision's own job — this metric must not report a pair whose
        names are byte-identical."""
        nodes = [{"id": f"n{i}", "name": _distinct_name(i)} for i in range(len(_DISTINCT_WORDS) - 2)]
        nodes.append({"id": "nA", "name": "Twin Name"})
        nodes.append({"id": "nB", "name": "Twin Name"})
        findings = self.metric.run(self._ctx(nodes))
        self.assertFalse(any(f.subject == "nA~nB" for f in findings))


class NameCollisionMetricTests(unittest.TestCase):
    def setUp(self) -> None:
        self.metric = NameCollisionMetric()

    def _ctx(self, nodes_by_tree) -> Ctx:
        return _ctx_with(PassiveTreePlanCtx(
            plans=[], archetypes=(), tier_count=10, unlock_first_points=0, unlock_step_points=0,
            reward_spread_max_ratio_milli=0, min_terminal_width=0, nodes_by_tree=nodes_by_tree))

    def test_a_corpus_of_unique_names_is_clean(self) -> None:
        nodes = {"t1": [{"id": f"n{i}", "name": f"Unique {i}"} for i in range(50)]}
        findings = self.metric.run(self._ctx(nodes))
        self.assertEqual(_gap_findings(findings), [])

    def test_a_duplicated_name_across_300_nodes_is_caught(self) -> None:
        """The todo's own named fixture, and the same defect shape the real historical incident
        was (83 of 83 commander effects sharing one name) — reproduced at 300 nodes across 30
        trees, all sharing the identical name."""
        tree_count, nodes_per_tree = 30, 10
        nodes_by_tree = {
            f"tree{t}": [{"id": f"tree{t}-n{i}", "name": "Ember's Wrath"} for i in range(nodes_per_tree)]
            for t in range(tree_count)
        }
        findings = self.metric.run(self._ctx(nodes_by_tree))
        gaps = _gap_findings(findings)
        # Formula, not a literal (population-pin SE3.5, 2026-09-20): one GAP per colliding node (this
        # test's own fixture size), plus the suite-level summary GAP.
        self.assertEqual(tree_count * nodes_per_tree + 1, len(gaps))
        suite = next(f for f in findings if f.subject == "(suite)")
        self.assertEqual(suite.evidence["collided"], 300)
        self.assertEqual(suite.evidence["sharePermille"], 1000)

    def test_a_partial_collision_names_only_the_colliding_nodes(self) -> None:
        nodes_by_tree = {"t1": [{"id": "n1", "name": "Shared"}, {"id": "n2", "name": "Shared"},
                                {"id": "n3", "name": "Unique"}]}
        findings = self.metric.run(self._ctx(nodes_by_tree))
        gaps = _gap_findings(findings)
        gap_subjects = {f.subject for f in gaps}
        self.assertIn("n1", gap_subjects)
        self.assertIn("n2", gap_subjects)
        self.assertNotIn("n3", gap_subjects)


class UnresolvedCountMetricTests(unittest.TestCase):
    def setUp(self) -> None:
        self.targets = tuning.load()
        self.metric = UnresolvedCountMetric()

    def _ctx(self, outcomes_by_tree) -> Ctx:
        return _ctx_with(PassiveTreePlanCtx(
            plans=[], archetypes=(), tier_count=10, unlock_first_points=0, unlock_step_points=0,
            reward_spread_max_ratio_milli=0, min_terminal_width=0, targets=self.targets,
            outcomes_by_tree=outcomes_by_tree))

    def test_reports_not_measured_with_no_outcomes(self) -> None:
        ctx = _ctx_with(PassiveTreePlanCtx(plans=[], archetypes=(), tier_count=10,
                                            unlock_first_points=0, unlock_step_points=0,
                                            reward_spread_max_ratio_milli=0, min_terminal_width=0))
        findings = self.metric.run(ctx)
        self.assertTrue(all(f.severity == Severity.NOT_MEASURED for f in findings))

    def test_zero_unresolved_is_clean(self) -> None:
        outcomes = {"t1": [{"nodeId": f"n{i}", "outcome": "accepted"} for i in range(40)]}
        findings = self.metric.run(self._ctx(outcomes))
        self.assertEqual(findings[0].severity, Severity.NOTE)

    def test_an_unresolved_share_above_target_is_a_gap(self) -> None:
        """`unresolvedCount.maxSharePermille` is 50 (5%) in the real targets file."""
        outcomes = {"t1": [{"nodeId": f"n{i}",
                            "outcome": "unresolved" if i < 10 else "accepted"}
                          for i in range(40)]}  # 25% unresolved
        findings = self.metric.run(self._ctx(outcomes))
        self.assertEqual(findings[0].severity, Severity.GAP)

    def test_is_the_one_closed_loop_hard_gate(self) -> None:
        self.assertIs(self.metric.loop, Loop.CLOSED)
        self.assertTrue(self.metric.gates)

    # -- J5 addition: the species-level mechanicalFavour population, a SECOND, independent subject
    # under this SAME gate (spec-species-tree.md §3.1/§4) -- never a second gates=True class.

    _NO_TARGETS_GIVEN = object()

    def _species_ctx(self, species_favour_outcomes, targets=_NO_TARGETS_GIVEN) -> Ctx:
        return _ctx_with(PassiveTreePlanCtx(
            plans=[], archetypes=(), tier_count=10, unlock_first_points=0, unlock_step_points=0,
            reward_spread_max_ratio_milli=0, min_terminal_width=0,
            targets=self.targets if targets is self._NO_TARGETS_GIVEN else targets,
            species_favour_outcomes=species_favour_outcomes))

    def test_no_species_favour_outcomes_supplied_reports_only_affixIds_exactly_as_before(self) -> None:
        # Every pre-J5 call site (every test above) never supplies this field -- must produce
        # EXACTLY the same single affixIds finding as before this task touched the class.
        findings = self.metric.run(self._ctx({"t1": [{"nodeId": "n0", "outcome": "accepted"}]}))
        self.assertEqual(1, len(findings))
        self.assertEqual("affixIds", findings[0].subject)

    def test_a_clean_species_favour_population_is_a_note(self) -> None:
        outcomes = [{"speciesId": f"s{i}", "outcome": "resolved"} for i in range(40)]
        findings = self.metric.run(self._species_ctx(outcomes))
        favour_finding = next(f for f in findings if f.subject == "mechanicalFavour")
        self.assertEqual(Severity.NOTE, favour_finding.severity)
        self.assertEqual(0, favour_finding.evidence["unresolved"])

    def test_species_favour_unresolved_above_fifty_permille_is_a_gap(self) -> None:
        # The exact bullet-5 proof: 6% (60‰) unresolved, above the shipped 50‰ bar, fails the run
        # naming the rate.
        outcomes = [{"speciesId": f"s{i}", "outcome": "unresolved" if i < 6 else "resolved"}
                   for i in range(100)]
        findings = self.metric.run(self._species_ctx(outcomes))
        favour_finding = next(f for f in findings if f.subject == "mechanicalFavour")
        self.assertEqual(Severity.GAP, favour_finding.severity)
        self.assertEqual(60, favour_finding.evidence["sharePermille"])
        self.assertIn("6/100", favour_finding.message)

    def test_species_favour_outcomes_without_targets_is_not_measured_for_that_subject(self) -> None:
        outcomes = [{"speciesId": "s0", "outcome": "unresolved"}]
        findings = self.metric.run(self._species_ctx(outcomes, targets=None))
        favour_finding = next(f for f in findings if f.subject == "mechanicalFavour")
        self.assertEqual(Severity.NOT_MEASURED, favour_finding.severity)

    def test_both_populations_are_reported_independently_in_the_same_run(self) -> None:
        outcomes_by_tree = {"t1": [{"nodeId": "n0", "outcome": "unresolved"},
                                   {"nodeId": "n1", "outcome": "accepted"}]}  # 500‰, a GAP
        species_outcomes = [{"speciesId": f"s{i}", "outcome": "resolved"} for i in range(20)]  # clean
        ctx = _ctx_with(PassiveTreePlanCtx(
            plans=[], archetypes=(), tier_count=10, unlock_first_points=0, unlock_step_points=0,
            reward_spread_max_ratio_milli=0, min_terminal_width=0, targets=self.targets,
            outcomes_by_tree=outcomes_by_tree, species_favour_outcomes=species_outcomes))
        findings = self.metric.run(ctx)
        self.assertEqual(2, len(findings))
        by_subject = {f.subject: f for f in findings}
        self.assertEqual(Severity.GAP, by_subject["affixIds"].severity)
        self.assertEqual(Severity.NOTE, by_subject["mechanicalFavour"].severity)


class AllPassiveTreeMetricsRegistrationTests(unittest.TestCase):
    """Confirms the family-wide invariant with the REAL shipped metric classes (never the
    `test_nodegen_verdict_gates.py` stand-in stubs, which only proved the MECHANISM accepts this
    shape ahead of H4): exactly one `PassiveTree/*` metric is `gates=True`, and running the whole
    family together over a clean corpus never crashes."""

    def test_registering_all_eight_plus_tree_equal_value_never_raises(self) -> None:
        registry = MetricRegistry()
        for metric_cls in ALL_PASSIVE_TREE_METRICS:
            registry.register(metric_cls())
        registry.register(TreeEqualValueMetric())
        self.assertEqual(len(registry.all()), 9)

    def test_exactly_one_hard_gate_via_assert_exactly_one_hard_gate(self) -> None:
        from seedsmith.adapters.trees.nodegen import verdict as tree_verdict

        registry = MetricRegistry()
        for metric_cls in ALL_PASSIVE_TREE_METRICS:
            registry.register(metric_cls())
        registry.register(TreeEqualValueMetric())
        tree_verdict.assert_exactly_one_hard_gate(registry, "PassiveTree")  # must not raise
        self.assertEqual(tree_verdict.hard_gate_ids(registry, "PassiveTree"),
                         ["PassiveTree/UnresolvedCount"])

    def test_run_all_over_a_clean_corpus_produces_no_gap(self) -> None:
        plan, targets, cells, nodes, outcomes = _clean_might_corpus()
        registry = MetricRegistry()
        for metric_cls in ALL_PASSIVE_TREE_METRICS:
            registry.register(metric_cls())
        ctx = _ctx_with(PassiveTreePlanCtx(
            plans=[plan.raw], archetypes=(), tier_count=10, unlock_first_points=0,
            unlock_step_points=0, reward_spread_max_ratio_milli=0, min_terminal_width=0,
            targets=targets, tree_plans=(plan,), nodes_by_tree={"might": nodes},
            quota_cells_by_tree={"might": cells}, outcomes_by_tree={"might": outcomes}))
        findings = run_all(registry, ctx)
        gaps = _gap_findings(findings)
        self.assertEqual(gaps, [], f"unexpected GAP(s) over a clean corpus: {gaps}")


# =================================================================================================
# Task H5 — the two remaining `tree-review` corpus metrics (spec-tree-review.md §4.1, §4.2, §7).
# =================================================================================================

#: The spec's own worked example (spec-tree-binder.md §3.4): tree-share/tree-budget at their
#: placeholder 1000/1000, branches=2 (D29), the atk anchor 135 (92*1000/680, power-scale.v2.json's
#: own published pins), a tier-5 node at budgetShareMilli=45 -> kMicro=3038. Reused verbatim rather
#: than a hand-picked toy so a green/red test here is provably checking the SAME arithmetic the
#: spec documents, not a private example invented for this file.
_WORKED_TREE_SHARE_MILLI = 1000
_WORKED_TREE_BUDGET_MILLI = 1000
_WORKED_BRANCHES = 2
_WORKED_CHANNEL_ANCHOR_MILLI = {"atk": 135, "defense": 32}
_WORKED_BUDGET_SHARE_MILLI = 45
_WORKED_EXPECTED_KMICRO = 3038


def _worked_plan(tree_id: str = "worked") -> dict:
    return {"treeId": tree_id, "nodes": [
        {"id": f"{tree_id}-n1", "branch": "offensive", "budgetShareMilli": _WORKED_BUDGET_SHARE_MILLI},
    ]}


def _worked_bound_report(tree_id: str = "worked", kmicro: int = _WORKED_EXPECTED_KMICRO) -> dict:
    return {
        "treeId": tree_id, "verdict": "Pass", "totalUnspentBudgetShareMilli": 0,
        "bound": [{
            "nodeId": f"{tree_id}-n1",
            "atoms": [{"kindId": "stat.derived", "channelId": "combat.power.fire", "op": "Flat",
                      "kMicro": kmicro, "unitClass": "GameUnits", "scaleAxis": "PTheta"}],
        }],
        "refused": [],
    }


def _real_might_ctx_kwargs() -> "tuple[dict, dict]":
    """The REAL, fully-valid `might` plan (same construction `TreeEqualValueMetricRegistrationTests`
    in `test_tree_plan_invariants.py` already uses) — the plan-side half runs FIRST inside
    `TreeEqualValueMetric.run()` and needs a plan that actually satisfies C1/R-A1/P-1/P-2 (real
    `budgetPoints`, real archetypes, real tuning), not a minimal synthetic stub. Returns the
    `PassiveTreePlanCtx` kwargs the plan-side half needs, plus the raw plan dict itself so a test
    can read a real node's own `id`/`budgetShareMilli` for the content-side half."""
    from seedsmith.adapters.trees.plan import emit as plan_emit
    from seedsmith.adapters.trees.plan import tuning as plan_tuning
    from seedsmith.adapters.trees.plan.archetypes import SHIPPED_ARCHETYPES, TIER_COUNT

    tuning_doc = plan_tuning.load()
    plan = plan_emit.build_plan(plan_emit.might_tree_spec(), tuning_doc)
    return {
        "plans": [plan], "archetypes": SHIPPED_ARCHETYPES, "tier_count": TIER_COUNT,
        "unlock_first_points": tuning_doc["unlockCost"]["firstPoints"],
        "unlock_step_points": tuning_doc["unlockCost"]["stepPoints"],
        "reward_spread_max_ratio_milli": tuning_doc["archetype"]["rewardSpreadMaxRatioMilli"],
        "min_terminal_width": tuning_doc["potency"]["minTerminalWidth"],
    }, plan


class TreeEqualValueContentSideMetricTests(unittest.TestCase):
    """H5's own acceptance bullet: "TreeEqualValue reads bound prices and reports through the same
    registry C1 registered it in — one metric, two inputs, never two metrics with one name" and the
    todo's own Verification line: "a corpus with one over-priced tree fails TreeEqualValue".

    Runs the metric over the REAL `might` plan (not a synthetic stub) — the plan-side half executes
    first inside `TreeEqualValueMetric.run()` and refuses a plan that does not itself satisfy
    C1/R-A1/P-1/P-2, so any content-side test that wants to see PAST the plan-side half needs a
    plan that actually clears it."""

    def setUp(self) -> None:
        from seedsmith.metrics import passive_tree as passive_tree_module

        self.metric = TreeEqualValueMetric()
        self.ctx_kwargs, self.plan = _real_might_ctx_kwargs()
        self.node = self.plan["nodes"][0]
        # The exact formula spec-tree-binder.md §3.3 / `CoefficientBinder.Bind` compute in C#,
        # applied to this REAL node's own `budgetShareMilli` — never a value invented for the test.
        self.expected_kmicro = passive_tree_module._expected_kmicro(
            _WORKED_TREE_SHARE_MILLI, _WORKED_TREE_BUDGET_MILLI, self.node["budgetShareMilli"],
            _WORKED_CHANNEL_ANCHOR_MILLI["atk"], _WORKED_BRANCHES)

    def _bound_report(self, kmicro: int) -> dict:
        return {
            "treeId": self.plan["treeId"], "verdict": "Pass", "totalUnspentBudgetShareMilli": 0,
            "bound": [{
                "nodeId": self.node["id"],
                "atoms": [{"kindId": "stat.derived", "channelId": "combat.power.fire", "op": "Flat",
                          "kMicro": kmicro, "unitClass": "GameUnits", "scaleAxis": "PTheta"}],
            }],
            "refused": [],
        }

    def _ctx(self, **overrides) -> Ctx:
        base = dict(self.ctx_kwargs)
        base.update(
            tree_share_milli=_WORKED_TREE_SHARE_MILLI, tree_budget_milli=_WORKED_TREE_BUDGET_MILLI,
            branches=_WORKED_BRANCHES, channel_anchor_milli=dict(_WORKED_CHANNEL_ANCHOR_MILLI),
            bound_reports_by_tree={self.plan["treeId"]: self._bound_report(self.expected_kmicro)},
        )
        base.update(overrides)
        return _ctx_with(PassiveTreePlanCtx(**base))

    def test_registration_is_exactly_one_metric_id(self) -> None:
        # C1's own instruction, restated as a test: the content-side half must never become a
        # second metric with a similar name.
        self.assertEqual(TreeEqualValueMetric.id, "PassiveTree/TreeEqualValue")
        registry = MetricRegistry()
        registry.register(self.metric)
        self.assertEqual(len([m for m in registry.all() if "TreeEqualValue" in m.id]), 1)

    def test_a_clean_bound_report_matches_the_real_nodes_own_budget(self) -> None:
        findings = self.metric.run(self._ctx())
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.NOTE)
        self.assertEqual(findings[0].evidence["boundTreesChecked"], 1)

    def test_an_over_priced_node_fails_tree_equal_value(self) -> None:
        """The todo's own named proof: one tree whose bound price diverges from what the budget
        column says it should cost must fail this metric."""
        bad_report = {self.plan["treeId"]: self._bound_report(self.expected_kmicro + 500)}
        findings = self.metric.run(self._ctx(bound_reports_by_tree=bad_report))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.GAP)
        self.assertEqual(findings[0].evidence["priceMismatchCount"], 1)
        problem = findings[0].evidence["problems"][0]
        self.assertEqual(problem["reason"], "priceMismatch")
        self.assertEqual(problem["expectedKMicro"], self.expected_kmicro)
        self.assertEqual(problem["actualKMicro"], self.expected_kmicro + 500)

    def test_no_bound_reports_supplied_runs_the_plan_side_only(self) -> None:
        """Every pre-H5 construction site (every OTHER test class in this file) supplies no
        `bound_reports_by_tree` at all — this must keep behaving exactly as it did before H5, so
        `TreeEqualValueMetricRegistrationTests.test_runs_through_run_all_and_reports_a_clean_note`
        (len==1, one NOTE) never regresses."""
        findings = self.metric.run(_ctx_with(PassiveTreePlanCtx(**self.ctx_kwargs)))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.NOTE)
        self.assertNotIn("boundTreesChecked", findings[0].evidence)

    def test_missing_tree_share_or_budget_milli_is_not_measured_rather_than_a_crash(self) -> None:
        findings = self.metric.run(self._ctx(tree_share_milli=None))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.NOT_MEASURED)


class CheckBoundPricesHonourBudgetFunctionTests(unittest.TestCase):
    """Direct tests of the free function H5 added — the arithmetic and the corpus-consistency
    checks, isolated from `TreeEqualValueMetric.run()`'s own plan-side gate (these fixture plans
    are deliberately minimal, never meant to satisfy C1/R-A1/P-1/P-2)."""

    def test_the_spec_worked_example_matches_exactly(self) -> None:
        """spec-tree-binder.md §3.4's own worked numbers: budgetShareMilli=45 at the atk anchor
        (135) over 1000/1000/2 branches derives kMicro=3038, exactly."""
        problems = check_bound_prices_honour_budget(
            [_worked_plan()], {"worked": _worked_bound_report(kmicro=_WORKED_EXPECTED_KMICRO)},
            _WORKED_TREE_SHARE_MILLI, _WORKED_TREE_BUDGET_MILLI, _WORKED_BRANCHES,
            channel_anchor_milli=dict(_WORKED_CHANNEL_ANCHOR_MILLI))
        self.assertEqual(problems, [])

    def test_check_bound_prices_honour_budget_flags_a_missing_channel_anchor(self) -> None:
        problems = check_bound_prices_honour_budget(
            [_worked_plan()], {"worked": _worked_bound_report()},
            _WORKED_TREE_SHARE_MILLI, _WORKED_TREE_BUDGET_MILLI, _WORKED_BRANCHES,
            channel_anchor_milli={})  # no anchor supplied for "atk" at all
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["reason"], "noChannelAnchorSupplied")

    def test_a_channel_outside_the_two_anchored_families_is_skipped_not_guessed(self) -> None:
        """§4.1: `TreeBinderRun` composes a `PerMilleRatio`/`ThetaLinear` atom but does not price
        it by this formula — this check must skip it too, never invent an expected value."""
        report = _worked_bound_report()
        report["bound"][0]["atoms"][0]["channelId"] = "combat.reflect.rate.omni"
        problems = check_bound_prices_honour_budget(
            [_worked_plan()], {"worked": report},
            _WORKED_TREE_SHARE_MILLI, _WORKED_TREE_BUDGET_MILLI, _WORKED_BRANCHES,
            channel_anchor_milli=dict(_WORKED_CHANNEL_ANCHOR_MILLI))
        self.assertEqual(problems, [])

    def test_a_node_the_plan_does_not_carry_is_named_not_silently_dropped(self) -> None:
        report = _worked_bound_report()
        report["bound"][0]["nodeId"] = "worked-ghost-node"
        problems = check_bound_prices_honour_budget(
            [_worked_plan()], {"worked": report},
            _WORKED_TREE_SHARE_MILLI, _WORKED_TREE_BUDGET_MILLI, _WORKED_BRANCHES,
            channel_anchor_milli=dict(_WORKED_CHANNEL_ANCHOR_MILLI))
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["reason"], "nodeNotInPlan")


class DeepMechanismValueMetricTests(unittest.TestCase):
    """spec-tree-review.md §4.2's settled ruling: reports, never gates."""

    def setUp(self) -> None:
        self.metric = DeepMechanismValueMetric()

    def _ctx(self, **overrides) -> Ctx:
        base = dict(plans=[], archetypes=(), tier_count=10, unlock_first_points=0,
                    unlock_step_points=0, reward_spread_max_ratio_milli=0, min_terminal_width=0)
        base.update(overrides)
        return _ctx_with(PassiveTreePlanCtx(**base))

    def test_registers_gates_false(self) -> None:
        self.assertIs(self.metric.loop, Loop.CLOSED)
        self.assertFalse(self.metric.gates)

    def test_reports_not_measured_with_no_samples(self) -> None:
        findings = self.metric.run(self._ctx())
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.NOT_MEASURED)

    def test_a_below_threshold_sample_is_a_gap_finding(self) -> None:
        samples = {"might": [{"nodeId": "n10", "winShareDeltaMilli": 2}]}
        findings = self.metric.run(self._ctx(
            deep_mechanism_samples=samples, deep_mechanism_value_min_win_share_delta_milli=10))
        gaps = _gap_findings(findings)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].subject, "might:n10")

    def test_a_below_threshold_finding_never_gates_the_registry_verdict(self) -> None:
        """The metric's own class attribute AND the registry-level consequence: absent from
        `targets.GATING_METRICS` and never equal to `UNRESOLVED_COUNT_METRIC`, so
        `RunReport.verdict` structurally cannot read this metric's outcome at all."""
        from seedsmith.adapters.trees.nodegen.verdict import UNRESOLVED_COUNT_METRIC
        from seedsmith.adapters.trees.targets import GATING_METRICS

        self.assertFalse(self.metric.gates)
        self.assertNotIn(self.metric.id, GATING_METRICS)
        self.assertNotEqual(self.metric.id, UNRESOLVED_COUNT_METRIC)

        registry = MetricRegistry()
        registry.register(self.metric)
        samples = {"might": [{"nodeId": "n10", "winShareDeltaMilli": 0}]}
        findings = run_all(registry, self._ctx(
            deep_mechanism_samples=samples, deep_mechanism_value_min_win_share_delta_milli=999))
        self.assertTrue(_gap_findings(findings), "a below-threshold sample must still be a GAP")


class HiddenFileCountMetricTests(unittest.TestCase):
    """spec-tree-review.md §7: walks every `_`-prefixed file WITHOUT the skip convention other
    tools use, and always reports `visitedFileCount` so a green over nothing is distinguishable
    from a green over a real corpus."""

    def setUp(self) -> None:
        self.metric = HiddenFileCountMetric()

    def _ctx(self, roots) -> Ctx:
        return _ctx_with(PassiveTreePlanCtx(
            plans=[], archetypes=(), tier_count=10, unlock_first_points=0, unlock_step_points=0,
            reward_spread_max_ratio_milli=0, min_terminal_width=0, tree_seed_roots=tuple(roots)))

    def test_zero_roots_reports_visited_file_count_zero_explicitly(self) -> None:
        findings = self.metric.run(self._ctx([]))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.NOTE)
        self.assertEqual(findings[0].evidence["visitedFileCount"], 0)
        self.assertEqual(findings[0].evidence["rootCount"], 0)

    def test_a_canary_parked_entry_in_an_underscore_file_is_found(self) -> None:
        """The todo's own named proof: a fixture root with one `_`-prefixed file is found — this
        metric does NOT skip `_`-prefixed entries the way `CreatureQualityReport` does."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "zombie").mkdir()
            canary = root / "zombie" / "_needs-review.json"
            canary.write_text(json.dumps({"SnorkleZombie": {"rarity": "chaff"}}), encoding="utf-8")

            findings = self.metric.run(self._ctx([root]))
            gaps = _gap_findings(findings)
            self.assertEqual(len(gaps), 1)
            self.assertEqual(gaps[0].evidence["path"], str(canary))
            self.assertEqual(gaps[0].evidence["entryCount"], 1)

            note = next(f for f in findings if f.severity == Severity.NOTE)
            self.assertEqual(note.evidence["visitedFileCount"], 1)
            self.assertEqual(note.evidence["rootCount"], 1)

    def test_an_empty_underscore_file_is_not_a_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "_exemplar.json").write_text("{}", encoding="utf-8")

            findings = self.metric.run(self._ctx([root]))
            self.assertEqual(_gap_findings(findings), [])
            note = next(f for f in findings if f.severity == Severity.NOTE)
            # the empty file IS visited (walked, opened, read) — just not a GAP.
            self.assertEqual(note.evidence["visitedFileCount"], 1)

    def test_index_json_is_named_skipped_and_never_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "_index.json").write_text(json.dumps({"a": {"x": 1}, "b": {"y": 2}}),
                                              encoding="utf-8")

            findings = self.metric.run(self._ctx([root]))
            self.assertEqual(_gap_findings(findings), [])
            note = next(f for f in findings if f.severity == Severity.NOTE)
            self.assertEqual(note.evidence["visitedFileCount"], 0)

    def test_a_non_underscore_file_is_never_walked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "regular.json").write_text(json.dumps({"a": {"x": 1}}), encoding="utf-8")

            findings = self.metric.run(self._ctx([root]))
            self.assertEqual(_gap_findings(findings), [])
            note = next(f for f in findings if f.severity == Severity.NOTE)
            self.assertEqual(note.evidence["visitedFileCount"], 0)


def _favour_targets() -> PassiveTreeTargets:
    return PassiveTreeTargets(
        aptitude_weight_scheme="uniform",
        node_class_weights_milli=(500, 500), node_class_order=("mechanism", "magnitude"),
        exclusion_form_weights_milli=(450, 450, 100),
        exclusion_form_order=("reroute", "precedence", "nullification"),
        legitimate_skew_rows=(), exclusion_target_share_milli=20, species_unique_affix_min=8,
        tier2_sample_size=60, tier3_additional_sample_size=30, acceptance_ladder=(),
        cell_occupancy_median_max=2, quota_drift_tolerance_units=1,
        mechanism_ramp_deepest_tier_share_milli=1000, exclusion_rate_max_share_permille=30,
        near_duplicate_rate_max_share_permille=5, unresolved_count_max_share_permille=50,
    )


class FavourDriftMetricTests(unittest.TestCase):
    """Task J5 (spec-species-tree.md §3.1 step 4, §3.2/D32). Every fixture pins aptitude and status
    to one real id for every species (`Might`/`poison`) so the test can focus its assertions on the
    `element` axis alone — aptitude/status necessarily show their own concentration in these tiny
    fixtures too, which is real and expected, just out of scope for what each test below checks."""

    def setUp(self) -> None:
        self.targets = _favour_targets()
        self.metric = FavourDriftMetric()
        self.axis_tables = species_plan.axis_weight_tables(self.targets)
        # Real element ids, in the real roster's own declared order (`axis_weight_tables`' own
        # dict preserves it -- built by iterating the roster tuple itself, never re-sorted).
        self.elements = list(self.axis_tables["element"])

    def _assignment(self, element: str) -> dict:
        return {"aptitude": "Might", "element": element, "status": "poison"}

    def _ctx(self, assignments, tolerance=None) -> Ctx:
        return _ctx_with(PassiveTreePlanCtx(
            plans=[], archetypes=(), tier_count=10, unlock_first_points=0, unlock_step_points=0,
            reward_spread_max_ratio_milli=0, min_terminal_width=0, targets=self.targets,
            species_favour_assignments=assignments,
            favour_drift_tolerance_share_permille=tolerance))

    def _element_finding(self, findings, element: str):
        return next(f for f in findings if f.subject == f"element={element}")

    def test_no_assignments_supplied_is_not_measured(self) -> None:
        findings = self.metric.run(self._ctx([], tolerance=20))
        self.assertEqual(1, len(findings))
        self.assertEqual(Severity.NOT_MEASURED, findings[0].severity)

    def test_no_targets_supplied_is_not_measured(self) -> None:
        ctx = _ctx_with(PassiveTreePlanCtx(
            plans=[], archetypes=(), tier_count=10, unlock_first_points=0, unlock_step_points=0,
            reward_spread_max_ratio_milli=0, min_terminal_width=0,
            species_favour_assignments=[self._assignment(self.elements[0])]))
        findings = self.metric.run(ctx)
        self.assertEqual(1, len(findings))
        self.assertEqual(Severity.NOT_MEASURED, findings[0].severity)

    def test_a_near_uniform_corpus_reports_no_gap_on_the_element_axis(self) -> None:
        # Every real element gets an equal share -- cycling through them the same number of times
        # each is the closest a hand-built fixture gets to "matches the re-derived target exactly."
        n_per_element = 10
        assignments = [self._assignment(e) for e in self.elements for _ in range(n_per_element)]
        findings = self.metric.run(self._ctx(assignments, tolerance=5))
        for element in self.elements:
            finding = self._element_finding(findings, element)
            self.assertEqual(Severity.NOTE, finding.severity,
                             f"element={element}: {finding.message}")

    def test_an_injected_element_skew_is_a_gap_overshoot(self) -> None:
        # One element locks 100% of a small corpus -- the extreme case of the 166x defect this
        # gate exists to catch, made unmissable rather than borderline.
        skewed_element = self.elements[0]
        assignments = [self._assignment(skewed_element) for _ in range(30)]
        findings = self.metric.run(self._ctx(assignments, tolerance=20))
        finding = self._element_finding(findings, skewed_element)
        self.assertEqual(Severity.GAP, finding.severity)
        self.assertGreater(finding.evidence["driftSharePermille"], 0)

    def test_favour_drift_catches_undershoot_symmetrically_not_only_overshoot(self) -> None:
        # The flip side of the same fixture: an element that NEVER appears, while the target says
        # it should, is exactly as much a drift as one that appears too often.
        skewed_element = self.elements[0]
        other_elements = self.elements[1:]
        assignments = [self._assignment(e) for e in other_elements for _ in range(10)]
        findings = self.metric.run(self._ctx(assignments, tolerance=20))
        finding = self._element_finding(findings, skewed_element)
        self.assertEqual(Severity.GAP, finding.severity)
        self.assertEqual(0, finding.evidence["observedCount"])
        self.assertLess(finding.evidence["driftSharePermille"], 0)

    def test_with_no_tolerance_supplied_nothing_is_ever_flagged_gap(self) -> None:
        # gates=False and no real generation run exists yet to calibrate against -- every finding
        # is reported, none is escalated, mirroring DeepMechanismValueMetric's own shipped posture.
        skewed_element = self.elements[0]
        assignments = [self._assignment(skewed_element) for _ in range(30)]
        findings = self.metric.run(self._ctx(assignments, tolerance=None))
        self.assertEqual([], _gap_findings(findings))
        finding = self._element_finding(findings, skewed_element)
        self.assertEqual(Severity.NOTE, finding.severity)

    def test_the_metric_never_appears_in_all_passive_tree_metrics(self) -> None:
        # Same registration posture as H5's own two metrics: a real, registrable metric, but never
        # added to the H4-only convenience tuple a test elsewhere pins to an exact length.
        self.assertNotIn(FavourDriftMetric, ALL_PASSIVE_TREE_METRICS)

    def test_gates_is_false(self) -> None:
        self.assertFalse(FavourDriftMetric.gates)


def _cell(node_class="mechanism", trigger="onHit", element="fire", status="poison",
         channel_family="atk", exclusion_form="reroute"):
    return quota.QuotaCell(node_class=node_class, trigger=trigger, element=element, status=status,
                           channel_family=channel_family, exclusion_form=exclusion_form)


def _uniq_node(node_id: str, *, name="Node", flavor="Flavor.", affix_ids=("atom.a",)) -> dict:
    return {"id": node_id, "name": name, "flavor": flavor, "affixIds": list(affix_ids)}


class SpeciesUniquenessMetricTests(unittest.TestCase):
    """Task J6 (spec-species-tree.md §5, §5.1). The reverse index over a fixture with two trees
    sharing a namespace affix -- the todo's own named verification -- plus U1/U2's own equivalents."""

    def setUp(self) -> None:
        self.metric = SpeciesUniquenessMetric()

    def _ctx(self, nodes_by_tree, quota_cells_by_tree=None) -> Ctx:
        return _ctx_with(PassiveTreePlanCtx(
            plans=[], archetypes=(), tier_count=10, unlock_first_points=0, unlock_step_points=0,
            reward_spread_max_ratio_milli=0, min_terminal_width=0,
            nodes_by_tree=nodes_by_tree, quota_cells_by_tree=quota_cells_by_tree or {}))

    def test_no_nodes_supplied_is_not_measured(self) -> None:
        findings = self.metric.run(self._ctx({}))
        self.assertEqual(1, len(findings))
        self.assertEqual(Severity.NOT_MEASURED, findings[0].severity)

    def test_a_clean_two_tree_corpus_has_no_gap(self) -> None:
        nodes_by_tree = {
            "might": [_uniq_node("n0", name="Might Strike", flavor="A steady line.")],
            "fortitude": [_uniq_node("n0", name="Fortitude Wall", flavor="A different line.")],
        }
        findings = self.metric.run(self._ctx(nodes_by_tree))
        self.assertEqual([], _gap_findings(findings))

    def test_u1_a_repeated_name_and_flavor_pair_across_two_trees_is_a_gap(self) -> None:
        nodes_by_tree = {
            "might": [_uniq_node("n0", name="Same Name", flavor="Same flavor.")],
            "fortitude": [_uniq_node("n0", name="Same Name", flavor="Same flavor.")],
        }
        findings = self.metric.run(self._ctx(nodes_by_tree))
        gaps = [f for f in _gap_findings(findings) if f.subject.startswith("U1:")]
        self.assertEqual(1, len(gaps))
        self.assertEqual({"might:n0", "fortitude:n0"}, set(gaps[0].evidence["nodeRefs"]))

    def test_u1_the_same_name_with_a_different_flavor_is_not_a_collision(self) -> None:
        nodes_by_tree = {
            "might": [_uniq_node("n0", name="Same Name", flavor="First flavor.")],
            "fortitude": [_uniq_node("n0", name="Same Name", flavor="Second flavor.")],
        }
        findings = self.metric.run(self._ctx(nodes_by_tree))
        self.assertEqual([], [f for f in _gap_findings(findings) if f.subject.startswith("U1:")])

    def test_u2_the_same_affixids_and_quotacell_fingerprint_across_two_trees_is_a_gap(self) -> None:
        nodes_by_tree = {
            "might": [_uniq_node("n0", affix_ids=("atom.a", "atom.b"))],
            "fortitude": [_uniq_node("n1", affix_ids=("atom.b", "atom.a"))],  # same set, different order
        }
        cells = {"might": {"n0": _cell()}, "fortitude": {"n1": _cell()}}  # identical cell
        findings = self.metric.run(self._ctx(nodes_by_tree, cells))
        gaps = [f for f in _gap_findings(findings) if f.subject.startswith("U2:")]
        self.assertEqual(1, len(gaps))
        self.assertEqual({"might", "fortitude"}, set(gaps[0].evidence["treeIds"]))

    def test_u2_the_same_affixids_with_a_different_quotacell_is_not_a_collision(self) -> None:
        nodes_by_tree = {
            "might": [_uniq_node("n0", affix_ids=("atom.a",))],
            "fortitude": [_uniq_node("n1", affix_ids=("atom.a",))],
        }
        cells = {"might": {"n0": _cell(element="fire")},
                "fortitude": {"n1": _cell(element="earth")}}
        findings = self.metric.run(self._ctx(nodes_by_tree, cells))
        self.assertEqual([], [f for f in _gap_findings(findings) if f.subject.startswith("U2:")])

    def test_u2_a_node_with_no_observed_quota_cell_contributes_nothing_not_a_crash(self) -> None:
        nodes_by_tree = {"might": [_uniq_node("n0", affix_ids=("atom.a",))]}
        findings = self.metric.run(self._ctx(nodes_by_tree, quota_cells_by_tree={}))
        self.assertEqual([], [f for f in _gap_findings(findings) if f.subject.startswith("U2:")])

    def test_u3_a_species_namespace_affix_referenced_by_two_trees_is_a_gap(self) -> None:
        # The todo's own named verification: "the reverse index over a fixture with two trees
        # sharing a namespace affix."
        nodes_by_tree = {
            "SpeciesA": [_uniq_node("n0", affix_ids=("affix.species.SpeciesA.mark",))],
            "SpeciesB": [_uniq_node("n1", affix_ids=("affix.species.SpeciesA.mark",))],
        }
        findings = self.metric.run(self._ctx(nodes_by_tree))
        gaps = [f for f in _gap_findings(findings) if f.subject.startswith("U3:")]
        self.assertEqual(1, len(gaps))
        self.assertEqual("SpeciesA", gaps[0].evidence["owner"])
        self.assertEqual(["SpeciesB"], gaps[0].evidence["foreignTreeIds"])

    def test_u3_a_species_namespace_affix_used_only_by_its_own_tree_is_not_a_finding(self) -> None:
        nodes_by_tree = {
            "SpeciesA": [_uniq_node("n0", affix_ids=("affix.species.SpeciesA.mark",))],
        }
        findings = self.metric.run(self._ctx(nodes_by_tree))
        self.assertEqual([], [f for f in _gap_findings(findings) if f.subject.startswith("U3:")])

    def test_the_metric_never_appears_in_all_passive_tree_metrics(self) -> None:
        self.assertNotIn(SpeciesUniquenessMetric, ALL_PASSIVE_TREE_METRICS)

    def test_gates_is_false(self) -> None:
        self.assertFalse(SpeciesUniquenessMetric.gates)


if __name__ == "__main__":
    unittest.main()
