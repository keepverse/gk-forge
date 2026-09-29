"""NS15 — the gloss commit step, the review sample and the preflight (spec-gloss-fill.md §4-§5).

    python -m pytest gk-forge/tools/seedsmith/tests/test_narrative_gloss_commit.py -q

Kept as its own file rather than appended to `test_narrative_gloss_fill.py` so the two halves of this
module (fill, then commit/preflight) stay separately readable. Fixtures only; every call goes through a
stub.
"""
from __future__ import annotations

import json
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.narrative.gloss.commit import (  # noqa: E402
    commit_glosses,
    regeneration_requests,
    review_sample,
)
from seedsmith.adapters.narrative.preflight import PREFLIGHT_MOTIF, preflight  # noqa: E402
from seedsmith.briefkit.gloss import BriefRefusal  # noqa: E402
from seedsmith.pipeline.llm_caller import LlmCallerConfig  # noqa: E402

MOTIFS = ["\u9F99\u7FFC", "\u6697\u6F6E", "\u706B"]          # 龙翼, 暗潮, 火
EXEMPLARS = [{"motif": "\u706B", "gloss": "fire", "sense": "concrete"}]


class StubCall:
    def __init__(self, answers: "list") -> None:
        import collections

        self._answers = collections.deque(answers)
        self.calls: "list[tuple[str, str]]" = []

    def __call__(self, system: str, user: str, *, config=None, schema=None) -> str:
        self.calls.append((system, user))
        if not self._answers:
            raise AssertionError("stub exhausted")
        answer = self._answers.popleft()
        return answer if isinstance(answer, str) else json.dumps(answer)


def _answer(*rows: "tuple[str, str, str]", blocked: str = "") -> dict:
    return {"blocked": blocked,
            "glosses": [{"motif": m, "gloss": g, "sense": s} for m, g, s in rows]}


class CommitTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.registry = Path(self.tmp.name) / "motif-glosses.en.v1.json"
        self.registry.write_text(json.dumps({
            "schemaVersion": 1, "registryVersion": 1, "locale": "en",
            "source": {"registry": "data/seed/creatures/_registry/motifs.v1.json", "registryVersion": 1},
            "glosses": {}}, ensure_ascii=False), encoding="utf-8")

    def _rows(self) -> dict:
        return {MOTIFS[0]: {"gloss": "dragon wing", "sense": "concrete"},
                MOTIFS[1]: {"gloss": "dark tide", "sense": "abstract"}}

    def test_commit_writes_only_accepted_rows_and_refuses_an_unreplaced_rejection(self):
        verdicts = {MOTIFS[0]: [{"verdict": "accept", "reason": ""}],
                    MOTIFS[1]: [{"verdict": "reject", "reason": "too literal"}]}
        # The rejected motif has no accepted row yet, so the batch must not be written at all.
        rows_without_rejected = {MOTIFS[0]: self._rows()[MOTIFS[0]]}
        with self.assertRaises(ValueError) as ctx:
            commit_glosses(rows_without_rejected, model="m", prompt_version="gloss/1", verdicts=verdicts,
                           registry_path=self.registry)
        self.assertIn("no accepted replacement", str(ctx.exception))
        self.assertIn(MOTIFS[1], str(ctx.exception))

        verdicts[MOTIFS[1]].append({"verdict": "accept", "reason": ""})
        commit_glosses(self._rows(), model="test-model", prompt_version="gloss/1", verdicts=verdicts,
                       registry_path=self.registry)
        written = json.loads(self.registry.read_text(encoding="utf-8"))
        self.assertEqual(sorted(written["glosses"]), sorted(MOTIFS[:2]))
        self.assertEqual(written["glosses"][MOTIFS[0]]["model"], "test-model")
        self.assertEqual(written["glosses"][MOTIFS[0]]["promptVersion"], "gloss/1")
        self.assertNotIn(MOTIFS[2], written["glosses"])

    def test_commit_is_byte_identical_on_rerun_and_makes_no_call(self):
        with unittest.mock.patch("seedsmith.pipeline.llm_caller.call_model",
                                 side_effect=AssertionError("the commit step makes no call")):
            commit_glosses(self._rows(), model="m", prompt_version="gloss/1",
                           registry_path=self.registry)
            first = self.registry.read_bytes()
            commit_glosses(self._rows(), model="m", prompt_version="gloss/1",
                           registry_path=self.registry)
            second = self.registry.read_bytes()
        self.assertEqual(first, second)
        self.assertNotIn(b"generatedUtc", first)      # no timestamp: identical bytes on a rerun

    def test_rejected_gloss_regenerates_with_reason(self):
        verdicts = {MOTIFS[0]: [{"verdict": "reject", "reason": "too literal"},
                                {"verdict": "reject", "reason": "still too literal"}],
                    MOTIFS[1]: [{"verdict": "accept", "reason": ""}]}
        self.assertEqual(regeneration_requests(verdicts), {MOTIFS[0]: "still too literal"})

    def test_review_sample_is_seeded_and_stratified(self):
        rows = {f"m{i}": {"gloss": "x", "sense": sense}
                for i, sense in enumerate(("concrete", "abstract", "action", "quality", "none"))}
        first = review_sample(rows, sample_size=3, run_id="gloss-run-1")
        second = review_sample(rows, sample_size=3, run_id="gloss-run-1")
        self.assertEqual(first, second)               # seeded from the run id
        self.assertEqual(sorted(first), ["abstract", "action", "concrete", "none", "quality"])
        for stratum in first:
            self.assertEqual(len(first[stratum]), 1)


class PreflightTests(unittest.TestCase):
    def test_preflight_makes_exactly_one_call_and_reports_the_reading(self):
        stub = StubCall([_answer((PREFLIGHT_MOTIF, "fire", "concrete"))])
        result = preflight(call=stub, config=LlmCallerConfig(model="m"), exemplars=EXEMPLARS)
        self.assertEqual(len(stub.calls), 1)
        self.assertEqual(result["calls"], 1)
        self.assertEqual(result["gloss"], "fire")

    def test_preflight_fails_loudly_on_every_non_conforming_reply(self):
        bad_replies = ["not json at all", _answer(), _answer(blocked="no idea"),
                       _answer((PREFLIGHT_MOTIF, PREFLIGHT_MOTIF, "concrete")),
                       _answer((PREFLIGHT_MOTIF, "fire 2", "concrete"))]
        for reply in bad_replies:
            stub = StubCall([reply])
            with self.assertRaises(BriefRefusal):
                preflight(call=stub, config=LlmCallerConfig(model="m"), exemplars=EXEMPLARS)
            self.assertEqual(len(stub.calls), 1, "a failed preflight still spends exactly one call")

    def test_preflight_fails_loudly_when_the_endpoint_is_dead(self):
        class Dead:
            def __call__(self, *args, **kwargs):
                raise RuntimeError("connection refused")

        with self.assertRaises(BriefRefusal):
            preflight(call=Dead(), config=LlmCallerConfig(model="m"), exemplars=EXEMPLARS)


if __name__ == "__main__":
    unittest.main()


class NarrativeCliTests(unittest.TestCase):
    """NS15's production host: `seedsmith narrative gloss fill|commit` and `seedsmith narrative
    preflight` must be the way the pipeline reaches the gloss modules.

    Every assertion enters through `main([...])`; the drivers' own tests are above. The transport and the
    scratch run directory are patched/redirected, so nothing here spends a call, needs a live endpoint, or
    writes the committed registry.
    """

    def setUp(self) -> None:
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runs = self.root / "_runs"
        self.registry = self.root / "motif-glosses.en.v1.json"
        self.registry.write_text(json.dumps({
            "schemaVersion": 1, "registryVersion": 1, "locale": "en",
            "source": {"registry": "data/seed/creatures/_registry/motifs.v1.json",
                       "registryVersion": 1},
            "glosses": {}}, ensure_ascii=False), encoding="utf-8")
        self.before = self.registry.read_bytes()

    def _cli(self, *argv) -> "tuple[int, str]":
        import contextlib
        import io

        from seedsmith.report.cli import main

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["narrative", *argv])
        return code, out.getvalue()

    def _patched(self, call):
        from contextlib import ExitStack
        from unittest.mock import patch

        stack = ExitStack()
        # Two bindings, both patched: `gloss/fill.py` imports `call_model` at module level (so the
        # global it reads is that module's), while `preflight.py` imports it inside the call.
        stack.enter_context(patch("seedsmith.adapters.narrative.gloss.fill.call_model", call))
        stack.enter_context(patch("seedsmith.pipeline.llm_caller.call_model", call))
        stack.enter_context(patch("seedsmith.pipeline.llm_caller.resolve_live_transport",
                                  lambda: LlmCallerConfig(model="test-resolved-model")))
        return stack

    def _payload(self, out: str) -> dict:
        """The verb's JSON, from the last line that is one: the transport logs progress to stdout too."""
        return json.loads([line for line in out.splitlines() if line.startswith("{")][-1])

    def _write_run(self, run_id: str = "gloss-fixture") -> Path:
        self.runs.mkdir(parents=True, exist_ok=True)
        document = {"runId": run_id, "model": "test-resolved-model", "promptVersion": "gloss/1",
                    "chunkSize": 20, "regenerated": [], "calls": 1, "chunks": 1,
                    "glosses": {MOTIFS[0]: {"gloss": "dragon wing", "sense": "concrete"},
                                MOTIFS[1]: {"gloss": "dark tide", "sense": "abstract"}},
                    "unresolved": {}, "verdicts": {}}
        path = self.runs / f"{run_id}.json"
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        return path

    def test_the_fill_verb_dry_run_counts_chunks_and_calls_nothing(self) -> None:
        def boom(*_args, **_kwargs):
            raise AssertionError("a dry run must make no call")

        with self._patched(boom):
            code, out = self._cli("gloss", "fill", "--dry-run", "--limit", "2",
                                  "--runs-dir", str(self.runs))
        self.assertEqual(code, 0)
        payload = self._payload(out)
        self.assertTrue(payload["dryRun"])
        self.assertEqual(payload["calls"], 0)
        self.assertEqual(payload["chunks"], 2)
        self.assertGreater(payload["toGloss"], 0)
        self.assertFalse(self.runs.exists())          # a dry run writes no run file either

    def test_the_fill_verb_writes_a_run_with_the_resolved_model(self) -> None:
        stub = StubCall([_answer(blocked="cannot gloss these")])
        with self._patched(stub):
            code, out = self._cli("gloss", "fill", "--write", "--limit", "1",
                                  "--runs-dir", str(self.runs))
        self.assertEqual(code, 0)
        payload = self._payload(out)
        self.assertEqual((payload["calls"], len(stub.calls)), (1, 1))
        run = json.loads((self.runs / f"{payload['runId']}.json").read_text(encoding="utf-8"))
        self.assertEqual(run["model"], "test-resolved-model")
        self.assertEqual(run["promptVersion"], "gloss/1")
        self.assertEqual(len(run["unresolved"]), run["chunkSize"])   # the whole one chunk is unresolved
        self.assertEqual(self.registry.read_bytes(), self.before)    # a fill never writes the registry

    def test_the_preflight_verb_makes_exactly_one_call(self) -> None:
        stub = StubCall([_answer((PREFLIGHT_MOTIF, "fire", "concrete"))])
        with self._patched(stub):
            code, out = self._cli("preflight")
        self.assertEqual(code, 0)
        payload = self._payload(out)
        self.assertEqual((payload["motif"], payload["gloss"], payload["sense"]),
                         (PREFLIGHT_MOTIF, "fire", "concrete"))
        self.assertEqual(len(stub.calls), 1)

    def test_the_preflight_verb_refuses_a_dead_endpoint(self) -> None:
        def dead(*_args, **_kwargs):
            raise RuntimeError("connection refused")

        with self._patched(dead):
            code, out = self._cli("preflight")
        self.assertEqual(code, 3)
        self.assertIn("refused:", out)
        self.assertIn("RuntimeError", out)

    def test_the_commit_verb_writes_accepted_rows_and_refuses_an_unreplaced_rejection(self) -> None:
        self._write_run()
        code, out = self._cli("gloss", "commit", "--run", "gloss-fixture", "--accept", MOTIFS[0],
                              "--reject", f"{MOTIFS[1]}=too literal", "--registry", str(self.registry),
                              "--runs-dir", str(self.runs))
        self.assertEqual(code, 3)
        self.assertIn("no accepted replacement", out)
        self.assertEqual(self.registry.read_bytes(), self.before)

        # The verdict history is part of the run, so the regeneration's accept closes the rejection.
        code, out = self._cli("gloss", "commit", "--run", "gloss-fixture", "--accept", MOTIFS[1],
                              "--registry", str(self.registry), "--runs-dir", str(self.runs))
        self.assertEqual(code, 0)
        self.assertEqual(self._payload(out)["committed"], sorted(MOTIFS[:2]))
        written = json.loads(self.registry.read_text(encoding="utf-8"))
        self.assertEqual(sorted(written["glosses"]), sorted(MOTIFS[:2]))
        self.assertEqual(written["glosses"][MOTIFS[0]]["model"], "test-resolved-model")
        self.assertEqual(written["glosses"][MOTIFS[0]]["promptVersion"], "gloss/1")

    def test_the_commit_verb_refuses_a_run_that_does_not_exist(self) -> None:
        code, out = self._cli("gloss", "commit", "--run", "gloss-not-a-run",
                              "--registry", str(self.registry), "--runs-dir", str(self.runs))
        self.assertEqual(code, 3)
        self.assertIn("no run file", out)
