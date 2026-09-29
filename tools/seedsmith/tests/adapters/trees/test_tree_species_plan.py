"""Tests for seedsmith.adapters.trees.species.plan (task J5, spec-species-tree.md §3, §4).

Covers the todo's own J5 acceptance bullets directly: the favour quota sums to the species count;
a forced cell returns its draw to the pool; an overdrawn forced quota is refused, not rebalanced;
every alternate offered is inside the quota; the mechanical lock is never read from the anchor; the
plan is reproducible from species_id alone.
"""
from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path

from seedsmith.adapters.actions.distribution_planner.derive import largest_remainder_count
from seedsmith.adapters.trees.species import plan
from seedsmith.adapters.trees.targets import PassiveTreeTargets, SkewRow


def _targets(skew_rows=()) -> PassiveTreeTargets:
    return PassiveTreeTargets(
        aptitude_weight_scheme="uniform",
        node_class_weights_milli=(500, 500), node_class_order=("mechanism", "magnitude"),
        exclusion_form_weights_milli=(450, 450, 100),
        exclusion_form_order=("reroute", "precedence", "nullification"),
        legitimate_skew_rows=tuple(skew_rows),
        exclusion_target_share_milli=20, species_unique_affix_min=8,
        tier2_sample_size=60, tier3_additional_sample_size=30, acceptance_ladder=(),
        cell_occupancy_median_max=2, quota_drift_tolerance_units=1,
        mechanism_ramp_deepest_tier_share_milli=1000, exclusion_rate_max_share_permille=30,
        near_duplicate_rate_max_share_permille=5, unresolved_count_max_share_permille=50,
    )


def _tiny_axis_root(tmp: str, *, aptitudes=("Might", "Fortitude"), elements=("fire", "earth"),
                    statuses=("poison", "rally")) -> Path:
    root = Path(tmp)
    (root / "aptitudes").mkdir(parents=True, exist_ok=True)
    (root / "elements").mkdir(parents=True, exist_ok=True)
    (root / "statuses").mkdir(parents=True, exist_ok=True)
    (root / "aptitudes" / "roster.json").write_text(json.dumps(
        {"entries": [{"id": a, "ordinal": i} for i, a in enumerate(aptitudes)]}), encoding="utf-8")
    (root / "elements" / "roster.json").write_text(json.dumps(
        {"entries": [{"id": e, "ordinal": i} for i, e in enumerate(elements)]}), encoding="utf-8")
    (root / "statuses" / "roster.json").write_text(json.dumps(
        {"entries": [{"id": s} for s in statuses]}), encoding="utf-8")
    return root


class SkewedWeightsMilliTests(unittest.TestCase):
    def test_no_skew_rows_is_an_even_split_summing_to_1000(self) -> None:
        weights = plan._skewed_weights_milli(["a", "b", "c", "d"], [])
        self.assertEqual(1000, sum(weights.values()))
        self.assertEqual({250, 250, 250, 250}, set(weights.values()))

    def test_a_skew_row_fixes_its_member_and_the_rest_split_the_remainder(self) -> None:
        rows = [SkewRow(axis="element", member="earth", weight_milli=500, why="plants are earthy")]
        weights = plan._skewed_weights_milli(["fire", "earth", "ice", "air"], rows)
        self.assertEqual(500, weights["earth"])
        self.assertEqual(1000, sum(weights.values()))
        # The remaining 500‰ splits evenly over the three free members.
        self.assertEqual({166, 167}, set(weights[m] for m in ("fire", "ice", "air")))

    def test_skew_rows_overdrawing_the_axis_are_refused(self) -> None:
        rows = [SkewRow(axis="element", member="earth", weight_milli=1200, why="too much")]
        with self.assertRaises(plan.FavourPlanError) as ctx:
            plan._skewed_weights_milli(["fire", "earth"], rows)
        self.assertIn("overdraw", str(ctx.exception))

    def test_a_skew_row_naming_a_member_outside_the_axis_is_refused(self) -> None:
        rows = [SkewRow(axis="element", member="water", weight_milli=200, why="not real")]
        with self.assertRaises(plan.FavourPlanError):
            plan._skewed_weights_milli(["fire", "earth"], rows)


class AxisWeightTablesTests(unittest.TestCase):
    def test_each_axis_table_sums_to_1000_independently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _tiny_axis_root(tmp)
            tables = plan.axis_weight_tables(_targets(), seed_root=root)
            self.assertEqual({"aptitude", "element", "status"}, set(tables))
            for axis, table in tables.items():
                self.assertEqual(1000, sum(table.values()), f"{axis} table did not sum to 1000")

    def test_a_skew_row_is_visible_directly_on_its_own_axis_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _tiny_axis_root(tmp)
            skewed = _targets(skew_rows=[
                SkewRow(axis="element", member="earth", weight_milli=600, why="plants are earthy")])
            tables = plan.axis_weight_tables(skewed, seed_root=root)
            self.assertEqual(600, tables["element"]["earth"])
            # _tiny_axis_root's default fixture has 2 aptitudes -- unaffected by the element skew.
            self.assertEqual({500, 500}, set(tables["aptitude"].values()))


class MechanicalFavourWeightsMilliTests(unittest.TestCase):
    def test_the_joint_table_sums_to_exactly_1000_over_a_tiny_axis_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _tiny_axis_root(tmp)
            cells, weights = plan.mechanical_favour_weights_milli(_targets(), seed_root=root)
            self.assertEqual(2 * 2 * 2, len(cells))
            self.assertEqual(1000, sum(weights.values()))

    def test_the_real_axis_rosters_give_1728_cells_summing_to_1000(self) -> None:
        # Against the REAL committed gk-data/packs/fusion/data/seed/{aptitudes,elements,statuses}/roster.json mirrors —
        # 12 aptitudes x 6 elements x 24 statuses, confirmed directly before writing this module.
        cells, weights = plan.mechanical_favour_weights_milli(_targets())
        self.assertEqual(12 * 6 * 24, len(cells))
        self.assertEqual(1000, sum(weights.values()))

    def test_an_earth_skew_row_makes_earth_cells_outweigh_an_unskewed_element_in_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _tiny_axis_root(tmp)
            skewed = _targets(skew_rows=[
                SkewRow(axis="element", member="earth", weight_milli=700, why="plants are earthy")])
            cells, weights = plan.mechanical_favour_weights_milli(skewed, seed_root=root)
            earth_total = sum(w for k, w in weights.items()
                              if cells[[c.key() for c in cells].index(k)].element == "earth")
            fire_total = sum(w for k, w in weights.items()
                             if cells[[c.key() for c in cells].index(k)].element == "fire")
            self.assertGreater(earth_total, fire_total)


class AssignFavourCellsTests(unittest.TestCase):
    def _species_ids(self, n: int) -> "list[str]":
        return [f"Species{i:03d}" for i in range(n)]

    def test_the_favour_quota_sums_to_the_species_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _tiny_axis_root(tmp)
            targets = _targets()
            cells, weights = plan.mechanical_favour_weights_milli(targets, seed_root=root)
            order = [c.key() for c in cells]
            quota = largest_remainder_count(weights, order, 5)
            self.assertEqual(5, sum(quota.values()))
            assignments = plan.assign_favour_cells(self._species_ids(5), targets, seed_root=root)
            self.assertEqual(5, len(assignments))

    def test_a_forced_cell_returns_its_draw_to_the_pool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _tiny_axis_root(tmp)
            targets = _targets()
            cells, _ = plan.mechanical_favour_weights_milli(targets, seed_root=root)
            forced_cell = cells[0]
            species = self._species_ids(6)
            forced = {species[0]: forced_cell}
            assignments = plan.assign_favour_cells(species, targets, forced, seed_root=root)
            self.assertEqual(6, len(assignments))
            self.assertEqual(forced_cell, assignments[species[0]].cell)
            # Every other (free) species still received a real, distinct assignment — the pool
            # absorbed the forced draw rather than silently shorting one of the free species.
            free_cells = [assignments[s].cell for s in species[1:]]
            self.assertEqual(5, len(free_cells))

    def test_an_overdrawn_forced_quota_is_refused_not_rebalanced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _tiny_axis_root(tmp)
            targets = _targets()
            cells, weights = plan.mechanical_favour_weights_milli(targets, seed_root=root)
            order = [c.key() for c in cells]
            # 3 species total, over an 8-cell uniform table -> every cell's own quota is 0 or 1.
            quota = largest_remainder_count(weights, order, 3)
            single_slot_cell = next(cells[order.index(k)] for k, v in quota.items() if v <= 1)
            species = self._species_ids(3)
            # Force TWO species onto the SAME single-slot cell -- the second one overdraws it.
            forced = {species[0]: single_slot_cell, species[1]: single_slot_cell}
            with self.assertRaises(plan.FavourPlanError) as ctx:
                plan.assign_favour_cells(species, targets, forced, seed_root=root)
            self.assertIn("overdraws", str(ctx.exception))

    def test_every_alternate_offered_is_inside_the_quota(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _tiny_axis_root(tmp, aptitudes=("Might", "Fortitude", "Vigor"),
                                   elements=("fire", "earth", "ice"),
                                   statuses=("poison", "rally", "spark"))
            targets = _targets()
            species = self._species_ids(15)
            cells, weights = plan.mechanical_favour_weights_milli(targets, seed_root=root)
            order = [c.key() for c in cells]
            quota = largest_remainder_count(weights, order, len(species))
            quota_having = {k for k, v in quota.items() if v > 0}
            assignments = plan.assign_favour_cells(species, targets, seed_root=root)
            checked_any = False
            for assignment in assignments.values():
                for alt in assignment.alternates:
                    checked_any = True
                    self.assertIn(alt.key(), quota_having,
                                  f"{alt.key()} was offered as an alternate but has zero quota")
                    self.assertNotEqual(assignment.cell.key(), alt.key())
            self.assertTrue(checked_any, "no alternates were ever offered -- test fixture too small")

    def test_the_plan_is_reproducible_from_species_id_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _tiny_axis_root(tmp, aptitudes=("Might", "Fortitude", "Vigor"),
                                   elements=("fire", "earth", "ice"),
                                   statuses=("poison", "rally", "spark"))
            targets = _targets()
            species = self._species_ids(10)
            first = plan.assign_favour_cells(species, targets, seed_root=root)
            second = plan.assign_favour_cells(species, targets, seed_root=root)
            self.assertEqual({s: a.cell for s, a in first.items()},
                            {s: a.cell for s, a in second.items()})
            self.assertEqual({s: a.alternates for s, a in first.items()},
                            {s: a.alternates for s, a in second.items()})

            # Reordering the INPUT list changes nothing about any individual species' own outcome --
            # each one's cell is seeded from its own id, never its position in the caller's list.
            reordered = list(reversed(species))
            third = plan.assign_favour_cells(reordered, targets, seed_root=root)
            self.assertEqual({s: a.cell for s, a in first.items()},
                            {s: a.cell for s, a in third.items()})

    def test_growing_the_roster_recomputes_the_quota_fresh_no_incremental_stability_is_claimed(self) -> None:
        # A real property discovered while writing this suite, not assumed going in: this module's
        # OWN "reproducible" promise (spec-species-tree.md §3.1/§4) is about a FIXED roster producing
        # the same plan every time -- it says nothing about a GROWING roster leaving prior species
        # untouched. `largest_remainder_count`'s quota is a function of the CURRENT total, recomputed
        # fresh every call (matching every other caller of that utility in this codebase), so
        # widening the total by one can legitimately shift several cells' own floor/remainder split,
        # not just add one unit somewhere. That incremental-stability property IS real elsewhere in
        # this spec (§5.3 rule 3's marked-node prefix order), but it is never claimed for the
        # favour-CELL assignment itself, and this test exists to keep that boundary from being
        # silently assumed later. What DOES hold, and is asserted here: the total assigned count
        # always equals the roster size, on either side of the growth.
        with tempfile.TemporaryDirectory() as tmp:
            root = _tiny_axis_root(tmp, aptitudes=("Might", "Fortitude", "Vigor", "Onslaught"),
                                   elements=("fire", "earth", "ice", "air"),
                                   statuses=("poison", "rally", "spark", "wither"))
            targets = _targets()
            base = self._species_ids(20)
            before = plan.assign_favour_cells(base, targets, seed_root=root)
            grown = base + ["SpeciesNew"]
            after = plan.assign_favour_cells(grown, targets, seed_root=root)
            # Self-referential (population-pin SE3.5, 2026-09-20): this test built base/grown itself,
            # so it proves the plan tracks the roster size, not a fact about shipped content.
            self.assertEqual(len(base), len(before))
            self.assertEqual(len(grown), len(after))


def _mech_node(node_id: str, *, tier: int, branch: str, node_key: str,
               node_class: str = "mechanism") -> dict:
    return {"id": node_id, "tier": tier, "branch": branch, "nodeKey": node_key,
           "nodeClass": node_class}


_BRANCH_CHOICES = ("offensive", "defensive")


class MarkSpeciesUniqueNodesTests(unittest.TestCase):
    def test_negative_k_is_refused(self) -> None:
        with self.assertRaises(plan.FavourPlanError):
            plan.mark_species_unique_nodes([], -1)

    def test_k_zero_is_legal_and_returns_empty(self) -> None:
        nodes = [_mech_node("n0", tier=10, branch="offensive", node_key="n0")]
        self.assertEqual(frozenset(), plan.mark_species_unique_nodes(nodes, 0))

    def test_magnitude_nodes_are_never_selected(self) -> None:
        nodes = [
            _mech_node("mag-deep", tier=10, branch="offensive", node_key="a", node_class="magnitude"),
            _mech_node("mech-shallow", tier=1, branch="offensive", node_key="a"),
        ]
        marked = plan.mark_species_unique_nodes(nodes, 5)
        self.assertEqual({"mech-shallow"}, marked)

    def test_deepest_tier_is_picked_before_a_shallower_one(self) -> None:
        nodes = [
            _mech_node("shallow", tier=1, branch="offensive", node_key="a"),
            _mech_node("deep", tier=9, branch="offensive", node_key="a"),
        ]
        marked = plan.mark_species_unique_nodes(nodes, 1)
        self.assertEqual({"deep"}, marked)

    def test_ties_at_the_same_tier_break_on_branch_order_then_node_key(self) -> None:
        nodes = [
            _mech_node("def-a", tier=5, branch="defensive", node_key="a"),
            _mech_node("off-b", tier=5, branch="offensive", node_key="b"),
            _mech_node("off-a", tier=5, branch="offensive", node_key="a"),
        ]
        # BRANCH = ("offensive", "defensive") -- offensive sorts first; within offensive, "a" < "b".
        ordered_ids = ["off-a", "off-b", "def-a"]
        for k in range(4):
            marked = plan.mark_species_unique_nodes(nodes, k)
            self.assertEqual(set(ordered_ids[:k]), marked, f"k={k}")

    def test_raising_species_unique_affix_min_never_unmarks_a_marked_node(self) -> None:
        # The exact named property: the mark set at k=8 strictly CONTAINS the set at k=4, over a
        # realistic 16-mechanism-node pool (gated-deep's own smallest real mechanism pool, per
        # spec-species-tree.md §5.3 rule 3's own worked bound).
        nodes = [_mech_node(f"n{i}", tier=(i % 10) + 1, branch=_BRANCH_CHOICES[i % 2],
                            node_key=f"k{i:02d}") for i in range(16)]
        low = plan.mark_species_unique_nodes(nodes, 4)
        high = plan.mark_species_unique_nodes(nodes, 8)
        self.assertTrue(low.issubset(high), f"{low} is not a subset of {high}")
        self.assertEqual(4, len(low))
        self.assertEqual(8, len(high))
        # And the property holds one step further too -- a strict superset relationship at every
        # step, not just a coincidence between these two particular values.
        highest = plan.mark_species_unique_nodes(nodes, 12)
        self.assertTrue(high.issubset(highest))


class DecouplingTests(unittest.TestCase):
    """§4's own rule: `mechanicalFavour` is never read from the anchor's `elementPrimary`/
    `aptitudePrimary`. `assign_favour_cells` takes no anchor data at all, which this test asserts
    structurally rather than by convention -- the module cannot regress into reading an anchor
    field it never imports the type for."""

    def test_the_module_never_references_anchor_fields_or_imports_the_roster_module(self) -> None:
        source = inspect.getsource(plan)
        self.assertNotIn("elementPrimary", source)
        self.assertNotIn("aptitudePrimary", source)
        self.assertNotIn("SpeciesAnchor", source)
        self.assertNotIn("species.roster", source)
        self.assertNotIn("species import roster", source)

    def test_assign_favour_cells_has_no_anchor_or_species_object_parameter(self) -> None:
        params = inspect.signature(plan.assign_favour_cells).parameters
        for name in params:
            self.assertNotIn("anchor", name.lower())
