"""Tests for the quest half of seedsmith.adapters.dungeon.briefs (D1.10's real remaining scope).

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_quest_briefs.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.dungeon.briefs import (  # noqa: E402
    COUNT_LESS_TEMPLATES,
    ITEM_ROLES,
    TARGET_KIND_NEEDING_REF,
    build_quest_brief,
    build_quest_schema_for_cell,
    target_ref_candidates_for,
)
from seedsmith.adapters.dungeon.planner import Cell  # noqa: E402

REAL_TEMPLATES = {
    "explore-rooms": {"targetKind": "none", "sinkAvoidance": False},
    "cleanse-fights": {"targetKind": "room-kind", "sinkAvoidance": False},
    "gather-curio-kind": {"targetKind": "curio-kind", "sinkAvoidance": False},
    "kill-boss": {"targetKind": "boss", "sinkAvoidance": False},
    "extract-with-item-kind": {"targetKind": "item-kind", "sinkAvoidance": False},
    "bring-creature-home-alive": {"targetKind": "none", "sinkAvoidance": False},
    "finish-under-hunger": {"targetKind": "none", "sinkAvoidance": True},
    "survive-no-downed": {"targetKind": "none", "sinkAvoidance": True},
    "spend-no-provision": {"targetKind": "none", "sinkAvoidance": True},
}
ROOM_KINDS = frozenset({"fight", "elite", "cache", "curio", "wild", "shrine", "rest", "merchant", "trap", "unknown", "boss"})
EVENT_KINDS = ("curio", "encounter-event", "shrine", "trap", "bargain", "story")
REWARD_BANDS = frozenset({"modest", "fair", "rich"})
COUNT_BANDS = frozenset({"lone", "few", "several", "many"})
REPEAT_SCOPES = ("per-delve", "per-domain", "once-per-player")


class TargetRefCandidatesForTests(unittest.TestCase):
    def test_room_kind_returns_the_real_eleven_room_kinds_sorted(self) -> None:
        result = target_ref_candidates_for("room-kind", ROOM_KINDS, EVENT_KINDS)
        self.assertEqual(result, tuple(sorted(ROOM_KINDS)))

    def test_curio_kind_returns_the_real_event_kind_vocabulary(self) -> None:
        # QuestProgress.cs:39 compares against DelveReportEvent.Kind, an EVENT's own six-member
        # kind -- not a curio sub-type, despite the template's own name.
        result = target_ref_candidates_for("curio-kind", ROOM_KINDS, EVENT_KINDS)
        self.assertEqual(result, EVENT_KINDS)

    def test_item_kind_returns_the_real_fifteen_item_roles(self) -> None:
        result = target_ref_candidates_for("item-kind", ROOM_KINDS, EVENT_KINDS)
        # The count is fully implied by the equality above -- never pinned separately
        # (population-pin SE3.5, 2026-09-20).
        self.assertEqual(result, ITEM_ROLES)
        self.assertNotIn("standard", result)  # the reserved 16th -- never generated into

    def test_none_and_boss_never_reach_this_function(self) -> None:
        with self.assertRaises(ValueError):
            target_ref_candidates_for("none", ROOM_KINDS, EVENT_KINDS)
        with self.assertRaises(ValueError):
            target_ref_candidates_for("boss", ROOM_KINDS, EVENT_KINDS)


class NeedsTargetRefTests(unittest.TestCase):
    def test_exactly_three_targetKinds_need_a_real_ref(self) -> None:
        self.assertEqual(TARGET_KIND_NEEDING_REF, frozenset({"room-kind", "curio-kind", "item-kind"}))

    def test_kill_boss_own_boss_targetKind_does_not_need_one(self) -> None:
        # The one counter-intuitive rule: "boss" READS like it should need a ref (which boss?) but
        # QuestCatalog.cs's own needsTargetRef check explicitly excludes it -- there is only one
        # boss per domain, nothing to disambiguate.
        self.assertNotIn("boss", TARGET_KIND_NEEDING_REF)


class CountLessTemplatesTests(unittest.TestCase):
    def test_matches_the_real_csharp_fixed_six_id_set_exactly(self) -> None:
        # QuestCatalog.cs's own CountLessTemplates, transcribed -- not derived from targetKind
        # (extract-with-item-kind has a real item-kind targetKind yet is still count-less).
        self.assertEqual(COUNT_LESS_TEMPLATES, frozenset({
            "kill-boss", "extract-with-item-kind", "bring-creature-home-alive",
            "finish-under-hunger", "survive-no-downed", "spend-no-provision",
        }))


class BuildQuestSchemaForCellTests(unittest.TestCase):
    def _schema(self, template_id: str, scope: str = "delve") -> dict:
        cell = Cell("dungeon-quest", (template_id, scope), f"{template_id}-{scope}")
        return build_quest_schema_for_cell(
            cell, f"quest.{cell.cell_key}-001", objective_templates=REAL_TEMPLATES,
            room_kinds=ROOM_KINDS, event_kinds=EVENT_KINDS, reward_bands=REWARD_BANDS,
            count_bands=COUNT_BANDS, repeat_scopes=REPEAT_SCOPES)

    def test_questId_objectiveTemplate_scope_are_pinned_to_the_real_cell(self) -> None:
        schema = self._schema("explore-rooms", "domain")
        props = schema["properties"]
        self.assertEqual(props["questId"]["const"], "quest.explore-rooms-domain-001")
        self.assertEqual(props["objectiveTemplate"]["const"], "explore-rooms")
        self.assertEqual(props["scope"]["const"], "domain")

    def test_required_matches_the_kindspecs_own_eleven_fields(self) -> None:
        schema = self._schema("explore-rooms")
        self.assertEqual(set(schema["required"]), {
            "questId", "objectiveTemplate", "scope", "name", "flavor", "targetRef",
            "countBand", "rewardBand", "repeatScope", "prereqRefs", "chainRef",
        })

    def test_a_count_less_template_pins_countBand_to_none(self) -> None:
        for template_id in COUNT_LESS_TEMPLATES:
            schema = self._schema(template_id)
            self.assertEqual(schema["properties"]["countBand"], {"type": "string", "const": "none"}, template_id)

    def test_a_real_count_template_offers_the_real_countBand_enum(self) -> None:
        for template_id in ("explore-rooms", "cleanse-fights", "gather-curio-kind"):
            schema = self._schema(template_id)
            self.assertEqual(set(schema["properties"]["countBand"]["enum"]), COUNT_BANDS, template_id)

    def test_a_none_or_boss_targetKind_pins_targetRef_to_none(self) -> None:
        for template_id in ("explore-rooms", "kill-boss", "bring-creature-home-alive"):
            schema = self._schema(template_id)
            self.assertEqual(schema["properties"]["targetRef"], {"type": "string", "const": "none"}, template_id)

    def test_room_kind_targetKind_offers_the_real_room_kind_enum(self) -> None:
        schema = self._schema("cleanse-fights")
        self.assertEqual(set(schema["properties"]["targetRef"]["enum"]), ROOM_KINDS)

    def test_curio_kind_targetKind_offers_the_real_event_kind_enum(self) -> None:
        schema = self._schema("gather-curio-kind")
        self.assertEqual(set(schema["properties"]["targetRef"]["enum"]), set(EVENT_KINDS))

    def test_item_kind_targetKind_offers_the_real_item_role_enum(self) -> None:
        schema = self._schema("extract-with-item-kind")
        self.assertEqual(set(schema["properties"]["targetRef"]["enum"]), set(ITEM_ROLES))

    def test_chainRef_is_always_pinned_none_quests_never_chain(self) -> None:
        schema = self._schema("explore-rooms")
        self.assertEqual(schema["properties"]["chainRef"], {"type": "string", "const": "none"})

    def test_rewardBand_always_offers_the_full_real_enum(self) -> None:
        schema = self._schema("explore-rooms")
        self.assertEqual(set(schema["properties"]["rewardBand"]["enum"]), REWARD_BANDS)

    def test_additionalProperties_is_false_a_closed_contract(self) -> None:
        schema = self._schema("explore-rooms")
        self.assertFalse(schema["additionalProperties"])


class BuildQuestBriefTests(unittest.TestCase):
    def test_every_target_kind_produces_a_nonempty_brief_with_no_crash(self) -> None:
        cell = Cell("dungeon-quest", ("explore-rooms", "delve"), "explore-rooms-delve")
        for target_kind in ("none", "boss", "room-kind", "curio-kind", "item-kind"):
            brief = build_quest_brief(cell, "explore-rooms", "delve", target_kind)
            self.assertIsInstance(brief, str)
            self.assertGreater(len(brief), 0)
            self.assertIn("explore-rooms", brief)
            self.assertIn("this one descent alone", brief)  # the "delve" scope's own real hint text

    def test_every_scope_produces_a_genuinely_different_hint(self) -> None:
        # The real, 2026-09-07 fix for a measured live name-collision problem: each scope's own
        # hint must actually differ, or the model has no signal to write a different name/flavor
        # for "the same template, a different scope" -- proven directly rather than trusted.
        cell = Cell("dungeon-quest", ("explore-rooms", "delve"), "explore-rooms-delve")
        briefs = {scope: build_quest_brief(cell, "explore-rooms", scope, "none") for scope in ("delve", "domain", "roster")}
        self.assertEqual(len(set(briefs.values())), 3, "all three scopes must produce distinct briefs")


if __name__ == "__main__":
    unittest.main()
