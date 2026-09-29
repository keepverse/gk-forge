"""Tests for seedsmith.metrics.linkage (tasks/seedsmith-todo.md, S3).

Ported from `tools/seed_graph/test_reachability.py`'s 16 tests. Synthetic corpora only, never the
live one: these must keep failing on a broken graph long after the real corpus is fixed, and a
test that reads shipping content stops testing the day the content changes.

Every check gets a pair — one corpus that must trip it and one that must not. The negative half is
the important half: a reachability checker that fires on everything is indistinguishable from one
that has understood nothing, and the categorical-vs-specific grant distinction is exactly where
that goes wrong.

    python -m pytest gk-forge/tools/seedsmith/tests/test_linkage.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.corpus import Corpus  # noqa: E402
from seedsmith.metrics import Ctx, MetricRegistry, Severity, run_all  # noqa: E402
from seedsmith.metrics.linkage import ALL_LINKAGE_METRICS  # noqa: E402


def build(*specs):
    """Write a throwaway corpus from (kind, entries) pairs and load it back.

    Kinds are passed explicitly rather than as keyword arguments because the corpus kind is
    singular (`set`, `gem`) while its directory is plural — inferring one from the other is how
    the original seed_graph harness first produced seven false failures.
    """
    tmp = Path(tempfile.mkdtemp())
    for kind, entries in specs:
        directory = tmp / (kind + "s")
        directory.mkdir(parents=True, exist_ok=True)
        doc = {"schemaVersion": 1, "kind": kind, "_meta": {"partition": kind + "/test"},
              "entries": entries}
        (directory / "test.json").write_text(json.dumps(doc), encoding="utf-8")
    return Corpus.load(tmp)


def codes(corpus, severity=None):
    registry = MetricRegistry()
    for metric_cls in ALL_LINKAGE_METRICS:
        registry.register(metric_cls())
    ctx = Ctx(corpus=corpus, adapter=None)
    findings = run_all(registry, ctx)
    return [f.evidence["code"] for f in findings
           if severity is None or f.severity == severity]


def drop_table(*entries):
    return ("drop-table", [{
        "id": "droptable.d1-001", "name": "Cache",
        "groups": [{"groupKey": "g", "entries": list(entries)}],
    }])


SET_BY_ROLE = {
    "id": "set.test-001", "name": "Testset",
    "members": [{"role": "core-guard"}, {"role": "head-guard"}],
    "thresholds": [{"pieces": 2, "atoms": []}],
}
SET_PINNED = {
    "id": "set.test-001", "name": "Testset",
    "members": [
        {"role": "core-guard", "frame": "plant", "baseType": "item.plant-stem-a-001"},
        {"role": "head-guard", "frame": "plant", "baseType": "item.plant-crown-a-001"},
    ],
    "thresholds": [{"pieces": 2, "atoms": []}],
}


class SetCompletabilityTests(unittest.TestCase):
    def test_members_by_role_alone_cannot_complete(self):
        """The finding this whole tool exists for. Nothing is a member, so no bonus is earnable."""
        corpus = build(("set", [SET_BY_ROLE]))
        self.assertIn("SetUncompletable", codes(corpus, Severity.GAP))

    def test_pinned_members_complete(self):
        corpus = build(("set", [SET_PINNED]))
        self.assertNotIn("SetUncompletable", codes(corpus))

    def test_threshold_above_member_count_is_a_gap(self):
        entry = dict(SET_PINNED, thresholds=[{"pieces": 2}, {"pieces": 4}])
        corpus = build(("set", [entry]))
        self.assertIn("SetShortOfThreshold", codes(corpus, Severity.GAP))


class ObtainabilityTests(unittest.TestCase):
    def test_a_gem_no_table_yields_is_a_gap(self):
        corpus = build(("gem", [{"id": "gem.g1-001", "name": "Ember Shard"}]))
        self.assertIn("Unobtainable", codes(corpus, Severity.GAP))

    def test_a_gem_named_by_a_drop_table_is_reachable(self):
        corpus = build(
            ("gem", [{"id": "gem.g1-001", "name": "Ember Shard"}]),
            drop_table({"entryKind": "insert", "ref": "gem.g1-001", "dropBand": "seldom"}))
        self.assertNotIn("Unobtainable", codes(corpus))

    def test_base_types_are_reached_categorically_not_by_name(self):
        """A drop table grants equipment by role and frame; it never names hundreds of base
        types. Requiring a specific grant here would report the entire equipment corpus as
        unobtainable — the single most likely way for this tool to be confidently wrong."""
        corpus = build(
            ("base-type", [{"id": "item.plant-stem-a-001", "name": "Stem",
                           "role": "core-guard", "frame": "plant"}]),
            drop_table({"entryKind": "equipment", "role": "core-guard", "frame": "plant",
                       "dropBand": "occasional"}))
        self.assertNotIn("Unobtainable", codes(corpus))
        self.assertNotIn("SlotUncovered", codes(corpus))

    def test_an_uncovered_role_frame_slot_is_a_gap(self):
        corpus = build(
            ("base-type", [{"id": "item.plant-roots-a-001", "name": "Roots",
                           "role": "footing", "frame": "plant"}]))
        self.assertIn("SlotUncovered", codes(corpus, Severity.GAP))

    def test_a_material_is_reached_by_its_runtime_id(self):
        """Tracking id vs runtime id — the split that has produced several separate defects."""
        corpus = build(
            ("material", [{"id": "material.001", "name": "Ash", "runtimeId": "essence.fire"}]),
            drop_table({"entryKind": "material", "ref": "essence.fire", "dropBand": "frequent"}))
        self.assertNotIn("Unobtainable", codes(corpus))

    def test_a_recipe_output_counts_as_acquisition(self):
        corpus = build(
            ("gem", [{"id": "gem.g1-001", "name": "Ember Shard"}]),
            ("recipe", [{"id": "recipe.001", "name": "Forge: Shard", "operation": "forge",
                        "outputKind": "container", "outputRef": "gem.g1-001", "costLines": []}]))
        self.assertNotIn("Unobtainable", codes(corpus))


class IngredientsTests(unittest.TestCase):
    GEM = ("gem", [{"id": "gem.g1-001", "name": "Ember Shard",
                    "family": "atom.vitality", "powerBand": "low"}])

    def test_a_word_needing_an_unsupplied_family_is_a_gap(self):
        # strain-splice-host SSH2.6: `socket-word` is retired for real (COMBINATION_KINDS is now
        # `("combination",)` alone) -- kinding this fixture `combination` keeps the test actually
        # exercising the gate instead of vacuously passing over a kind nothing checks any more.
        corpus = build(self.GEM, ("combination", [{
            "id": "combo.001", "name": "Dual Strike",
            "ingredients": [{"position": 0, "family": "atom.nonexistent",
                            "minPowerBand": "high"}]}]))
        self.assertIn("IngredientUnsatisfiable", codes(corpus, Severity.GAP))

    def test_a_word_whose_families_all_exist_is_fine(self):
        corpus = build(self.GEM, ("combination", [{
            "id": "combo.001", "name": "Dual Strike",
            "ingredients": [{"position": 0, "family": "atom.vitality",
                            "minPowerBand": "low"}]}]))
        self.assertNotIn("IngredientUnsatisfiable", codes(corpus))


class RecipeInputTests(unittest.TestCase):
    @staticmethod
    def recipe(material):
        return ("recipe", [{"id": "recipe.001", "name": "Forge: Thing", "operation": "forge",
                           "outputKind": "mutation",
                           "costLines": [{"material": material, "costBand": "modest"}]}])

    def test_spending_an_unobtainable_material_is_a_gap(self):
        corpus = build(self.recipe("essence.void"))
        self.assertIn("RecipeInputUnobtainable", codes(corpus, Severity.GAP))

    def test_spending_a_dropped_material_is_fine(self):
        corpus = build(
            self.recipe("essence.fire"),
            drop_table({"entryKind": "material", "ref": "essence.fire", "dropBand": "frequent"}))
        self.assertNotIn("RecipeInputUnobtainable", codes(corpus))


class EnhancementTrackTests(unittest.TestCase):
    MILESTONE = ("enhancement-milestone", [{"id": "enh.001", "name": "Enhancement Vigor"}])

    def test_milestones_with_no_track_anywhere_are_unreachable(self):
        corpus = build(self.MILESTONE, ("base-type", [
            {"id": "item.plant-stem-a-001", "name": "Stem",
             "role": "core-guard", "frame": "plant"}]))
        self.assertIn("FeatureUnbound", codes(corpus, Severity.GAP))

    def test_one_base_type_with_a_track_binds_the_feature(self):
        corpus = build(self.MILESTONE, ("base-type", [
            {"id": "item.plant-stem-a-001", "name": "Stem",
             "role": "core-guard", "frame": "plant",
             "enhanceTrack": [{"milestone": 4, "family": "atom.enhance-vigor"}]}]))
        self.assertNotIn("FeatureUnbound", codes(corpus))


class EmptyCorpusTests(unittest.TestCase):
    def test_nothing_to_say_about_nothing(self):
        corpus = build()
        self.assertEqual(codes(corpus), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
