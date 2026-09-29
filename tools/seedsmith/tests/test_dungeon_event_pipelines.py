"""Tests for the event half of seedsmith.adapters.dungeon.pipelines (D1.10's real remaining scope,
2026-09-07).

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_event_pipelines.py -v

`FakeCall` proves the one-call-per-slot / motif-quality-retry logic without any network dependency,
matching `test_dungeon_quest_pipelines.py`'s own established shape.
"""
from __future__ import annotations

import collections
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.dungeon.pipelines import (  # noqa: E402
    MAX_QUALITY_RETRY,
    glossed_motif_words,
    run_event_draws,
)
from seedsmith.adapters.dungeon.planner import Cell  # noqa: E402
from seedsmith.briefkit.gloss import GlossRow, GlossTable, Sense  # noqa: E402
from seedsmith.pipeline.staleness import brief_hash  # noqa: E402
from seedsmith.workflow.validators.scripts import ScriptClass, script_of  # noqa: E402

FAMILIES = frozenset({"atom.might"})
POWER_BANDS = frozenset({"medium"})
OVERRIDE_TAGS = frozenset({"herbs"})

THEMES = {
    "creature.a": {"motifs": ["motifA1", "motifA2"], "antiMotifs": ["banA"]},
    "creature.b": {"motifs": ["motifB1", "motifB2", "motifB3", "motifB4"], "antiMotifs": []},
}

#: The gloss table these tests inject (NS9): the theme's motifs are the registry's raw tokens, and the
#: drafts below quote the ENGLISH words the brief actually asks for.
GLOSSES = {
    "motifA1": "bright ember", "motifA2": "quiet stone", "banA": "hollow oath",
    "motifB1": "sea glass", "motifB2": "salt wind", "motifB3": "pale root", "motifB4": "iron shard",
}


def _table(glosses: "dict[str, str]") -> GlossTable:
    """A fixture table, built directly — the loader's own refusals are `test_briefkit_gloss.py`'s job."""
    return GlossTable(
        locale="en", registry_version=1, source_registry="fixture", source_registry_version=1,
        rows={k: GlossRow(key=k, gloss=v, sense=Sense.CONCRETE, model="test-model",
                          prompt_version="gloss/1") for k, v in glosses.items()})


def _outcome(ordinal: str = "good") -> dict:
    return {"ordinal": ordinal, "consequence": "none", "dropBand": "staple", "effects": []}


def _event(event_id: str, kind: str, theme: str, *, flavor: str = "A scene.", name: str = "Title") -> dict:
    return {
        "eventId": event_id, "kind": kind, "theme": theme, "name": name,
        "flavor": flavor, "reason": "because", "climateAffinity": "none",
        "repeatScope": "per-delve", "eligibility": None,
        "outcomes": [_outcome("good"), _outcome("bad")],
        "supplyOverride": "none", "chainRef": "none",
    }


class FakeCall:
    def __init__(self, responses: "list[dict]") -> None:
        self._responses = collections.deque(responses)
        self.calls: "list[tuple[str, str]]" = []
        #: Every schema this stub was handed — the per-cell schema is where NS11's PLANNED consts live.
        self.schemas: "list[dict | None]" = []

    def __call__(self, system: str, user: str, *, config=None, schema=None) -> str:
        self.calls.append((system, user))
        self.schemas.append(schema)
        if not self._responses:
            raise AssertionError("FakeCall exhausted -- more calls made than responses supplied")
        return json.dumps(self._responses.popleft())


def _kwargs():
    return dict(themes=THEMES, glosses=_table(GLOSSES), grantable_atom_families=FAMILIES,
                power_bands=POWER_BANDS, override_tags=OVERRIDE_TAGS)


class RunEventDrawsTests(unittest.TestCase):
    def test_one_call_per_slot_no_vote(self) -> None:
        cell = Cell("dungeon-event", ("curio", "creature.a"), "curio-creature.a")
        fake = FakeCall([_event("event.curio-creature.a-001", "curio", "creature.a", flavor="Uses bright ember here.")])
        results = run_event_draws([cell], {"curio-creature.a": ["event.curio-creature.a-001"]}, call=fake, **_kwargs())

        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].entry)
        self.assertEqual(results[0].entry["eventId"], "event.curio-creature.a-001")

    def test_a_target_two_cell_makes_two_independent_calls_with_different_motif_briefs(self) -> None:
        cell = Cell("dungeon-event", ("curio", "creature.b"), "curio-creature.b")
        ids = ["event.curio-creature.b-001", "event.curio-creature.b-002"]
        fake = FakeCall([
            _event(ids[0], "curio", "creature.b", name="Title One", flavor="Uses sea glass here."),
            _event(ids[1], "curio", "creature.b", name="Title Two", flavor="Uses salt wind here."),
        ])
        results = run_event_draws([cell], {"curio-creature.b": ids}, call=fake, **_kwargs())

        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(len(results), 2)
        self.assertNotEqual(fake.calls[0][1], fake.calls[1][1])  # different briefs, different motif slices
        self.assertTrue(all(r.entry is not None for r in results))

    def test_an_empty_target_cell_produces_zero_results(self) -> None:
        cell = Cell("dungeon-event", ("curio", "creature.a"), "curio-creature.a")
        fake = FakeCall([])
        results = run_event_draws([cell], {"curio-creature.a": []}, call=fake, **_kwargs())
        self.assertEqual(results, [])
        self.assertEqual(len(fake.calls), 0)

    def test_a_motif_coverage_rejection_triggers_a_quality_retry_that_then_succeeds(self) -> None:
        cell = Cell("dungeon-event", ("curio", "creature.a"), "curio-creature.a")
        fake = FakeCall([
            _event("event.curio-creature.a-001", "curio", "creature.a", flavor="No motif word appears here at all."),
            _event("event.curio-creature.a-001", "curio", "creature.a", flavor="Now it uses bright ember properly."),
        ])
        results = run_event_draws([cell], {"curio-creature.a": ["event.curio-creature.a-001"]}, call=fake, **_kwargs())

        self.assertEqual(len(fake.calls), 2)  # first rejected, second accepted
        self.assertIsNotNone(results[0].entry)
        self.assertIn("bright ember", results[0].entry["flavor"])
        # the retry's own brief names the defect back to the model
        self.assertIn("rejected", fake.calls[1][1].lower())

    def test_an_anti_motif_violation_also_triggers_a_quality_retry(self) -> None:
        cell = Cell("dungeon-event", ("curio", "creature.a"), "curio-creature.a")
        fake = FakeCall([
            _event("event.curio-creature.a-001", "curio", "creature.a", flavor="Uses bright ember but also hollow oath, forbidden."),
            _event("event.curio-creature.a-001", "curio", "creature.a", flavor="Uses bright ember cleanly this time."),
        ])
        results = run_event_draws([cell], {"curio-creature.a": ["event.curio-creature.a-001"]}, call=fake, **_kwargs())
        self.assertEqual(len(fake.calls), 2)
        self.assertIsNotNone(results[0].entry)

    def test_a_name_collision_within_the_same_run_triggers_a_quality_retry(self) -> None:
        cell_a = Cell("dungeon-event", ("curio", "creature.a"), "curio-creature.a")
        cell_b = Cell("dungeon-event", ("trap", "creature.a"), "trap-creature.a")
        fake = FakeCall([
            _event("event.curio-creature.a-001", "curio", "creature.a", name="The Crimson Stage", flavor="Uses bright ember."),
            _event("event.trap-creature.a-001", "trap", "creature.a", name="The Crimson Stage", flavor="Uses bright ember too."),
            _event("event.trap-creature.a-001", "trap", "creature.a", name="A Genuinely Different Title", flavor="Uses bright ember as well."),
        ])
        results = run_event_draws(
            [cell_a, cell_b],
            {"curio-creature.a": ["event.curio-creature.a-001"], "trap-creature.a": ["event.trap-creature.a-001"]},
            call=fake, **_kwargs())

        self.assertEqual(len(fake.calls), 3)  # cell_a: 1 call; cell_b: rejected once, then accepted
        self.assertEqual(results[0].entry["name"], "The Crimson Stage")
        self.assertEqual(results[1].entry["name"], "A Genuinely Different Title")
        self.assertIn("already used", fake.calls[2][1])

    def test_existing_names_seeds_the_collision_set_across_batches(self) -> None:
        cell = Cell("dungeon-event", ("curio", "creature.a"), "curio-creature.a")
        fake = FakeCall([
            _event("event.curio-creature.a-001", "curio", "creature.a", name="An Old Title", flavor="Uses bright ember."),
            _event("event.curio-creature.a-001", "curio", "creature.a", name="A Fresh Title", flavor="Uses bright ember too."),
        ])
        results = run_event_draws(
            [cell], {"curio-creature.a": ["event.curio-creature.a-001"]}, call=fake,
            existing_names=["An Old Title"], **_kwargs())
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(results[0].entry["name"], "A Fresh Title")

    def test_exhausting_every_retry_leaves_the_slot_unresolved_never_a_silent_bad_answer(self) -> None:
        cell = Cell("dungeon-event", ("curio", "creature.a"), "curio-creature.a")
        bad = _event("event.curio-creature.a-001", "curio", "creature.a", flavor="Never mentions a motif at all.")
        fake = FakeCall([bad] * (MAX_QUALITY_RETRY + 1))
        results = run_event_draws([cell], {"curio-creature.a": ["event.curio-creature.a-001"]}, call=fake, **_kwargs())

        self.assertEqual(len(fake.calls), MAX_QUALITY_RETRY + 1)
        self.assertIsNone(results[0].entry)
        self.assertTrue(results[0].reason.startswith("quality_retry"))

    def test_a_call_that_never_parses_reports_unresolved_not_a_crash(self) -> None:
        class NeverParses:
            def __call__(self, *args, **kwargs) -> str:
                return "not json"
        cell = Cell("dungeon-event", ("curio", "creature.a"), "curio-creature.a")
        results = run_event_draws([cell], {"curio-creature.a": ["event.curio-creature.a-001"]},
                                   call=NeverParses(), **_kwargs())
        self.assertIsNone(results[0].entry)
        self.assertEqual(results[0].reason, "insufficient_valid_samples")

    def test_never_calls_the_real_transport_when_a_stub_is_supplied(self) -> None:
        cell = Cell("dungeon-event", ("curio", "creature.a"), "curio-creature.a")
        fake = FakeCall([_event("event.curio-creature.a-001", "curio", "creature.a", flavor="Uses bright ember.")])
        results = run_event_draws([cell], {"curio-creature.a": ["event.curio-creature.a-001"]}, call=fake, **_kwargs())
        self.assertIsNotNone(results[0].entry)


class GlossedMotifBriefTests(unittest.TestCase):
    """NS9 (spec-dungeon-generator-repair.md §2) — gloss before brief, refuse an unglossed slot."""

    def test_brief_contains_glosses_not_raw_motifs(self) -> None:
        cell = Cell("dungeon-event", ("curio", "creature.a"), "curio-creature.a")
        fake = FakeCall([_event("event.curio-creature.a-001", "curio", "creature.a",
                                flavor="Uses bright ember here.")])
        run_event_draws([cell], {"curio-creature.a": ["event.curio-creature.a-001"]}, call=fake,
                        **_kwargs())

        brief = fake.calls[0][1]
        self.assertIn("bright ember", brief)
        self.assertIn("hollow oath", brief)
        self.assertNotIn("motifA1", brief)
        self.assertNotIn("banA", brief)
        allowed = {ScriptClass.LATIN, ScriptClass.DIGIT, ScriptClass.COMMON}
        outsiders = sorted({ch for ch in brief if script_of(ch) not in allowed})
        self.assertEqual(outsiders, [], "the brief must carry no character outside latin/digit/common")

    def test_unglossed_motif_makes_slot_unresolved_without_a_call(self) -> None:
        cell = Cell("dungeon-event", ("curio", "creature.a"), "curio-creature.a")
        fake = FakeCall([])   # zero responses: any call at all would raise inside FakeCall
        results = run_event_draws([cell], {"curio-creature.a": ["event.curio-creature.a-001"]},
                                  call=fake, themes=THEMES, glosses=_table({"motifA1": "bright ember"}),
                                  grantable_atom_families=FAMILIES, power_bands=POWER_BANDS,
                                  override_tags=OVERRIDE_TAGS)

        self.assertEqual(len(fake.calls), 0, "an unglossed slot must spend no model call")
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].entry)
        self.assertTrue(results[0].reason.startswith("gloss_missing:"), results[0].reason)
        self.assertIn("motifA2", results[0].reason)
        self.assertIn("banA", results[0].reason)

    def test_shared_gloss_is_dropped_from_anti_motifs(self) -> None:
        themes = {"creature.c": {"motifs": ["motifC1"], "antiMotifs": ["banC1"]}}
        shared = _table({"motifC1": "twin word", "banC1": "twin word"})
        cell = Cell("dungeon-event", ("curio", "creature.c"), "curio-creature.c")
        fake = FakeCall([_event("event.curio-creature.c-001", "curio", "creature.c",
                                flavor="Uses twin word.")])
        results = run_event_draws([cell], {"curio-creature.c": ["event.curio-creature.c-001"]},
                                  call=fake, themes=themes, glosses=shared,
                                  grantable_atom_families=FAMILIES, power_bands=POWER_BANDS,
                                  override_tags=OVERRIDE_TAGS)

        self.assertIsNotNone(results[0].entry)
        self.assertEqual(results[0].droppedAntiMotifs, ("twin word",))
        brief = fake.calls[0][1]
        self.assertIn("never use them: (none)", brief)

    def test_glossed_motif_words_resolves_both_lists_and_names_every_missing_motif(self) -> None:
        words, missing = glossed_motif_words({"motifs": ["motifA1", "motifA2"], "antiMotifs": ["banA"]},
                                             _table(GLOSSES))
        self.assertEqual(missing, ())
        self.assertEqual(words.motifs, ("bright ember", "quiet stone"))
        self.assertEqual(words.antiMotifs, ("hollow oath",))

        none_words, missing = glossed_motif_words(
            {"motifs": ["motifA1", "motifA2"], "antiMotifs": []},
            _table({"motifA1": "bright ember"}))
        self.assertIsNone(none_words)
        self.assertEqual(missing, ("motifA2",))


class EventScriptCheckTests(unittest.TestCase):
    """NS10 (spec-dungeon-generator-repair.md §3-§4) — the script check in the retry loop, the
    undeclared-field rule, and the brief hash on the draw result."""

    def test_script_defect_triggers_named_quality_retry(self) -> None:
        cell = Cell("dungeon-event", ("curio", "creature.a"), "curio-creature.a")
        fake = FakeCall([
            _event("event.curio-creature.a-001", "curio", "creature.a",
                   flavor="Uses bright ember and \u5206\u914D in the same line."),
            _event("event.curio-creature.a-001", "curio", "creature.a",
                   flavor="Uses bright ember cleanly at last."),
        ])
        results = run_event_draws([cell], {"curio-creature.a": ["event.curio-creature.a-001"]},
                                  call=fake, **_kwargs())

        self.assertEqual(len(fake.calls), 2)
        retry_prompt = fake.calls[1][1]
        self.assertIn("'flavor'", retry_prompt)
        self.assertIn("han", retry_prompt)          # the class is named, not just the fault
        self.assertIsNotNone(results[0].entry)

    def test_script_defect_exhausts_to_unresolved(self) -> None:
        cell = Cell("dungeon-event", ("curio", "creature.a"), "curio-creature.a")
        bad = _event("event.curio-creature.a-001", "curio", "creature.a",
                     flavor="Uses bright ember but \u5206\u914D remains.")
        fake = FakeCall([bad] * (MAX_QUALITY_RETRY + 1))
        results = run_event_draws([cell], {"curio-creature.a": ["event.curio-creature.a-001"]},
                                  call=fake, **_kwargs())

        self.assertEqual(len(fake.calls), MAX_QUALITY_RETRY + 1)
        self.assertIsNone(results[0].entry)
        self.assertTrue(results[0].reason.startswith("quality_retry"), results[0].reason)

    def test_undeclared_string_field_is_a_defect(self) -> None:
        cell = Cell("dungeon-event", ("curio", "creature.a"), "curio-creature.a")
        extra = _event("event.curio-creature.a-001", "curio", "creature.a",
                       flavor="Uses bright ember here.")
        extra["banana"] = "an undeclared prose field"
        fake = FakeCall([
            extra,
            _event("event.curio-creature.a-001", "curio", "creature.a",
                   flavor="Uses bright ember cleanly."),
        ])
        results = run_event_draws([cell], {"curio-creature.a": ["event.curio-creature.a-001"]},
                                  call=fake, **_kwargs())

        self.assertEqual(len(fake.calls), 2)
        self.assertIn("banana", fake.calls[1][1])
        self.assertNotIn("banana", results[0].entry)

    def test_event_draw_result_carries_the_rendered_brief_hash(self) -> None:
        cell = Cell("dungeon-event", ("curio", "creature.a"), "curio-creature.a")
        fake = FakeCall([_event("event.curio-creature.a-001", "curio", "creature.a",
                                flavor="Uses bright ember.")])
        results = run_event_draws([cell], {"curio-creature.a": ["event.curio-creature.a-001"]},
                                  call=fake, **_kwargs())

        self.assertEqual(results[0].brief_hash, brief_hash(fake.calls[0][1]))
        # The length is SHA-256's own contract, derived rather than pinned: a bare `64` here is a
        # population-pin finding (guard-population-pin P1), and that guard's fix is the contract form.
        self.assertEqual(len(results[0].brief_hash), 2 * hashlib.sha256().digest_size)

    def test_a_slot_refused_for_a_missing_gloss_has_no_brief_hash(self) -> None:
        cell = Cell("dungeon-event", ("curio", "creature.a"), "curio-creature.a")
        results = run_event_draws([cell], {"curio-creature.a": ["event.curio-creature.a-001"]},
                                  call=FakeCall([]), themes=THEMES,
                                  glosses=_table({"motifA1": "bright ember"}),
                                  grantable_atom_families=FAMILIES, power_bands=POWER_BANDS,
                                  override_tags=OVERRIDE_TAGS)
        self.assertEqual(results[0].brief_hash, "")


class EventClimateAndChainTests(unittest.TestCase):
    """NS11 (spec-dungeon-generator-repair.md §5-§6): the climate is PLANNED per cell, the legacy
    chain forge is deleted, and a `story` cell needs a COMMITTED chainRef."""

    def test_every_event_cell_pins_a_planned_climate_const(self) -> None:
        cell = Cell("dungeon-event", ("curio", "creature.a"), "curio-creature.a")
        fake = FakeCall([_event("event.curio-creature.a-001", "curio", "creature.a",
                                flavor="Uses bright ember.")])
        run_event_draws([cell], {"curio-creature.a": ["event.curio-creature.a-001"]}, call=fake,
                        **_kwargs())

        node = fake.schemas[0]["properties"]["climateAffinity"]
        self.assertIn("const", node)
        self.assertNotIn("enum", node, "a PLANNED field must not be a free choice")
        self.assertEqual(node["const"], "fire")   # one slot of one kind -> the rotation's first value

    def test_story_cell_is_refused_without_a_committed_chain_ref(self) -> None:
        cell = Cell("dungeon-event", ("story", "creature.a"), "story-creature.a")
        fake = FakeCall([])
        with self.assertRaises(ValueError) as ctx:
            run_event_draws([cell], {"story-creature.a": ["event.story-creature.a-001"]},
                            call=fake, **_kwargs())
        self.assertIn("story-creature.a", str(ctx.exception))
        self.assertIn("arc links under the narrative adapter", str(ctx.exception))
        self.assertEqual(len(fake.calls), 0, "a refused story cell must make no call")

    def test_a_committed_chain_ref_passes_through_byte_identical(self) -> None:
        committed = "event.story-creature.a-009"
        cell = Cell("dungeon-event", ("story", "creature.a"), "story-creature.a")
        fake = FakeCall([_event("event.story-creature.a-001", "story", "creature.a",
                                flavor="Uses bright ember.")])
        results = run_event_draws([cell], {"story-creature.a": ["event.story-creature.a-001"]},
                                  call=fake, committed_chain_refs={"event.story-creature.a-001": committed},
                                  **_kwargs())

        self.assertIsNotNone(results[0].entry)
        self.assertEqual(fake.schemas[0]["properties"]["chainRef"]["const"], committed)

    def test_no_forged_chain_ref(self) -> None:
        cells = [Cell("dungeon-event", ("curio", "creature.a"), "curio-creature.a"),
                 Cell("dungeon-event", ("trap", "creature.a"), "trap-creature.a")]
        fake = FakeCall([
            _event("event.curio-creature.a-001", "curio", "creature.a", name="Ash Confluence",
                   flavor="Uses bright ember."),
            _event("event.trap-creature.a-001", "trap", "creature.a", name="Iron Reckoning",
                   flavor="Uses bright ember too."),
        ])
        results = run_event_draws(
            cells, {"curio-creature.a": ["event.curio-creature.a-001"],
                    "trap-creature.a": ["event.trap-creature.a-001"]}, call=fake, **_kwargs())

        for result in results:
            self.assertEqual(result.entry["chainRef"], "none")
            for other in ("event.curio-creature.a-001", "event.trap-creature.a-001"):
                self.assertNotEqual(result.entry["chainRef"], other)
        for schema in fake.schemas:
            self.assertEqual(schema["properties"]["chainRef"]["const"], "none")


if __name__ == "__main__":
    unittest.main()
