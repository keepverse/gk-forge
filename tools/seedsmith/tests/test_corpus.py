"""Tests for seedsmith.corpus (tasks/seedsmith-todo.md, S1).

    python -m pytest gk-forge/tools/seedsmith/tests/test_corpus.py -v

Synthetic fixtures only, written to a throwaway temp directory per test — never the live corpus,
so these keep testing the graph contract long after the real corpus changes shape.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.corpus import Corpus, CorpusLoadError  # noqa: E402


def write_seed_file(root: Path, rel_path: str, kind: str, entries: list[dict],
                    partition: str = "a") -> None:
    doc = {"kind": kind, "_meta": {"partition": partition}, "entries": entries}
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


class LoadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())

    def test_loads_entries_indexed_by_id_kind_and_partition(self) -> None:
        write_seed_file(self.root, "widgets/a.json", "widget",
                        [{"id": "widget.a-001"}, {"id": "widget.a-002"}], partition="a")
        write_seed_file(self.root, "widgets/b.json", "widget",
                        [{"id": "widget.b-001"}], partition="b")

        corpus = Corpus.load(self.root)

        self.assertEqual(corpus.by_id("widget.a-001").kind, "widget")
        self.assertEqual({e.id for e in corpus.by_kind("widget")},
                         {"widget.a-001", "widget.a-002", "widget.b-001"})
        self.assertEqual({e.id for e in corpus.by_partition("a")},
                         {"widget.a-001", "widget.a-002"})
        self.assertEqual({e.id for e in corpus.by_partition("b")}, {"widget.b-001"})

    def test_entry_without_id_is_skipped_not_a_load_error(self) -> None:
        write_seed_file(self.root, "widgets/a.json", "widget",
                        [{"id": "widget.a-001"}, {"name": "no id here"}])
        corpus = Corpus.load(self.root)
        self.assertEqual(len(corpus.by_kind("widget")), 1)

    def test_file_without_kind_or_entries_is_silently_not_corpus_content(self) -> None:
        (self.root / "_registry").mkdir()
        (self.root / "_registry" / "bands.v1.json").write_text(
            json.dumps({"version": 1, "bands": {"low": 1}}), encoding="utf-8")
        corpus = Corpus.load(self.root)
        self.assertEqual(len(corpus.entries), 0)

    def test_exemplar_directory_loads_but_is_flagged(self) -> None:
        write_seed_file(self.root, "_exemplars/widget.json", "widget",
                        [{"id": "widget.exemplar-001"}])
        write_seed_file(self.root, "widgets/a.json", "widget", [{"id": "widget.a-001"}])

        corpus = Corpus.load(self.root)

        exemplar = corpus.by_exemplar_id("widget.exemplar-001")
        real = corpus.by_id("widget.a-001")
        self.assertIsNotNone(exemplar)
        self.assertTrue(exemplar.is_exemplar)
        self.assertFalse(real.is_exemplar)

    def test_exemplar_never_occupies_a_slot_in_the_cross_row_ledger(self) -> None:
        # The exact incident spec-foundation §1 names: an exemplar reusing a real id (a
        # worked example of a SHIPPED row) must never shadow or be confused with that real
        # entry in by_id/by_kind/by_partition — reproduced against the live item corpus during
        # S2 review, where 6 of 8 exemplar entries share an id with real content.
        write_seed_file(self.root, "_exemplars/widget.json", "widget",
                        [{"id": "widget.a-001", "color": "EXEMPLAR-VALUE"}])
        write_seed_file(self.root, "widgets/a.json", "widget",
                        [{"id": "widget.a-001", "color": "real-value"}])

        corpus = Corpus.load(self.root)

        self.assertEqual(corpus.by_id("widget.a-001").data["color"], "real-value")
        self.assertEqual(corpus.by_exemplar_id("widget.a-001").data["color"], "EXEMPLAR-VALUE")
        self.assertEqual(len(corpus.by_kind("widget")), 1)
        self.assertEqual({e.id for e in corpus.by_partition("a")}, {"widget.a-001"})

    def test_two_real_entries_sharing_an_id_raises(self) -> None:
        write_seed_file(self.root, "widgets/a.json", "widget", [{"id": "widget.a-001"}])
        write_seed_file(self.root, "widgets/b.json", "widget", [{"id": "widget.a-001"}])

        with self.assertRaises(CorpusLoadError) as ctx:
            Corpus.load(self.root)
        self.assertIn("widget.a-001", str(ctx.exception))

    def test_invalid_json_raises_corpus_load_error_naming_the_file(self) -> None:
        path = self.root / "widgets" / "broken.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not valid json", encoding="utf-8")

        with self.assertRaises(CorpusLoadError) as ctx:
            Corpus.load(self.root)
        self.assertIn("broken.json", str(ctx.exception))

    def test_provenance_carries_the_full_meta_object(self) -> None:
        write_seed_file(self.root, "widgets/a.json", "widget", [{"id": "widget.a-001"}],
                        partition="a")
        entry = Corpus.load(self.root).by_id("widget.a-001")
        self.assertEqual(entry.provenance, {"partition": "a"})


class ResolveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        write_seed_file(self.root, "widgets/a.json", "widget", [{"id": "widget.a-001"}])
        self.corpus = Corpus.load(self.root)

    def test_resolves_a_real_entry_id(self) -> None:
        self.assertTrue(self.corpus.resolves("widget.a-001"))

    def test_does_not_resolve_an_unknown_id(self) -> None:
        self.assertFalse(self.corpus.resolves("widget.nonexistent"))

    def test_resolves_a_registered_minted_id(self) -> None:
        self.assertFalse(self.corpus.resolves("atom.enhance-vigor"))
        self.corpus.register_minted_ids(["atom.enhance-vigor"])
        self.assertTrue(self.corpus.resolves("atom.enhance-vigor"))


class DiscoverEdgesTests(unittest.TestCase):
    ID_LIKE = re.compile(r"^widget\.[a-z0-9]+(-[a-z0-9]+)*$")

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())

    def test_finds_edges_nested_in_dicts_and_lists_including_ones_that_do_not_resolve(self) -> None:
        write_seed_file(self.root, "widgets/a.json", "widget", [
            {"id": "widget.a-001", "parts": [{"ref": "widget.a-002"}]},
            {"id": "widget.a-002", "upgradesTo": "widget.a-999-typo"},
        ])
        corpus = Corpus.load(self.root)

        edges = corpus.discover_edges(self.ID_LIKE)
        pairs = {(e.from_id, e.to_id) for e in edges}

        self.assertIn(("widget.a-001", "widget.a-002"), pairs)
        # unresolved reference is still an edge — that is the whole point of discovery over
        # declaration (spec-foundation §1)
        self.assertIn(("widget.a-002", "widget.a-999-typo"), pairs)
        self.assertFalse(corpus.resolves("widget.a-999-typo"))

    def test_skip_fields_excludes_named_leaves_even_if_id_shaped(self) -> None:
        write_seed_file(self.root, "widgets/a.json", "widget", [
            {"id": "widget.a-001", "name": "widget.a-002", "ref": "widget.a-002"},
        ])
        corpus = Corpus.load(self.root)

        edges = corpus.discover_edges(self.ID_LIKE, skip_fields={"name"})
        via_fields = {e.via.rsplit(".", 1)[-1] for e in edges}

        self.assertNotIn("name", via_fields)
        self.assertIn("ref", via_fields)

    def test_non_matching_strings_are_not_edges(self) -> None:
        write_seed_file(self.root, "widgets/a.json", "widget",
                        [{"id": "widget.a-001", "notes": "just some prose, not a reference"}])
        corpus = Corpus.load(self.root)
        self.assertEqual(corpus.discover_edges(self.ID_LIKE), [])


if __name__ == "__main__":
    unittest.main()
