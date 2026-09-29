"""Tests for seedsmith.adapters.trees.nodegen.brief (task H1) — the per-node §6.2 brief text;
permutation seeded from `nodeId|field|sampleIndex`; no number ever appears in the rendered text.
"""
from __future__ import annotations

import unittest

from seedsmith.adapters.trees.nodegen import brief
from seedsmith.adapters.trees.nodegen.vocab import AffixOption


def _affixes() -> "list[AffixOption]":
    return [
        AffixOption(affix_id="atom.freezing", name="Killing Frost", tags=("offensive",),
                   kind_id="status.apply"),
        AffixOption(affix_id="atom.bulwark", name="Bulwark", tags=("defensive",),
                   kind_id="stat.modify"),
        AffixOption(affix_id="atom.venomous", name="Venomous", tags=("offensive",),
                   kind_id="status.apply"),
    ]


class TierToDepthTests(unittest.TestCase):
    def test_shallow_mid_deep_partition_all_ten_tiers(self) -> None:
        bands = {brief.tier_to_depth(t, 10) for t in range(1, 11)}
        self.assertEqual(bands, {"shallow", "mid", "deep"})

    def test_tier_one_is_shallow_and_tier_ten_is_deep(self) -> None:
        self.assertEqual(brief.tier_to_depth(1, 10), "shallow")
        self.assertEqual(brief.tier_to_depth(10, 10), "deep")

    def test_out_of_range_tier_raises(self) -> None:
        with self.assertRaises(ValueError):
            brief.tier_to_depth(0, 10)
        with self.assertRaises(ValueError):
            brief.tier_to_depth(11, 10)


class PermutationTests(unittest.TestCase):
    def test_permuted_affix_ids_is_deterministic_for_the_same_seed(self) -> None:
        a = brief.permuted_affix_ids("skill.t-off-t1-n0", 0, _affixes())
        b = brief.permuted_affix_ids("skill.t-off-t1-n0", 0, _affixes())
        self.assertEqual([o.affix_id for o in a], [o.affix_id for o in b])

    def test_a_different_sample_index_can_reorder(self) -> None:
        """Not asserted as a strict inequality (a shuffle CAN coincide by chance for tiny lists),
        but the returned set must always be identical regardless of order."""
        a = brief.permuted_affix_ids("skill.t-off-t1-n0", 0, _affixes())
        b = brief.permuted_affix_ids("skill.t-off-t1-n0", 1, _affixes())
        self.assertEqual({o.affix_id for o in a}, {o.affix_id for o in b})

    def test_permuted_property_keys_never_invents_a_key(self) -> None:
        keys = ["posture", "conversionState"]
        result = brief.permuted_property_keys("skill.t-off-t1-n0", 0, keys)
        self.assertEqual(set(result), set(keys))


class RenderBriefTests(unittest.TestCase):
    def test_render_contains_only_the_permitted_affixes(self) -> None:
        text = brief.render_brief(
            node_id="skill.t-off-t1-n0", sample_index=0, tree_display_name="Might",
            tree_reading="raw physical force", branch="offensive", tier=1, node_class="mechanism",
            motifs=["ferocity"], anti_motifs=["cowardice"],
            permitted_affixes=_affixes()[:2], permitted_properties=["posture"],
        )
        self.assertIn("atom.freezing", text)
        self.assertIn("atom.bulwark", text)
        self.assertNotIn("atom.venomous", text)

    def test_render_never_contains_a_bare_tier_number(self) -> None:
        text = brief.render_brief(
            node_id="skill.t-off-t1-n0", sample_index=0, tree_display_name="Might",
            tree_reading="raw physical force", branch="offensive", tier=7, node_class="magnitude",
            motifs=[], anti_motifs=[], permitted_affixes=_affixes(), permitted_properties=[],
        )
        self.assertNotIn("tier: 7", text.lower())
        self.assertNotIn("tier 7", text.lower())
        self.assertIn("deep", text)  # the label this stage sees instead

    def test_render_rejects_an_illegal_branch_or_node_class(self) -> None:
        with self.assertRaises(ValueError):
            brief.render_brief(
                node_id="n", sample_index=0, tree_display_name="x", tree_reading="y",
                branch="neutral", tier=1, node_class="mechanism", motifs=[], anti_motifs=[],
                permitted_affixes=[], permitted_properties=[],
            )
        with self.assertRaises(ValueError):
            brief.render_brief(
                node_id="n", sample_index=0, tree_display_name="x", tree_reading="y",
                branch="offensive", tier=1, node_class="ultimate", motifs=[], anti_motifs=[],
                permitted_affixes=[], permitted_properties=[],
            )

    def test_render_includes_siblings_when_given(self) -> None:
        siblings = [brief.SiblingSummary(node_id="skill.t-off-t1-n1", name="Chill Touch",
                                         affix_ids=("atom.freezing",))]
        text = brief.render_brief(
            node_id="skill.t-off-t1-n0", sample_index=0, tree_display_name="Might",
            tree_reading="raw physical force", branch="offensive", tier=1, node_class="mechanism",
            motifs=[], anti_motifs=[], permitted_affixes=_affixes(), permitted_properties=[],
            siblings=siblings,
        )
        self.assertIn("Chill Touch", text)

    def test_affinity_instruction_states_one_entry_per_effect(self) -> None:
        """2026-09-11 real-call finding: the brief's item 2 said only "how central each is", so the
        real model repeatedly returned ONE `affinity` entry for a two-member `affixIds`. That failed
        the §6.3 same-length gate, forced a self-heal, and the heal re-rolled the affix set — so the
        three §6.1 vote samples disagreed by construction and the vote resolved to `1-1-1
        unresolved` on roughly a quarter of nodes. The schema states "the same order as `affixIds`
        and the same length"; the brief now says the same thing, and this test keeps it that way."""
        text = brief.render_brief(
            node_id="skill.t-off-t1-n0", sample_index=0, tree_display_name="Might",
            tree_reading="raw physical force", branch="offensive", tier=1, node_class="mechanism",
            motifs=[], anti_motifs=[], permitted_affixes=_affixes(), permitted_properties=[],
        )
        affinity_clause = text[text.index("2. `affinity`"):text.index("3. `exclusion`")]
        normalized = " ".join(affinity_clause.split())
        self.assertIn("PER chosen effect", normalized)
        self.assertIn("same order as `affixIds`", normalized)
        self.assertIn("the same length", normalized)


class ExclusionInstructionOrderingTests(unittest.TestCase):
    """2026-09-07 real-corpus finding, guarded against regressing: `check --family PassiveTree
    --gate` measured 1638/1677 real committed nodes (97.7%) at exclusion form `reroute`, every one
    with the IDENTICAL propertyKeys=['posture'], against a target of <=30 per mille — root-caused to
    this brief's own item-3 wording opening with "Prefer `reroute`. Most nodes have none." (the
    encouragement read first, the actual rule landing as an aside). Fixed to open with the rule
    itself; these tests lock in that ordering rather than the exact prose, so a future genuine
    reword stays free to vary wording as long as it keeps the rule-before-preference shape."""

    def _exclusion_clause(self) -> str:
        text = brief.render_brief(
            node_id="skill.t-off-t1-n0", sample_index=0, tree_display_name="Might",
            tree_reading="raw physical force", branch="offensive", tier=1, node_class="mechanism",
            motifs=[], anti_motifs=[], permitted_affixes=_affixes(), permitted_properties=["posture"],
        )
        # The `exclusion` bullet is item 3 of the numbered "Choose, and nothing else" list, ending
        # right before item 4 (`name`/`nameKey`/`flavor`) — slice it out rather than assert against
        # the whole brief, so this test fails on THIS clause's own wording, never an unrelated edit
        # elsewhere in the brief.
        start = text.index("3. `exclusion`")
        end = text.index("4. `name`")
        return text[start:end]

    def test_most_nodes_have_none_is_stated_before_any_preference_between_forms(self) -> None:
        clause = self._exclusion_clause()
        self.assertIn("most nodes have none", clause.lower())
        self.assertIn("reroute", clause.lower())
        self.assertLess(clause.lower().index("most nodes have none"),
                        clause.lower().index("reroute"),
                        "the 'have none' rule must be read before any form is offered as a "
                        "preference, or the model reaches for the preferred form by default")

    def test_the_clause_conditions_on_a_genuine_conflict_not_mere_availability(self) -> None:
        clause = self._exclusion_clause().lower()
        self.assertIn("conflict", clause)


if __name__ == "__main__":
    unittest.main()
