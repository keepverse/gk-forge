"""Tests for seedsmith.adapters.trees.identity (`seedsmith-content-standard`, Task 17,
spec-passive-tree-identity-content.md). The tree-identity stage: name+description, each 3-way
voted independently via exact-match `resolve_vote` — the SAME machinery species'
`codexSummary` (`generate_codex.py`) already uses successfully, mirrored here.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from seedsmith.adapters.trees.identity.generate_identity import (
    real_sample_nodes, resolve_tree_identities, write_identity_file,
)
from seedsmith.adapters.trees.identity.schemas import TREE_IDENTITY_RESPONSE_SCHEMA, tree_identity_defects
from seedsmith.pipeline.model import audit_schema


def _stub_call(responses_by_call_order: "list[dict]"):
    """The same `call()` double `test_tree_species_codex.py`'s own `_stub_call` uses."""
    log: "list[str]" = []

    def call(system, user, *, config=None, schema=None):
        log.append(user)
        return json.dumps(responses_by_call_order[len(log) - 1])

    return call, log


class SchemaTests(unittest.TestCase):
    def test_schema_is_audit_clean(self) -> None:
        self.assertEqual([], audit_schema(TREE_IDENTITY_RESPONSE_SCHEMA))

    def test_defects_catch_a_digit_in_either_field(self) -> None:
        self.assertTrue(tree_identity_defects("Fine Name", "Grants a 15 percent bonus."))
        self.assertTrue(tree_identity_defects("Tier 3 Path", "A clean description."))

    def test_defects_catch_a_channel_id_shaped_token(self) -> None:
        self.assertTrue(tree_identity_defects("Fine Name", "Boosts combat.power.fire directly."))

    def test_a_clean_pair_has_no_defects(self) -> None:
        self.assertEqual([], tree_identity_defects("Ironbound Vigil", "Rewards steady defense."))

    def test_ordinary_punctuation_is_not_a_false_positive(self) -> None:
        self.assertEqual([], tree_identity_defects("Ferocity", "e.g. a bold offensive line."))


class RealSampleNodesTests(unittest.TestCase):
    def test_reads_real_name_flavor_pairs_from_a_real_seed_document_shape(self) -> None:
        seed = json.dumps({"nodes": [
            {"id": "skill.x-off-t1-n0", "name": "Thickened Marrow", "flavor": "Dense and heavy."},
            {"id": "skill.x-off-t2-n0", "name": "", "flavor": ""},  # not yet generated -- skipped
        ]})
        pairs = real_sample_nodes(seed)
        self.assertEqual([("Thickened Marrow", "Dense and heavy.")], pairs)

    def test_caps_at_six_samples(self) -> None:
        seed = json.dumps({"nodes": [
            {"id": f"skill.x-off-t{i}-n0", "name": f"Name{i}", "flavor": f"Flavor{i}"}
            for i in range(1, 10)
        ]})
        self.assertEqual(6, len(real_sample_nodes(seed)))

    def test_the_real_committed_ferocity_seed_yields_real_sample_pairs(self) -> None:
        root = Path(__file__).resolve().parents[5]
        seed_path = root / "data" / "seed" / "passive-tree" / "nodes" / "ferocity.json"
        pairs = real_sample_nodes(seed_path.read_text(encoding="utf-8"))
        self.assertEqual(6, len(pairs))
        self.assertIn(("Thickened Marrow",
                       "The bone grows dense and heavy, a foundation that refuses to crack under "
                       "the weight of the struggle."), pairs)


class ResolveTreeIdentitiesTests(unittest.TestCase):
    def _tree(self, tree_id, category="primary", branches=None, sample_nodes=None):
        return (tree_id, category, branches or ["Off", "Def"],
               sample_nodes or [("Thickened Marrow", "Dense and heavy.")])

    def test_a_unanimous_name_vote_resolves_high_confidence(self) -> None:
        responses = [{"name": "Ironbound Vigil", "description": "Rewards steady defense."}] * 3
        call, log = _stub_call(responses)
        fresh, unresolved, _ = resolve_tree_identities(
            [self._tree("ferocity")], provenance_base={"pipeline": "tree-identity"},
            call=call, workers=1)
        self.assertEqual(3, len(log))
        self.assertEqual({}, unresolved)
        self.assertEqual("Ironbound Vigil", fresh["ferocity"]["name"])
        self.assertEqual("Rewards steady defense.", fresh["ferocity"]["description"])
        self.assertEqual("high", fresh["ferocity"]["_provenance"]["nameVoteConfidence"])

    def test_a_split_name_vote_resolves_with_the_majority_and_pairs_its_own_description(self) -> None:
        # Real, measured finding (2026-09-08): description text from 3 independent generations
        # rarely matches exactly, even when the name does — the paired description must come from
        # a sample that ACTUALLY produced the winning name, never a separately-voted value.
        responses = [
            {"name": "Ironbound Vigil", "description": "Rewards steady defense, first phrasing."},
            {"name": "Ironbound Vigil", "description": "Rewards steady defense, second phrasing."},
            {"name": "Something Else Entirely", "description": "A totally different pitch."},
        ]
        call, _ = _stub_call(responses)
        fresh, unresolved, _ = resolve_tree_identities(
            [self._tree("ferocity")], provenance_base={"pipeline": "tree-identity"},
            call=call, workers=1)
        self.assertEqual({}, unresolved)
        self.assertEqual("Ironbound Vigil", fresh["ferocity"]["name"])
        # The FIRST sample carrying the winning name -- deterministic, not the majority's "average".
        self.assertEqual("Rewards steady defense, first phrasing.", fresh["ferocity"]["description"])
        self.assertEqual("split", fresh["ferocity"]["_provenance"]["nameVoteConfidence"])
        self.assertEqual("Something Else Entirely", fresh["ferocity"]["_provenance"]["nameVoteMinority"])

    def test_a_three_way_split_on_name_marks_the_whole_tree_unresolved(self) -> None:
        responses = [
            {"name": "First Name", "description": "Rewards steady defense."},
            {"name": "Second Name", "description": "Rewards steady defense."},
            {"name": "Third Name", "description": "Rewards steady defense."},
        ]
        call, _ = _stub_call(responses)
        fresh, unresolved, _ = resolve_tree_identities(
            [self._tree("ferocity")], provenance_base={"pipeline": "tree-identity"},
            call=call, workers=1)
        self.assertEqual({}, fresh)
        self.assertEqual("name_vote_unresolved", unresolved["ferocity"]["reason"])

    def test_three_way_different_descriptions_with_a_unanimous_name_still_resolve(self) -> None:
        # The real PoC's own measured shape: name converges, description text varies across all 3
        # samples -- this must now RESOLVE (picking the first sample's description), not fail.
        responses = [
            {"name": "Ironbound Vigil", "description": "First description."},
            {"name": "Ironbound Vigil", "description": "Second description."},
            {"name": "Ironbound Vigil", "description": "Third description."},
        ]
        call, _ = _stub_call(responses)
        fresh, unresolved, _ = resolve_tree_identities(
            [self._tree("ferocity")], provenance_base={"pipeline": "tree-identity"},
            call=call, workers=1)
        self.assertEqual({}, unresolved)
        self.assertEqual("Ironbound Vigil", fresh["ferocity"]["name"])
        self.assertEqual("First description.", fresh["ferocity"]["description"])

    def test_a_persistently_numeric_answer_never_reaches_fresh(self) -> None:
        responses = [{"name": "Tier 3 Path", "description": "Grants a 15 percent bonus."}] * 3
        call, _ = _stub_call(responses)
        fresh, unresolved, _ = resolve_tree_identities(
            [self._tree("ferocity")], provenance_base={"pipeline": "tree-identity"},
            call=call, workers=1)
        self.assertEqual({}, fresh)
        self.assertEqual("insufficient_valid_samples", unresolved["ferocity"]["reason"])

    def test_multiple_trees_are_resolved_independently_in_one_call(self) -> None:
        call, log = _stub_call([
            {"name": "Ironbound Vigil", "description": "Rewards steady defense."},
            {"name": "Ironbound Vigil", "description": "Rewards steady defense."},
            {"name": "Ironbound Vigil", "description": "Rewards steady defense."},
            {"name": "First", "description": "First."},
            {"name": "Second", "description": "Second."},
            {"name": "Third", "description": "Third."},
        ])
        fresh, unresolved, _ = resolve_tree_identities(
            [self._tree("ferocity"), self._tree("fire", category="elemental")],
            provenance_base={"pipeline": "tree-identity"}, call=call, workers=1)
        self.assertEqual(6, len(log))
        self.assertEqual({"ferocity"}, set(fresh))
        self.assertEqual({"fire"}, set(unresolved))


class WriteIdentityFileTests(unittest.TestCase):
    def test_writes_a_real_per_tree_identity_file(self) -> None:
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp())
        entry = {"name": "Ironbound Vigil", "description": "Rewards steady defense.",
                "_provenance": {"pipeline": "tree-identity"}}
        path = write_identity_file(tmp_dir, "ferocity", entry)
        self.assertTrue(path.exists())
        written = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual("ferocity", written["treeId"])
        self.assertEqual("Ironbound Vigil", written["name"])


if __name__ == "__main__":
    unittest.main()
