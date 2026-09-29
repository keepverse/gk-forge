"""Tests for seedsmith.adapters.trees.nodegen.emit (task H1) — `nameKey` grammar; `NodeKeyRefused`,
never sanitised; the `gk-data/packs/fusion/data/seed/passive-tree/nodes/<treeId>.json` writer.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from seedsmith.adapters.trees.nodegen import emit


def _sample_response(name_key: str = "tree.node.frost-bite") -> dict:
    return {
        "affixIds": ["atom.freezing"], "affinity": ["core"],
        "exclusion": {"form": "none", "propertyKeys": []},
        "name": "Frost Bite", "nameKey": name_key, "flavor": "Cold enough to bite.",
        "blocked": "",
    }


class NameKeyGrammarTests(unittest.TestCase):
    def test_a_well_formed_name_key_passes(self) -> None:
        emit.assert_name_key_grammar("tree.node.frost-bite")  # must not raise

    def test_a_malformed_name_key_is_refused_not_sanitised(self) -> None:
        with self.assertRaises(emit.NodeKeyRefused):
            emit.assert_name_key_grammar("Tree.Node.FrostBite")

    def test_a_name_key_missing_the_tree_node_prefix_is_refused(self) -> None:
        with self.assertRaises(emit.NodeKeyRefused):
            emit.assert_name_key_grammar("frost-bite")


class DuplicateNameKeyTests(unittest.TestCase):
    def test_distinct_keys_pass(self) -> None:
        emit.assert_no_duplicate_name_keys(["tree.node.a", "tree.node.b"])  # must not raise

    def test_a_duplicate_within_one_tree_is_refused(self) -> None:
        with self.assertRaises(emit.NodeKeyRefused):
            emit.assert_no_duplicate_name_keys(["tree.node.a", "tree.node.a"])


class BuildNodeRecordTests(unittest.TestCase):
    def test_builds_a_record_from_a_well_formed_response(self) -> None:
        record = emit.build_node_record(
            node_id="skill.might-off-t1-n0", node_key="n0", branch="offensive", tier=1,
            node_class="mechanism", response=_sample_response(),
        )
        self.assertEqual(record.name_key, "tree.node.frost-bite")
        self.assertEqual(record.affix_ids, ("atom.freezing",))
        self.assertEqual(record.exclusion_form, "none")

    def test_a_none_form_response_composes_no_printed_text(self) -> None:
        """task H3: `printedText` is composed from the response's own exclusion object, never
        asked of the model. `form == 'none'` (the normal case) composes to the empty string."""
        record = emit.build_node_record(
            node_id="skill.might-off-t1-n0", node_key="n0", branch="offensive", tier=1,
            node_class="mechanism", response=_sample_response(),
        )
        self.assertEqual(record.printed_text, "")

    def test_a_nullification_response_composes_non_empty_printed_text(self) -> None:
        response = _sample_response()
        response["exclusion"] = {"form": "nullification", "propertyKeys": ["posture"]}
        record = emit.build_node_record(
            node_id="skill.might-off-t1-n0", node_key="n0", branch="offensive", tier=1,
            node_class="mechanism", response=response,
        )
        self.assertTrue(record.printed_text)
        self.assertIn("posture", record.printed_text)

    def test_printed_text_round_trips_through_to_dict(self) -> None:
        response = _sample_response()
        response["exclusion"] = {"form": "reroute", "propertyKeys": ["conversionState"]}
        record = emit.build_node_record(
            node_id="skill.might-off-t1-n0", node_key="n0", branch="offensive", tier=1,
            node_class="mechanism", response=response,
        )
        as_dict = record.to_dict()
        self.assertEqual(as_dict["exclusion"]["printedText"], record.printed_text)
        self.assertTrue(as_dict["exclusion"]["printedText"])

    def test_quota_cell_is_absent_by_default(self) -> None:
        """Additive: every pre-persistence call site (and every old committed record) leaves
        `quotaCell` off the dict entirely — never a silently-empty map that looks like a real cell."""
        record = emit.build_node_record(
            node_id="skill.might-off-t1-n0", node_key="n0", branch="offensive", tier=1,
            node_class="mechanism", response=_sample_response(),
        )
        self.assertIsNone(record.quota_cell)
        self.assertNotIn("quotaCell", record.to_dict())

    def test_quota_cell_round_trips_through_to_dict_and_build(self) -> None:
        cell = {
            "nodeClass": "mechanism", "trigger": "OnHit", "element": "fire",
            "status": "none", "channelFamily": "atk", "exclusionForm": "none",
        }
        record = emit.build_node_record(
            node_id="skill.might-off-t1-n0", node_key="n0", branch="offensive", tier=1,
            node_class="mechanism", response=_sample_response(), quota_cell=cell,
        )
        as_dict = record.to_dict()
        self.assertEqual(as_dict["quotaCell"], cell)
        # Load path: a response that already carries quotaCell (ledger replay) reconstructs it
        # without the caller re-supplying the kwarg.
        replay = emit.build_node_record(
            node_id="skill.might-off-t1-n0", node_key="n0", branch="offensive", tier=1,
            node_class="mechanism", response={**_sample_response(), "quotaCell": cell},
        )
        self.assertEqual(dict(replay.quota_cell or {}), cell)

    def test_quota_cell_from_dict_refuses_a_partial_map(self) -> None:
        with self.assertRaises(KeyError):
            emit.quota_cell_from_dict({"nodeClass": "mechanism"})

    def test_refuses_a_malformed_name_key_even_from_a_response(self) -> None:
        with self.assertRaises(emit.NodeKeyRefused):
            emit.build_node_record(
                node_id="skill.might-off-t1-n0", node_key="n0", branch="offensive", tier=1,
                node_class="mechanism", response=_sample_response(name_key="NOT-LEGAL"),
            )


class SeedDocumentRoundTripTests(unittest.TestCase):
    def test_write_then_read_round_trips(self) -> None:
        seed_root = Path(tempfile.mkdtemp())
        record = emit.build_node_record(
            node_id="skill.might-off-t1-n0", node_key="n0", branch="offensive", tier=1,
            node_class="mechanism", response=_sample_response(),
        )
        doc = emit.build_seed_document(
            "might", [record], plan_hash="deadbeef", prompt_version="tree-language/1",
            model="sonnet",
        )
        path = emit.write_seed_document(doc, seed_root)
        self.assertTrue(path.exists())
        read_back = emit.read_seed_document("might", seed_root)
        self.assertEqual(read_back["treeId"], "might")
        self.assertEqual(len(read_back["nodes"]), 1)
        self.assertEqual(read_back["_provenance"]["planHash"], "deadbeef")

    def test_read_of_a_missing_document_returns_none(self) -> None:
        seed_root = Path(tempfile.mkdtemp())
        self.assertIsNone(emit.read_seed_document("nope", seed_root))

    def test_build_seed_document_refuses_a_within_tree_duplicate_name_key(self) -> None:
        record_a = emit.build_node_record(
            node_id="skill.might-off-t1-n0", node_key="n0", branch="offensive", tier=1,
            node_class="mechanism", response=_sample_response(name_key="tree.node.same"),
        )
        record_b = emit.build_node_record(
            node_id="skill.might-off-t1-n1", node_key="n1", branch="offensive", tier=1,
            node_class="magnitude", response=_sample_response(name_key="tree.node.same"),
        )
        with self.assertRaises(emit.NodeKeyRefused):
            emit.build_seed_document(
                "might", [record_a, record_b], plan_hash="x", prompt_version="tree-language/1",
                model="sonnet",
            )

    def test_a_rerun_over_unchanged_input_is_byte_identical(self) -> None:
        """The narrower half of §7 gate 24's discipline: `canonical_json_bytes` makes two builds of
        the SAME logical document byte-identical, the same property H2's full rerun test proves at
        corpus scale."""
        seed_root_a = Path(tempfile.mkdtemp())
        seed_root_b = Path(tempfile.mkdtemp())
        record = emit.build_node_record(
            node_id="skill.might-off-t1-n0", node_key="n0", branch="offensive", tier=1,
            node_class="mechanism", response=_sample_response(),
        )
        doc = emit.build_seed_document(
            "might", [record], plan_hash="deadbeef", prompt_version="tree-language/1",
            model="sonnet",
        )
        path_a = emit.write_seed_document(doc, seed_root_a)
        path_b = emit.write_seed_document(doc, seed_root_b)
        self.assertEqual(path_a.read_bytes(), path_b.read_bytes())

    def test_an_all_current_vintage_document_is_stamped_with_it(self) -> None:
        records = [
            emit.build_node_record(
                node_id="skill.might-off-t1-n0", node_key="n0", branch="offensive", tier=1,
                node_class="mechanism", response=_sample_response(name_key="tree.node.a"),
                prompt_version="tree-language/3"),
            emit.build_node_record(
                node_id="skill.might-off-t1-n1", node_key="n1", branch="offensive", tier=1,
                node_class="magnitude", response=_sample_response(name_key="tree.node.b"),
                prompt_version="tree-language/3"),
        ]
        doc = emit.build_seed_document("might", records, plan_hash="x",
                                       prompt_version="tree-language/3", model="sonnet")
        self.assertEqual("tree-language/3", doc["_provenance"]["promptVersion"])
        self.assertNotIn("promptVersionByNode", doc["_provenance"])

    def test_a_partially_superseded_document_is_stamped_mixed_not_current(self) -> None:
        """2026-09-11, D2's own exposed lie. Under `--supersede`, a failed re-roll KEEPS its prior,
        pre-provenance record (so the tree stays complete). Filtering empties out of the vintage set
        would then see only the current vintage and stamp the WHOLE document with it — hiding the
        exact stale nodes the stamp exists to name. An empty per-record vintage is its own sentinel.
        """
        records = [
            emit.build_node_record(
                node_id="skill.might-off-t1-n0", node_key="n0", branch="offensive", tier=1,
                node_class="mechanism", response=_sample_response(name_key="tree.node.a"),
                prompt_version="tree-language/3"),
            # A re-roll that failed: prior record kept, no per-record vintage (the legacy shape).
            emit.build_node_record(
                node_id="skill.might-off-t1-n1", node_key="n1", branch="offensive", tier=1,
                node_class="magnitude", response=_sample_response(name_key="tree.node.b"),
                prompt_version=""),
        ]
        doc = emit.build_seed_document("might", records, plan_hash="x",
                                       prompt_version="tree-language/3", model="sonnet")
        self.assertEqual("mixed", doc["_provenance"]["promptVersion"])
        self.assertEqual({"skill.might-off-t1-n0": "tree-language/3",
                          "skill.might-off-t1-n1": ""},
                         doc["_provenance"]["promptVersionByNode"])

    def test_an_all_empty_vintage_document_keeps_the_legacy_caller_stamp(self) -> None:
        records = [
            emit.build_node_record(
                node_id="skill.might-off-t1-n0", node_key="n0", branch="offensive", tier=1,
                node_class="mechanism", response=_sample_response(name_key="tree.node.a"),
                prompt_version=""),
        ]
        doc = emit.build_seed_document("might", records, plan_hash="x",
                                       prompt_version="tree-language/3", model="sonnet")
        self.assertEqual("tree-language/3", doc["_provenance"]["promptVersion"])
        self.assertNotIn("promptVersionByNode", doc["_provenance"])


if __name__ == "__main__":
    unittest.main()
