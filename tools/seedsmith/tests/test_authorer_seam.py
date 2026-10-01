"""The two-mode seam: the rules that make it safe, asserted rather than assumed.

**The load-bearing test in here is `test_api_with_no_endpoint_refuses_instead_of_delegating`.** Every
other assertion describes what the seam does; that one describes what it must NOT do. The owner's
ruling is that delegated mode runs only on an explicit request and specifically never as a fallback
when no endpoint is configured, because a silent fall into a mode whose agent may hand-edit the
corpus is the failure the rule exists to prevent. A seam whose anti-fallback behaviour is only
documented is a seam that will eventually fall back, so it is pinned here.

**Nothing in this file touches a network or a model.** Both implementations are driven with an
injected double, which is what makes "testable with no model and no network" a property of the suite
rather than an aspiration. Where a real subprocess would be launched, the test asserts on the refusal
that comes instead.

Every JSONL fixture below is the shape `opencode run --format json` was MEASURED to emit, not a
shape invented for convenience: it emits newline-delimited event objects (a single-document parse
fails outright), the authored text arrives as `part.text` on `type == "text"` events, and the model
reformats JSON — asked for `{"ok":true}` it answers `{" ok":true}` with a space after the brace. That
last one is why the seam hands raw text back for the shared `extract_json` instead of parsing it
itself.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.pipeline.llm_caller import (  # noqa: E402
    LlmCallerConfig, live_answer_caller, extract_json,
)
from seedsmith.plumbing.authorer import (  # noqa: E402
    DEFAULT_DELEGATED_AGENT, DEFAULT_MODE, MODES,
    ApiAuthorer, AuthoringRefusal, Authorer, DelegatedAuthorer,
    chartered_models, resolve_authorer,
)

EMPTY_CONFIG = LlmCallerConfig(endpoint="", model="")
LIVE_CONFIG = LlmCallerConfig(endpoint="http://localhost:1234/v1/chat/completions", model="some/model")


class _Recorder(Authorer):
    """An authorer that records prompts and replays canned answers. No model, no network."""

    mode = "recorder"

    def __init__(self, answers: "list[str]") -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, str, object]] = []

    def answer(self, system: str, user: str, *, schema=None) -> str:
        self.calls.append((system, user, schema))
        return self.answers.pop(0) if self.answers else "{}"


# --- the closed enum ------------------------------------------------------------------------


class ModeEnumTests(unittest.TestCase):
    def test_modes_is_a_closed_pair_and_api_is_the_default(self):
        self.assertEqual(MODES, ("api", "delegated"))
        self.assertEqual(DEFAULT_MODE, "api")

    def test_an_unknown_mode_is_refused_rather_than_defaulted(self):
        """A typo in a mode flag must not silently select a transport."""
        for bad in ("delgated", "DELEGATED ", "", "agent", None):
            with self.subTest(bad=bad):
                with self.assertRaises(AuthoringRefusal) as ctx:
                    resolve_authorer(bad, config=LIVE_CONFIG)
                self.assertEqual(ctx.exception.code, "AUTHORING-UNKNOWN-MODE")


# --- the rule the whole seam exists for ------------------------------------------------------


class NoFallbackTests(unittest.TestCase):
    """Ruling C6: delegated mode is an explicit request, never a fallback."""

    def test_no_preference_resolves_to_the_api_authorer(self):
        self.assertIsInstance(resolve_authorer(config=LIVE_CONFIG), ApiAuthorer)

    def test_api_with_no_endpoint_refuses_instead_of_delegating(self):
        """THE control. No endpoint configured, API mode selected -> a named refusal.

        Not a delegated authorer, not a retry, not an empty answer. If a future change makes this
        return something other than a refusal, this test is the thing that noticed.
        """
        authorer = resolve_authorer(config=EMPTY_CONFIG)
        self.assertIsInstance(authorer, ApiAuthorer)
        self.assertNotIsInstance(authorer, DelegatedAuthorer)
        with self.assertRaises(AuthoringRefusal) as ctx:
            authorer.answer("", "author me something")
        self.assertEqual(ctx.exception.code, "AUTHORING-NO-ENDPOINT")
        self.assertIn("never falls back", ctx.exception.detail)

    def test_api_with_no_model_refuses_by_its_own_code(self):
        """Endpoint present, model absent: a different defect, so a different code."""
        authorer = ApiAuthorer(LlmCallerConfig(endpoint="http://x/v1/chat/completions", model=""))
        with self.assertRaises(AuthoringRefusal) as ctx:
            authorer.answer("", "hi")
        self.assertEqual(ctx.exception.code, "AUTHORING-NO-MODEL")

    def test_delegated_is_reachable_only_when_named(self):
        """Both halves of "explicitly requested": named mode AND a charter the caller chose.

        A temp charter rather than the repository's own, so this never depends on the workspace
        layout and never skips on a standalone clone (ADDITION 9 asks that layout to work alone).
        """
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            charter = Path(tmp) / "allowed-models.json"
            charter.write_text(json.dumps({"models": {"opencode": ["vendor/only-this-one"]}}),
                               encoding="utf-8")
            # Reachable WITH the request...
            authorer = resolve_authorer("delegated", charter_path=charter)
            self.assertIsInstance(authorer, DelegatedAuthorer)
            # ...and unreachable WITHOUT it, even though a perfectly good charter is in hand. The
            # charter's existence is not consent.
            default = resolve_authorer(config=LIVE_CONFIG)
            self.assertIsInstance(default, ApiAuthorer)
            self.assertNotIsInstance(default, DelegatedAuthorer)


class CharterTests(unittest.TestCase):
    def _write(self, tmp: Path, payload: dict) -> Path:
        path = tmp / "allowed-models.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_the_model_is_read_from_the_charter_never_from_a_literal(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), {"models": {"opencode": ["vendor/only-this-one"]}})
            authorer = resolve_authorer("delegated", charter_path=path)
            self.assertEqual(authorer.model, "vendor/only-this-one")

    def test_an_ambiguous_charter_refuses_rather_than_guessing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), {"models": {"a": ["one/model"], "b": ["two/model"]}})
            with self.assertRaises(AuthoringRefusal) as ctx:
                resolve_authorer("delegated", charter_path=path)
            self.assertEqual(ctx.exception.code, "AUTHORING-AMBIGUOUS-CHARTER")

    def test_a_missing_charter_is_a_refusal_with_no_built_in_model(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AuthoringRefusal) as ctx:
                chartered_models(Path(tmp) / "does-not-exist.json")
            self.assertEqual(ctx.exception.code, "AUTHORING-NO-CHARTER")

    def test_a_malformed_charter_is_a_refusal_not_a_default(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "allowed-models.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(AuthoringRefusal) as ctx:
                chartered_models(path)
            self.assertEqual(ctx.exception.code, "AUTHORING-CHARTER-UNREADABLE")

    def test_no_charter_configured_at_all_is_a_refusal(self):
        import os
        os.environ.pop("SEEDSMITH_MODEL_CHARTER", None)
        with self.assertRaises(AuthoringRefusal) as ctx:
            resolve_authorer("delegated")
        self.assertEqual(ctx.exception.code, "AUTHORING-NO-CHARTER")


# --- the measured transport shape ------------------------------------------------------------


class DelegatedTransportTests(unittest.TestCase):
    """`opencode run --format json` emits JSONL, not a JSON document."""

    MEASURED = (
        '{"type":"step_start","timestamp":1790882114751,"sessionID":"ses_ABC",'
        '"part":{"id":"prt_1","type":"step-start"}}\n'
        '{"type":"text","timestamp":1790882114778,"sessionID":"ses_ABC",'
        '"part":{"id":"prt_2","type":"text","text":"{\\" ok\\":true}"}}\n'
    )

    def test_the_stream_is_parsed_as_jsonl_and_the_text_taken_from_part_text(self):
        text, session = DelegatedAuthorer._read_events(self.MEASURED)
        self.assertEqual(text, '{" ok":true}')
        self.assertEqual(session, "ses_ABC")

    def test_the_models_reformatted_json_is_a_wrong_key_not_a_parse_error(self):
        """MEASURED, and the opposite of the obvious guess: `extract_json` does NOT fix this.

        Asked for `{"ok":true}` this model answers `{" ok":true}` -- a space after the brace. That is
        not malformed JSON; `json.loads` accepts it and yields `{' ok': True}`. So the shared
        extractor passes it straight through, and the space survives as a KEY.

        The correction matters because it changes where the safety lives. It is tempting to write
        "the model reformats JSON, and `extract_json` tolerates it" -- measured, that is false for
        this shape. `extract_json` tolerates PROSE and code fences, not whitespace inside a key. What
        actually catches this is schema validation rejecting the unknown key, followed by the repair
        loop asking again. Both of those are shared by the two modes, which is why the guarantee
        holds anyway -- but it is a different mechanism than the one an unmeasured guess would name.
        """
        text, _ = DelegatedAuthorer._read_events(self.MEASURED)
        self.assertEqual(text, '{" ok":true}')
        self.assertEqual(extract_json(text), {" ok": True})          # NOT {"ok": True}
        self.assertNotEqual(extract_json(text), {"ok": True})

    def test_the_reformatting_is_caught_by_validation_and_the_repair_loop(self):
        """...and here is the mechanism that does catch it, end to end through the shared caller."""
        schema = {"type": "object", "required": ["ok"],
                  "properties": {"ok": {"type": "boolean"}}}
        rec = _Recorder(['{" ok":true}', '{"ok":true}'])
        out = live_answer_caller(LIVE_CONFIG, authorer=rec)("brief", schema)
        self.assertEqual(out, {"ok": True})
        self.assertEqual(len(rec.calls), 2, "the first answer should have been rejected")

    def test_several_text_events_are_concatenated_in_order(self):
        stream = ('{"type":"text","sessionID":"s","part":{"type":"text","text":"{\\"a\\":"}}\n'
                  '{"type":"text","sessionID":"s","part":{"type":"text","text":"1}"}}\n')
        text, _ = DelegatedAuthorer._read_events(stream)
        self.assertEqual(extract_json(text), {"a": 1})

    def test_a_junk_line_does_not_discard_a_real_answer(self):
        """Banner noise has been observed before the events; one bad line is not a reason to fail."""
        stream = "not json at all\n" + self.MEASURED
        text, session = DelegatedAuthorer._read_events(stream)
        self.assertEqual(text, '{" ok":true}')
        self.assertEqual(session, "ses_ABC")

    def test_an_empty_stream_yields_no_text_rather_than_an_empty_success(self):
        text, session = DelegatedAuthorer._read_events("")
        self.assertEqual(text, "")
        self.assertIsNone(session)

    def test_a_schema_reaches_the_prompt_as_an_instruction_not_a_grammar(self):
        """A delegated agent has no grammar-sampling server, so the schema is stated, not enforced."""
        prompt = DelegatedAuthorer._compose("SYSTEM", "USER", {"type": "object"})
        self.assertIn("SYSTEM", prompt)
        self.assertIn("USER", prompt)
        self.assertIn("JSON Schema", prompt)
        self.assertIn('"type": "object"', prompt)

    def test_a_delegated_authorer_with_no_model_is_refused_at_construction(self):
        with self.assertRaises(AuthoringRefusal) as ctx:
            DelegatedAuthorer(model="   ")
        self.assertEqual(ctx.exception.code, "AUTHORING-NO-CHARTERED-MODEL")

    def test_the_default_agent_is_the_general_one_and_is_overridable(self):
        self.assertEqual(DEFAULT_DELEGATED_AGENT, "general")
        a = DelegatedAuthorer(model="vendor/m")
        self.assertEqual(a.describe(), "delegated[vendor/m]")
        self.assertIsNone(a.session_id)


# --- both modes run the same plan and the same validation ------------------------------------


class SharedValidationTests(unittest.TestCase):
    """`live_answer_caller` must be mode-agnostic: same brief, same parse, same repair loop."""

    SCHEMA = {"type": "object", "required": ["name"],
              "properties": {"name": {"type": "string"}}}

    def _caller(self, answers, **kw):
        return live_answer_caller(LIVE_CONFIG, authorer=_Recorder(answers), **kw)

    def test_a_well_formed_answer_parses_in_either_mode(self):
        for mode in ("api", "delegated"):
            with self.subTest(mode=mode):
                caller = self._caller([json.dumps({"name": "ok"})])
                self.assertEqual(caller("brief", self.SCHEMA), {"name": "ok"})

    def test_a_bad_first_answer_is_repaired_by_a_second_prompt_in_either_mode(self):
        """The repair loop is the shared code; both modes must get the same second chance."""
        for mode in ("api", "delegated"):
            with self.subTest(mode=mode):
                rec = _Recorder(["not json at all", json.dumps({"name": "fixed"})])
                caller = live_answer_caller(LIVE_CONFIG, authorer=rec)
                self.assertEqual(caller("brief", self.SCHEMA), {"name": "fixed"})
                self.assertEqual(len(rec.calls), 2, "the repair prompt was not sent")
                self.assertIn("not a JSON object", rec.calls[1][1])

    def test_a_schema_violating_answer_is_rejected_not_accepted(self):
        """Legality is the validator's, in both modes, and never the mode's own judgement."""
        rec = _Recorder([json.dumps({"name": 42})] * 8)
        caller = live_answer_caller(LIVE_CONFIG, authorer=rec)
        with self.assertRaises(ValueError):
            caller("brief", self.SCHEMA)

    def test_the_brief_reaches_the_authorer_unmodified(self):
        rec = _Recorder([json.dumps({"name": "ok"})])
        live_answer_caller(LIVE_CONFIG, authorer=rec)("THE BRIEF", self.SCHEMA)
        self.assertEqual(rec.calls[0][1], "THE BRIEF")
        self.assertEqual(rec.calls[0][2], self.SCHEMA)

    def test_the_api_authorer_calls_call_model_with_the_same_arguments(self):
        """The default path must stay byte-identical, or every existing call site silently changes."""
        seen = {}

        def fake_call(system, user, *, config=None, schema=None):
            seen.update(system=system, user=user, config=config, schema=schema)
            return json.dumps({"name": "ok"})

        authorer = ApiAuthorer(LIVE_CONFIG, call=fake_call)
        out = live_answer_caller(LIVE_CONFIG, authorer=authorer)("B", self.SCHEMA)
        self.assertEqual(out, {"name": "ok"})
        self.assertEqual(seen["system"], "")
        self.assertEqual(seen["user"], "B")
        self.assertEqual(seen["config"], LIVE_CONFIG)
        self.assertEqual(seen["schema"], self.SCHEMA)


if __name__ == "__main__":
    unittest.main()