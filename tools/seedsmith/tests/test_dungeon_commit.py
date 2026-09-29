"""Tests for `seedsmith.adapters.dungeon.commit` (NS12, spec-dungeon-generator-repair.md §9).

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_commit.py -q

Fixture text only — invented names and flavours, so a real committed event can never turn a test red.
Every test writes into pytest's `tmp_path` (the in-memory/disk rule: disk is the thing under test here
because the committer's contract IS its bytes).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.dungeon.briefs import EVENT_PROMPT_VERSION, build_event_schema_for_cell  # noqa: E402
from seedsmith.adapters.dungeon.commit import (  # noqa: E402
    EVENT_KEY_PREFIX,
    EVENT_SCHEMA_VERSION,
    commit_event_draws,
    text_key,
)
from seedsmith.adapters.dungeon.pipelines import MAX_QUALITY_RETRY, EventDrawResult  # noqa: E402
from seedsmith.adapters.dungeon.regen import (  # noqa: E402
    plan_legacy_regen,
    render_plan,
)
from seedsmith.adapters.dungeon.planner import Cell  # noqa: E402
from seedsmith.adapters.dungeon.schema import (  # noqa: E402
    DERIVED_FIELDS_BY_KIND,
    build_event_schema,
)
from seedsmith.pipeline.llm_caller import LlmCallerConfig  # noqa: E402

class _StubCall:
    """A transport stub: queues raw answers, records every (system, user) and every schema."""

    def __init__(self, responses: "list[dict]") -> None:
        import collections
        self._responses = collections.deque(responses)
        self.calls: "list[tuple[str, str]]" = []
        self.schemas: "list[dict | None]" = []

    def __call__(self, system: str, user: str, *, config=None, schema=None) -> str:
        self.calls.append((system, user))
        self.schemas.append(schema)
        if not self._responses:
            raise AssertionError("stub exhausted -- more calls made than responses supplied")
        return json.dumps(self._responses.popleft())

EVENT_ID = "event.curio-creature.wallnut-001"


def _entry(event_id: str = EVENT_ID, name: str = "Ash Confluence",
           flavor: str = "A cold draught crosses the chamber.") -> dict:
    return {
        "eventId": event_id, "kind": "curio", "theme": "creature.wallnut", "name": name,
        "flavor": flavor, "reason": "because", "climateAffinity": "fire",
        "repeatScope": "per-delve", "eligibility": None,
        "outcomes": [{"ordinal": "good", "consequence": "none", "dropBand": "staple", "effects": []}],
        "supplyOverride": "none", "chainRef": "none",
    }


def _result(*, brief_hash: str = "b" * 64, entry: "dict | None" = None) -> EventDrawResult:
    return EventDrawResult("curio-creature.wallnut", 0, _entry() if entry is None else entry,
                           reason=None if entry is None else None, droppedAntiMotifs=(),
                           brief_hash=brief_hash)


class CommitEventDrawsTests(unittest.TestCase):
    def test_commit_stamps_provenance_from_resolved_config(self) -> None:
        out = self.tmp_path / "events"
        commit_event_draws([_result()], out, config=LlmCallerConfig(model="test-resolved-model"))

        written = json.loads((out / f"{EVENT_ID}.json").read_text(encoding="utf-8"))
        provenance = written["_provenance"]
        self.assertEqual(provenance["modelId"], "test-resolved-model")
        self.assertEqual(provenance["promptVersion"], EVENT_PROMPT_VERSION)
        self.assertEqual(provenance["schemaVersion"], EVENT_SCHEMA_VERSION)
        self.assertEqual(provenance["briefHash"], "b" * 64)
        self.assertTrue(provenance["stalenessKey"])
        index = json.loads((out / "_index.json").read_text(encoding="utf-8"))
        self.assertEqual(index, {EVENT_ID: f"{EVENT_ID}.json"})

    def setUp(self) -> None:
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)

    def test_commit_writes_name_and_flavor_keys(self) -> None:
        out = self.tmp_path / "events"
        entry = _entry()
        commit_event_draws([_result(entry=entry)], out, config=LlmCallerConfig(model="m"))

        written = json.loads((out / f"{EVENT_ID}.json").read_text(encoding="utf-8"))
        body = EVENT_ID.split(".", 1)[1]
        for field in ("name", "flavor"):
            key = written[f"{field}Key"]
            self.assertTrue(key.startswith(f"{EVENT_KEY_PREFIX}.{body}.{field}."), key)
            self.assertRegex(key, r"^[a-z0-9.-]+$")
            self.assertEqual(key, text_key(EVENT_ID, field, entry[field]))
            # A changed string is a new key; an unchanged one keeps its key.
            self.assertNotEqual(key, text_key(EVENT_ID, field, entry[field] + "!"))
        self.assertNotEqual(written["nameKey"], written["flavorKey"])

    def test_unresolved_draws_write_nothing(self) -> None:
        out = self.tmp_path / "events"
        unresolved = EventDrawResult("curio-creature.wallnut", 0, None, reason="quality_retry: nope")
        written = commit_event_draws([unresolved], out, config=LlmCallerConfig(model="m"))
        self.assertEqual(written, [])
        self.assertFalse(out.exists())

    def test_keys_are_not_model_facing(self) -> None:
        for field in DERIVED_FIELDS_BY_KIND["dungeon-event"]:
            self.assertNotIn(field, build_event_schema()["properties"])
        cell = Cell("dungeon-event", ("curio", "creature.wallnut"), "curio-creature.wallnut")
        per_cell = build_event_schema_for_cell(
            cell, EVENT_ID, grantable_atom_families=frozenset({"atom.might"}),
            power_bands=frozenset({"medium"}), override_tags=frozenset({"herbs"}), climate="fire")
        for field in ("nameKey", "flavorKey"):
            self.assertNotIn(field, per_cell["properties"])
            self.assertNotIn(field, json.dumps(per_cell, ensure_ascii=False))

    def test_text_key_refuses_a_field_that_carries_no_key(self) -> None:
        with self.assertRaises(ValueError):
            text_key(EVENT_ID, "reason", "because")


if __name__ == "__main__":
    unittest.main()


class LegacyRegenPlanTests(unittest.TestCase):
    """NS13 (spec-dungeon-generator-repair §8), the read-only half: the plan reuses the COMMITTED ids,
    carries the committed `story` chainRefs over, keeps other events' names in the collision set, and
    spends nothing."""

    def setUp(self) -> None:
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.events = Path(self.tmp.name) / "events"
        self.events.mkdir(parents=True)
        self._write("event.bargain-creature.a-001", "bargain", "creature.a", "The Cinder-Soul Pact", "none")
        self._write("event.story-creature.a-001", "story", "creature.a", "The Long Walk", "event.story-creature.a-002")
        self._write("event.story-creature.a-002", "story", "creature.a", "The Last Walk", "event.story-creature.a-003")
        self._write("event.story-creature.b-001", "story", "creature.b", "A Different Beat", "none")
        (self.events / "_index.json").write_text("{}\n", encoding="utf-8")

    def _write(self, event_id: str, kind: str, theme: str, name: str, chain: str) -> None:
        doc = {"eventId": event_id, "kind": kind, "theme": theme, "name": name,
               "flavor": "A cold draught crosses the chamber.", "reason": "because",
               "climateAffinity": "fire", "repeatScope": "per-delve", "eligibility": None,
               "outcomes": [{"ordinal": "good", "consequence": "none", "dropBand": "staple", "effects": []}],
               "supplyOverride": "none", "chainRef": chain}
        (self.events / f"{event_id}.json").write_text(json.dumps(doc), encoding="utf-8")

    def test_regen_reuses_committed_ids_and_no_room_pool_reference_dangles(self) -> None:
        plan = plan_legacy_regen(self.events)
        self.assertEqual(set(plan.event_ids), {
            "event.bargain-creature.a-001", "event.story-creature.a-001",
            "event.story-creature.a-002", "event.story-creature.b-001"})
        # A room's eventPool names committed ids; every one of them is still planned under that id.
        event_pool = ["event.story-creature.a-001", "event.story-creature.a-002"]
        for event_id in event_pool:
            self.assertIn(event_id, plan.event_ids)
        # Three cells: (bargain, creature.a), (story, creature.a) and (story, creature.b).
        self.assertEqual(len(plan.cells), 3)
        self.assertEqual(plan.planned_ids_by_cell["story-creature.a"],
                         ["event.story-creature.a-001", "event.story-creature.a-002"])

    def test_regen_regenerates_story_events_keeping_chain(self) -> None:
        plan = plan_legacy_regen(self.events)
        self.assertIn("event.story-creature.a-001", plan.committed_chain_refs)
        self.assertEqual(plan.committed_chain_refs["event.story-creature.a-001"],
                         "event.story-creature.a-002")
        self.assertNotIn("event.bargain-creature.a-001", plan.committed_chain_refs)
        # A non-story event's chainRef stays "none" and is NOT carried as a committed ref.
        self.assertEqual(plan.events["event.bargain-creature.a-001"]["chainRef"], "none")

    def test_regen_dry_run_makes_no_call_and_reports_both_bounds(self) -> None:
        from unittest.mock import patch

        with patch("seedsmith.pipeline.llm_caller.call_model",
                   side_effect=AssertionError("a dry run must make no model call")):
            plan = plan_legacy_regen(self.events)
            reading = render_plan(plan)
        self.assertEqual(plan.base_calls, 4)
        self.assertEqual(plan.worst_calls, 4 * (1 + MAX_QUALITY_RETRY))
        self.assertIn(f"{plan.base_calls} base call(s)", reading)
        self.assertIn(f"{plan.worst_calls} worst call(s)", reading)

    def test_existing_names_excludes_the_batch_being_regenerated(self) -> None:
        whole = plan_legacy_regen(self.events)
        self.assertEqual(whole.existing_names, ())   # the whole tree IS the batch
        partial = plan_legacy_regen(self.events, ids=["event.bargain-creature.a-001"])
        self.assertEqual(set(partial.existing_names),
                         {"The Long Walk", "The Last Walk", "A Different Beat"})
        self.assertNotIn("The Cinder-Soul Pact", partial.existing_names)

    def test_an_id_that_is_not_committed_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            plan_legacy_regen(self.events, ids=["event.curio-creature.zzz-001"])

    def test_the_committed_budget_publishes_the_review_sample(self) -> None:
        from seedsmith.workspace_roots import content_root

        budget = json.loads((content_root() / "data/seed/dungeon/_plan/budget.v2.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(budget["version"], 2)
        self.assertIsInstance(budget["event"]["regenReviewSample"], int)
        v1 = json.loads((content_root() / "data/seed/dungeon/_plan/budget.v1.json")
                        .read_text(encoding="utf-8"))
        self.assertEqual(budget["rows"], v1["rows"])   # v2 is v1 plus the event block


class LegacyRegenRunTests(unittest.TestCase):
    """NS13's draw/review/commit half: the resolved config is used, only accepted events are written,
    and an unresolved or rejected event keeps its committed bytes."""

    #: Two motifs per theme, so a 2-slot cell gives each slot its OWN motif: slot 1's anti-motifs
    #: are slot 0's half (`motif_brief_for_slot`), so a fixture with one motif would make the
    #: second slot unable to use it — which is the rule working, not a defect.
    THEMES = {"creature.a": {"motifs": ["motifA1", "motifA2"], "antiMotifs": []},
              "creature.b": {"motifs": ["motifB1", "motifB2"], "antiMotifs": []}}
    GLOSSES = {"motifA1": "bright ember", "motifA2": "quiet stone",
               "motifB1": "salt wind", "motifB2": "pale root"}

    def setUp(self) -> None:
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.events = self.root / "events"
        self.events.mkdir(parents=True)
        self._write("event.bargain-creature.a-001", "bargain", "creature.a", "The Cinder-Soul Pact", "none")
        self._write("event.story-creature.a-001", "story", "creature.a", "The Long Walk",
                    "event.story-creature.a-002")
        self._write("event.story-creature.a-002", "story", "creature.a", "The Last Walk", "event.chain-tail")
        self._write("event.story-creature.b-001", "story", "creature.b", "A Different Beat", "none")

    def _write(self, event_id: str, kind: str, theme: str, name: str, chain: str) -> None:
        doc = {"eventId": event_id, "kind": kind, "theme": theme, "name": name,
               "flavor": "A cold draught crosses the chamber.", "reason": "because",
               "climateAffinity": "fire", "repeatScope": "per-delve", "eligibility": None,
               "outcomes": [{"ordinal": "good", "consequence": "none", "dropBand": "staple", "effects": []}],
               "supplyOverride": "none", "chainRef": chain}
        (self.events / f"{event_id}.json").write_text(json.dumps(doc), encoding="utf-8")

    def _gloss_table(self):
        from seedsmith.briefkit.gloss import GlossRow, GlossTable, Sense

        return GlossTable(locale="en", registry_version=1, source_registry="fixture",
                          source_registry_version=1,
                          rows={k: GlossRow(key=k, gloss=v, sense=Sense.CONCRETE, model="m",
                                            prompt_version="gloss/1") for k, v in self.GLOSSES.items()})

    def _draft(self, event_id: str, kind: str, theme: str, name: str, flavor: str) -> dict:
        return {"eventId": event_id, "kind": kind, "theme": theme, "name": name, "flavor": flavor,
                "reason": "because", "climateAffinity": "fire", "repeatScope": "per-delve",
                "eligibility": None,
                "outcomes": [{"ordinal": "good", "consequence": "none", "dropBand": "staple", "effects": []}],
                "supplyOverride": "none", "chainRef": "none"}

    def test_a_run_uses_the_resolved_config_and_commits_only_accepted_events(self) -> None:
        from seedsmith.adapters.dungeon.regen import commit_reviewed, record_verdict, run_legacy_regen
        from seedsmith.pipeline.llm_caller import LlmCallerConfig

        contaminated = self._draft("event.story-creature.a-002", "story", "creature.a", "The Last Walk",
                                   "It uses quiet stone and 分配 in one line.")
        responses = [
            self._draft("event.bargain-creature.a-001", "bargain", "creature.a", "Ember Pact",
                        "It uses bright ember."),
            self._draft("event.story-creature.a-001", "story", "creature.a", "The Long Walk Redux",
                        "It uses bright ember."),
        ] + [contaminated] * 3 + [
            self._draft("event.story-creature.b-001", "story", "creature.b", "A Different Beat Redux",
                        "It uses salt wind."),
        ]
        fake = _StubCall(responses)
        config = LlmCallerConfig(model="test-resolved-model")
        before = {p.name: p.read_bytes() for p in self.events.glob("event.*.json")}

        run = run_legacy_regen(self.events, call=fake, config=config, glosses=self._gloss_table(),
                               themes=self.THEMES, dry_run=False, runs_dir=self.root / "_runs")
        self.assertEqual(set(run.events), {"event.bargain-creature.a-001", "event.story-creature.a-001",
                                           "event.story-creature.b-001"})
        self.assertIn("event.story-creature.a-002", run.unresolved)
        self.assertTrue(run.unresolved["event.story-creature.a-002"].startswith("quality_retry"))
        self.assertEqual(len(fake.calls), len(responses))     # one call per slot, three on the retry

        run = record_verdict(run, "event.bargain-creature.a-001", verdict="accept",
                             runs_dir=self.root / "_runs")
        run = record_verdict(run, "event.story-creature.a-001", verdict="accept",
                             runs_dir=self.root / "_runs")
        run = record_verdict(run, "event.story-creature.b-001", verdict="reject", reason="flat scene",
                             runs_dir=self.root / "_runs")
        committed = commit_reviewed(run, self.events, config=config)

        self.assertEqual({p.name for p in committed},
                         {"event.bargain-creature.a-001.json", "event.story-creature.a-001.json",
                          "_index.json"})
        written = json.loads((self.events / "event.bargain-creature.a-001.json").read_text(encoding="utf-8"))
        self.assertEqual(written["_provenance"]["modelId"], "test-resolved-model")
        self.assertEqual(written["name"], "Ember Pact")
        self.assertIn("nameKey", written)
        # Rejected and unresolved events keep their committed bytes, untouched.
        for name in ("event.story-creature.b-001.json", "event.story-creature.a-002.json"):
            self.assertEqual((self.events / name).read_bytes(), before[name], name)

    def test_the_committed_story_chain_ref_reaches_the_schema(self) -> None:
        from seedsmith.adapters.dungeon.regen import run_legacy_regen
        from seedsmith.pipeline.llm_caller import LlmCallerConfig

        fake = _StubCall([
            self._draft("event.bargain-creature.a-001", "bargain", "creature.a", "Ember Pact",
                        "It uses bright ember."),
            self._draft("event.story-creature.a-001", "story", "creature.a", "One", "It uses bright ember."),
            self._draft("event.story-creature.a-002", "story", "creature.a", "Two", "It uses quiet stone."),
            self._draft("event.story-creature.b-001", "story", "creature.b", "Three", "It uses salt wind."),
        ])
        run_legacy_regen(self.events, call=fake, config=LlmCallerConfig(model="m"),
                         glosses=self._gloss_table(), themes=self.THEMES, dry_run=False,
                         runs_dir=self.root / "_runs")
        chain_consts = [schema["properties"]["chainRef"]["const"] for schema in fake.schemas]
        self.assertIn("event.story-creature.a-002", chain_consts)   # carried over from the committed file
        self.assertIn("event.chain-tail", chain_consts)             # the committed dangling tail, as-is
        self.assertIn("none", chain_consts)                         # every non-story event

    def test_a_reject_requires_a_reason(self) -> None:
        from seedsmith.adapters.dungeon.regen import RegenRun, record_verdict

        run = RegenRun(run_id="regen-x", events={"event.a-001": {"entry": {"eventId": "event.a-001"}, "briefHash": "h"}},
                       unresolved={}, verdicts={})
        with self.assertRaises(ValueError):
            record_verdict(run, "event.a-001", verdict="reject", reason="  ")
        with self.assertRaises(ValueError):
            record_verdict(run, "event.a-001", verdict="maybe")

    def test_the_review_sample_is_seeded_and_stratified(self) -> None:
        from seedsmith.adapters.dungeon.regen import RegenRun, review_sample

        events = {eid: {"entry": {"eventId": eid, "kind": kind}, "briefHash": "h"}
                  for eid, kind in (("event.a-001", "bargain"), ("event.a-002", "curio"),
                                    ("event.b-001", "shrine"), ("event.b-002", "trap"))}
        run = RegenRun(run_id="regen-y", events=events, unresolved={}, verdicts={})
        first = review_sample(run, sample_size=2)
        second = review_sample(run, sample_size=2)
        self.assertEqual(first, second)                       # seeded from the run id
        # Four strata, so every one is represented: `stratified_sample` guarantees one per stratum even
        # when that exceeds `n` (its docstring says "bounded by n overall", its code gives one each --
        # recorded as a finding, not fixed here).
        self.assertEqual(sorted(first), ["bargain", "curio", "shrine", "trap"])
        for stratum in first:
            self.assertEqual(len(first[stratum]), 1)

    def test_a_dry_run_object_holds_no_events(self) -> None:
        from seedsmith.adapters.dungeon.regen import run_legacy_regen

        run = run_legacy_regen(self.events, dry_run=True, runs_dir=self.root / "_runs")
        self.assertEqual(run.events, {})
        self.assertEqual(run.unresolved, {})


class DungeonRegenCliTests(LegacyRegenRunTests):
    """NS13's production host: a real run is planned, drawn, reviewed, accepted and committed through
    `seedsmith dungeon events regen`.

    Every assertion below enters through `main([...])`. The driver's own tests are above; these prove the
    pipeline can REACH it at all — which is exactly what was missing (`report/cli.py` had no `dungeon`
    subcommand tree, so the tested driver had no production caller).

    The inputs the verb deliberately reads from the corpus rather than a flag — the transport, the gloss
    table and the theme registry — are patched to fixtures, so the whole loop is hermetic, spends nothing
    and depends on no real registry row.
    """

    def _responses(self) -> list:
        contaminated = self._draft("event.story-creature.a-002", "story", "creature.a", "The Last Walk",
                                   "It uses quiet stone and \u5206\u914d in one line.")
        return [
            self._draft("event.bargain-creature.a-001", "bargain", "creature.a", "Ember Pact",
                        "It uses bright ember."),
            self._draft("event.story-creature.a-001", "story", "creature.a", "The Long Walk Redux",
                        "It uses bright ember."),
        ] + [contaminated] * 3 + [
            self._draft("event.story-creature.b-001", "story", "creature.b", "A Different Beat Redux",
                        "It uses salt wind."),
        ]

    def _patched(self, fake, config):
        from contextlib import ExitStack
        from unittest.mock import patch

        stack = ExitStack()
        stack.enter_context(patch("seedsmith.pipeline.llm_caller.call_model", fake))
        stack.enter_context(patch("seedsmith.pipeline.llm_caller.resolve_live_transport",
                                  lambda: config))
        stack.enter_context(patch("seedsmith.briefkit.gloss.load_glosses", self._gloss_table))
        stack.enter_context(patch("seedsmith.adapters.dungeon.registries.load_themes",
                                  lambda: self.THEMES))
        return stack

    def _cli(self, *argv) -> "tuple[int, str]":
        import contextlib
        import io

        from seedsmith.report.cli import main

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["dungeon", "events", "regen", "--events-dir", str(self.events),
                         "--runs-dir", str(self.root / "_runs"), *argv])
        return code, out.getvalue()

    def test_the_regen_verb_plans_without_spending(self) -> None:
        from unittest.mock import patch

        with patch("seedsmith.pipeline.llm_caller.call_model",
                   side_effect=AssertionError("--dry-run must make no model call")):
            code, out = self._cli("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("4 base call(s)", out)
        self.assertIn(f"{4 * (1 + MAX_QUALITY_RETRY)} worst call(s)", out)

    def test_the_regen_verb_draws_reviews_accepts_and_commits(self) -> None:
        from seedsmith.adapters.dungeon.regen import latest_run_id
        from seedsmith.pipeline.llm_caller import LlmCallerConfig

        config = LlmCallerConfig(model="test-resolved-model")
        before = {p.name: p.read_bytes() for p in self.events.glob("event.*.json")}
        runs_dir = self.root / "_runs"

        with self._patched(_StubCall(self._responses()), config):
            code, out = self._cli("--write")
        self.assertEqual(code, 0)
        self.assertIn("drew 3 event(s), 1 unresolved", out)
        for name, blob in before.items():
            self.assertEqual((self.events / name).read_bytes(), blob, name)
        run_id = latest_run_id(runs_dir)
        self.assertIsNotNone(run_id)

        with self._patched(_StubCall([]), config):
            code, out = self._cli("--review", "--run", run_id)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(json.loads(out)["sample"]), ["bargain", "story"])

        # A commit with no accepted event must refuse: `commit_event_draws` rewrites the index even for
        # an empty batch, which would look like the verb had done something.
        with self._patched(_StubCall([]), config):
            code, out = self._cli("--commit", "--run", run_id)
        self.assertEqual(code, 3)
        self.assertIn("no accepted event", out)
        for name, blob in before.items():
            self.assertEqual((self.events / name).read_bytes(), blob, name)

        with self._patched(_StubCall([]), config):
            code, out = self._cli("--accept", "event.bargain-creature.a-001", "--reject",
                                  "event.story-creature.b-001=flat scene", "--run", run_id)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["accepted"], ["event.bargain-creature.a-001"])

        with self._patched(_StubCall([]), config):
            code, out = self._cli("--commit", "--run", run_id)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["committed"],
                         ["_index.json", "event.bargain-creature.a-001.json"])
        written = json.loads((self.events / "event.bargain-creature.a-001.json")
                             .read_text(encoding="utf-8"))
        self.assertEqual(written["_provenance"]["modelId"], "test-resolved-model")
        # The rejected and the unresolved event keep their committed bytes, untouched.
        for name in ("event.story-creature.b-001.json", "event.story-creature.a-002.json"):
            self.assertEqual((self.events / name).read_bytes(), before[name], name)

    def test_the_regen_verb_refuses_a_run_that_does_not_exist(self) -> None:
        code, out = self._cli("--commit", "--run", "regen-not-a-run")
        self.assertEqual(code, 3)
        self.assertIn("no run file", out)
