"""Tests for the supply-ext half of seedsmith.adapters.dungeon.briefs/pipelines (D1.10's real
remaining scope, 2026-09-07).

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_supply_ext.py -v
"""
from __future__ import annotations

import collections
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.dungeon.briefs import (  # noqa: E402
    SUPPLY_EXT_ELIGIBLE_CLASSES,
    build_supply_ext_brief,
    build_supply_ext_schema_for_consumable,
)
from seedsmith.adapters.dungeon.pipelines import run_supply_ext_draws  # noqa: E402


class SupplyExtEligibleClassesTests(unittest.TestCase):
    def test_only_restore_and_ward_are_eligible_draught_is_excluded(self) -> None:
        self.assertEqual(SUPPLY_EXT_ELIGIBLE_CLASSES, frozenset({"restore", "ward"}))
        self.assertNotIn("draught", SUPPLY_EXT_ELIGIBLE_CLASSES)


class BuildSupplyExtSchemaTests(unittest.TestCase):
    def test_consumableRef_is_pinned_to_the_real_id(self) -> None:
        schema = build_supply_ext_schema_for_consumable("consumable.k1-001")
        self.assertEqual(schema["properties"]["consumableRef"]["const"], "consumable.k1-001")

    def test_overrideTags_is_pinned_empty_never_offered_as_a_choice(self) -> None:
        schema = build_supply_ext_schema_for_consumable("consumable.k1-001")
        self.assertEqual(schema["properties"]["overrideTags"]["const"], [])

    def test_useContextAdds_offers_exactly_rest_and_curio(self) -> None:
        schema = build_supply_ext_schema_for_consumable("consumable.k1-001")
        self.assertEqual(schema["properties"]["useContextAdds"]["items"]["enum"], ["rest", "curio"])

    def test_required_matches_the_kindspecs_own_three_fields(self) -> None:
        schema = build_supply_ext_schema_for_consumable("consumable.k1-001")
        self.assertEqual(set(schema["required"]), {"consumableRef", "overrideTags", "useContextAdds"})

    def test_additionalProperties_is_false(self) -> None:
        schema = build_supply_ext_schema_for_consumable("consumable.k1-001")
        self.assertFalse(schema["additionalProperties"])


class BuildSupplyExtBriefTests(unittest.TestCase):
    def test_brief_names_the_real_consumable_facts(self) -> None:
        brief = build_supply_ext_brief("consumable.k1-001", "Vital Herb", "restore", "atom.vitality")
        self.assertIn("Vital Herb", brief)
        self.assertIn("restore", brief)
        self.assertIn("atom.vitality", brief)
        self.assertIn("useContextAdds", brief)


def raising_call(*args, **kwargs) -> str:
    raise AssertionError("a real model call was attempted -- this test's transport must never be reached")


class FakeCall:
    def __init__(self, responses: "list[dict]") -> None:
        self._responses = collections.deque(responses)
        self.calls: "list[tuple[str, str]]" = []

    def __call__(self, system: str, user: str, *, config=None, schema=None) -> str:
        self.calls.append((system, user))
        if not self._responses:
            raise AssertionError("FakeCall exhausted -- more calls made than responses supplied")
        return json.dumps(self._responses.popleft())


class RunSupplyExtDrawsTests(unittest.TestCase):
    def test_one_call_per_consumable_no_vote(self) -> None:
        consumables = [
            ("consumable.k1-001", "Vital Herb", "restore", "atom.vitality"),
            ("consumable.k1-010", "Amber Ward", "ward", "atom.warding"),
        ]
        fake = FakeCall([
            {"consumableRef": "consumable.k1-001", "overrideTags": [], "useContextAdds": ["rest"]},
            {"consumableRef": "consumable.k1-010", "overrideTags": [], "useContextAdds": ["rest", "curio"]},
        ])
        results = run_supply_ext_draws(consumables, call=fake)

        self.assertEqual(len(fake.calls), 2)  # ONE call per consumable, no 3-sample vote
        self.assertEqual(results[0].entry["useContextAdds"], ["rest"])
        self.assertEqual(results[1].entry["useContextAdds"], ["rest", "curio"])

    def test_an_empty_useContextAdds_is_a_legitimate_result_never_a_defect(self) -> None:
        consumables = [("consumable.k2-001", "Draught of Might", "draught", "atom.might")]
        fake = FakeCall([{"consumableRef": "consumable.k2-001", "overrideTags": [], "useContextAdds": []}])
        results = run_supply_ext_draws(consumables, call=fake)
        self.assertIsNotNone(results[0].entry)
        self.assertEqual(results[0].entry["useContextAdds"], [])

    def test_a_call_that_never_parses_reports_unresolved_not_a_crash(self) -> None:
        class NeverParses:
            def __call__(self, *args, **kwargs) -> str:
                return "not json"
        consumables = [("consumable.k1-001", "Vital Herb", "restore", "atom.vitality")]
        results = run_supply_ext_draws(consumables, call=NeverParses())
        self.assertIsNone(results[0].entry)
        self.assertEqual(results[0].reason, "insufficient_valid_samples")

    def test_never_calls_the_real_transport_when_a_stub_is_supplied(self) -> None:
        consumables = [("consumable.k1-001", "Vital Herb", "restore", "atom.vitality")]
        fake = FakeCall([{"consumableRef": "consumable.k1-001", "overrideTags": [], "useContextAdds": ["rest"]}])
        results = run_supply_ext_draws(consumables, call=fake)
        self.assertIsNotNone(results[0].entry)


if __name__ == "__main__":
    unittest.main()
