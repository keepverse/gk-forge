"""Tests for seedsmith.adapters._stub (tasks/seedsmith-todo.md, S1) — the conformance fixture
for the feature seam itself. If the core ever reaches into item concepts, importing this module
in place of a real one stops passing, which is the entire point of the stub existing.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters import SeedAdapter  # noqa: E402
from seedsmith.adapters._stub import StubAdapter  # noqa: E402
from seedsmith.adapters.registry import known_adapter_names, resolve_adapter  # noqa: E402


class StubAdapterConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = StubAdapter()

    def test_satisfies_seed_adapter_protocol_structurally(self) -> None:
        self.assertIsInstance(self.adapter, SeedAdapter)

    def test_declares_two_kinds(self) -> None:
        self.assertEqual({k.kind for k in self.adapter.kinds()}, {"widget", "gadget"})

    def test_declares_two_dimensions(self) -> None:
        self.assertEqual({d.id for d in self.adapter.dimensions()}, {"color", "size"})

    def test_declares_one_channel(self) -> None:
        self.assertEqual([c.id for c in self.adapter.channels()], ["power"])

    def test_legal_combinations_has_both_a_true_and_a_false_case(self) -> None:
        legal = self.adapter.legal_combinations()
        # the one illegal pair — a LegalityFn returning True unconditionally is the trap
        # spec-foundation §2 warns about, and this is what proves the stub avoids it
        self.assertFalse(legal("color", "red", "size", "large"))
        self.assertTrue(legal("color", "blue", "size", "large"))
        self.assertTrue(legal("color", "red", "size", "small"))

    def test_registries_expose_a_closed_vocabulary(self) -> None:
        registries = self.adapter.registries()
        self.assertTrue(registries.is_legal("tags", "shiny"))
        self.assertFalse(registries.is_legal("tags", "not-a-real-tag"))


class AdapterRegistryTests(unittest.TestCase):
    def test_stub_is_resolvable_by_name(self) -> None:
        self.assertIsInstance(resolve_adapter("stub"), StubAdapter)

    def test_unknown_name_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            resolve_adapter("does-not-exist")

    def test_known_names_includes_stub(self) -> None:
        self.assertIn("stub", known_adapter_names())


class PackageShapeTests(unittest.TestCase):
    def test_no_seedsmith_dot_py_shadows_the_package(self) -> None:
        seedsmith_root = Path(__file__).resolve().parent.parent
        self.assertFalse((seedsmith_root / "seedsmith.py").exists())
        self.assertTrue((seedsmith_root / "seedsmith" / "__main__.py").exists())


if __name__ == "__main__":
    unittest.main()
