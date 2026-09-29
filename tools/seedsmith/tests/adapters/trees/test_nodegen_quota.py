"""Tests for seedsmith.adapters.trees.nodegen.quota (task H1) — axis-marginal apportionment via the
shared `largest_remainder_count`, and `permitted()`'s own load-bearing line: the permitted subset
IS the enum, so an out-of-quota value is unsampleable.

Task H3's own additions are tested below: the per-slot cell walk (`build_slot`,
`assign_quota_cells`), the return-to-pool rebalance (`rebalance_axis`) and its refusal on an
overdrawn cell (`OverdrawnQuota`), and the plan-facing wrapper (`quota_for_plan`,
`permitted_ids_for_cell`) — including an integration pass against the REAL committed `might.v1.json`
plan and the REAL `passive-tree-targets.v2.json`, which is the "corpus-level quota check reproduces
the declared target" verification the todo's own H3 entry names.
"""
from __future__ import annotations

import collections
import unittest
from types import SimpleNamespace

from seedsmith.adapters.trees.nodegen import plan_read, quota, tuning


class UniformWeightsMilliTests(unittest.TestCase):
    def test_sums_to_exactly_1000(self) -> None:
        weights = quota.uniform_weights_milli(["a", "b", "c", "d", "e", "f", "g"])
        self.assertEqual(sum(weights.values()), 1000)

    def test_every_member_is_present(self) -> None:
        members = ["fire", "water", "earth", "omni"]
        weights = quota.uniform_weights_milli(members)
        self.assertEqual(set(weights), set(members))

    def test_refuses_an_empty_member_list(self) -> None:
        with self.assertRaises(ValueError):
            quota.uniform_weights_milli([])


class AxisMarginalsTests(unittest.TestCase):
    def test_marginals_sum_to_the_requested_total(self) -> None:
        weights = quota.uniform_weights_milli(["mechanism", "magnitude"])
        order = ("mechanism", "magnitude")
        marginals = quota.axis_marginals(weights, order, 1560)
        self.assertEqual(sum(marginals.values()), 1560)

    def test_expand_counts_flattens_to_the_exact_length(self) -> None:
        weights = {"reroute": 450, "precedence": 450, "nullification": 100}
        order = ("reroute", "precedence", "nullification")
        marginals = quota.axis_marginals(weights, order, 40)
        flattened = quota.expand_counts(marginals, order)
        self.assertEqual(len(flattened), 40)
        self.assertEqual(flattened.count("nullification"), marginals["nullification"])


class QuotaCellTests(unittest.TestCase):
    def _cell(self) -> quota.QuotaCell:
        return quota.QuotaCell(
            node_class="magnitude", trigger="onHit", element="fire", status="status.burn",
            channel_family="combat.dmg", exclusion_form="none",
        )

    def test_value_for_reads_the_matching_axis(self) -> None:
        cell = self._cell()
        self.assertEqual(cell.value_for("element"), "fire")
        self.assertEqual(cell.value_for("exclusionForm"), "none")

    def test_value_for_raises_on_an_unknown_axis(self) -> None:
        with self.assertRaises(KeyError):
            self._cell().value_for("notAnAxis")

    def test_axes_constant_has_exactly_the_six_named_in_the_spec(self) -> None:
        self.assertEqual(
            quota.AXES,
            ("nodeClass", "trigger", "element", "status", "channelFamily", "exclusionForm"),
        )


class PermittedTests(unittest.TestCase):
    """Gate 8's own load-bearing line, reproduced from the spec's Code style section verbatim."""

    def _vocab_and_tags(self):
        vocab_ids = {"element": ("fire", "water", "earth", "omni")}
        tag_of = {"element": {"fire": "fire", "water": "water", "earth": "earth", "omni": "omni"}}
        return vocab_ids, tag_of

    def test_permitted_narrows_to_only_the_cells_own_value(self) -> None:
        vocab_ids, tag_of = self._vocab_and_tags()
        cell = {"element": "fire"}
        result = quota.permitted("element", cell, vocab_ids, tag_of)
        self.assertEqual(result, ["fire"])
        for out_of_quota in ("water", "earth", "omni"):
            self.assertNotIn(out_of_quota, result)

    def test_an_unsatisfiable_cell_is_held_not_widened(self) -> None:
        vocab_ids, tag_of = self._vocab_and_tags()
        cell = {"element": "shadow"}  # not in the vocabulary at all
        with self.assertRaises(quota.UnsatisfiableCell):
            quota.permitted("element", cell, vocab_ids, tag_of)

    def test_raises_a_key_error_when_the_cell_has_no_value_for_the_axis(self) -> None:
        vocab_ids, tag_of = self._vocab_and_tags()
        with self.assertRaises(KeyError):
            quota.permitted("element", {}, vocab_ids, tag_of)


# ---------------------------------------------------------------------------------------------
# task H3 — axis_members / axis_order / axis_weights_milli: reading a real plan's own
# propertyVocabulary and a real targets object, never a hardcoded roster.
# ---------------------------------------------------------------------------------------------

class AxisMembersTests(unittest.TestCase):
    PROPERTY_VOCAB = {
        "nodeClass": ("mechanism", "magnitude"),
        "atomTrigger": ("OnHit", "OnKill", "OnGranted", "OnRemoved"),
        "element": ("fire", "water", "omni"),
        "status": ("burn", "freeze"),
        "channelFamily": ("combat.dmg",),
        "exclusionForm": ("reroute", "precedence", "nullification"),
    }

    def test_trigger_drops_the_two_non_authorable_members(self) -> None:
        members = quota.axis_members("trigger", self.PROPERTY_VOCAB)
        self.assertEqual(set(members), {"OnHit", "OnKill"})
        for non_authorable in quota.NON_AUTHORABLE_TRIGGERS:
            self.assertNotIn(non_authorable, members)

    def test_every_other_axis_reads_its_own_key_unfiltered(self) -> None:
        self.assertEqual(quota.axis_members("element", self.PROPERTY_VOCAB), ("fire", "water", "omni"))
        self.assertEqual(quota.axis_members("nodeClass", self.PROPERTY_VOCAB), ("mechanism", "magnitude"))

    def test_a_missing_key_refuses_rather_than_synthesising(self) -> None:
        with self.assertRaises(KeyError):
            quota.axis_members("status", {"nodeClass": ("mechanism", "magnitude")})

    def test_an_axis_left_with_no_authorable_members_refuses(self) -> None:
        with self.assertRaises(ValueError):
            quota.axis_members("trigger", {"atomTrigger": ("OnGranted", "OnRemoved")})


class AxisOrderAndWeightsTests(unittest.TestCase):
    """A minimal stand-in for `PassiveTreeTargets` — only the four attributes `axis_order`/
    `axis_weights_milli` actually read for the two explicitly-weighted axes."""

    def _targets(self) -> SimpleNamespace:
        return SimpleNamespace(
            node_class_order=("mechanism", "magnitude"), node_class_weights_milli=(500, 500),
            exclusion_form_order=("reroute", "precedence", "nullification"),
            exclusion_form_weights_milli=(450, 450, 100),
        )

    def test_node_class_order_and_weights_come_straight_off_targets(self) -> None:
        targets = self._targets()
        members = ("mechanism", "magnitude")
        self.assertEqual(quota.axis_order("nodeClass", targets, members), ("mechanism", "magnitude"))
        self.assertEqual(quota.axis_weights_milli("nodeClass", targets, members),
                        {"mechanism": 500, "magnitude": 500})

    def test_a_uniform_axis_orders_by_the_plans_own_member_listing(self) -> None:
        targets = self._targets()
        members = ("fire", "water", "omni")
        self.assertEqual(quota.axis_order("element", targets, members), members)
        weights = quota.axis_weights_milli("element", targets, members)
        self.assertEqual(sum(weights.values()), 1000)
        self.assertEqual(set(weights), set(members))

    def test_mismatched_node_class_membership_refuses(self) -> None:
        targets = self._targets()
        with self.assertRaises(ValueError):
            quota.axis_weights_milli("nodeClass", targets, ("mechanism", "magnitude", "extra"))


# ---------------------------------------------------------------------------------------------
# task H3 — build_slot: the two category overrides (elemental -> element, status -> status) plus
# the universal nodeClass override every slot carries regardless of category.
# ---------------------------------------------------------------------------------------------

class BuildSlotTests(unittest.TestCase):
    def _node(self, node_id: str = "skill.t-off-t1-n0", node_class: str = "magnitude"):
        return SimpleNamespace(node_id=node_id, node_class=node_class)

    def test_a_primary_tree_only_forces_node_class(self) -> None:
        slot = quota.build_slot(self._node(), category="primary")
        self.assertEqual(slot.forced, {"nodeClass": "magnitude"})

    def test_an_elemental_tree_also_forces_element(self) -> None:
        slot = quota.build_slot(self._node(), category="elemental", forced_element="fire")
        self.assertEqual(slot.forced, {"nodeClass": "magnitude", "element": "fire"})

    def test_a_status_tree_also_forces_status(self) -> None:
        slot = quota.build_slot(self._node(), category="status", forced_status="burn")
        self.assertEqual(slot.forced, {"nodeClass": "magnitude", "status": "burn"})

    def test_an_elemental_tree_without_a_forced_element_refuses(self) -> None:
        with self.assertRaises(ValueError):
            quota.build_slot(self._node(), category="elemental")

    def test_a_status_tree_without_a_forced_status_refuses(self) -> None:
        with self.assertRaises(ValueError):
            quota.build_slot(self._node(), category="status")

    def test_a_species_tree_forces_both_element_and_status_at_once(self) -> None:
        # Task J8 (2026-09-07): the real, different shape from elemental/status trees, which each
        # force exactly ONE of the two. Found and fixed while wiring `TreeSpec.mechanical_favour`
        # through to a real quota computation -- the original `if/elif` could never express "both,"
        # and silently forced NEITHER for `category="species"` before this fix.
        slot = quota.build_slot(self._node(), category="species", forced_element="air",
                               forced_status="spark")
        self.assertEqual({"nodeClass": "magnitude", "element": "air", "status": "spark"}, slot.forced)

    def test_a_species_tree_without_a_forced_element_refuses(self) -> None:
        with self.assertRaises(ValueError):
            quota.build_slot(self._node(), category="species", forced_status="spark")

    def test_a_species_tree_without_a_forced_status_refuses(self) -> None:
        with self.assertRaises(ValueError):
            quota.build_slot(self._node(), category="species", forced_element="air")

    def test_a_primary_tree_never_silently_forces_element_or_status(self) -> None:
        # The other real regression the old if/elif shape risked in reverse -- confirming the fix
        # did not widen forcing to categories that must NOT have it.
        slot = quota.build_slot(self._node(), category="primary", forced_element="air",
                               forced_status="spark")
        self.assertEqual({"nodeClass": "magnitude"}, slot.forced)


# ---------------------------------------------------------------------------------------------
# task H3 — rebalance_axis: the step-5 return-to-pool, and OverdrawnQuota's own refusal.
# ---------------------------------------------------------------------------------------------

class RebalanceAxisTests(unittest.TestCase):
    def test_a_forced_value_returns_its_draw_to_the_pool(self) -> None:
        quota_for_axis = {"fire": 10, "water": 10, "omni": 20}
        forced = {"fire": 10}  # e.g. one elemental tree's whole 10-node share, all forced to fire
        residual = quota.rebalance_axis(quota_for_axis, forced)
        self.assertEqual(residual, {"fire": 0, "water": 10, "omni": 20})
        # the residual is exactly the free-slot count: 40 - 10 == 30
        self.assertEqual(sum(residual.values()), sum(quota_for_axis.values()) - sum(forced.values()))

    def test_no_forced_values_leaves_the_quota_untouched(self) -> None:
        quota_for_axis = {"fire": 10, "water": 10, "omni": 20}
        self.assertEqual(quota.rebalance_axis(quota_for_axis, {}), quota_for_axis)

    def test_forcing_more_than_the_quota_allocated_is_refused(self) -> None:
        quota_for_axis = {"fire": 5, "water": 35}
        with self.assertRaises(quota.OverdrawnQuota):
            quota.rebalance_axis(quota_for_axis, {"fire": 6})

    def test_forcing_a_value_outside_the_axis_quota_entirely_is_refused(self) -> None:
        quota_for_axis = {"fire": 5, "water": 35}
        with self.assertRaises(quota.OverdrawnQuota):
            quota.rebalance_axis(quota_for_axis, {"shadow": 1})


# ---------------------------------------------------------------------------------------------
# task H3 — assign_quota_cells: the full two-pass per-slot walk over a small synthetic corpus.
# ---------------------------------------------------------------------------------------------

class AssignQuotaCellsTests(unittest.TestCase):
    def _uniform_quota(self, members, total):
        weights = quota.uniform_weights_milli(list(members))
        return quota.axis_marginals(weights, tuple(members), total)

    def _base_quota_and_order(self, total: int):
        node_class_order = ("mechanism", "magnitude")
        trigger_order = ("OnHit", "OnKill")
        element_order = ("fire", "water")
        status_order = ("burn", "freeze")
        channel_order = ("combat.dmg",)
        exclusion_order = ("reroute", "precedence", "nullification")
        order = {
            "nodeClass": node_class_order, "trigger": trigger_order, "element": element_order,
            "status": status_order, "channelFamily": channel_order, "exclusionForm": exclusion_order,
        }
        quota_map = {
            "nodeClass": self._uniform_quota(node_class_order, total),
            "trigger": self._uniform_quota(trigger_order, total),
            "element": self._uniform_quota(element_order, total),
            "status": self._uniform_quota(status_order, total),
            "channelFamily": self._uniform_quota(channel_order, total),
            "exclusionForm": self._uniform_quota(exclusion_order, total),
        }
        return quota_map, order

    def test_forced_axes_are_never_drawn_from_the_free_sequence(self) -> None:
        """Two slots, both from an elemental tree forced to 'fire' — every returned cell's own
        `element` must be exactly 'fire', never a free draw, and the returned draw goes back to
        the pool for the OTHER (unforced) slots."""
        quota_map, order = self._base_quota_and_order(total=4)
        slots = [
            quota.QuotaSlot(node_id="n0", forced={"nodeClass": "magnitude", "element": "fire"}),
            quota.QuotaSlot(node_id="n1", forced={"nodeClass": "mechanism", "element": "fire"}),
            quota.QuotaSlot(node_id="n2", forced={"nodeClass": "magnitude"}),
            quota.QuotaSlot(node_id="n3", forced={"nodeClass": "mechanism"}),
        ]
        cells = quota.assign_quota_cells(slots, quota_map, order)
        self.assertEqual(cells["n0"].element, "fire")
        self.assertEqual(cells["n1"].element, "fire")
        self.assertEqual(cells["n0"].node_class, "magnitude")
        self.assertEqual(cells["n1"].node_class, "mechanism")
        # every axis value on every cell must be a real member of that axis
        for cell in cells.values():
            self.assertIn(cell.trigger, order["trigger"])
            self.assertIn(cell.status, order["status"])
            self.assertIn(cell.channel_family, order["channelFamily"])
            self.assertIn(cell.exclusion_form, order["exclusionForm"])

    def test_every_slot_gets_exactly_one_cell_and_none_are_skipped(self) -> None:
        quota_map, order = self._base_quota_and_order(total=4)
        classes = ["magnitude", "magnitude", "mechanism", "mechanism"]  # matches the 2/2 quota
        slots = [quota.QuotaSlot(node_id=f"n{i}", forced={"nodeClass": classes[i]}) for i in range(4)]
        cells = quota.assign_quota_cells(slots, quota_map, order)
        self.assertEqual(set(cells), {"n0", "n1", "n2", "n3"})

    def test_an_axis_whose_free_slot_count_exceeds_its_residual_is_refused(self) -> None:
        """A pathological caller: `quota` built for a SMALLER total than `slots` actually has. The
        free sequence runs dry before the walk does -- refused, never wrapped or reused."""
        quota_map, order = self._base_quota_and_order(total=2)  # only 2 slots' worth of draws
        slots = [quota.QuotaSlot(node_id=f"n{i}", forced={"nodeClass": "magnitude"}) for i in range(4)]
        with self.assertRaises(quota.OverdrawnQuota):
            quota.assign_quota_cells(slots, quota_map, order)


# ---------------------------------------------------------------------------------------------
# task H3 — quota_for_plan / permitted_ids_for_cell: the plan-facing wrapper, proven against the
# REAL committed `might.v1.json` plan and the REAL passive-tree-targets.v2.json. This is the
# "corpus-level quota check reproduces the declared target" verification the H3 todo entry names.
# ---------------------------------------------------------------------------------------------

class QuotaForRealMightPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = plan_read.load("might")
        cls.targets = tuning.load()
        cls.cells = quota.quota_for_plan(cls.plan, cls.targets, category="primary")

    def test_every_node_gets_exactly_one_cell(self) -> None:
        self.assertEqual(set(self.cells), {n.node_id for n in self.plan.nodes})

    def test_node_class_is_forced_to_the_plans_own_value_on_every_node(self) -> None:
        by_id = {n.node_id: n for n in self.plan.nodes}
        for node_id, cell in self.cells.items():
            self.assertEqual(cell.node_class, by_id[node_id].node_class)

    def test_node_class_marginal_reproduces_the_declared_target(self) -> None:
        """`might` is `broad-and-flat` (10 mechanism / 10 magnitude per branch, 20/20 over both) —
        which is EXACTLY the targets file's own 500/500 nodeClass split at N=40. Reproduced here by
        counting the (fully-forced) nodeClass axis across every emitted cell."""
        counts = collections.Counter(cell.node_class for cell in self.cells.values())
        self.assertEqual(counts["mechanism"], 20)
        self.assertEqual(counts["magnitude"], 20)

    def test_free_axis_marginals_match_an_independent_re_derivation(self) -> None:
        """Nothing forces trigger/status/channelFamily for a PRIMARY tree, so their marginals
        across the emitted cells must equal `axis_marginals` computed independently over the same
        members/weights/order/total -- proving the walk did not silently drop or duplicate a draw
        anywhere.

        `exclusionForm` is asserted separately (the two-stage test below): 2026-09-11's domain fix
        makes its marginals a two-stage split -- `none` vs the excluded subset by
        `exclusion.targetShareMilli`, then the 450/450/100 rung weights over the excluded subset --
        which a flat re-derivation over all 40 slots can never reproduce by design.
        """
        total = len(self.plan.nodes)
        for axis in ("trigger", "status", "channelFamily"):
            members = quota.axis_members(axis, self.plan.property_vocabulary)
            weights = quota.axis_weights_milli(axis, self.targets, members)
            order = quota.axis_order(axis, self.targets, members)
            expected = quota.axis_marginals(weights, order, total)
            actual = collections.Counter(cell.value_for(axis) for cell in self.cells.values())
            # `expected` names every member (including a 0 count); `Counter` only names members
            # that were actually drawn -- fill the zeros back in so the comparison is over the
            # same key set, never dropping a "this member got zero, and that's correct" fact.
            actual_full = {m: actual.get(m, 0) for m in expected}
            self.assertEqual(actual_full, expected, f"axis {axis!r} marginal drifted from target")

    def test_exclusion_form_follows_the_two_stage_apportionment(self) -> None:
        """2026-09-11's A2 quota-domain fix: `none` holds the non-designated share of cells
        (`exclusion.targetShareMilli` names the designated subset's size), and the 450/450/100
        rung weights split the EXCLUDED subset, never the whole tree. Reproduced here against the
        real `might` plan: 40 slots x 20 per mille -> ~1 designated slot; its rung is the first
        of the declared 450/450/100 order."""
        targets = self.targets
        total = len(self.plan.nodes)
        designated = quota.largest_remainder_count(
            {"kept": 1000 - targets.exclusion_target_share_milli,
             "excluded": targets.exclusion_target_share_milli},
            ("kept", "excluded"), total)["excluded"]
        counts = collections.Counter(cell.exclusion_form for cell in self.cells.values())
        self.assertEqual(counts["none"], total - designated)
        # The rung split over the designated subset, by the declared weights/order:
        members = quota.axis_members("exclusionForm", self.plan.property_vocabulary)
        weights = quota.axis_weights_milli("exclusionForm", targets, members)
        order = quota.axis_order("exclusionForm", targets, members)
        rungs = {m: counts.get(m, 0) for m in members}
        self.assertEqual(rungs, quota.axis_marginals(weights, order, designated))
        # And the whole axis still sums to the tree's own node count:
        self.assertEqual(sum(counts.values()), total)

    def test_every_free_axis_value_sums_to_the_real_node_count(self) -> None:
        total = len(self.plan.nodes)
        for axis in quota.AXES:
            counts = collections.Counter(cell.value_for(axis) for cell in self.cells.values())
            self.assertEqual(sum(counts.values()), total)

    def test_a_rerun_over_the_same_plan_is_byte_identical(self) -> None:
        """No RNG anywhere in the walk: two independent calls over the same plan/targets produce
        the exact same cell per node, every axis."""
        again = quota.quota_for_plan(self.plan, self.targets, category="primary")
        self.assertEqual(self.cells, again)

    def test_permitted_ids_for_cell_narrows_every_axis_to_the_cells_own_value(self) -> None:
        sample_node_id = self.plan.nodes[0].node_id
        cell = self.cells[sample_node_id]
        permitted_ids = quota.permitted_ids_for_cell(cell, self.plan.property_vocabulary)
        self.assertEqual(set(permitted_ids), set(quota.AXES))
        for axis in quota.AXES:
            self.assertEqual(permitted_ids[axis], [cell.value_for(axis)])

    def test_missing_property_vocabulary_is_never_silently_widened(self) -> None:
        """§5.1/R8, restated at the quota layer: an axis this plan's own propertyVocabulary does
        not carry is a refusal, never a fallback to the whole vocabulary."""
        with self.assertRaises(KeyError):
            quota.axis_members("status", {k: v for k, v in self.plan.property_vocabulary.items()
                                          if k != "status"})


class QuotaForForcedElementOrStatusCategoryTests(unittest.TestCase):
    """2026-09-06, found by an adversarial spec audit (not a second real crash): `nodeClass`'s own
    fix (quota derived from the real tally whenever an axis is forced on every slot) was written
    against nodeClass's OWN always-100%-forced shape, but `build_slot` forces `element`/`status`
    the exact same way -- 100% of a tree's own 40 slots -- whenever `category` is `"elemental"` /
    `"status"`. A flat, tree-oblivious weight (the targets file's own near-uniform ~1/7-per-element
    split) can never satisfy "this whole 40-node tree is one element," for the identical reason a
    flat 500/500 nodeClass split could never satisfy a `gated-deep` tree's real 16/24 archetype
    split. Proven here by reproducing the crash directly (against the REAL might.v1.json plan
    reused as a stand-in shape, since no elemental/status tree has ever been planned for real) and
    confirming the same general fix that already covers `nodeClass` for primary trees also covers
    this case, with zero special-casing by axis name."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = plan_read.load("might")
        cls.targets = tuning.load()

    def test_a_synthetic_elemental_tree_forcing_every_slot_to_one_element_no_longer_overdraws(self) -> None:
        cells = quota.quota_for_plan(self.plan, self.targets, category="elemental",
                                     forced_element="fire", forced_status=None)
        self.assertEqual(len(cells), len(self.plan.nodes))
        for cell in cells.values():
            self.assertEqual(cell.value_for("element"), "fire")

    def test_a_synthetic_status_tree_forcing_every_slot_to_one_status_no_longer_overdraws(self) -> None:
        cells = quota.quota_for_plan(self.plan, self.targets, category="status",
                                     forced_element=None, forced_status="wither")
        self.assertEqual(len(cells), len(self.plan.nodes))
        for cell in cells.values():
            self.assertEqual(cell.value_for("status"), "wither")

    def test_a_primary_trees_own_element_axis_still_draws_freely_not_forced(self) -> None:
        """The fix must not accidentally force `element` on a tree whose category never triggers
        the override -- a primary tree's element distribution stays a real, near-uniform spread."""
        cells = quota.quota_for_plan(self.plan, self.targets, category="primary")
        counts = collections.Counter(cell.value_for("element") for cell in cells.values())
        self.assertGreater(len(counts), 1, "a primary tree's element axis must still be freely drawn")

    def test_an_elemental_trees_own_nodeClass_axis_is_still_forced_by_the_plans_archetype(self) -> None:
        """Both mechanisms (nodeClass always-forced, element forced-by-category) apply
        simultaneously on the same synthetic elemental tree -- neither one's fix regresses the
        other."""
        cells = quota.quota_for_plan(self.plan, self.targets, category="elemental",
                                     forced_element="fire", forced_status=None)
        by_id = {n.node_id: n for n in self.plan.nodes}
        for node_id, cell in cells.items():
            self.assertEqual(cell.node_class, by_id[node_id].node_class)

    def test_a_synthetic_species_tree_forces_element_and_status_together_not_either_or(self) -> None:
        """Task J8 (2026-09-07): a species tree's own real, different shape from elemental/status
        trees -- BOTH axes forced from the ONE mechanical-favour lock at once, on the same 40-node
        tree. Reproduces the exact same class of crash `build_slot`'s own `if/elif` would have
        caused here (silently forcing NEITHER axis for `category="species"`) if this fix had not
        been made -- proven by checking every cell lands on the forced value, not by trusting the
        function never raised."""
        cells = quota.quota_for_plan(self.plan, self.targets, category="species",
                                     forced_element="air", forced_status="spark")
        self.assertEqual(len(cells), len(self.plan.nodes))
        for cell in cells.values():
            self.assertEqual("air", cell.value_for("element"))
            self.assertEqual("spark", cell.value_for("status"))

    def test_a_species_tree_missing_either_forced_value_refuses_rather_than_silently_forcing_neither(self) -> None:
        with self.assertRaises(ValueError):
            quota.quota_for_plan(self.plan, self.targets, category="species",
                                 forced_element="air", forced_status=None)
        with self.assertRaises(ValueError):
            quota.quota_for_plan(self.plan, self.targets, category="species",
                                 forced_element=None, forced_status="spark")


class RetiredFamilySuccessorTests(unittest.TestCase):
    """solid-enforcement `retire-atk` R5 (owner ruling 2026-09-18): the closed successor map that
    lets the 16 already-accepted nodes naming `progression.bonus.atk` re-target to `combat.power`
    without a re-quota."""

    def test_the_map_is_exactly_the_one_retirement_the_owner_ruled(self) -> None:
        self.assertEqual(quota.RETIRED_FAMILY_SUCCESSOR, {"progression.bonus.atk": "combat.power"})

    def test_resolve_retired_channel_family_maps_the_retired_value(self) -> None:
        self.assertEqual(quota.resolve_retired_channel_family("progression.bonus.atk"), "combat.power")

    def test_resolve_retired_channel_family_is_identity_for_every_live_value(self) -> None:
        for family in ("combat.power", "combat.dmg", "progression.bonus.defense", "move.range"):
            self.assertEqual(quota.resolve_retired_channel_family(family), family)

    def test_resolve_retired_quota_cell_changes_only_channel_family(self) -> None:
        cell = {"nodeClass": "mechanism", "trigger": "OnTimer", "element": "dark",
                "status": "rally", "channelFamily": "progression.bonus.atk", "exclusionForm": "none"}
        resolved = quota.resolve_retired_quota_cell(cell)
        self.assertEqual(resolved, {**cell, "channelFamily": "combat.power"})
        # every other axis is untouched, including the cell's own element
        self.assertEqual(resolved["element"], "dark")

    def test_resolve_retired_quota_cell_is_a_no_op_on_a_live_cell(self) -> None:
        cell = {"nodeClass": "magnitude", "trigger": "OnHit", "element": "fire",
                "status": "status.burn", "channelFamily": "combat.dmg", "exclusionForm": "none"}
        self.assertEqual(quota.resolve_retired_quota_cell(cell), cell)

    def test_resolve_retired_quota_cell_never_mutates_its_input(self) -> None:
        cell = {"nodeClass": "mechanism", "trigger": "OnTimer", "element": "dark",
                "status": "rally", "channelFamily": "progression.bonus.atk", "exclusionForm": "none"}
        before = dict(cell)
        quota.resolve_retired_quota_cell(cell)
        self.assertEqual(cell, before)


if __name__ == "__main__":
    unittest.main()
