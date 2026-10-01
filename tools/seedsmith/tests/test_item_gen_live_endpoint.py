"""Tests for `set-charm-live-endpoint` (item module 13, Phase 4) — the live-model transport for
`items generate --write`.

    python -m pytest gk-forge/tools/seedsmith/tests/test_item_gen_live_endpoint.py -q

⭐ **What this proves.** Before this module, `items generate --write` had exactly one transport —
`--answers <file>` replaying a hand-authored answer — and refused outright without it
(`docs/architecture/item-seedgen/spec-set-charm-live-endpoint.md`). This file proves the second,
real transport: `--endpoint <url>` reaches `pipeline.llm_caller.call_model` through
`setgen.run.live_caller`, the exact pattern `effects generate`/`creatures generate` already use, and
the refusal narrows correctly — `--write` still refuses with NEITHER flag, but no longer refuses
with `--endpoint` alone.

⚠ **No reachable-endpoint skip convention exists elsewhere in this repo to reuse.** Searched: the
only `skipif` in `gk-forge/tools/seedsmith/tests/` (`test_candidate_assembly.py`) gates on a *file* being
present, not network reachability, and `test_llm_caller.py`'s own live-transport tests
(`ReasoningDisabledTests`, `SelfHealTests`, `ConstrainedDecodingTests`) never skip at all — they spin
up a real `http.server.HTTPServer` on loopback and talk to it for real. `LiveEndpointTests` below
follows that exact precedent: it is a genuine, real HTTP round trip through `call_model`, just to a
mock server this test owns, so it needs no skip and runs in CI like every other test here.
"""
from __future__ import annotations

import contextlib
import http.server
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.setgen import answers as answers_mod  # noqa: E402
from seedsmith.adapters.items.setgen import run as run_mod  # noqa: E402
from seedsmith.adapters.items.setgen import themes as themes_mod  # noqa: E402
from seedsmith.pipeline.llm_caller import DEFAULT_CONFIG, LlmCallerConfig  # noqa: E402
from seedsmith.report import cli as cli_mod  # noqa: E402

from test_item_gen_wiring import (  # noqa: E402
    TUNING,
    VOCAB,
    _clean_set_answer,
    _set_plan,
)


# --------------------------------------------------------------------------------------------
# A real loopback OpenAI-compatible endpoint — the same fixture shape test_llm_caller.py already
# uses, duplicated here rather than imported since it is test-local infrastructure, not a library.
# --------------------------------------------------------------------------------------------

class _Handler(http.server.BaseHTTPRequestHandler):
    """⛔ Rewritten 2026-09-08 to speak real SSE streaming — `call_model` now always sends
    `"stream": true` and reads an OpenAI-compatible `data: {...}` chunk stream (see
    `llm_caller._stream_once`), so a mock that replied with one plain JSON body no longer matches
    what the real transport sends or expects."""

    def log_message(self, fmt, *args):  # silence stdlib per-request logging
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        self.server.requests.append(body)  # type: ignore[attr-defined]
        queued = self.server.responses  # type: ignore[attr-defined]
        content = queued.pop(0) if queued else "{}"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        chunk_size = 4
        for i in range(0, len(content), chunk_size):
            piece = content[i:i + chunk_size]
            frame = json.dumps({"choices": [{"delta": {"content": piece}}]})
            self.wfile.write(f"data: {frame}\n\n".encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")


class MockModelServer:
    def __init__(self) -> None:
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.requests = []  # type: ignore[attr-defined]
        self.httpd.responses = []  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_port}/v1/chat/completions"

    @property
    def requests(self) -> "list[dict]":
        return self.httpd.requests  # type: ignore[attr-defined]

    def queue(self, *contents: str) -> None:
        self.httpd.responses.extend(contents)  # type: ignore[attr-defined]

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


def _write_args(**overrides) -> "cli_mod.argparse.Namespace":
    base = dict(kind="set", population="build", answers="", endpoint="", model="",
                out_dir="", allow_production_tree=False, ledger="",
                authored_utc="1970-01-01T00:00:00Z")
    base.update(overrides)
    return cli_mod.argparse.Namespace(**base)


def _generate_args(**overrides) -> "cli_mod.argparse.Namespace":
    """The full `cmd_items` Namespace — unlike `_write_args`, this drives `cmd_items` itself (the
    dispatcher that calls `plan_run` before `_cmd_items_write`), not `_cmd_items_write` directly."""
    base = dict(items_command="generate", kind="set", population="build", dry_run=False,
                write=True, sample_brief=False, limit=1, briefs_out="",
                answers="", endpoint="", out_dir="", allow_production_tree=False,
                ledger="", ignore_ledger=False, model="unrecorded",
                authored_utc="1970-01-01T00:00:00Z")
    base.update(overrides)
    return cli_mod.argparse.Namespace(**base)


# --------------------------------------------------------------------------------------------
# Criterion: `live_caller` is shaped exactly like `ReplayTransport.__call__`.
# --------------------------------------------------------------------------------------------

class LiveCallerShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = MockModelServer()

    def tearDown(self) -> None:
        self.server.close()

    def test_live_caller_reaches_the_bound_endpoint_and_ignores_the_incoming_config(self):
        """The graph always passes `config=<build_item_set_graph's own default>` on every call
        (`workflow/nodes/generate.py:generate_node`) — `live_caller` must talk to ITS OWN bound
        endpoint regardless, never the graph's unrelated default."""
        self.server.queue('{"hello": "live"}')
        live_config = LlmCallerConfig(endpoint=self.server.url, model="test-model", attempts=1,
                                      retry_delay=0)
        call = run_mod.live_caller(live_config)

        result = call("sys prompt", "user prompt", config=DEFAULT_CONFIG, schema=None)

        self.assertEqual(result, '{"hello": "live"}')
        self.assertEqual(len(self.server.requests), 1)
        req = self.server.requests[0]
        self.assertEqual(req["model"], "test-model")
        self.assertEqual(req["messages"], [{"role": "system", "content": "sys prompt"},
                                           {"role": "user", "content": "user prompt"}])

    def test_live_caller_accepts_the_replay_transports_own_call_signature(self):
        """Same shape `ReplayTransport.__call__` satisfies: `(system, user, *, config=None,
        schema=None)`, callable with config/schema omitted entirely."""
        self.server.queue('{"ok": true}')
        call = run_mod.live_caller(LlmCallerConfig(endpoint=self.server.url, attempts=1,
                                                   retry_delay=0))
        self.assertEqual(call("sys", "user"), '{"ok": true}')


# --------------------------------------------------------------------------------------------
# Criterion 1/2: the CLI flags exist and the refusal narrows correctly.
# --------------------------------------------------------------------------------------------

class CliFlagTests(unittest.TestCase):
    def test_items_generate_parses_endpoint_and_model_like_effects_generate_does(self):
        parser = cli_mod.build_parser()
        args = parser.parse_args([
            "items", "generate", "--kind", "set", "--write",
            "--endpoint", "http://localhost:9999/v1/chat/completions",
            "--model", "some-model",
        ])
        self.assertEqual(args.endpoint, "http://localhost:9999/v1/chat/completions")
        self.assertEqual(args.model, "some-model")
        self.assertIs(args.func, cli_mod.cmd_items)

    def test_endpoint_and_model_default_to_empty_and_unrecorded(self):
        parser = cli_mod.build_parser()
        args = parser.parse_args(["items", "generate", "--kind", "set"])
        self.assertEqual(args.endpoint, "")
        self.assertEqual(args.model, "unrecorded")

    def test_dry_run_reads_the_configured_kind_ledger(self):
        """A read-only plan must reconcile against the same default ledger as a write."""
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "set-charm-gen.ledger.json"
            ledger.write_text(json.dumps({"done": {
                "charm-species-creature.allpeater": {"outcome": "done"},
            }}), encoding="utf-8")
            args = _generate_args(kind="charm", population="species", dry_run=True, write=False,
                                  out_dir="")
            output = io.StringIO()
            with patch("seedsmith.adapters.items.defaults.default_out_dir", return_value=tmp), \
                    contextlib.redirect_stdout(output):
                exit_code = cli_mod.cmd_items(args)
            self.assertEqual(exit_code, cli_mod.EXIT_CLEAN)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["alreadyDone"], 1)


class RefusalNarrowingTests(unittest.TestCase):
    """`_cmd_items_write`'s own refusal — proven directly, the same way `authored_mod.run_batch`
    is proven directly in test_item_gen_wiring.py, rather than through the full `cmd_items` plan
    machinery, so the assertion is about the transport gate and nothing else."""

    def test_neither_answers_nor_resolved_endpoint_still_refuses(self):
        """Empty CLI `--endpoint` is no longer enough to refuse — `.env` / defaults can supply
        one. Refuse only when the *resolved* transport endpoint is blank."""
        empty = LlmCallerConfig(endpoint="", model="x")
        with tempfile.TemporaryDirectory() as tmp:
            plan = _set_plan()
            args = _write_args(out_dir=str(Path(tmp) / "out"), allow_production_tree=True)
            with patch("seedsmith.pipeline.llm_caller.resolve_live_transport",
                       return_value=empty):
                exit_code = cli_mod._cmd_items_write(
                    args, plan=plan, tuning=TUNING, vocabulary=VOCAB)
        self.assertEqual(exit_code, cli_mod.EXIT_REFUSED)

    def test_no_out_dir_still_refuses_even_with_an_endpoint(self):
        """A live endpoint is not a substitute for somewhere to write — the write half of the
        contract is unchanged when production defaults are off."""
        plan = _set_plan()
        args = _write_args(endpoint="http://127.0.0.1:1/v1/chat/completions", out_dir="",
                           allow_production_tree=False)
        with patch("seedsmith.adapters.items.defaults.allow_production_tree",
                   return_value=False), \
             patch("seedsmith.adapters.items.defaults.resolve_out_dir_arg",
                   return_value=""):
            exit_code = cli_mod._cmd_items_write(args, plan=plan, tuning=TUNING, vocabulary=VOCAB)
        self.assertEqual(exit_code, cli_mod.EXIT_REFUSED)

    # `--endpoint` alone no longer hitting the refusal gate is proven by
    # `LiveEndToEndTests.test_a_live_call_writes_a_seed_file_identical_in_shape_to_the_replay_path`
    # below: it drives `_cmd_items_write` with `--endpoint` and no `--answers` all the way to
    # `EXIT_CLEAN`, which is strictly stronger than "not refused". A separate refusal-only probe
    # Runtime transport failures are handled per subject by `authored.run_batch` and recorded as
    # terminal escalations; the batch driver test covers that isolation boundary directly.


#: The single build theme `one_uncovered_build_subject` plants. A SYNTHETIC archetype on purpose:
#: `build.might-offense` is a real shipped partition, so a fixture built on it would silently depend
#: on whatever the production corpus happens to contain — and `might-fixture` is a partition name no
#: real corpus can collide with, so the fixture's plan cannot be perturbed by content shipping.
_FIXTURE_BUILD_THEME = {
    "id": "might-fixture",
    "themeKey": "build.might-fixture",
    "aptitude": "Might",
    "posture": "force",
    "archetype": "fixture",
    "displayName": "Might / Fixture",
    "motifs": ["might", "force"],
    "antiMotifs": ["defense"],
    "expression": {"item": "stat emphasis and threshold shape",
                   "action": "not applicable - a build theme names no action expression"},
    "basis": "derived",
    "retired": False,
}


@contextlib.contextmanager
def one_uncovered_build_subject(root: Path):
    """Point `setgen`'s two corpus reads at a planted one-subject build catalogue under `root`.

    ⛔ **Why this exists.** These two tests were written against the LIVE corpus, and their premise
    rotted. They assert that a *resumed* run makes no second model call, which only holds if the
    population is FINITE and the first invocation EXHAUSTS it. The comment the first test carried
    claimed "the live build-theme catalogue has one uncovered subject in this fixture" — true when it
    was written, and false the moment content shipped: all 36 build themes exist, so `plan_run`
    returns an EMPTY plan BEFORE the ledger is ever consulted, `_cmd_items_write` is handed zero
    subjects, and the very FIRST invocation makes 0 calls where the test asserted 1. Measured:
    `population=build subjects=0 alreadyDone=36` with `ledger={}`, i.e. the subjects are absent
    because `_set_entry_on_disk` finds every one already in the corpus, not because a ledger row
    claims them. The 2026-09-08 regression these tests guard is still intact and still provable —
    varying only `--population` gives `species` 1 uncovered subject and green lines, `build` 0 and
    red — so the fix is to make the premise a FIXTURE, never to weaken the assertions.

    Two constants carry every live read on this path, and both are module-level lookups resolved
    per call, so patching them redirects the real code rather than replacing it:
    `themes.BUILD_THEME_REGISTRY` (the pool `plan_run` plans from) and `run.DEFAULT_SETS_DIR` (the
    corpus `plan_run` checks for an already-written entry, via `_set_entry_on_disk` when
    `sets_dir=None` — which is exactly how `cmd_items` calls it).

    This plants no corpus rows, so the planted catalogue owes exactly one subject on any machine
    today and after the next content ship: the tests mean what they say.
    """
    registry = root / "_registry" / "build-themes.v1.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps(
        {"schemaVersion": 1, "registryVersion": "fixture", "themes": [_FIXTURE_BUILD_THEME]},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sets_dir = root / "sets"
    sets_dir.mkdir(parents=True, exist_ok=True)
    with patch.object(themes_mod, "BUILD_THEME_REGISTRY", registry), \
            patch.object(run_mod, "DEFAULT_SETS_DIR", sets_dir):
        yield


class LedgerReadPathMatchesWritePathTests(unittest.TestCase):
    """⛔ Real incident, 2026-09-08: a live 53-subject production run, resumed across THREE
    separate `items generate --write` invocations against the same `--out-dir`, reported
    `"alreadyDone": 0` and `"toGenerate": 53` — the FULL, un-resumed population — every single
    time, no matter how many subjects earlier invocations had already persisted. Root cause:
    `cmd_items` passed `ledger=None` to `plan_run` whenever `--ignore-ledger` was not given,
    which fell through to `plan_run`'s own `read_ledger()` with NO PATH — a hardcoded default
    (`data/seed/items/_runs/set-charm-gen.ledger.json`) completely disconnected from the ledger
    `_cmd_items_write` actually reads and writes (`<out-dir>/set-charm-gen.ledger.json`, computed
    separately, further down, only once `--write` runs). This is `cmd_items` itself under test —
    not `_cmd_items_write` directly, the way `RefusalNarrowingTests`/`LiveEndToEndTests` above
    test it — because the bug is entirely in the PLANNING call that happens before `_cmd_items_write`
    ever sees a ledger path."""

    def setUp(self) -> None:
        self.server = MockModelServer()

    def tearDown(self) -> None:
        self.server.close()

    def test_a_second_invocation_does_not_redo_the_first_invocations_subject(self):
        with tempfile.TemporaryDirectory() as tmp, \
                one_uncovered_build_subject(Path(tmp) / "corpus"):
            out_dir = str(Path(tmp) / "sets")
            self.server.queue(json.dumps(_clean_set_answer()))
            first = _generate_args(endpoint=self.server.url, out_dir=out_dir, limit=1)
            with patch("sys.stdout"):
                exit_code = cli_mod.cmd_items(first)
            self.assertEqual(exit_code, cli_mod.EXIT_CLEAN)
            self.assertEqual(len(self.server.requests), 1)

            # The planted build-theme catalogue has exactly one uncovered subject (see
            # `one_uncovered_build_subject`). The first invocation therefore exhausts the finite
            # population; resume must make no second call rather than inventing a new subject merely
            # to prove the ledger is being read.
            self.server.queue(json.dumps(_clean_set_answer()))
            second = _generate_args(endpoint=self.server.url, out_dir=out_dir, limit=1)
            with patch("sys.stdout"):
                cli_mod.cmd_items(second)

            self.assertEqual(len(self.server.requests), 1,
                             "a resumed run must not redo an exhausted subject")
            files = [f for f in Path(out_dir).glob("*.json")
                    if f.name != "set-charm-gen.ledger.json"]
            self.assertEqual(len(files), 1,
                             "a resumed run must preserve the first invocation's file")

    def test_ignore_ledger_still_replans_the_full_population(self):
        """The fix must not accidentally make `--ignore-ledger` a no-op — it is the documented
        escape hatch for "replan every generatable subject, even ones a previous run recorded"."""
        with tempfile.TemporaryDirectory() as tmp, \
                one_uncovered_build_subject(Path(tmp) / "corpus"):
            out_dir = str(Path(tmp) / "sets")
            self.server.queue(json.dumps(_clean_set_answer()))
            first = _generate_args(endpoint=self.server.url, out_dir=out_dir, limit=1)
            with patch("sys.stdout"):
                cli_mod.cmd_items(first)

            self.server.queue(json.dumps(_clean_set_answer()))
            second = _generate_args(endpoint=self.server.url, out_dir=out_dir, limit=1,
                                    ignore_ledger=True)
            with patch("sys.stdout"):
                cli_mod.cmd_items(second)

            self.assertEqual(self.server.requests[0]["messages"], self.server.requests[1]["messages"],
                             "--ignore-ledger must re-plan the SAME first subject, not advance past it")

    def test_the_planted_fixture_owes_exactly_one_build_subject(self):
        """The PREMISE of the two tests above, asserted rather than assumed.

        Both neighbours prove a resume makes no second call, which is only meaningful if the first
        invocation had a subject to spend. That is exactly the premise that rotted unnoticed when
        these tests read the live corpus: the population went to zero and the tests went red at
        their FIRST assertion instead of reporting "the fixture no longer owes anything". This test
        is the canary — it reads the planted catalogue through the real `plan_run` and fails loudly
        if the fixture ever stops owing exactly one generatable subject, so the rot is named at its
        cause instead of surfacing two tests downstream.

        It also pins the two ways the planted plan can silently collapse to zero: the theme becoming
        held (`retired` / non-generatable `basis` / no motifs), and the theme's minted entry id
        appearing in the sets corpus `plan_run` checks.
        """
        with tempfile.TemporaryDirectory() as tmp:
            with one_uncovered_build_subject(Path(tmp) / "corpus"):
                plan = run_mod.plan_run(kind="set", population="build", tuning=TUNING,
                                        vocabulary=VOCAB, ledger={})
        self.assertEqual(len(plan.subjects), 1,
                         "the planted catalogue must owe exactly one build subject")
        self.assertEqual(plan.subjects[0].subject_id, "set-build-build.might-fixture")
        self.assertEqual(plan.already_done, [],
                         "no planted subject may start out already done")
        self.assertFalse(plan.subjects[0].brief.strip() == "",
                         "a planned subject must carry the brief the model is asked to answer")


# --------------------------------------------------------------------------------------------
# Criterion 4: a real, small end-to-end live call — genuinely over HTTP, to a loopback mock model.
# --------------------------------------------------------------------------------------------

class LiveEndToEndTests(unittest.TestCase):
    """Proves the full path: CLI flags -> `live_caller` -> `call_model` -> a real HTTP POST -> the
    generation graph -> the same distributors/schema/emit the replay path already proved -> a
    written seed file — with NO `--answers` file anywhere in the run."""

    def setUp(self) -> None:
        self.server = MockModelServer()

    def tearDown(self) -> None:
        self.server.close()

    def test_a_live_call_writes_a_seed_file_identical_in_shape_to_the_replay_path(self):
        self.server.queue(json.dumps(_clean_set_answer()))
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "sets"
            plan = _set_plan()
            args = _write_args(endpoint=self.server.url, model="live-endpoint-proof",
                               out_dir=str(out_dir))
            exit_code = cli_mod._cmd_items_write(args, plan=plan, tuning=TUNING, vocabulary=VOCAB)

            self.assertEqual(exit_code, cli_mod.EXIT_CLEAN,
                             "a clean live answer must persist cleanly")
            self.assertEqual(len(self.server.requests), 1, "exactly one model call for one subject")
            files = list(out_dir.glob("*.json"))
            # the ledger also lands in out_dir; exactly one seed file besides it
            seed_files = [f for f in files if f.name != "set-charm-gen.ledger.json"]
            self.assertEqual(len(seed_files), 1)
            doc = json.loads(seed_files[0].read_text(encoding="utf-8"))
            self.assertEqual(doc["kind"], "set")
            self.assertEqual(doc["_meta"]["model"], "live-endpoint-proof",
                             "the live model id is stamped, not the --answers metadata sentinel")
            entry = doc["entries"][0]
            self.assertEqual(entry["themeKey"], "build.might-offense")
            self.assertIn("thresholds", entry)

    def test_no_model_flag_falls_back_to_llm_callers_own_default_not_the_metadata_sentinel(self):
        """`--model` defaults to `"unrecorded"` for the --answers metadata-only path; going live
        without --model must not send that sentinel to the endpoint as a real model id.

        Isolated from this machine's own `tools/seedsmith/.env` (patches `load_config` to return
        the plain built-in default) — otherwise this test's result would depend on whatever model
        a developer happens to have configured locally, which is exactly the kind of ambient-state
        leak `test_dot_env_model_reaches_the_wire_when_no_model_flag_is_passed` below exists to
        prove is now respected rather than silently ignored."""
        self.server.queue(json.dumps(_clean_set_answer()))
        with tempfile.TemporaryDirectory() as tmp:
            plan = _set_plan()
            args = _write_args(endpoint=self.server.url, out_dir=str(Path(tmp) / "out"))
            with patch("seedsmith.pipeline.llm_caller.load_config", return_value=DEFAULT_CONFIG):
                cli_mod._cmd_items_write(args, plan=plan, tuning=TUNING, vocabulary=VOCAB)
        self.assertEqual(self.server.requests[0]["model"], DEFAULT_CONFIG.model)

    def test_dot_env_model_reaches_the_wire_when_no_model_flag_is_passed(self):
        """⛔ Real bug, found 2026-09-08 from a live run: `_cmd_items_write` used to build
        `LlmCallerConfig(endpoint=..., model=...)` directly, NEVER calling `load_config()` — a
        real `.env` (`SEEDSMITH_LLM_MODEL=meta/muse-glimmer`) had zero effect on this path; the
        live call always used `google/gemma-4-26b-a4b-qat` (`LlmCallerConfig`'s hardcoded
        default) regardless. Proven fixed: a `load_config()` that returns a distinct model (and a
        distinct `max_tokens`, the other field this same bug silently dropped) is honored end to
        end through the real HTTP request, with no `--model` flag involved."""
        self.server.queue(json.dumps(_clean_set_answer()))
        configured = LlmCallerConfig(endpoint="http://unused-because-endpoint-overrides-it",
                                      model="meta/muse-glimmer", max_tokens=777)
        with tempfile.TemporaryDirectory() as tmp:
            plan = _set_plan()
            args = _write_args(endpoint=self.server.url, out_dir=str(Path(tmp) / "out"))
            with patch("seedsmith.pipeline.llm_caller.load_config", return_value=configured):
                exit_code = cli_mod._cmd_items_write(args, plan=plan, tuning=TUNING, vocabulary=VOCAB)
        self.assertEqual(exit_code, cli_mod.EXIT_CLEAN)
        self.assertEqual(self.server.requests[0]["model"], "meta/muse-glimmer")
        self.assertEqual(self.server.requests[0]["max_tokens"], 777)

    def test_explicit_model_flag_still_overrides_dot_env(self) -> None:
        """`--model` is the more specific instruction and must win over whatever `load_config()`
        returns — the fix must not make `.env` unconditionally override an operator's explicit
        flag."""
        self.server.queue(json.dumps(_clean_set_answer()))
        configured = LlmCallerConfig(endpoint="http://unused", model="meta/muse-glimmer")
        with tempfile.TemporaryDirectory() as tmp:
            plan = _set_plan()
            args = _write_args(endpoint=self.server.url, model="explicit/on-the-cli",
                               out_dir=str(Path(tmp) / "out"))
            with patch("seedsmith.pipeline.llm_caller.load_config", return_value=configured):
                cli_mod._cmd_items_write(args, plan=plan, tuning=TUNING, vocabulary=VOCAB)
        self.assertEqual(self.server.requests[0]["model"], "explicit/on-the-cli")

    def test_answers_file_still_works_unchanged_and_is_preferred_over_endpoint(self):
        """`ReplayTransport`/`--answers` must stay fully functional — the deterministic path this
        program's CI depends on — even with an (unreachable) --endpoint also given."""
        with tempfile.TemporaryDirectory() as tmp:
            plan = _set_plan()
            subject_id = plan.subjects[0].subject_id
            answer_path = Path(tmp) / "answers.json"
            answer_path.write_text(json.dumps({
                "schemaVersion": answers_mod.ANSWER_FILE_SCHEMA_VERSION, "kind": "set",
                "population": "build", "promptVersion": "x",
                "answers": {subject_id: _clean_set_answer()},
            }), encoding="utf-8")
            args = _write_args(answers=str(answer_path),
                               endpoint="http://127.0.0.1:1/v1/chat/completions",
                               out_dir=str(Path(tmp) / "out"))
            exit_code = cli_mod._cmd_items_write(args, plan=plan, tuning=TUNING, vocabulary=VOCAB)
        self.assertEqual(exit_code, cli_mod.EXIT_CLEAN)
        self.assertEqual(len(self.server.requests), 0,
                         "the answers path must never reach the network, even with --endpoint set")


if __name__ == "__main__":
    unittest.main()
