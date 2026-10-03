"""Mode plumbing: the operator's request must REACH the authoring call.

The seam in `plumbing/authorer.py` is only an implementation if something can select it.
These tests pin the whole path, and each is written so it fails for the right reason:

    CLI/`--mode`  ->  `resolve_live_transport(cli_mode=...)`
                  ->  `LlmCallerConfig.mode`      (flows to all 46 config-threading sites)
                  ->  `call_model` dispatch        (the one place WHO answers is decided)
                  ->  `live_answer_caller`         (which resolved straight to DEFAULT_MODE)

Every test runs with NO model and NO network: the seam is reached through an injected
authorer, or through a monkeypatched `resolve_authorer`, never by launching anything.
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from seedsmith.pipeline import llm_caller
from seedsmith.pipeline.llm_caller import (
    DEFAULT_CONFIG,
    LlmCallerConfig,
    call_model,
    live_answer_caller,
    load_config,
    resolve_live_transport,
)
from seedsmith.plumbing import authorer as authorer_mod
from seedsmith.plumbing.authorer import (
    DEFAULT_MODE,
    MODES,
    ApiAuthorer,
    AuthoringRefusal,
    _describe_exit,
    _describe_oserror,
    resolve_authorer,
)


class _Fake:  # noqa: N801 - a test double, deliberately not an Authorer subclass
    """Stands in for an Authorer. Records what it was asked, answers a fixed string.

    Not a subclass on purpose: `resolve_authorer` returns real `ApiAuthorer`/`DelegatedAuthorer`
    objects and callers only ever need `.answer(...)`, so inheriting would assert a relationship
    that does not hold. An earlier version of this line read
    `class _Fake(llm_caller.LlmCallerConfig if False else object)` — the conditional meant nothing
    could ever be selected, and it was dead code in a test file.
    """

    mode = "fake"

    def __init__(self, text: str = '{"ok": true}') -> None:
        self.text = text
        self.calls: list[tuple[str, str, object]] = []

    def answer(self, system: str, user: str, *, schema=None) -> str:
        self.calls.append((system, user, schema))
        return self.text


# --- the closed pair, and no drift between the two homes of the default ----------------


class DefaultModeTests(unittest.TestCase):
    def test_the_config_default_and_the_seam_default_are_the_same_value(self):
        """They are spelled in two modules because of an import cycle; they must not drift.

        `plumbing/authorer.py` imports this module (`ApiAuthorer.answer` calls `call_model`),
        so the config cannot import `DEFAULT_MODE` back at module scope. This assertion is the
        thing that notices if someone changes one and not the other.
        """
        self.assertEqual(DEFAULT_CONFIG.mode, DEFAULT_MODE)
        self.assertEqual(load_config().mode, DEFAULT_MODE)

    def test_a_fresh_config_is_api_with_no_env_and_no_toml(self, ):
        self.assertEqual(LlmCallerConfig().mode, "api")

    def test_modes_is_a_closed_pair(self):
        self.assertEqual(MODES, ("api", "delegated"))


# --- call_model is the dispatch point ---------------------------------------------------


class CallModelDispatchTests(unittest.TestCase):
    def test_a_delegated_config_is_answered_through_the_seam_not_the_endpoint(self):
        """THE test. A delegated request must not reach the HTTP path at all."""
        fake = _Fake('{"authored": "by an agent"}')
        cfg = LlmCallerConfig(mode="delegated", endpoint="http://127.0.0.1:1/never")
        with mock.patch.object(authorer_mod, "resolve_authorer", return_value=fake) as seam:
            out = call_model("sys", "user", config=cfg, schema={"type": "object"})
        self.assertEqual(out, '{"authored": "by an agent"}')
        self.assertEqual(seam.call_count, 1, "call_model must resolve through the seam in delegated mode")
        self.assertEqual(seam.call_args.args[0], "delegated")
        # and the prompt reached the seam intact, schema included
        self.assertEqual(fake.calls, [("sys", "user", {"type": "object"})])

    def test_api_mode_never_touches_the_seam(self):
        """API mode keeps its own streaming endpoint; the seam is not consulted."""
        with mock.patch.object(authorer_mod, "resolve_authorer") as seam:
            with self.assertRaises(Exception) as ctx:
                # endpoint is unroutable on purpose; the point is WHICH path was taken
                call_model("sys", "user", config=LlmCallerConfig(mode="api", endpoint="http://127.0.0.1:1/x"))
        seam.assert_not_called()
        self.assertNotIsInstance(ctx.exception, AuthoringRefusal)

    def test_an_unknown_mode_is_refused_and_reaches_neither_transport(self):
        """C6 fail-closed: a typo must not select a transport, and must not become api either."""
        with mock.patch.object(authorer_mod, "resolve_authorer") as seam:
            with self.assertRaises(AuthoringRefusal) as ctx:
                call_model("sys", "user", config=LlmCallerConfig(mode="DELEGATED "))
        self.assertEqual(ctx.exception.code, "AUTHORING-UNKNOWN-MODE")
        seam.assert_not_called()

    def test_a_whitespace_padded_mode_is_normalised_not_rejected(self):
        """`.env` values arrive with whatever spacing the operator typed."""
        fake = _Fake("{}")
        with mock.patch.object(authorer_mod, "resolve_authorer", return_value=fake):
            out = call_model("sys", "user", config=LlmCallerConfig(mode=" delegated "))
        self.assertEqual(out, "{}")


# --- live_answer_caller resolved straight to DEFAULT_MODE, ignoring the config -----------


class LiveAnswerCallerModeTests(unittest.TestCase):
    """This is the defect these tests exist for.

    `live_answer_caller` used to do `mode if mode is not None else DEFAULT_MODE`, so a config
    carrying `mode="delegated"` was still answered by the API: the operator asked for a
    delegated agent and silently got the endpoint instead. Precedence is now
    argument -> config -> default.
    """

    def test_a_delegated_config_is_honoured_without_an_explicit_mode_argument(self):
        fake = _Fake('{"ok": 1}')
        cfg = LlmCallerConfig(mode="delegated")
        with mock.patch.object(authorer_mod, "resolve_authorer", return_value=fake) as seam:
            call = live_answer_caller(cfg, validator=None)
        self.assertEqual(seam.call_args.args[0], "delegated")
        self.assertEqual(call("brief", {"type": "object"}), {"ok": 1})

    def test_an_explicit_mode_argument_beats_the_config(self):
        fake = _Fake("{}")
        cfg = LlmCallerConfig(mode="api")
        with mock.patch.object(authorer_mod, "resolve_authorer", return_value=fake) as seam:
            live_answer_caller(cfg, mode="delegated", validator=None)
        self.assertEqual(seam.call_args.args[0], "delegated")

    def test_an_injected_authorer_wins_over_both(self):
        """Tests (and the delegated runner) can pin an authorer without touching config."""
        fake = _Fake('{"pinned": true}')
        call = live_answer_caller(LlmCallerConfig(mode="api"), authorer=fake, validator=None)
        self.assertEqual(call("brief", {}), {"pinned": True})


# --- the operator's three request channels ----------------------------------------------


class RequestChannelTests(unittest.TestCase):
    def test_cli_mode_reaches_the_config(self):
        cfg = resolve_live_transport("", "", cli_mode="delegated",
                                    dotenv_path=Path("nonexistent.env"))
        self.assertEqual(cfg.mode, "delegated")

    def test_an_empty_cli_mode_falls_through_to_the_default(self):
        cfg = resolve_live_transport("", "", cli_mode="",
                                    dotenv_path=Path("nonexistent.env"))
        self.assertEqual(cfg.mode, "api")

    def test_an_unknown_cli_mode_is_refused_at_resolution_time(self):
        with self.assertRaises(AuthoringRefusal) as ctx:
            resolve_live_transport("", "", cli_mode="agent",
                                   dotenv_path=Path("nonexistent.env"))
        self.assertEqual(ctx.exception.code, "AUTHORING-UNKNOWN-MODE")

    def test_dotenv_mode_is_read_and_beats_the_default(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("SEEDSMITH_LLM_MODE=delegated\n", encoding="utf-8")
            cfg = resolve_live_transport("", "", dotenv_path=env)
        self.assertEqual(cfg.mode, "delegated")

    def test_toml_mode_is_read(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            toml = Path(tmp) / "seedsmith.toml"
            toml.write_text("[pipeline.llm_caller]\nmode = \"delegated\"\n", encoding="utf-8")
            cfg = resolve_live_transport("", "", toml_path=toml,
                                        dotenv_path=Path(tmp) / "nope.env")
        self.assertEqual(cfg.mode, "delegated")

    def test_a_dataclass_replace_preserves_the_mode(self):
        """`resolve_live_transport` rebuilds via `dataclasses.replace`; a forgotten field here
        would silently drop the operator's request while keeping endpoint and model."""
        base = LlmCallerConfig(mode="delegated")
        moved = dataclasses.replace(base, endpoint="http://x", model="m")
        self.assertEqual(moved.mode, "delegated")


# --- no implicit trigger ----------------------------------------------------------------


class NoImplicitTriggerTests(unittest.TestCase):
    """C6: nothing infers delegated mode. These are the shapes that would do it."""

    def test_a_missing_endpoint_does_not_select_delegated_mode(self):
        with mock.patch.object(authorer_mod, "resolve_authorer") as seam:
            with self.assertRaises(Exception):
                call_model("sys", "user", config=LlmCallerConfig(mode="api", endpoint=""))
        seam.assert_not_called()

    def test_an_unreachable_endpoint_does_not_select_delegated_mode(self):
        with mock.patch.object(authorer_mod, "resolve_authorer") as seam:
            with self.assertRaises(Exception):
                call_model("sys", "user",
                           config=LlmCallerConfig(mode="api", endpoint="http://127.0.0.1:1/x"))
        seam.assert_not_called()

    def test_an_empty_config_object_is_api(self):
        """An unset mode takes the safe direction (api), never the corpus-editing one.

        The endpoint is pinned dead because `LlmCallerConfig`'s endpoint default is now `""` - which
        refuses with AUTHORING-NO-ENDPOINT before any transport is chosen, so this test is really
        about the MODE, and pinning the endpoint keeps the refusal independent of that. An earlier
        version of this docstring justified the pinning by the default being a REAL routable
        address; that was true when written and stopped being true in the same session, and a
        comment stating a deleted fact as current is its own kind of wrong.
        """
        with mock.patch.object(authorer_mod, "resolve_authorer") as seam:
            # An unset mode must not select a transport. What it DOES here is attempt the API path
            # against a dead endpoint and fail there — so the assertion is the absence of the seam
            # call, not a particular exception. An earlier version of this test expected
            # AUTHORING-NO-ENDPOINT, which was wrong twice over: that refusal needs an EMPTY endpoint,
            # and this test pins a non-empty one. Asserting a code the code path cannot produce is
            # how a test ends up pinning an accident.
            with self.assertRaises(Exception) as ctx:
                call_model("sys", "user",
                           config=LlmCallerConfig(mode="", endpoint="http://127.0.0.1:1/x"))
        self.assertNotIsInstance(ctx.exception, AuthoringRefusal,
                                 "an unset mode must not be refused as an unknown mode either")
        seam.assert_not_called()


# --- the seam's decision must survive the trip down to call_model -----------------------


class SeamDecisionIsAuthoritativeTests(unittest.TestCase):
    """The inversion an audit found, and the mutation that fixed it passed BOTH suites green.

    `ApiAuthorer.answer` calls `llm_caller.call_model`, and `call_model` dispatches on
    `config.mode`. So `resolve_authorer("api", config=<mode=delegated>)` used to build an
    ApiAuthorer which then re-dispatched and delegated anyway — the seam asked for api, the
    transport answered with a sub-agent. Nothing tested it. Latent (no call site passes `mode=`),
    and latent is how this becomes live.
    """

    def test_api_authorer_pins_api_on_the_config_it_hands_down(self):
        seen: dict = {}

        def fake_call(system, user, *, config=None, schema=None):
            seen["mode"] = getattr(config, "mode", "<absent>")
            return "answer"

        authorer = ApiAuthorer(LlmCallerConfig(mode="delegated", endpoint="http://127.0.0.1:1/x"),
                               call=fake_call)
        self.assertEqual(authorer.answer("s", "u"), "answer")
        self.assertEqual(seen["mode"], "api",
                         "ApiAuthorer must hand call_model an api config, whatever its own config says")

    def test_the_inversion_is_reachable_through_live_answer_caller(self):
        """The same trap one layer up, which is how an operator would actually hit it."""
        seen: dict = {}

        def fake_call(system, user, *, config=None, schema=None):
            seen["mode"] = getattr(config, "mode", "<absent>")
            return '{"ok": true}'

        call = live_answer_caller(LlmCallerConfig(mode="delegated", endpoint="http://127.0.0.1:1/x"),
                                  mode="api", authorer=ApiAuthorer(
                                      LlmCallerConfig(mode="delegated",
                                                      endpoint="http://127.0.0.1:1/x"),
                                      call=fake_call),
                                  validator=None)
        self.assertEqual(call("brief", {}), {"ok": True})
        self.assertEqual(seen["mode"], "api")


# --- no routable default endpoint -------------------------------------------------------


class NoRoutableDefaultTests(unittest.TestCase):
    """Owner ruling 2026-10-03, after a test answered from a live model instead of raising."""

    def test_the_built_in_endpoint_is_empty(self):
        self.assertEqual(LlmCallerConfig().endpoint, "",
                         "a routable built-in endpoint lets an unconfigured run reach a live model")

    def test_api_mode_with_no_endpoint_is_a_named_refusal_not_a_connection_error(self):
        with self.assertRaises(AuthoringRefusal) as ctx:
            call_model("sys", "user", config=LlmCallerConfig(mode="api", endpoint=""))
        self.assertEqual(ctx.exception.code, "AUTHORING-NO-ENDPOINT")

    def test_the_refusal_names_how_to_configure_an_endpoint(self):
        with self.assertRaises(AuthoringRefusal) as ctx:
            call_model("sys", "user", config=LlmCallerConfig(mode="api"))
        self.assertIn("SEEDSMITH_LLM_ENDPOINT", ctx.exception.detail)

    def test_api_mode_with_an_endpoint_configured_still_reaches_the_transport(self):
        """The refusal must not swallow a legitimately configured call."""
        import unittest.mock as m
        with m.patch.object(llm_caller, "_stream_once", return_value='{"k": "v"}') as stream:
            out = call_model("sys", "user",
                             config=LlmCallerConfig(mode="api",
                                                    endpoint="http://127.0.0.1:1/x"))
        self.assertEqual(out, '{"k": "v"}')
        self.assertEqual(stream.call_count, 1)


# --- the CLI flag must reach nested subcommands -----------------------------------------


# --- an exit code that IS the diagnosis must say so --------------------------------------


class ExitCodeIsDiagnosedTests(unittest.TestCase):
    """Measured 2026-10-03 on the 904-species delegated run.

    16 concurrent agents produced 35 failures, 15 of them `exited 3221226505` with NO stderr. That
    message is true and useless: it reads like a flaky model, and it is a page-file ceiling. The
    whole cost of that misreading was a misattribution - the failure was first blamed on "contention
    among sub-agents" and only an earlier log read turned up the real Windows error codes.
    """

    def test_a_fail_fast_abort_is_named_rather_than_reported_as_a_number(self):
        out = _describe_exit(0xC0000409, "")
        self.assertIn("STATUS_FAIL_FAST_EXCEPTION", out)
        self.assertIn("Lower the worker count", out)

    def test_resource_exhaustion_codes_are_all_named(self):
        for code in (0xC0000409, 0xC0000005, 0xC0000017, 3221225781, 3221225786):
            with self.subTest(code=hex(code)):
                self.assertNotEqual(_describe_exit(code, ""), "(no stderr)",
                                    f"{hex(code)} is in the table but its description is missing")

    def test_a_resource_winerror_is_named_and_the_unknown_one_is_not(self):
        """WinError 1455/1450 arrived as bare OSError strings, which is the whole reason for this.

        Measured on the real run: `seedsmith: Pickaxe_a: [WinError 1455] The paging file is too
        small for this operation to complete`. A table of subprocess EXIT codes cannot catch these -
        they are exceptions raised while spawning, not statuses returned by a finished process.
        """
        for code, needle in ((1455, "paging file"), (1450, "commit"), (8, "memory")):
            with self.subTest(code=code):
                self.assertIn(needle, _describe_oserror(OSError(code, "boom")).lower())

    def test_an_unknown_winerror_is_passed_through_unchanged(self):
        """The table adds meaning; it must never fabricate a diagnosis it has no evidence for."""
        exc = OSError(9999, "totally unrelated")
        self.assertEqual(_describe_oserror(exc), str(exc).strip())

    def test_a_resource_exhaustion_on_spawn_is_a_named_refusal_not_a_bare_OSError(self):
        """The end-to-end shape: a WinError during the spawn becomes AUTHORING-DELEGATE-EXHAUSTED.

        Without this, the exception escapes `answer()` and the run record stores the bare string,
        which is what made the 36-failure burst unattributable hours after the fact.
        """
        code = textwrap.dedent(
            """
            import seedsmith.plumbing.authorer as A
            from seedsmith.plumbing.authorer import DelegatedAuthorer, AuthoringRefusal
            def boom(*a, **k):
                raise OSError(1455, "The paging file is too small for this operation to complete")
            A.run_tool = boom
            a = DelegatedAuthorer(model="vendor/m", agent="general")
            try:
                a.answer("sys", "user")
                print("OUTCOME no-refusal")
            except AuthoringRefusal as e:
                print("OUTCOME", e.code, "paging" in e.detail.lower())
            except OSError:
                print("OUTCOME raw-OSError")
            """
        )
        proc = subprocess.run([sys.executable, "-c", code], cwd=str(Path(__file__).parent.parent),
                              capture_output=True, text=True, timeout=180,
                              env={**os.environ, "PYTHONPATH": "."})
        out = proc.stdout.strip()
        self.assertIn("AUTHORING-DELEGATE-EXHAUSTED", out, f"got: {out!r} {proc.stderr[-200:]}")
        self.assertIn("True", out, "the refusal detail must say what ran out")

    def test_an_unknown_code_reports_the_number_and_invents_nothing(self):
        """The table adds meaning; it must never fabricate a diagnosis."""
        out = _describe_exit(999, "")
        self.assertEqual(out, "(no stderr)")
        out = _describe_exit(1, "some agent error")
        self.assertEqual(out, "some agent error")

    def test_real_stderr_is_preserved_and_the_note_appended(self):
        out = _describe_exit(0xC0000409, "TypeError: something specific")
        self.assertTrue(out.startswith("TypeError: something specific"))
        self.assertIn("note:", out)

    def test_the_message_actually_reaches_the_refusal(self):
        """The table is useless if `answer()` does not call it - proven by E3 in the control."""
        code = textwrap.dedent(
            """
            from seedsmith.plumbing.authorer import DelegatedAuthorer, AuthoringRefusal
            class _Proc:
                returncode = 0xC0000409
                stdout = ""
                stderr = ""
            import seedsmith.plumbing.authorer as A
            A.run_tool = lambda *a, **k: _Proc()
            a = DelegatedAuthorer(model="vendor/m", agent="general")
            try:
                a.answer("sys", "user")
            except AuthoringRefusal as e:
                print("CODE", e.code)
                print("DETAIL", e.detail)
            """
        )
        proc = subprocess.run([sys.executable, "-c", code], cwd=str(Path(__file__).parent.parent),
                              capture_output=True, text=True, timeout=180,
                              env={**os.environ, "PYTHONPATH": "."})
        out = proc.stdout or ""
        self.assertIn("AUTHORING-DELEGATE-FAILED", out, f"no refusal raised: {proc.stderr[-300:]}")
        self.assertIn("STATUS_FAIL_FAST_EXCEPTION", out,
                      "the refusal detail does not carry the exit-code diagnosis")


class CliModeReachesNestedTests(unittest.TestCase):
    """Audit finding: 4 of 9 `--mode` subcommands accepted the flag and silently discarded it.

    The subcommands dispatch by rebuilding a `passthrough` argv for a child module that has its own
    parser. Six child parsers had `--endpoint`/`--model` and no `--mode`. Forwarding alone would
    have made argparse reject it, so the fix exports the flag as process config at the CLI boundary
    and every child reads it through `load_config`.
    """

    def test_main_exports_the_flag_as_process_config(self):
        import os as _os
        from seedsmith.report import cli as cli_mod

        seen: dict = {}

        def _func(args):
            seen["func_ran"] = True
            return 0

        class _Args:
            mode = "delegated"

            def __init__(self):
                self.func = _func

        class _Parser:
            def parse_args(self, argv=None):
                return _Args()

        old_build = cli_mod.build_parser
        cli_mod.build_parser = lambda: _Parser()
        old_env = _os.environ.pop("SEEDSMITH_LLM_MODE", None)
        exported: dict = {}
        try:
            rc = cli_mod.main([])
            exported["mode"] = _os.environ.get("SEEDSMITH_LLM_MODE")
        finally:
            cli_mod.build_parser = old_build
            _os.environ.pop("SEEDSMITH_LLM_MODE", None)
            if old_env is not None:
                _os.environ["SEEDSMITH_LLM_MODE"] = old_env
        self.assertEqual(rc, 0)
        self.assertTrue(seen.get("func_ran"))
        # captured DURING the call, before the finally block cleaned the environment
        self.assertEqual(exported.get("mode"), "delegated")

    def test_load_config_honours_the_exported_process_variable(self):
        import os as _os
        import pathlib as _pl
        old = _os.environ.get("SEEDSMITH_LLM_MODE")
        _os.environ["SEEDSMITH_LLM_MODE"] = "delegated"
        try:
            self.assertEqual(load_config(dotenv_path=_pl.Path("nonexistent.env")).mode, "delegated")
        finally:
            _os.environ.pop("SEEDSMITH_LLM_MODE", None)
            if old is not None:
                _os.environ["SEEDSMITH_LLM_MODE"] = old

    def test_an_absent_flag_leaves_the_environment_alone(self):
        """The export must never be what CREATES a delegated run - only what carries one."""
        import os as _os
        import pathlib as _pl
        _os.environ.pop("SEEDSMITH_LLM_MODE", None)
        self.assertEqual(load_config(dotenv_path=_pl.Path("nonexistent.env")).mode, "api")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()