"""Tests for seedsmith.adapters.creatures (spec-adapter-creatures.md, wave D1).

D1's own success criterion is structural: this must be `StubAdapter`-shaped, `ItemsAdapter`-sized,
and provably not have taught the core a creature concept — the last row of every test class here
either asserts that directly or re-runs `test_stub_adapter.py`'s own suite.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters import SeedAdapter  # noqa: E402
from seedsmith.adapters.creatures import CreaturesAdapter  # noqa: E402
from seedsmith.adapters.creatures.kinds import KINDS, NO_GENERATOR_YET  # noqa: E402
from seedsmith.adapters.registry import known_adapter_names, resolve_adapter  # noqa: E402
from seedsmith.briefkit.render import CITATION_PATTERNS  # noqa: E402


class CreaturesAdapterConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = CreaturesAdapter()

    def test_satisfies_seed_adapter_protocol_structurally(self) -> None:
        self.assertIsInstance(self.adapter, SeedAdapter)

    def test_kinds_are_exactly_creature_aspect_commander_effect_environment(self) -> None:
        self.assertEqual(
            {k.kind for k in self.adapter.kinds()},
            {"creature", "aspect", "commander-effect", "environment"},
        )

    def test_item_and_action_kinds_are_absent(self) -> None:
        # audit A3 — a creature "item" would be a different thing from a real item, unequippable and
        # outside the item corpus's own role/frame/affix rules. Asserted as an ABSENCE, not merely
        # "not currently present", so a future kind addition here fails loudly.
        kind_ids = {k.kind for k in self.adapter.kinds()}
        self.assertNotIn("item", kind_ids)
        self.assertNotIn("action", kind_ids)

    def test_channels_are_empty(self) -> None:
        # audit A4 — asserted so nobody "fixes" the empty list later.
        self.assertEqual(self.adapter.channels(), [])

    def test_legal_combinations_false_branch_is_reachable_and_real(self) -> None:
        legal = self.adapter.legal_combinations()
        # Real fact, not a synthetic example: CreatureSpeciesGenerator.cs draws ElementPrimary only
        # from ElementRoster.Concrete (6 elements), which excludes omni — no creature of any rarity
        # can ever have ElementPrimary=omni.
        self.assertFalse(legal("element", "omni", "rarity", "legendary"))
        self.assertFalse(legal("element", "omni", "rarity", "common"))
        self.assertTrue(legal("element", "fire", "rarity", "legendary"))
        self.assertTrue(legal("element", "fire", "rarity", "common"))

    def test_family_dimension_declared_with_empty_values_in_d1(self) -> None:
        by_id = {d.id: d for d in self.adapter.dimensions()}
        self.assertIn("family", by_id)
        self.assertEqual(by_id["family"].values, ())

    def test_side_rarity_element_dimensions_are_populated(self) -> None:
        by_id = {d.id: d for d in self.adapter.dimensions()}
        self.assertEqual(set(by_id["side"].values), {"plant", "zombie"})
        self.assertEqual(set(by_id["rarity"].values), {"common", "rare", "epic", "legendary"})
        self.assertIn("fire", by_id["element"].values)
        self.assertIn("omni", by_id["element"].values)  # legal vocabulary value even though no
        # creature's primary element is ever omni (the legality rule above, not vocabulary exclusion,
        # is what encodes that fact)

    def test_environment_partitions_excluded_from_coverage(self) -> None:
        # audit A7 — declared here as the single source `creatures` package coverage wiring reads,
        # so the exclusion cannot drift from what `kinds()` actually ships.
        self.assertIn("environment", NO_GENERATOR_YET)
        self.assertIn("aspect", NO_GENERATOR_YET)  # blocked on aspect-scope being BUILT (audit S2)
        self.assertNotIn("creature", NO_GENERATOR_YET)
        self.assertNotIn("commander-effect", NO_GENERATOR_YET)

    def test_every_registry_vocabulary_is_non_empty_and_inlinable(self) -> None:
        registries = self.adapter.registries()
        for name, values in registries.vocabularies.items():
            if name in ("family", "motif"):
                continue  # deliberately empty in D1, asserted separately below
            self.assertTrue(values, f"{name} vocabulary must be non-empty")
            for value in values:
                for pattern in CITATION_PATTERNS:
                    self.assertIsNone(
                        pattern.search(value),
                        f"registry value {name}={value!r} looks like a citation",
                    )

    def test_family_and_motif_vocabularies_are_empty_in_d1(self) -> None:
        registries = self.adapter.registries()
        self.assertEqual(registries.vocabularies["family"], frozenset())
        self.assertEqual(registries.vocabularies["motif"], frozenset())

    def test_motif_expression_rules_present_for_every_kind(self) -> None:
        for kind in KINDS:
            self.assertTrue(
                kind.motif_expression,
                f"kind {kind.kind!r} has no motif expression rule (§2.7)",
            )

    def test_motif_expression_rules_are_inlinable(self) -> None:
        for kind in KINDS:
            for pattern in CITATION_PATTERNS:
                self.assertIsNone(
                    pattern.search(kind.motif_expression),
                    f"kind {kind.kind!r}'s motif_expression looks like a citation",
                )

    def test_reference_fields_declare_creature_id_where_expected(self) -> None:
        by_kind = {k.kind: k for k in KINDS}
        self.assertIn("creatureId", by_kind["aspect"].reference_fields)
        self.assertIn("creatureId", by_kind["commander-effect"].reference_fields)
        self.assertIn("creatureId", by_kind["environment"].reference_fields)
        self.assertEqual(by_kind["creature"].reference_fields, frozenset())  # references nothing;
        # everything else references it


class AdapterRegistryTests(unittest.TestCase):
    def test_creatures_is_resolvable_by_name(self) -> None:
        self.assertIsInstance(resolve_adapter("creatures"), CreaturesAdapter)

    def test_known_names_includes_creatures(self) -> None:
        self.assertIn("creatures", known_adapter_names())


class TheSeamItselfTests(unittest.TestCase):
    """The row every other test in this module exists to earn the right to make: adding a real
    second feature did not teach the core a creature concept. Runs `test_stub_adapter.py`'s own
    conformance suite from inside this test module so a regression here is attributed correctly."""

    def test_stub_adapter_still_conforms(self) -> None:
        import test_stub_adapter

        loader = unittest.TestLoader()
        suite = loader.loadTestsFromModule(test_stub_adapter)
        result = unittest.TextTestRunner(verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful(), "test_stub_adapter.py regressed")
