"""Tests for seedsmith.adapters.trees.census (task P0.1, tasks/passive-tree-repair-plan.md §1).

The census exists because an aggregate hid a per-class collapse. These tests hold it to the CONTRACT
that makes the distribution visible — bind rate split by node class and by tier — using small
SYNTHETIC artifacts, never the committed corpus. A test that asserted "42 trees" or "266 bound" would
be asserting a population reading, and would fail when content legitimately ships; the contract below
is stable across generations.
"""
from __future__ import annotations

import unittest

from seedsmith.adapters.trees import census as census_mod
from seedsmith.workspace_roots import owned_path


def _plan(tree_id: str, nodes: "list[tuple[str, str, int]]", *, category: str = "primary") -> dict:
    return {
        "treeId": tree_id,
        "category": category,
        "gateQuantity": f"aptitude.{tree_id}@Commander",
        "archetype": "gated-deep",
        "nodes": [
            {"id": node_id, "nodeClass": node_class, "tier": tier,
             "branch": "offensive", "budgetShareMilli": 9, "nodeKey": f"n{index}"}
            for index, (node_id, node_class, tier) in enumerate(nodes)
        ],
    }


def _seed(nodes: "list[tuple[str, list[str]]]") -> dict:
    return {
        "treeId": "t",
        "nodes": [
            {"id": node_id, "affixIds": affix_ids}
            for node_id, affix_ids in nodes
        ],
    }


def _generated(bound, refused,
               *, verdict: str = "Fail", unspent: int = 0) -> dict:
    """Bound tuples are (nodeId, atoms[, statusAtoms]) — the third element carries MC-1's
    sibling array; absent means none bound (every pre-MC-1 call below)."""
    bound_entries = []
    for entry in bound:
        node_id, atoms = entry[0], entry[1]
        status = entry[2] if len(entry) > 2 else []
        bound_entries.append({"nodeId": node_id, "atoms": atoms, "statusAtoms": status})
    return {
        "treeId": "t",
        "verdict": verdict,
        "shapeArchetype": "gated-deep",
        "totalUnspentBudgetShareMilli": unspent,
        "bound": bound_entries,
        "refused": [
            {"nodeId": node_id, "reason": reason, "unspentBudgetShareMilli": 9,
             "deliberateHole": False}
            for node_id, reason in refused
        ],
    }


def _atom(channel: str = "atk", kind: str = "stat.modify") -> dict:
    return {"kindId": kind, "attachPoint": "Stat", "channelId": channel,
            "op": "Flat", "kMicro": 608, "unitClass": "GameUnits", "scaleAxis": "PTheta"}


class ReadableVsPricedTests(unittest.TestCase):
    """R4 / P4.3. A bound node can be fully PRICED and completely UNREAD: the resolver reads only
    `stat.derived`, so a `stat.modify` atom contributes zero. Counting priced atoms reported 243
    healthy nodes on 2026-09-13 where the truth was 0. These tests pin the distinction.
    """

    def test_a_priced_but_unreadable_atom_counts_as_priced_and_not_readable(self) -> None:
        plan = _plan("t", [("skill.t-t1-n0", "magnitude", 1)])
        gen = _generated([("skill.t-t1-n0", [_atom("atk", "stat.modify")])], [])
        row = census_mod.census_tree("t", plan, _seed([]), gen)
        self.assertEqual(row.bound_with_priced_atoms, 1)
        self.assertEqual(row.priced_atom_count, 1)
        self.assertEqual(row.bound_with_readable_atoms, 0)
        self.assertEqual(row.readable_atom_count, 0)
        self.assertEqual(row.unreadable_share_permille, 1000)

    def test_a_derived_atom_is_both_priced_and_readable(self) -> None:
        plan = _plan("t", [("skill.t-t1-n0", "magnitude", 1)])
        gen = _generated([("skill.t-t1-n0", [_atom("combat.power.fire", "stat.derived")])], [])
        row = census_mod.census_tree("t", plan, _seed([]), gen)
        self.assertEqual(row.bound_with_readable_atoms, 1)
        self.assertEqual(row.readable_atom_count, 1)
        self.assertEqual(row.unreadable_share_permille, 0)

    def test_a_node_with_both_kinds_is_readable_and_counted_by_kind(self) -> None:
        plan = _plan("t", [("skill.t-t1-n0", "magnitude", 1)])
        gen = _generated([("skill.t-t1-n0", [_atom("atk", "stat.modify"),
                                             _atom("combat.power.fire", "stat.derived")])], [])
        row = census_mod.census_tree("t", plan, _seed([]), gen)
        self.assertEqual(row.bound_with_readable_atoms, 1)
        self.assertEqual(row.bound_atoms_by_kind, {"stat.derived": 1, "stat.modify": 1})

    def test_a_status_carrying_node_counts_status_not_priced(self) -> None:
        """MC-1: a node whose atoms are all status-class counts its statusAtoms, not priced
        atoms — the census must stop reporting status-carrying nodes as unpriced."""
        plan = _plan("t", [("skill.t-t1-n0", "mechanism", 1)])
        status = [{"statusId": "blight", "durationMs": 2000, "level": 1,
                   "chancePermille": 25, "trigger": None}]
        gen = _generated([("skill.t-t1-n0", [], status)], [])
        row = census_mod.census_tree("t", plan, _seed([]), gen)
        self.assertEqual(row.bound_with_status_atoms, 1)
        self.assertEqual(row.status_atom_count, 1)
        self.assertEqual(row.bound_with_priced_atoms, 0)
        payload = census_mod.DistributionCensus(trees=(row,), by_reason={},
                                                by_reason_class={}).to_dict()
        self.assertEqual(payload["totals"]["boundWithStatusAtoms"], 1)
        self.assertEqual(payload["totals"]["statusAtoms"], 1)

    def test_the_readable_kind_matches_the_resolver_source(self) -> None:
        # The census's copy of the resolver's predicate must not drift from the resolver itself.
        # `BoundAtomsFor` skips anything whose KindId != the readable kind, so the literal it compares
        # against is the contract this constant mirrors.
        # The file is gk-core's, not gk-forge's: `REPO_ROOT / "src" / ...` names a directory this
        # repository does not have, and `owned_path` asks which repository actually TRACKS the path.
        source = owned_path(
            "src/FusionRpg.Core/PassiveTree/Resolve/TreeAtomSource.cs", census_mod.REPO_ROOT
        )
        self.assertTrue(source.is_file(), f"resolver source not found: {source}")
        text = source.read_text(encoding="utf-8")
        self.assertIn(f'"{census_mod.READABLE_KIND_ID}"', text,
                      "the resolver no longer mentions the census's READABLE_KIND_ID — update both together")

    def test_corpus_reports_bound_atoms_by_kind(self) -> None:
        plan = _plan("a", [("skill.a-t1-n0", "magnitude", 1)])
        rows = (
            census_mod.census_tree(
                "a", plan, _seed([]),
                _generated([("skill.a-t1-n0", [_atom("atk", "stat.modify")])], [])),
        )
        result = census_mod.DistributionCensus(trees=rows, by_reason={}, by_reason_class={})
        self.assertEqual(result.totals()["readableAtoms"], 0)
        self.assertEqual(result.totals()["unreadableBoundNodes"], 1)
        self.assertEqual(result.bound_atoms_by_kind(), {"stat.modify": 1})


class ClassSplitTests(unittest.TestCase):
    def test_mechanism_and_magnitude_bind_rates_are_reported_separately(self) -> None:
        # 2 magnitude (both bound) + 2 mechanism (neither bound): the aggregate is 50%, but the
        # class split is what exposes the mechanism collapse.
        plan = _plan("t", [("skill.t-t1-n0", "magnitude", 1), ("skill.t-t1-n1", "magnitude", 1),
                           ("skill.t-t9-n0", "mechanism", 9), ("skill.t-t9-n1", "mechanism", 9)])
        gen = _generated(
            bound=[("skill.t-t1-n0", [_atom()]), ("skill.t-t1-n1", [_atom()])],
            refused=[("skill.t-t9-n0", "affix 'x' does not exist in the shipped seed content"),
                     ("skill.t-t9-n1", "affix 'x' does not exist in the shipped seed content")])
        row = census_mod.census_tree("t", plan, _seed([]), gen)
        self.assertEqual(row.bound_mechanism, 0)
        self.assertEqual(row.expected_mechanism, 2)
        self.assertEqual(row.mechanism_bind_permille, 0)
        self.assertEqual(row.bound_magnitude, 2)
        self.assertEqual(row.magnitude_bind_permille, 1000)

    def test_mechanism_by_tier_counts_only_class_mechanism_nodes(self) -> None:
        plan = _plan("t", [("skill.t-t9-n0", "mechanism", 9), ("skill.t-t10-n0", "mechanism", 10),
                           ("skill.t-t10-n1", "mechanism", 10), ("skill.t-t1-n0", "magnitude", 1)])
        row = census_mod.census_tree("t", plan, _seed([]), _generated([], []))
        # One mechanism at tier 9 (index 8), two at tier 10 (index 9); the magnitude at tier 1 is
        # not counted, and tiers 1-8 carry no mechanism node at all.
        self.assertEqual(row.expected_mechanism_by_tier, (0, 0, 0, 0, 0, 0, 0, 0, 1, 2))
        self.assertEqual(row.expected_mechanism_by_tier[8], 1)
        self.assertEqual(row.expected_mechanism_by_tier[9], 2)


class InertBoundTests(unittest.TestCase):
    def test_a_bound_node_with_no_priced_atoms_counts_as_inert_not_bound_value(self) -> None:
        plan = _plan("t", [("skill.t-t1-n0", "magnitude", 1), ("skill.t-t1-n1", "magnitude", 1)])
        gen = _generated(bound=[("skill.t-t1-n0", [_atom()]), ("skill.t-t1-n1", [])], refused=[])
        row = census_mod.census_tree("t", plan, _seed([]), gen)
        self.assertEqual(row.bound_nodes, 2)
        self.assertEqual(row.bound_with_priced_atoms, 1)
        self.assertEqual(row.bound_without_priced_atoms, 1)
        self.assertEqual(row.inert_share_permille, 500)

    def test_priced_atom_count_sums_every_atom_on_every_bound_node(self) -> None:
        plan = _plan("t", [("skill.t-t1-n0", "magnitude", 1)])
        gen = _generated(bound=[("skill.t-t1-n0", [_atom("atk"), _atom("defense")])], refused=[])
        row = census_mod.census_tree("t", plan, _seed([]), gen)
        self.assertEqual(row.priced_atom_count, 2)
        self.assertEqual(row.bound_without_priced_atoms, 0)


class ReconciliationTests(unittest.TestCase):
    def test_expected_population_comes_from_the_plan_not_the_seed(self) -> None:
        # A partly-generated tree: the seed holds 1 node, the plan holds 2. Expected must be 2.
        plan = _plan("t", [("skill.t-t1-n0", "magnitude", 1), ("skill.t-t1-n1", "magnitude", 1)])
        seed = _seed([("skill.t-t1-n0", ["atom.might"])])
        row = census_mod.census_tree("t", plan, seed, _generated([("skill.t-t1-n0", [_atom()])], []))
        self.assertEqual(row.expected_nodes, 2)
        self.assertEqual(row.seed_nodes, 1)
        self.assertEqual(row.bound_nodes, 1)

    def test_unaccounted_is_plan_minus_bound_minus_refused(self) -> None:
        plan = _plan("t", [("skill.t-t1-n0", "magnitude", 1), ("skill.t-t1-n1", "magnitude", 1),
                           ("skill.t-t1-n2", "magnitude", 1)])
        gen = _generated(bound=[("skill.t-t1-n0", [_atom()])],
                         refused=[("skill.t-t1-n1", "affix 'x' does not exist in the shipped seed content")])
        row = census_mod.census_tree("t", plan, _seed([]), gen)
        self.assertEqual(row.unaccounted_nodes, 1)

    def test_a_missing_generated_report_reads_as_missing_never_an_error(self) -> None:
        plan = _plan("t", [("skill.t-t1-n0", "magnitude", 1)])
        row = census_mod.census_tree("t", plan, None, None)
        self.assertEqual(row.verdict, "MISSING")
        self.assertEqual(row.bound_nodes, 0)
        self.assertEqual(row.expected_nodes, 1)


class OrphanTests(unittest.TestCase):
    def test_a_generated_node_absent_from_the_plan_is_a_defect(self) -> None:
        plan = _plan("t", [("skill.t-t1-n0", "magnitude", 1)])
        gen = _generated([("skill.t-t1-n0", [_atom()]), ("skill.t-t9-n9", [_atom()])], [])
        row = census_mod.census_tree("t", plan, _seed([]), gen)
        self.assertEqual(row.orphan_generated_node_ids, ("skill.t-t9-n9",))

    def test_a_plan_node_with_no_seed_record_is_never_generated_not_an_orphan(self) -> None:
        # The wither case: 39 of 40 generated, one plan node the language stage never reached.
        plan = _plan("t", [("skill.t-t1-n0", "magnitude", 1), ("skill.t-t9-n1", "mechanism", 9)])
        seed = _seed([("skill.t-t1-n0", ["atom.might"])])
        gen = _generated([("skill.t-t1-n0", [_atom()])],
                         [("skill.t-t9-n1", "affix 'x' does not exist in the shipped seed content")])
        row = census_mod.census_tree("t", plan, seed, gen)
        self.assertEqual(row.orphan_generated_node_ids, ())
        self.assertEqual(row.never_generated_node_ids, ("skill.t-t9-n1",))

    def test_never_generated_reported_when_the_seed_document_is_absent(self) -> None:
        # A tree the language stage has not touched has no seed doc at all -- every plan node is
        # not-yet-generated, which is an unstarted tree, not a defect.
        plan = _plan("t", [("skill.t-t1-n0", "magnitude", 1)])
        row = census_mod.census_tree("t", plan, None, _generated([("skill.t-t1-n0", [_atom()])], []))
        self.assertEqual(row.never_generated_node_ids, ("skill.t-t1-n0",))
        self.assertEqual(row.orphan_generated_node_ids, ())


class RefusalBucketTests(unittest.TestCase):
    def test_each_known_refusal_shape_maps_to_its_bucket(self) -> None:
        self.assertEqual(
            census_mod.classify_refusal(
                "affix 'atom.x' does not exist in the shipped seed content"), "affixNotGenerated")
        self.assertEqual(
            census_mod.classify_refusal(
                "node 'n': channel 'atk' op 'more' is not one of Flat|Increased|Replace|Flag"),
            "opMore")

    def test_an_unrecognised_reason_lands_in_other_and_is_preserved_verbatim(self) -> None:
        reason = "some refusal shape nobody has seen yet"
        self.assertEqual(census_mod.classify_refusal(reason), "other")

    def test_corpus_buckets_sum_to_the_refusal_total(self) -> None:
        # Two trees, three refusals across two shapes.
        plans = {
            "a": _plan("a", [("skill.a-t1-n0", "magnitude", 1)]),
            "b": _plan("b", [("skill.b-t1-n0", "magnitude", 1)]),
        }
        gens = {
            "a": _generated([], [("skill.a-t1-n0", "affix 'x' does not exist in the shipped seed content")]),
            "b": _generated([], [("skill.b-t1-n0", "op 'more' is not one of Flat"), ("skill.b-t9-n0", "unknown shape")]),
        }
        rows = [census_mod.census_tree(tid, plans[tid], _seed([]), gens[tid]) for tid in plans]
        result = census_mod.DistributionCensus(trees=tuple(rows),
                                               by_reason={"a": 1, "b": 2},
                                               by_reason_class={"affixNotGenerated": 1, "opMore": 1, "other": 1})
        self.assertEqual(sum(result.by_reason_class.values()), 3)


class AggregateTests(unittest.TestCase):
    def test_zero_denominator_reports_zero_permille_not_a_crash(self) -> None:
        plan = _plan("t", [("skill.t-t1-n0", "magnitude", 1)])
        row = census_mod.census_tree("t", plan, _seed([]), _generated([], []))
        self.assertEqual(row.mechanism_bind_permille, 0)  # no mechanism nodes at all

    def test_by_class_and_by_category_agree_with_the_tree_rows(self) -> None:
        plan_a = _plan("a", [("skill.a-t1-n0", "magnitude", 1), ("skill.a-t9-n0", "mechanism", 9)],
                       category="primary")
        plan_b = _plan("b", [("skill.b-t1-n0", "magnitude", 1), ("skill.b-t9-n0", "mechanism", 9)],
                       category="status")
        rows = (
            census_mod.census_tree("a", plan_a, _seed([]),
                                   _generated([("skill.a-t1-n0", [_atom()])],
                                              [("skill.a-t9-n0", "affix 'x' does not exist in the shipped seed content")])),
            census_mod.census_tree("b", plan_b, _seed([]),
                                   _generated([("skill.b-t1-n0", [_atom()]), ("skill.b-t9-n0", [_atom("defense")])],
                                              [])),
        )
        result = census_mod.DistributionCensus(trees=rows, by_reason={}, by_reason_class={})
        totals = result.totals()
        self.assertEqual(totals["expectedNodes"], 4)
        self.assertEqual(totals["boundNodes"], 3)
        cls = result.by_class()
        self.assertEqual(cls["magnitude"]["bound"], 2)
        self.assertEqual(cls["mechanism"]["bound"], 1)
        self.assertEqual(cls["mechanism"]["bindPermille"], 500)
        self.assertEqual(result.by_category()["primary"]["trees"], 1)
        self.assertEqual(result.by_category()["status"]["bound"], 2)


class JsonShapeTests(unittest.TestCase):
    def test_to_dict_round_trips_every_reported_field(self) -> None:
        plan = _plan("t", [("skill.t-t1-n0", "magnitude", 1)])
        row = census_mod.census_tree("t", plan, _seed([("skill.t-t1-n0", ["atom.might"])]),
                                     _generated([("skill.t-t1-n0", [_atom()])], [], verdict="Pass"))
        payload = census_mod.DistributionCensus(trees=(row,), by_reason={}, by_reason_class={}).to_dict()
        self.assertEqual(payload["totals"]["trees"], 1)
        self.assertIn("byClass", payload)
        self.assertIn("byTierMechanism", payload)
        entry = payload["trees"][0]
        self.assertEqual(entry["treeId"], "t")
        self.assertEqual(entry["chosenAffixIds"], ["atom.might"])
        self.assertIn("mechanismBindPermille", entry)


class FormatTextTests(unittest.TestCase):
    def test_text_report_names_the_class_split_and_the_tier_collapse(self) -> None:
        plan = _plan("t", [("skill.t-t9-n0", "mechanism", 9)])
        row = census_mod.census_tree("t", plan, _seed([]), _generated([], []))
        text = census_mod.DistributionCensus(trees=(row,), by_reason={}, by_reason_class={}).format_text()
        self.assertIn("by node class", text)
        self.assertIn("mechanism by tier", text)
        self.assertIn("mechanism", text)


class RealCorpusEnvelopeTests(unittest.TestCase):
    """Runs against the COMMITTED corpus, so the envelope below is stable across generations and
    content growth; no count of nodes, trees, or affixes is asserted (that is a reading, not a
    contract). The one thing that must never be true — a generated node the corpus never planned —
    is checked in both directions.
    """

    def setUp(self) -> None:
        from seedsmith.adapters.trees import census as c
        if not (c.DEFAULT_OUT_ROOT / "might.json").is_file() and not (
                c.DEFAULT_SEED_ROOT / "passive-tree" / "plan").is_dir():
            self.skipTest("committed passive-tree corpus not present")

    def test_the_committed_corpus_has_no_true_orphans(self) -> None:
        result = census_mod.census()
        offenders = [(t.tree_id, t.orphan_generated_node_ids)
                     for t in result.trees if t.orphan_generated_node_ids]
        self.assertEqual(offenders, [],
                         "a generated node exists that no plan node declares — the binder emitted an id nobody planned")

    def test_expected_reconciles_to_bound_plus_refused(self) -> None:
        # The plan is the authoritative population, and the binder enumerates EVERY plan node — so
        # `bound + refused` must equal it exactly. A tree that does not reconcile has a seed, plan, or
        # binder inconsistency hiding in it, the exact class the census exists to surface.
        result = census_mod.census()
        for row in result.trees:
            self.assertEqual(
                row.expected_nodes, row.bound_nodes + row.refused_nodes,
                f"{row.tree_id}: plan={row.expected_nodes} bound={row.bound_nodes} "
                f"refused={row.refused_nodes} unaccounted={row.unaccounted_nodes}")

    def test_no_never_generated_node_is_reported_as_bound(self) -> None:
        # A plan node the language stage has not generated has no affixIds, so the binder can only
        # refuse it — it is a SUBSET of `refused`, never an extra bucket. The first version of this
        # envelope added it beside `bound + refused` and immediately disagreed with `wither`
        # (plan=40 vs 5+35+1=41), which is what caught the modelling error.
        result = census_mod.census()
        for row in result.trees:
            overlap = set(row.never_generated_node_ids) & set(row.bound_node_ids)
            self.assertEqual(overlap, set(),
                             f"{row.tree_id}: ungenerated node(s) reported as bound: {sorted(overlap)}")

    def test_the_binder_refuses_every_ungenerated_node_rather_than_dropping_it(self) -> None:
        # Population-level form of the same rule, and the one that stays true as content grows:
        # total refused must be at least the never-generated population. A tree that silently drops
        # ungenerated nodes instead of reporting them would fail here.
        result = census_mod.census()
        for row in result.trees:
            self.assertGreaterEqual(
                row.refused_nodes, row.never_generated_count,
                f"{row.tree_id}: {row.never_generated_count} ungenerated node(s) but only "
                f"{row.refused_nodes} refusal(s) — the binder dropped a node")

    def test_every_tree_reports_a_known_vintage_state(self) -> None:
        # The closed classification must cover every tree: an unclassified vintage is a bug in the
        # classifier (a new sentinel it does not know), and this fails the day one appears rather
        # than silently reporting "current". The STATE is asserted, never a count of trees.
        result = census_mod.census()
        known = {"current", "mixed", "stale", "pre-provenance"}
        for row in result.trees:
            self.assertIn(row.vintage_state, known, f"{row.tree_id}: unknown vintage state")

    def test_a_current_tree_never_lists_stale_records(self) -> None:
        result = census_mod.census()
        for row in result.trees:
            if row.vintage_state == "current":
                self.assertEqual(row.stale_vintage_node_ids, (),
                                 f"{row.tree_id}: current vintage with stale records")


class VintageTests(unittest.TestCase):
    """Task P1.3. `build_seed_document` stamps the caller's CURRENT vintage as the document value when
    every record predates the per-record field, so the document stamp alone can read "current" over
    stale content. Classification therefore reads the per-node map first.
    """

    def test_a_document_stamped_with_the_live_vintage_is_current(self) -> None:
        self.assertEqual(census_mod.classify_vintage("tree-language/3", "tree-language/3"), "current")

    def test_a_document_stamped_with_an_older_vintage_is_stale(self) -> None:
        self.assertEqual(census_mod.classify_vintage("tree-language/1", "tree-language/3"), "stale")

    def test_the_mixed_sentinel_is_mixed(self) -> None:
        self.assertEqual(census_mod.classify_vintage("mixed", "tree-language/3"), "mixed")

    def test_no_stamp_is_pre_provenance(self) -> None:
        self.assertEqual(census_mod.classify_vintage("", "tree-language/3"), "pre-provenance")

    def test_no_stamp_and_no_expected_vintage_is_current(self) -> None:
        # The pre-vintage program state: nothing stamped, nothing expected -- not stale.
        self.assertEqual(census_mod.classify_vintage("", ""), "current")

    def test_a_current_document_stamp_over_pre_provenance_records_reads_mixed(self) -> None:
        # The lie the emit docstring documents: document says the live vintage, but a node in the
        # per-node map has no vintage (a failed re-roll kept its pre-provenance prior).
        plan = _plan("t", [("skill.t-t1-n0", "magnitude", 1), ("skill.t-t1-n1", "magnitude", 1)])
        seed = {
            "treeId": "t",
            "nodes": [
                {"id": "skill.t-t1-n0", "affixIds": ["atom.might"], "promptVersion": "tree-language/3"},
                {"id": "skill.t-t1-n1", "affixIds": ["atom.might"]},
            ],
            "_provenance": {
                "promptVersion": "tree-language/3",
                "promptVersionByNode": {"skill.t-t1-n0": "tree-language/3", "skill.t-t1-n1": ""},
            },
        }
        row = census_mod.census_tree("t", plan, seed, _generated([], []),
                                     current_vintage="tree-language/3")
        self.assertEqual(row.vintage_state, "mixed")
        self.assertEqual(row.stale_vintage_node_ids, ("skill.t-t1-n1",))

    def test_per_node_vintages_override_a_stale_document_stamp(self) -> None:
        plan = _plan("t", [("skill.t-t1-n0", "magnitude", 1)])
        seed = {
            "treeId": "t",
            "nodes": [{"id": "skill.t-t1-n0", "affixIds": ["atom.might"]}],
            "_provenance": {
                "promptVersion": "tree-language/1",
                "promptVersionByNode": {"skill.t-t1-n0": "tree-language/3"},
            },
        }
        row = census_mod.census_tree("t", plan, seed, _generated([], []),
                                     current_vintage="tree-language/3")
        self.assertEqual(row.stale_vintage_node_ids, ())
        self.assertEqual(row.vintage_state, "stale")  # document stamp is still the old one

    def test_a_pre_provenance_document_reports_every_node_stale(self) -> None:
        plan = _plan("t", [("skill.t-t1-n0", "magnitude", 1), ("skill.t-t1-n1", "magnitude", 1)])
        seed = _seed([("skill.t-t1-n0", ["atom.might"]), ("skill.t-t1-n1", ["atom.might"])])
        row = census_mod.census_tree("t", plan, seed, _generated([], []),
                                     current_vintage="tree-language/3")
        self.assertEqual(row.vintage_state, "pre-provenance")
        self.assertEqual(len(row.stale_vintage_node_ids), 2)

    def test_by_vintage_counts_every_tree_state(self) -> None:
        plans = [_plan(t, [("skill.t-t1-n0", "magnitude", 1)]) for t in ("a", "b")]
        docs = [
            {**_seed([]), "_provenance": {"promptVersion": "tree-language/3"}},
            {**_seed([]), "_provenance": {"promptVersion": "tree-language/1"}},
        ]
        rows = tuple(census_mod.census_tree(t, p, d, _generated([], []), current_vintage="tree-language/3")
                     for t, p, d in zip(("a", "b"), plans, docs))
        result = census_mod.DistributionCensus(trees=rows, by_reason={}, by_reason_class={})
        self.assertEqual(result.by_vintage(), {"current": 1, "stale": 1})


if __name__ == "__main__":
    unittest.main()
