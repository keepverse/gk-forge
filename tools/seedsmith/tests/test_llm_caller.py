"""Tests for seedsmith.pipeline.llm_caller (tasks/seedsmith-todo.md, S0).

    python -m pytest gk-forge/tools/seedsmith/tests/test_llm_caller.py -v
    python gk-forge/tools/seedsmith/tests/test_llm_caller.py

Runs fully offline: every network-touching test talks only to a stdlib `http.server` spun up
in-process on `127.0.0.1`. Nothing here ever reaches `llm_caller.DEFAULT_CONFIG`'s real endpoint.
"""
from __future__ import annotations

import http.server
import json
import re
import socket
import sys
import tempfile
import threading
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.pipeline.llm_caller import (  # noqa: E402
    DEFAULT_CONFIG,
    DegenerateGenerationError,
    EmptyModelResponseError,
    LlmCallerConfig,
    call_model,
    call_with_self_heal,
    extract_json,
    live_answer_caller,
    load_config,
    resolve_live_transport,
    _has_repetition_loop,
)

LLM_CALLER_SRC = Path(__file__).resolve().parent.parent / "seedsmith" / "pipeline" / "llm_caller.py"


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
        # Streamed in small, fixed-size pieces -- exercises the real chunk-by-chunk accumulation
        # path (`_stream_once`), not a single-shot read.
        chunk_size = 4
        for i in range(0, len(content), chunk_size):
            piece = content[i:i + chunk_size]
            frame = json.dumps({"choices": [{"delta": {"content": piece}}]})
            self.wfile.write(f"data: {frame}\n\n".encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")


class MockModelServer:
    """A fake OpenAI-compatible chat endpoint: records every request body, replies with a
    scripted queue of `content` strings in order."""

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
    def requests(self) -> list[dict]:
        return self.httpd.requests  # type: ignore[attr-defined]

    def queue(self, *contents: str) -> None:
        self.httpd.responses.extend(contents)  # type: ignore[attr-defined]

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


class ReasoningDisabledTests(unittest.TestCase):
    """Every call must carry both reasoning-disable fields — different local servers/chat
    templates read different keys (spec-pipeline.md §5.1), so both are sent unconditionally."""

    def setUp(self) -> None:
        self.server = MockModelServer()
        self.config = LlmCallerConfig(endpoint=self.server.url, attempts=1, retry_delay=0)

    def tearDown(self) -> None:
        self.server.close()

    def test_reasoning_disable_fields_sent_on_every_call(self) -> None:
        self.server.queue('{"a": "1"}', '{"a": "2"}')
        call_model("sys", "user one", config=self.config)
        call_model("sys", "user two", config=self.config)

        self.assertEqual(len(self.server.requests), 2)
        for req in self.server.requests:
            self.assertEqual(req["reasoning_effort"], "none")
            self.assertEqual(
                req["chat_template_kwargs"],
                {"enable_thinking": False, "thinking": False},
            )

    def test_max_tokens_sent_on_every_call_using_the_configured_value(self) -> None:
        """⛔ Real incident, 2026-09-08: no `max_tokens` was ever sent, so a degenerate local-model
        response (a quantized model stuck repeating a short token cycle inside an unconstrained
        string field) had no upper bound short of the model's own context window — one real run
        ran past 20K tokens. This is the transport-level safety net, independent of any per-field
        schema constraint."""
        self.server.queue('{"a": "1"}')
        call_model("sys", "user", config=LlmCallerConfig(endpoint=self.server.url,
                                                          attempts=1, retry_delay=0,
                                                          max_tokens=777))
        self.assertEqual(self.server.requests[0]["max_tokens"], 777)

    def test_api_root_endpoint_is_normalized_to_chat_route(self) -> None:
        config = resolve_live_transport("http://localhost:1234/v1", "m",
                                        dotenv_path=Path("missing.env"))
        self.assertEqual(config.endpoint, "http://localhost:1234/v1/chat/completions")

    def test_call_model_returns_message_content(self) -> None:
        self.server.queue('{"hello": "world"}')
        result = call_model("sys", "user", config=self.config)
        self.assertEqual(result, '{"hello": "world"}')


class RetryExhaustionTests(unittest.TestCase):
    """No mock server here on purpose: an unreachable endpoint proves `call_model` actually
    retries `attempts` times (not just once) and then raises distinctly, rather than hanging
    or silently returning an empty result."""

    def test_raises_after_exhausting_attempts_against_an_unreachable_endpoint(self) -> None:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]
        probe.close()  # nothing listens here now; connecting refuses/times out fast

        config = LlmCallerConfig(
            endpoint=f"http://127.0.0.1:{dead_port}/v1/chat/completions",
            attempts=2, retry_delay=0, timeout=0.3,
        )
        with self.assertRaises(RuntimeError) as ctx:
            call_model("sys", "user", config=config)
        self.assertIn("2 attempts", str(ctx.exception))

    def test_empty_stream_is_a_failure_not_a_success(self) -> None:
        server = MockModelServer()
        try:
            server.queue("")
            config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)
            with self.assertRaises(RuntimeError) as ctx:
                call_model("sys", "user", config=config)
            self.assertIn("no assistant content", str(ctx.exception))
        finally:
            server.close()


class ExtractJsonTests(unittest.TestCase):
    def test_clean_json(self) -> None:
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})

    def test_fenced_json(self) -> None:
        text = '```json\n{"a": 1, "b": "two"}\n```'
        self.assertEqual(extract_json(text), {"a": 1, "b": "two"})

    def test_prose_wrapped_json(self) -> None:
        text = 'Sure, here is the result:\n{"a": 1}\nLet me know if you need anything else!'
        self.assertEqual(extract_json(text), {"a": 1})

    def test_unescaped_quote_inside_value_falls_back_to_regex(self) -> None:
        # The exact defect the docstring names: translating «the "bible"» leaves a raw
        # unescaped `"` inside a value, breaking strict json.loads.
        text = '{"a": "the "bible" thing"}'
        self.assertEqual(extract_json(text), {"a": 'the "bible" thing'})

    def test_no_json_object_raises(self) -> None:
        with self.assertRaises(ValueError):
            extract_json("no braces here at all")


class LiveAnswerCallerTests(unittest.TestCase):
    """⛔ Real gap, found 2026-09-08: `basetypegen`/`milestonegen`/`recipegen`/`droptablegen`'s own
    `main()` each explicitly refused to run a real generation — "no model call is wired into this
    CLI entrypoint yet" — despite each already declaring and testing against the exact
    `Callable[[str, dict], dict]` shape this closes. `live_answer_caller` is the missing piece,
    lifted once here rather than reimplemented per module."""

    def setUp(self) -> None:
        self.server = MockModelServer()
        self.config = LlmCallerConfig(endpoint=self.server.url, attempts=1, retry_delay=0)

    def tearDown(self) -> None:
        self.server.close()

    def test_call_sends_the_brief_as_the_user_message_with_no_separate_system_prompt(self) -> None:
        self.server.queue('{"name": "Test Widget"}')
        call = live_answer_caller(self.config)

        result = call("full brief text with embedded instructions", {})

        self.assertEqual(result, {"name": "Test Widget"})
        req = self.server.requests[0]
        self.assertEqual(req["messages"], [
            {"role": "system", "content": ""},
            {"role": "user", "content": "full brief text with embedded instructions"},
        ])

    def test_non_empty_schema_turns_on_constrained_decoding(self) -> None:
        self.server.queue('{"name": "Test Widget"}')
        call = live_answer_caller(self.config)
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}

        call("brief", schema)

        self.assertIn("response_format", self.server.requests[0])

    def test_empty_schema_sends_no_response_format(self) -> None:
        """An empty `{}` schema (a module that hasn't opted into constrained decoding) must not
        turn into a request for an empty-object-shaped response — `schema or None` treats it the
        same as no schema at all, matching `call_model`'s own `schema=None` contract."""
        self.server.queue('{"name": "Test Widget"}')
        call = live_answer_caller(self.config)

        call("brief", {})

        self.assertNotIn("response_format", self.server.requests[0])

    def test_prose_wrapped_answer_is_still_parsed(self) -> None:
        self.server.queue('Here you go:\n```json\n{"name": "Test Widget"}\n```')
        call = live_answer_caller(self.config)
        self.assertEqual(call("brief", {}), {"name": "Test Widget"})

    def test_non_json_answer_gets_one_explicit_json_repair_prompt(self) -> None:
        self.server.queue("I cannot provide that format.")
        self.server.queue('{"name": "Repaired Widget"}')
        call = live_answer_caller(self.config)

        self.assertEqual(call("brief", {}), {"name": "Repaired Widget"})
        self.assertEqual(len(self.server.requests), 2)
        self.assertIn("not a JSON object", self.server.requests[1]["messages"][1]["content"])
        self.assertIn("Original authoring brief:\nbrief",
                      self.server.requests[1]["messages"][1]["content"])

    def test_blocked_answer_passes_through_as_a_plain_field(self) -> None:
        """`{"blocked": "..."}` is not special to this function — it is just another field the
        caller (`run_draws`) itself interprets; this proves it survives the round trip unchanged."""
        self.server.queue('{"blocked": "no theme fits"}')
        call = live_answer_caller(self.config)
        self.assertEqual(call("brief", {}), {"blocked": "no theme fits"})

    def test_validator_defect_gets_one_named_repair_prompt(self) -> None:
        """Endpoint-side strict mode is advisory; the local validator owns acceptance."""
        self.server.queue('{"blocked": true}', '{"blocked": "no legal family fits"}')

        def validate(answer: dict, _schema: dict) -> list[str]:
            if answer.get("blocked") is True:
                return ["field 'blocked' should be string"]
            return []

        call = live_answer_caller(self.config, validator=validate)
        self.assertEqual(call("brief", {"type": "object"}),
                         {"blocked": "no legal family fits"})
        self.assertEqual(len(self.server.requests), 2)
        repair = self.server.requests[1]["messages"][1]["content"]
        self.assertIn("failed local validation", repair)
        self.assertIn("field 'blocked' should be string", repair)

    def test_schema_type_violation_gets_one_named_repair_prompt_without_adapter_help(self) -> None:
        """The transport boundary catches a server that ignores `strict` response formatting."""
        self.server.queue('{"blocked": true}', '{"blocked": "no legal family fits"}')
        schema = {"type": "object", "properties": {"blocked": {"type": "string"}}}

        call = live_answer_caller(self.config)
        self.assertEqual(call("brief", schema), {"blocked": "no legal family fits"})
        self.assertEqual(len(self.server.requests), 2)
        self.assertIn("field 'blocked' should be string",
                      self.server.requests[1]["messages"][1]["content"])


class SelfHealTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = MockModelServer()
        self.config = LlmCallerConfig(endpoint=self.server.url, attempts=1, retry_delay=0,
                                      max_heal=2)

    def tearDown(self) -> None:
        self.server.close()

    @staticmethod
    def _verify_k_equals_good(items: dict, out: dict) -> tuple[dict, dict]:
        if out.get("k") == "GOOD":
            return {}, {}
        return {"k": "must equal GOOD"}, {}

    def test_retry_reprompts_with_named_defect_and_accepts_the_fix(self) -> None:
        self.server.queue('{"k": "bad"}', '{"k": "GOOD"}')

        out, soft = call_with_self_heal(
            items={"k": "orig"},
            system="sys",
            build_user=lambda items: json.dumps(items),
            verify_fn=self._verify_k_equals_good,
            config=self.config,
        )

        self.assertEqual(out, {"k": "GOOD"})
        self.assertEqual(soft, {})
        self.assertEqual(len(self.server.requests), 2)
        # the second call's re-prompt must name the exact defect, not a generic retry
        heal_prompt = self.server.requests[1]["messages"][1]["content"]
        self.assertIn("must equal GOOD", heal_prompt)

    def test_exhausted_heal_falls_back_to_default_and_reports_failure(self) -> None:
        # max_heal=2 -> 3 total attempts; none of these ever satisfy verify_fn
        self.server.queue('{"k": "x1"}', '{"k": "x2"}', '{"k": "x3"}')

        out, soft = call_with_self_heal(
            items={"k": "orig"},
            system="sys",
            build_user=lambda items: json.dumps(items),
            verify_fn=lambda items, out: ({"k": "never satisfied"}, {}),
            config=self.config,
        )

        self.assertEqual(len(self.server.requests), 3)
        self.assertEqual(out["k"], "orig")  # no-silent-drop: falls back to the source value
        self.assertTrue(soft["k"].startswith("FAILED:"))

    def test_custom_default_for_is_honored(self) -> None:
        self.server.queue('{"k": "x1"}', '{"k": "x2"}', '{"k": "x3"}')

        out, soft = call_with_self_heal(
            items={"k": "orig"},
            system="sys",
            build_user=lambda items: json.dumps(items),
            verify_fn=lambda items, out: ({"k": "never satisfied"}, {}),
            config=self.config,
            default_for=lambda key, original: "SENTINEL",
        )

        self.assertEqual(out["k"], "SENTINEL")
        self.assertTrue(soft["k"].startswith("FAILED:"))

    def test_unparseable_output_is_treated_as_a_named_defect_not_a_crash(self) -> None:
        self.server.queue("not json at all", '{"k": "GOOD"}')

        out, soft = call_with_self_heal(
            items={"k": "orig"},
            system="sys",
            build_user=lambda items: json.dumps(items),
            verify_fn=self._verify_k_equals_good,
            config=self.config,
        )

        self.assertEqual(out, {"k": "GOOD"})
        self.assertEqual(len(self.server.requests), 2)


class LoadConfigTests(unittest.TestCase):
    """`load_config`'s default `dotenv_path` (`Path(".env")`, CWD-relative) means a real `.env`
    sitting in `gk-forge/tools/seedsmith/` — the one this project's own `.env.example` documents creating
    — silently leaks into any test that doesn't isolate it (found live: a real `.env` copied from
    the template broke `test_overrides_only_the_keys_present` by out-ranking its TOML value).
    Every test here passes an explicit, guaranteed-absent `dotenv_path` for that reason — this is
    NOT optional cleanup, it is what makes these tests hermetic regardless of the developer's
    working tree.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.no_dotenv = self.tmp / "no-such.env"  # never written by any test in this class

    def test_defaults_when_file_absent(self) -> None:
        missing = self.tmp / "does-not-exist.toml"
        self.assertEqual(load_config(missing, dotenv_path=self.no_dotenv), DEFAULT_CONFIG)

    def test_defaults_when_section_absent(self) -> None:
        path = self.tmp / "seedsmith.toml"
        path.write_text('[adapter]\nname = "items"\n', encoding="utf-8")
        self.assertEqual(load_config(path, dotenv_path=self.no_dotenv), DEFAULT_CONFIG)

    def test_overrides_only_the_keys_present(self) -> None:
        path = self.tmp / "seedsmith.toml"
        path.write_text(
            '[pipeline.llm_caller]\n'
            'endpoint = "http://127.0.0.1:9999/v1/chat/completions"\n'
            'max_heal = 5\n',
            encoding="utf-8",
        )
        cfg = load_config(path, dotenv_path=self.no_dotenv)
        self.assertEqual(cfg.endpoint, "http://127.0.0.1:9999/v1/chat/completions")
        self.assertEqual(cfg.max_heal, 5)
        # everything NOT set in the file falls back to the default, not to zero/None
        self.assertEqual(cfg.model, DEFAULT_CONFIG.model)
        self.assertEqual(cfg.attempts, DEFAULT_CONFIG.attempts)

    def test_max_tokens_overridable_from_toml_and_dotenv(self) -> None:
        toml_path = self.tmp / "seedsmith.toml"
        toml_path.write_text('[pipeline.llm_caller]\nmax_tokens = 2048\n', encoding="utf-8")
        cfg = load_config(toml_path, dotenv_path=self.no_dotenv)
        self.assertEqual(cfg.max_tokens, 2048)

        dotenv_path = self.tmp / ".env"
        dotenv_path.write_text("SEEDSMITH_LLM_MAX_TOKENS=512\n", encoding="utf-8")
        cfg = load_config(toml_path, dotenv_path=dotenv_path)
        self.assertEqual(cfg.max_tokens, 512)  # .env wins over toml, same as every other key

    def test_malformed_toml_raises_rather_than_silently_defaulting(self) -> None:
        path = self.tmp / "seedsmith.toml"
        path.write_text("this is not [valid toml", encoding="utf-8")
        with self.assertRaises(tomllib.TOMLDecodeError):
            load_config(path, dotenv_path=self.no_dotenv)

    def test_dotenv_absent_falls_through_to_toml_and_defaults(self) -> None:
        toml_path = self.tmp / "seedsmith.toml"
        toml_path.write_text('[pipeline.llm_caller]\nmax_heal = 5\n', encoding="utf-8")
        cfg = load_config(toml_path, dotenv_path=self.tmp / "no-such.env")
        self.assertEqual(cfg.max_heal, 5)
        self.assertEqual(cfg.endpoint, DEFAULT_CONFIG.endpoint)

    def test_dotenv_overrides_toml_which_overrides_default(self) -> None:
        toml_path = self.tmp / "seedsmith.toml"
        toml_path.write_text(
            '[pipeline.llm_caller]\n'
            'endpoint = "http://toml-only:1234/v1/chat/completions"\n'
            'max_heal = 5\n',
            encoding="utf-8")
        dotenv_path = self.tmp / ".env"
        dotenv_path.write_text(
            "# a comment, and a blank line above are both ignored\n"
            "SEEDSMITH_LLM_ENDPOINT=http://dotenv-wins:9999/v1/chat/completions\n"
            "SEEDSMITH_LLM_TIMEOUT=99\n",
            encoding="utf-8")
        cfg = load_config(toml_path, dotenv_path=dotenv_path)
        self.assertEqual(cfg.endpoint, "http://dotenv-wins:9999/v1/chat/completions")  # .env wins
        self.assertEqual(cfg.timeout, 99.0)                                            # .env-only key
        self.assertEqual(cfg.max_heal, 5)                                              # toml-only key, untouched

    def test_dotenv_blank_value_does_not_override(self) -> None:
        """`KEY=` with nothing after it is not a real override — matching a real `.env.example`
        left uncommented-but-unfilled by a user who copied the template."""
        dotenv_path = self.tmp / ".env"
        dotenv_path.write_text("SEEDSMITH_LLM_MODEL=\n", encoding="utf-8")
        cfg = load_config(self.tmp / "no-such.toml", dotenv_path=dotenv_path)
        self.assertEqual(cfg.model, DEFAULT_CONFIG.model)


class LateConfigResolutionTests(unittest.TestCase):
    """NS3 (spec-model-config-resolve §3.1): `call_model` / `call_with_self_heal` default to
    `config=None` and resolve through `load_config()` at call time, so a caller that omits
    `config` still honors the operator's `.env` — the defect was a parameter default bound to
    `DEFAULT_CONFIG`, which snapshotted the built-in model at import time and silently dropped
    every per-machine override."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env_path = Path(self.tmp.name) / ".env"
        # The endpoint is planted too, and deliberately so: these tests are about LATE config
        # resolution (the model must come from `.env` at call time, not from a snapshot taken at
        # import), and with no endpoint planted the call now refuses with AUTHORING-NO-ENDPOINT
        # before `_stream_once` is reached. Previously they passed only because the built-in
        # default was a routable localhost address, which meant a test whose subject was config
        # resolution also depended on whatever was listening on that port.
        env_path.write_text(
            "SEEDSMITH_LLM_MODEL=hermetic-env-model\n"
            "SEEDSMITH_LLM_ENDPOINT=http://hermetic.invalid/v1/chat/completions\n",
            encoding="utf-8")
        self.dotenv_path = env_path

    def test_call_model_resolves_env_when_config_omitted(self) -> None:
        seen: list[LlmCallerConfig] = []

        def fake_stream(config: LlmCallerConfig, body: bytes) -> str:
            seen.append(config)
            return '{"ok": "yes"}'

        with patch("seedsmith.pipeline.llm_caller.resolve_dotenv_path",
                   return_value=self.dotenv_path), \
             patch("seedsmith.pipeline.llm_caller._stream_once", side_effect=fake_stream):
            result = call_model("sys", "user")

        self.assertEqual(result, '{"ok": "yes"}')
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].model, "hermetic-env-model")

    def test_call_with_self_heal_resolves_env_when_config_omitted(self) -> None:
        seen: list[LlmCallerConfig] = []

        def fake_stream(config: LlmCallerConfig, body: bytes) -> str:
            seen.append(config)
            return '{"k": "GOOD"}'

        with patch("seedsmith.pipeline.llm_caller.resolve_dotenv_path",
                   return_value=self.dotenv_path), \
             patch("seedsmith.pipeline.llm_caller._stream_once", side_effect=fake_stream):
            out, soft = call_with_self_heal(
                items={"k": "orig"},
                system="sys",
                build_user=lambda items: json.dumps(items),
                verify_fn=lambda items, out: ({}, {}),
            )

        self.assertEqual(out, {"k": "GOOD"})
        self.assertEqual(soft, {})
        self.assertEqual(seen[0].model, "hermetic-env-model")

    def test_explicit_config_still_wins_over_the_env(self) -> None:
        """Passing a config is unchanged behaviour — late resolution applies only to `None`."""
        server = MockModelServer()
        self.addCleanup(server.close)
        server.queue('{"ok": "yes"}')
        config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0,
                                 model="explicit-model")
        with patch("seedsmith.pipeline.llm_caller.resolve_dotenv_path",
                   return_value=self.dotenv_path):
            call_model("sys", "user", config=config)
        self.assertEqual(server.requests[0]["model"], "explicit-model")


class RepetitionLoopDetectorTests(unittest.TestCase):
    """Pure unit tests for `_has_repetition_loop` — no network, no model, just the string
    heuristic that lets `_stream_once` abort a degenerate generation in real time (2026-09-08
    incident: a ~50-char unit repeated hundreds of times inside a `nameKey` string value)."""

    def test_short_unit_repeated_past_the_threshold_is_detected(self) -> None:
        self.assertTrue(_has_repetition_loop("abc" * 8))

    def test_longer_unit_near_max_period_is_still_detected(self) -> None:
        unit = "".join(f"tok{i:02d}-" for i in range(10))  # 50 chars, well under max_period=80
        self.assertTrue(_has_repetition_loop(unit * 6))

    def test_unit_repeated_exactly_min_repeats_times_is_detected(self) -> None:
        self.assertTrue(_has_repetition_loop("xy" * 6, min_repeats=6))

    def test_unit_repeated_one_fewer_than_min_repeats_is_not_detected(self) -> None:
        self.assertFalse(_has_repetition_loop("xy" * 5, min_repeats=6))

    def test_unit_wider_than_max_period_is_not_detected(self) -> None:
        # 81 non-repeating characters (no internal period <= 80), repeated 6 times: the detector
        # only searches periods up to `max_period` (80), so this real repeat must slip through.
        unit = "".join(f"{i:02d}-" for i in range(27))  # 81 chars, no internal period <= 80
        self.assertEqual(len(unit), 81)
        self.assertFalse(_has_repetition_loop(unit * 6, max_period=80))

    def test_legitimate_non_repeating_text_is_not_a_false_positive(self) -> None:
        text = ("The frost-bound sentinel guards the eastern vault, its runes flickering with "
                "each passing hour as the creature host gathers beyond the tree line.")
        self.assertFalse(_has_repetition_loop(text))

    def test_text_shorter_than_the_smallest_detection_window_is_not_a_false_positive(self) -> None:
        self.assertFalse(_has_repetition_loop("ab"))

    def test_only_the_trailing_tail_is_examined(self) -> None:
        """A repetition loop buried earlier in the text but NOT at the very end (e.g. one that
        already self-corrected) must not still trip the detector — only what is CURRENTLY
        happening at the tail matters, matching how `_stream_once` calls this after every chunk
        on a live, still-growing response."""
        text = ("ab" * 20) + ("legitimate closing prose that does not repeat at all here")
        self.assertFalse(_has_repetition_loop(text, tail=400))

    def test_repetition_confined_outside_the_tail_window_is_not_detected(self) -> None:
        old_loop = "zq" * 20
        fresh_text = "The ward held through the night watch entirely without incident at all."
        combined = old_loop + fresh_text
        self.assertFalse(_has_repetition_loop(combined, tail=len(fresh_text)))


class DegenerateGenerationAbortTests(unittest.TestCase):
    """Integration proof (via the real SSE-streaming `MockModelServer`) that a genuinely
    repeating response is caught mid-stream and turned into a raised error, rather than being
    accepted as a normal — if garbage — result. This is the regression test for the 2026-09-08
    incident: before `_stream_once`/`_has_repetition_loop` existed, `call_model` had no way to
    distinguish this from a slow-but-legitimate long answer and would return the whole repeated
    blob after burning the full `max_tokens` budget."""

    def setUp(self) -> None:
        self.server = MockModelServer()

    def tearDown(self) -> None:
        self.server.close()

    def test_call_model_raises_after_exhausting_attempts_on_a_repeating_response(self) -> None:
        garbage = "AbC12-" * 500  # a 6-char unit, hundreds of repeats -- the incident's own shape
        self.server.queue(garbage, garbage)
        config = LlmCallerConfig(endpoint=self.server.url, attempts=2, retry_delay=0)

        with self.assertRaises(RuntimeError) as ctx:
            call_model("sys", "user", config=config)
        self.assertIn("2 attempts", str(ctx.exception))

    def test_a_well_formed_non_repeating_response_is_unaffected(self) -> None:
        """The detector must not be so trigger-happy that it breaks the ordinary path — a normal
        JSON answer streamed in 4-char chunks (the mock's own chunking) must still come back
        whole and unmodified."""
        self.server.queue('{"name": "Frozen Barrier", "flavor": "A ward of ancient ice."}')
        config = LlmCallerConfig(endpoint=self.server.url, attempts=1, retry_delay=0)

        result = call_model("sys", "user", config=config)

        self.assertEqual(result, '{"name": "Frozen Barrier", "flavor": "A ward of ancient ice."}')


class DependencyIsolationTests(unittest.TestCase):
    """S0's whole reason for being a Phase-0, dependency-free slice: it must not import
    anything from the corpus/adapter/metrics chain. Enforced mechanically, not by prose,
    mirroring this repo's guard-secondary-no-unity.ps1 discipline for the C# side."""

    def test_no_import_from_corpus_adapters_or_metrics(self) -> None:
        source = LLM_CALLER_SRC.read_text(encoding="utf-8")
        forbidden = re.compile(
            r"^\s*(from\s+seedsmith\.(corpus|adapters|metrics)\b|"
            r"import\s+seedsmith\.(corpus|adapters|metrics)\b)",
            re.MULTILINE,
        )
        match = forbidden.search(source)
        self.assertIsNone(
            match,
            f"llm_caller.py must not depend on corpus/adapters/metrics, found: {match}",
        )


if __name__ == "__main__":
    unittest.main()


# ---- G0.3: constrained decoding (spec-dependency-baseline.md §2.4) -----------------------------


class ConstrainedDecodingTests(unittest.TestCase):
    """`schema` is optional and must be INERT when unused — the acceptance criterion that matters
    most, because every existing caller relies on today's body shape."""

    def setUp(self) -> None:
        self.server = MockModelServer()
        self.config = LlmCallerConfig(endpoint=self.server.url, attempts=1, retry_delay=0)

    def tearDown(self) -> None:
        self.server.close()

    def test_schema_none_produces_a_body_with_no_response_format_key(self) -> None:
        """Provably inert: omitting `schema` must not add anything to the request."""
        self.server.queue('{"a": "1"}')
        call_model("sys", "user", config=self.config)
        self.assertNotIn("response_format", self.server.requests[0])

    def test_schema_none_body_is_byte_identical_to_explicitly_passing_none(self) -> None:
        self.server.queue('{"a": "1"}', '{"a": "2"}')
        call_model("sys", "user", config=self.config)
        call_model("sys", "user", config=self.config, schema=None)
        self.assertEqual(self.server.requests[0], self.server.requests[1])

    def test_a_schema_is_sent_as_openai_style_json_schema_response_format(self) -> None:
        schema = {"type": "object", "properties": {"label": {"type": "string"}},
                  "required": ["label"], "additionalProperties": False}
        self.server.queue('{"label": "nut"}')
        call_model("sys", "user", config=self.config, schema=schema)

        rf = self.server.requests[0]["response_format"]
        self.assertEqual(rf["type"], "json_schema")
        self.assertTrue(rf["json_schema"]["strict"])
        self.assertEqual(rf["json_schema"]["schema"], schema)

    def test_reasoning_disable_fields_survive_alongside_a_schema(self) -> None:
        """Constrained decoding must not silently drop the reasoning-disable contract."""
        self.server.queue('{"label": "x"}')
        call_model("sys", "u", config=self.config, schema={"type": "object"})
        req = self.server.requests[0]
        self.assertEqual(req["reasoning_effort"], "none")
        self.assertEqual(req["chat_template_kwargs"], {"enable_thinking": False, "thinking": False})

    def test_extract_json_is_still_available_as_defense_in_depth(self) -> None:
        """Constrained decoding does not replace the fallback — schema behaviour is not guaranteed
        portable across serving implementations (JSON Schema does not specify whitespace)."""
        self.assertEqual(extract_json('```json\n{"a": "1"}\n```'), {"a": "1"})
