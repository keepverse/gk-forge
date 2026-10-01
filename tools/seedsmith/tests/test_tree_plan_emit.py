"""Tests for seedsmith.adapters.trees.plan.{vocabulary,emit,tuning} (task B1) — the full one-tree
plan, end to end, against the real committed roster mirrors.

    python -m pytest gk-forge/tools/seedsmith/tests/test_tree_plan_emit.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.workspace_roots import seed_root  # noqa: E402
from seedsmith.adapters.trees.plan import emit as plan_emit  # noqa: E402
from seedsmith.adapters.trees.plan import tuning as plan_tuning  # noqa: E402
from seedsmith.adapters.trees.plan import vocabulary  # noqa: E402
from seedsmith.adapters.trees.plan.ids import IdMintError  # noqa: E402


def real_seed_root() -> Path:
    """The REAL content pack's `data/seed` - NOT a path under this repository.

    This walked up to the nearest `CONTRIBUTING.md` and joined `data/seed` onto it. Measured across all nine
    repositories, `CONTRIBUTING.md` exists in gk-workflow and NOWHERE ELSE, so the walk always landed on the
    workspace root - which carries neither `data/seed` (gk-data's pack) nor `data/tuning` (gk-core's). A test
    whose stated contract is to read the real corpus was reading a path where the corpus is not.
    """
    return seed_root()


class RosterAndVocabularyTests(unittest.TestCase):
    """Reads the REAL committed mirrors (A1-A3's own output) — no fixture substitutes them, since
    B1's whole point is to prove it reads live counts, never typed ones."""

    def test_roster_counts_match_the_spec(self) -> None:
        roster = vocabulary.load_roster(real_seed_root())
        # AptitudeCatalog.Count is pinned once, AptitudeCatalogTests (population-pin SE3.5,
        # 2026-09-20); never a second literal here.
        self.assertTrue(len(roster.aptitudes) > 0)
        # pin: closed-vocabulary ElementRoster.Concrete — a new concrete element is a reviewed change
        self.assertEqual(len(roster.elements), 6)
        # D51 (2026-09-06): 21 -> 24, the live StatusCategoryRegistry's three nerve.* statuses
        # (afflicted, shaken, unsettled) accepted into this program's own corpus, re-baked via
        # `PassiveTreeRosterGen --status-emit`. StatusCatalogBootstrap is pinned once,
        # ResistanceEvaluatorTests (population-pin SE3.5, 2026-09-20); never a second literal here.
        self.assertTrue(len(roster.statuses) > 0)

    def test_property_vocabulary_counts_match_the_spec_table(self) -> None:
        vocab = vocabulary.load_property_vocabulary(10, real_seed_root())
        self.assertEqual(vocab.counts["nodeClass"], 2)
        self.assertEqual(vocab.counts["branch"], 2)
        self.assertEqual(vocab.counts["tier"], 10)
        self.assertEqual(vocab.counts["posture"], 3)
        self.assertEqual(vocab.counts["aptitude"], 12)
        self.assertEqual(vocab.counts["element"], 7)  # 6 + omni
        self.assertEqual(vocab.counts["status"], 24)  # D51: 21 -> 24, three nerve.* statuses accepted
        # `atomAttachPoint` and `atomKind` are NOT a closed vocabulary: they mirror the authored SSOT at
        # `gk-data/packs/fusion/data/seed/passive-tree/vocabulary.json` and grow whenever the atom corpus ships a new attach
        # point. They were pinned `7` / `16` and broke when `Element` and `Siege` were added, with
        # `element.convert` and `structure.place` using them - the same class as `channelFamily` below,
        # and the fix is the same one: assert the axis MIRRORS its SSOT, never a literal. A literal here
        # fails every time content ships, which is a guardrail guarding nothing; the relationship also
        # catches a stale, missing or half-read mirror, which a literal cannot.
        authored = json.loads(
            (real_seed_root() / "passive-tree" / "vocabulary.json").read_text(encoding="utf-8"))
        self.assertEqual(vocab.counts["atomAttachPoint"], len(authored["attachPoints"]))
        self.assertEqual(vocab.counts["atomKind"], len(authored["kinds"]))
        # `atomTrigger` (13) and `atomTriggerAuthorable` (11) are the SAME class and are still literals.
        # They do not fail today, and a selected failure is diagnosed at its own boundary rather than
        # authorising a broad sweep - so they are named here instead of quietly changed. Same fix when
        # they do: mirror `authored["triggers"]`, and drop the Authorable literal only once its
        # derivation from `triggers` is stated rather than counted.
        self.assertEqual(vocab.counts["atomTrigger"], 13)
        self.assertEqual(vocab.counts["atomTriggerAuthorable"], 11)
        # `channelFamily` is the INJECTED derived-stats catalog's own family set
        # (`gk-data/packs/fusion/data/seed/derived-stats/catalog.json`, read by `plan/vocabulary.py:122`), so the contract is
        # that the axis MIRRORS that file — never a literal. It was pinned `55` and broke when SE1.5
        # (`325191c05`, "remove the retired channel from code and publish the catalog") published the
        # catalog at 54 entries, i.e. a deliberate retirement the pin turned into a red suite; the count
        # is a reading, and "the axis equals the catalog" catches a stale, missing or half-read mirror,
        # which a literal cannot.
        catalog = json.loads((real_seed_root() / "derived-stats" / "catalog.json")
                             .read_text(encoding="utf-8"))
        catalog_families = {e["family"] for e in catalog["entries"]}
        self.assertEqual(set(vocab.axes["channelFamily"]), catalog_families)
        self.assertTrue(vocab.counts["channelFamily"] > 0)
        self.assertEqual(vocab.counts["conversionState"], 2)
        self.assertEqual(vocab.counts["exclusionForm"], 3)

    def test_a_missing_mirror_is_EXIT_CANNOT_RUN_naming_the_file_never_an_empty_axis(self) -> None:
        empty_root = Path(tempfile.mkdtemp())
        with self.assertRaises(vocabulary.VocabularyError) as ex:
            vocabulary.load_roster(empty_root)
        self.assertIn("roster.json", str(ex.exception))


class TuningTests(unittest.TestCase):
    def test_the_live_tuning_file_loads_every_key_tree_plan_owns(self) -> None:
        t = plan_tuning.load()
        self.assertEqual(t["tierLadder"]["reqScalePoints"], 5)
        self.assertEqual(t["archetype"]["rewardSpreadMaxRatioMilli"], 6000)
        self.assertEqual(t["potency"]["maxNodeShareMilli"], 182)


class BuildPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tuning = plan_tuning.load()
        self.spec = plan_emit.might_tree_spec()

    def test_forty_nodes_twenty_per_branch_rootless(self) -> None:
        plan = plan_emit.build_plan(self.spec, self.tuning)
        offensive = [n for n in plan["nodes"] if n["branch"] == "offensive"]
        defensive = [n for n in plan["nodes"] if n["branch"] == "defensive"]
        # Formula, not a literal (population-pin SE3.5, 2026-09-20): every node is offensive or
        # defensive (proves no third branch value), and the split is even.
        self.assertEqual(len(offensive) + len(defensive), len(plan["nodes"]))
        self.assertEqual(len(offensive), len(defensive))
        # Rootless: every node has a real (branch, tier) — none is a shared parentless root.
        for n in plan["nodes"]:
            self.assertIn(n["branch"], ("offensive", "defensive"))
            self.assertGreaterEqual(n["tier"], 1)

    def test_node_ids_match_the_grammar(self) -> None:
        plan = plan_emit.build_plan(self.spec, self.tuning)
        for n in plan["nodes"]:
            self.assertTrue(n["id"].startswith("skill.might-"))
            self.assertNotIn("/", n["id"][len("skill."):])

    def test_tier_budget_sums_to_1000_with_zero_residual_at_ten_tiers(self) -> None:
        plan = plan_emit.build_plan(self.spec, self.tuning)
        self.assertEqual(sum(plan["budget"]["tierShareMilli"]), 1000)

    def test_w_over_req_is_b_over_5_at_all_ten_tiers(self) -> None:
        plan = plan_emit.build_plan(self.spec, self.tuning)
        # req values ARE W/req's denominator at b=1 (ladder.py's own convention) — cross-check
        # against the spec table directly here too, at the plan level.
        self.assertEqual(plan["ladder"]["reqByTier"], [5, 15, 30, 50, 75, 105, 140, 180, 225, 275])

    def test_property_vocabulary_is_emitted_with_thirteen_axes(self) -> None:
        plan = plan_emit.build_plan(self.spec, self.tuning)
        expected_axes = {"nodeClass", "branch", "tier", "posture", "aptitude", "element", "status",
                         "atomAttachPoint", "atomKind", "atomTrigger", "channelFamily",
                         "conversionState", "exclusionForm"}
        self.assertEqual(set(plan["propertyVocabulary"].keys()), expected_axes)

    def test_no_hardcoded_roster_count_reaches_the_plan_wrongly(self) -> None:
        # If A3's mirror grows (e.g. a 22nd status), the plan must reflect it with zero code change
        # — proven here by asserting the plan's own count equals the LIVE mirror's count, not a
        # literal this test itself types as an assumption.
        plan = plan_emit.build_plan(self.spec, self.tuning)
        live_roster = vocabulary.load_roster()
        self.assertEqual(plan["propertyVocabularyCounts"]["status"], len(live_roster.statuses))

    def test_r_g0_gate_currency_is_aptitude_points(self) -> None:
        plan = plan_emit.build_plan(self.spec, self.tuning)
        self.assertEqual(plan["ladder"]["gateCurrency"], "aptitudePoints")

    def test_archetype_assigned_to_might_is_broad_and_flat(self) -> None:
        # Might is aptitude ordinal 0 -> archetypes[0 % 3] = broad-and-flat.
        plan = plan_emit.build_plan(self.spec, self.tuning)
        self.assertEqual(plan["archetype"], "broad-and-flat")


class SpeciesTreeSpecTests(unittest.TestCase):
    """Task J8 (spec-species-tree.md §3, §4, §8.1) — `species_tree_spec`'s own real difference from
    every sibling factory: `ordinal`/`mechanical_favour` are caller-supplied (no species-roster
    read inside this foundational module), and `forcedElement`/`forcedStatus` come from the favour
    lock rather than a category match."""

    def setUp(self) -> None:
        self.tuning = plan_tuning.load()

    def test_an_empty_favour_member_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            plan_emit.species_tree_spec("AbyssSwordStar", 0, ("Might", "", "poison"))

    def test_category_and_tree_id_and_gate_quantity_are_correct(self) -> None:
        spec = plan_emit.species_tree_spec("AbyssSwordStar", 3, ("Onslaught", "air", "spark"))
        self.assertEqual("species", spec.category)
        self.assertEqual("AbyssSwordStar", spec.tree_id)
        self.assertEqual(3, spec.ordinal)
        self.assertEqual("aptitude.Onslaught@UniqueCreature", spec.gate_quantity)
        self.assertEqual("aptitudePoints", spec.gate_index_kind)
        self.assertEqual(("Onslaught", "air", "spark"), spec.mechanical_favour)

    def test_build_plan_derives_forced_element_and_status_from_the_favour_lock(self) -> None:
        spec = plan_emit.species_tree_spec("AbyssSwordStar", 0, ("Onslaught", "air", "spark"))
        plan = plan_emit.build_plan(spec, self.tuning)
        self.assertEqual("air", plan["forcedElement"])
        self.assertEqual("spark", plan["forcedStatus"])
        self.assertEqual("Onslaught", plan["favouredAptitude"])

    def test_build_plan_still_produces_a_real_forty_node_tree_for_a_species_spec(self) -> None:
        spec = plan_emit.species_tree_spec("AbyssSwordStar", 0, ("Onslaught", "air", "spark"))
        plan = plan_emit.build_plan(spec, self.tuning)
        # Same fixed tree shape test_forty_nodes_twenty_per_branch_rootless proves by formula --
        # never a second literal (population-pin SE3.5, 2026-09-20).
        self.assertTrue(len(plan["nodes"]) > 0)
        # The MINTED node id's own slug is lowercased (`tree_slug_for`'s own grammar-only fold) —
        # the tree's own real id, `plan["treeId"]`, stays case-exact for everything else.
        self.assertEqual("AbyssSwordStar", plan["treeId"])
        for n in plan["nodes"]:
            self.assertTrue(n["id"].startswith("skill.abyssswordstar-"))

    def test_a_non_species_plan_never_carries_a_favouredAptitude_key_at_all(self) -> None:
        # The real regression this test guards: a bare `null` key on every OTHER category's own
        # plan would break `--check` byte-identity against every already-committed plan file
        # (caught for real while building this feature — `might.v1.json`'s own round-trip test
        # failed the moment this key was added unconditionally, fixed by gating it on category).
        spec = plan_emit.might_tree_spec()
        plan = plan_emit.build_plan(spec, self.tuning)
        self.assertNotIn("favouredAptitude", plan)
        self.assertIsNone(plan["forcedElement"])
        self.assertIsNone(plan["forcedStatus"])


class EmitCheckRoundTripTests(unittest.TestCase):
    """Uses a scratch seed root so this suite never touches the real committed
    gk-data/packs/fusion/data/seed/passive-tree/plan/might.v1.json."""

    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp())
        self.tuning = plan_tuning.load()
        self.spec = plan_emit.might_tree_spec()

    def _emit_to_scratch(self) -> Path:
        path = self.scratch / "might.v1.json"
        existing = plan_emit._read_existing_plan(path)
        plan = plan_emit.build_plan(self.spec, self.tuning, existing_plan=existing)
        path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def test_re_emit_is_byte_identical(self) -> None:
        path = self._emit_to_scratch()
        first = path.read_text(encoding="utf-8")
        second_text = self._emit_to_scratch().read_text(encoding="utf-8")
        self.assertEqual(first, second_text)

    def test_a_hand_corrupted_budget_column_fails_check(self) -> None:
        path = self._emit_to_scratch()
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["nodes"][0]["budgetShareMilli"] = 999999
        path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")

        existing = plan_emit._read_existing_plan(path)
        regenerated = plan_emit.build_plan(self.spec, self.tuning, existing_plan=existing)
        diffs: "list[str]" = []
        plan_emit._diff_json(doc, regenerated, "$", diffs)
        self.assertTrue(any("budgetShareMilli" in d for d in diffs))

    def test_re_emit_reads_back_existing_keys_rather_than_re_minting(self) -> None:
        # No hyphens: the id grammar uses "-" as the field separator, so a nodeKey containing one
        # would make skill.<tree>-<branch>-t<tier>-<nodeKey> unparseable back into its parts —
        # ids.py's own regex correctly refuses it (see NodeIdGrammarTests).
        path = self._emit_to_scratch()
        doc = json.loads(path.read_text(encoding="utf-8"))
        original_first_key = doc["nodes"][0]["nodeKey"]
        doc["nodes"][0]["nodeKey"] = "handpicked"
        path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")

        existing = plan_emit._read_existing_plan(path)
        regenerated = plan_emit.build_plan(self.spec, self.tuning, existing_plan=existing)
        self.assertEqual(regenerated["nodes"][0]["nodeKey"], "handpicked")
        self.assertNotEqual(regenerated["nodes"][0]["nodeKey"], original_first_key)

    def test_the_real_committed_plan_agrees_with_a_fresh_check(self) -> None:
        real_path = real_seed_root() / "passive-tree" / "plan" / "might.v1.json"
        if not real_path.exists():
            self.skipTest("might.v1.json not yet committed in this checkout")
        diffs = plan_emit.check(self.spec, self.tuning)
        self.assertEqual(diffs, [])


if __name__ == "__main__":
    unittest.main()
