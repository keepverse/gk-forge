"""seedsmith.plumbing.authorer — the ONE seam every authoring call resolves its model through.

**Two implementations, one interface.** `Authorer.answer(system, user, schema) -> str`. Exactly two
classes implement it: `ApiAuthorer` (an OpenAI-compatible chat endpoint) and `DelegatedAuthorer`
(a delegated sub-agent). There is no third, and a third is not a feature request — it is a third
transport to keep honest, which is the thing this seam exists to stop.

**Why a seam at all.** Before this, the transport lived inside `llm_caller.call_model`, and 24
adapter call sites plus 5 direct callers reached it by importing it. That is one implementation, so
it was never really "one seam" — it was one hard-wired default with no second option and no place to
put one. A delegated sub-agent is now the second option, and `call_model` dispatches through
`resolve_authorer`, so every one of those call sites goes through the seam without being edited.

**API IS THE DEFAULT, and delegated mode is reachable only by an explicit owner request.** Two rules,
both load-bearing, both from the owner's 2026-10-02 ruling:

1. `DEFAULT_MODE = "api"`. A caller that passes nothing gets the API authorer.
2. **There is no fallback into delegated mode.** If API mode is selected and no endpoint is
   configured, this raises `AUTHORING-NO-ENDPOINT`. It does NOT quietly reach for a sub-agent.

Rule 2 is the whole point. A silent fall into a mode whose delegated agent is *permitted to hand-edit
the corpus* is the precise failure the ruling exists to prevent: the operator asked for a missing
credential and instead got a process with write access to `data/`. So the absence of an endpoint is a
named refusal, never a substitution.

**A refusal is a value, not an exception message.** Every failure path raises `AuthoringRefusal`,
which carries a stable `code`. The CLI turns a refusal into a non-zero exit; a test asserts on the
code. That is what makes "no model and no network" a testable state rather than a hopeful one.

**Delegated mode runs the same plan and the same validation as API mode.** The seam only decides WHO
answers a brief. It does not decide what a brief is, and it does not decide whether an answer is
legal — `live_answer_caller`'s schema check and `ItemSeedValidator` are unchanged and run either way.
That is what makes the two modes comparable: same input, same acceptance, different author.

**Schema-constrained decoding is an API-mode capability.** `ApiAuthorer` can hand a JSON Schema to a
server that enforces it at decode time (llama.cpp GBNF grammar sampling). A delegated sub-agent has no
such server, so `schema` reaches it as *instructions in the prompt* and the result goes through the
same `extract_json` post-parse both modes already use. Documented here rather than papered over: the
two modes differ in enforcement strength, and pretending otherwise would make a comparison between
their outputs meaningless.

**Deterministic derivation comes first, always.** This module is the LAST resort, not the first. A
property that can be derived from a row's own fields must be derived — that is how 84 duplicate item
names were fixed with no model at all, and an authoring path in front of a derivable one is a defect.
The seam exists so that the authoring step that genuinely needs a model has exactly one shape.
"""

from __future__ import annotations

import abc
import json
import os
import subprocess  # for TimeoutExpired only - every LAUNCH goes through run_tool
import sys
import time
from pathlib import Path
from typing import Callable, Mapping, Sequence

from ..tooling import run_tool

#: The only two modes. A closed enum on purpose: `resolve_authorer` refuses anything else by name
#: rather than defaulting, so a typo in a CLI flag cannot silently select the wrong transport.
MODES: tuple[str, ...] = ("api", "delegated")

#: API is the default. Not a convenience — the ruling makes API the mode you get unless the owner
#: asks otherwise, so the "unless" has to be a deliberate act.
DEFAULT_MODE = "api"

#: Where the owner records which models may author, as CONFIGURATION. Never a literal here, and
#: never a default that quietly resolves: `tests/test_no_model_literal.py` exists to keep model
#: identity out of the package body, and the owner's charter is model identity. It is also better
#: design — seedsmith should not assume the shape of an agent tool's config directory. Point
#: `SEEDSMITH_MODEL_CHARTER` at `allowed-models.json`, whose conventional home in this workspace is
#: under the repository's assistant-config directory (see `.claude/opencode-agents/`).
CHARTER_ENV_VAR = "SEEDSMITH_MODEL_CHARTER"

#: The sub-agent persona delegated mode drives. Configurable because a persona is an operator choice,
#: not a protocol fact; the default is the repo's own general-purpose agent.
DEFAULT_DELEGATED_AGENT = "general"

#: How long a delegated run may take. A sub-agent reads a brief, reasons, and answers; it is not a
#: single HTTP round-trip, so it gets its own budget rather than borrowing the endpoint's.
DELEGATED_TIMEOUT_SECONDS = 1800.0


class AuthoringRefusal(RuntimeError):
    """A named refusal. `code` is the contract; the message is for a human.

    Every refusal path in this module raises this rather than returning `None` or an empty string, so
    "no model configured" can never be read as "the model answered nothing" — two failures that look
    identical downstream and mean completely different things.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class _DelegateCliMissing(RuntimeError):
    """`tooling.run_tool`'s own refusal type for this call site.

    `run_tool` constructs whatever `refusal=` it is handed with a single message, which is not the
    two-argument shape `AuthoringRefusal` uses (code + detail). Rather than bending `AuthoringRefusal`
    into a two-shapes-one-class lie, the launcher raises this and `answer` translates it — so every
    refusal leaving this module is still an `AuthoringRefusal` carrying a stable code.
    """


class Authorer(abc.ABC):
    """Who answers a brief. The whole of the seam."""

    #: Stable identifier, recorded in provenance so a corpus records WHICH mode authored it.
    mode: str = ""

    @abc.abstractmethod
    def answer(self, system: str, user: str, *, schema: Mapping | None = None) -> str:
        """Return the raw authored text for this brief.

        Raw, not parsed: parsing and validation belong to the caller so both modes are judged by the
        same code. A mode that returned already-parsed JSON could not be compared with one that did
        not, and the comparison is the point.
        """

    def describe(self) -> str:
        """One line naming the mode, for logs and refusals."""
        return self.mode


class ApiAuthorer(Authorer):
    """Answers through an OpenAI-compatible chat endpoint — the default, and the only mode that
    existed before delegated mode did.

    Holds the endpoint/model as *injected callables* rather than importing `llm_caller` at module
    scope, because `llm_caller.call_model` dispatches through this module: a module-level import
    would be a cycle. The lazy import below is what breaks it, and it is why this class carries no
    endpoint logic of its own — `llm_caller` remains the single implementation of the HTTP transport.
    """

    mode = "api"

    def __init__(self, config, *, call: Callable[..., str] | None = None) -> None:
        self._config = config
        self._call = call

    def answer(self, system: str, user: str, *, schema: Mapping | None = None) -> str:
        endpoint = (getattr(self._config, "endpoint", "") or "").strip()
        model = (getattr(self._config, "model", "") or "").strip()
        if not endpoint:
            # The refusal that must NOT become a fallback. See the module docstring, rule 2.
            raise AuthoringRefusal(
                "AUTHORING-NO-ENDPOINT",
                "API mode is selected and no endpoint is configured. Set SEEDSMITH_LLM_ENDPOINT (or "
                "an [llm] endpoint in seedsmith.toml), or run delegated mode ON PURPOSE with the "
                "owner's explicit request. This never falls back to a delegated agent: that mode "
                "may edit the corpus, and quietly entering it because a credential was missing is "
                "the failure this refusal exists to prevent.",
            )
        if not model:
            raise AuthoringRefusal(
                "AUTHORING-NO-MODEL",
                "API mode is selected and no model id is configured. Set SEEDSMITH_LLM_MODEL or an "
                "[llm] model in seedsmith.toml.",
            )
        call = self._call
        if call is None:
            from ..pipeline import llm_caller  # lazy: llm_caller dispatches through this module
            call = llm_caller.call_model
        return call(system, user, config=self._config, schema=dict(schema) if schema else None)

    def describe(self) -> str:
        return f"api[{getattr(self._config, 'model', '?')}]"


class DelegatedAuthorer(Authorer):
    """Answers by delegating to a sub-agent — the owner's ruling C3/C5 mode.

    **The agent may hand-edit seed data in this mode, and that is the point.** Seedsmith keeps this
    safe by PLANNING the work and VALIDATING the result: `ItemSeedValidator` remains the sole
    authority on whether a row or a name is legal, and the agent's own judgement never substitutes
    for it. In API mode the rule against hand-editing generated data continues in full.

    **The transport is a subprocess, and its output format was measured, not assumed.** `opencode run
    --format json` does NOT emit a JSON document — it emits JSONL, one event object per line. A
    single-document parse fails outright with "Additional text encountered after finish". The events
    seen are `step_start` and `text`, and the authored text is the concatenation of `part.text` over
    `type == "text"` events. `--session` gives a working multi-turn, which is what lets a repair
    prompt continue the same thread instead of restarting it.

    **The model's prose is not trusted as JSON.** Asked for `{"ok":true}` this model answers
    `{" ok":true}` — a space after the brace. So the raw text is handed back for `extract_json`,
    the same tolerant extractor every API answer already goes through. One parser for both modes.

    **The model comes from the charter, never from here.** `allowed-models.json` is the only
    authority on which model may author. A missing or unrecognised charter is a refusal, not a
    default — a hard-coded fallback id would be precisely the "no model fallback" the ruling forbids.
    """

    mode = "delegated"

    def __init__(self, *, model: str, agent: str = DEFAULT_DELEGATED_AGENT,
                 executable: str = "opencode", timeout: float = DELEGATED_TIMEOUT_SECONDS) -> None:
        if not model.strip():
            raise AuthoringRefusal(
                "AUTHORING-NO-CHARTERED-MODEL",
                "delegated mode was requested but the charter names no model to delegate to.",
            )
        self._model = model.strip()
        self._agent = agent
        self._executable = executable
        self._timeout = timeout
        #: Threaded across repair turns so a follow-up prompt continues the same sub-agent session
        #: instead of paying for a cold start on every repair attempt.
        self._session: str | None = None
        self._turns = 0

    @property
    def model(self) -> str:
        return self._model

    @property
    def session_id(self) -> str | None:
        """The delegated session, once one exists. Recorded in provenance when present."""
        return self._session

    def answer(self, system: str, user: str, *, schema: Mapping | None = None) -> str:
        prompt = self._compose(system, user, schema)
        argv = [
            self._executable, "run", "--format", "json",
            "--model", self._model,
            "--agent", self._agent,
        ]
        if self._session:
            argv += ["--session", self._session]
        argv.append(prompt)

        started = time.monotonic()
        # Through `tooling.run_tool`, never `subprocess` directly: `tests/test_tool_invocation_guard.py`
        # names `tooling.py` as the single sanctioned launcher precisely so that a missing executable
        # is a NAMED refusal instead of an opaque OSError, and a second launcher would put that back.
        # The `cwd` is required by the signature; the sub-agent inherits this process's directory,
        # which is the run root it is already operating in.
        try:
            proc = run_tool(argv, cwd=os.getcwd(), refusal=_DelegateCliMissing, what=self._executable,
                            timeout=self._timeout)
        except _DelegateCliMissing as exc:
            raise AuthoringRefusal(
                "AUTHORING-NO-DELEGATE-CLI",
                f"delegated mode was requested but {self._executable!r} could not be launched: {exc}",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AuthoringRefusal(
                "AUTHORING-DELEGATE-TIMEOUT",
                f"the delegated agent did not answer within {self._timeout:.0f}s: {exc}",
            ) from exc
        if proc.returncode != 0:
            raise AuthoringRefusal(
                "AUTHORING-DELEGATE-FAILED",
                f"the delegated agent exited {proc.returncode}: "
                f"{(proc.stderr or '').strip()[:400] or '(no stderr)'}",
            )
        text, session = self._read_events(proc.stdout or "")
        self._session = session or self._session
        self._turns += 1
        print(f"seedsmith.authorer: [delegated {self._model}] turn {self._turns}, "
              f"{len(text)} chars, {time.monotonic() - started:.1f}s"
              f"{', session ' + self._session if self._session else ''}", flush=True)
        if not text.strip():
            raise AuthoringRefusal(
                "AUTHORING-DELEGATE-EMPTY",
                "the delegated agent produced no text event. An empty answer is a refusal, not an "
                "empty result: it must never be mistaken for content.",
            )
        return text

    def describe(self) -> str:
        return f"delegated[{self._model}]"

    @staticmethod
    def _compose(system: str, user: str, schema: Mapping | None) -> str:
        """Flatten (system, user) into one delegated prompt.

        A sub-agent is a chat session, not a chat-completions endpoint: there is no separate system
        role to populate, so the system text is prepended as framing. A schema cannot be enforced at
        decode time without a grammar-sampling server, so it is stated as an instruction — and
        `extract_json` still validates the shape afterwards, in both modes.
        """
        parts = []
        if system.strip():
            parts.append(system.strip())
        parts.append(user.strip())
        if schema:
            parts.append(
                "Answer with a single JSON object and nothing else. It must satisfy this JSON "
                "Schema; every required field present, no extra fields:\n"
                + json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False)
            )
        return "\n\n".join(parts)

    @staticmethod
    def _read_events(stream: str) -> tuple[str, str | None]:
        """Parse the JSONL event stream into (authored text, session id).

        Tolerates unparseable lines instead of failing the run: the stream has been observed to carry
        banner noise before the events, and one junk line is not a reason to discard a real answer.
        A line that IS parseable but is not a known event is skipped rather than guessed at.
        """
        texts: list[str] = []
        session: str | None = None
        for raw in stream.splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            session = session or event.get("sessionID") or session
            part = event.get("part")
            if event.get("type") == "text" and isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    texts.append(text)
        return "".join(texts), session


def _charter_path(explicit: "str | Path | None" = None) -> Path:
    """Resolve the charter as CONFIGURATION: explicit argument, then the environment.

    No discovery walk and no built-in location. A path that seedsmith guessed would be a path that
    silently changes meaning when a repository is laid out differently, and this seam's whole
    argument is that a missing input must be a named refusal rather than a substituted default.
    """
    if explicit:
        return Path(explicit)
    from_env = (os.environ.get(CHARTER_ENV_VAR) or "").strip()
    if from_env:
        return Path(from_env)
    raise AuthoringRefusal(
        "AUTHORING-NO-CHARTER",
        f"delegated mode was requested but no model charter was given. Point {CHARTER_ENV_VAR} at "
        "the owner's `allowed-models.json`, or pass `charter_path=`. There is deliberately no "
        "built-in location and no default model: a guessed charter is a silent model fallback, "
        "which is the thing the charter exists to prevent.",
    )


def chartered_models(charter_path: "str | Path | None" = None) -> dict[str, list[str]]:
    """Read the owner charter. A missing or malformed charter is a refusal, never a default."""
    path = _charter_path(charter_path)
    if not path.is_file():
        raise AuthoringRefusal(
            "AUTHORING-NO-CHARTER",
            f"the charter named by {CHARTER_ENV_VAR} (or the `charter_path` argument) does not "
            f"exist: {path}. There is deliberately no built-in model id to fall back to.",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthoringRefusal("AUTHORING-CHARTER-UNREADABLE", f"{path}: {exc}") from exc
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, dict) or not models:
        raise AuthoringRefusal("AUTHORING-CHARTER-EMPTY", f"{path} names no models.")
    return {str(k): [str(v) for v in vs] for k, vs in models.items() if isinstance(vs, list)}


def resolve_authorer(mode: str = DEFAULT_MODE, *, config=None,
                     agent: str = DEFAULT_DELEGATED_AGENT,
                     executable: str = "opencode",
                     charter_path: "str | Path | None" = None) -> Authorer:
    """Resolve the ONE authorer for a run. This is the seam's only entry point.

    `mode` defaults to `DEFAULT_MODE` ("api"), so a caller that expresses no preference gets the API
    authorer. Selecting delegated requires passing `mode="delegated"` — an explicit act by the
    operator, which is exactly what ruling C6 asks for. Nothing here inspects the environment to
    decide: no "endpoint missing, try the agent instead", no auto-detection, no fallback.

    The returned object is created but never used to probe the network or the CLI, so this is safe to
    call in a test with no model and no endpoint. Actually answering is what can fail, and it fails
    by refusal.
    """
    chosen = (mode or "").strip()
    if chosen not in MODES:
        raise AuthoringRefusal(
            "AUTHORING-UNKNOWN-MODE",
            f"{mode!r} is not one of {list(MODES)}. Refused rather than defaulted: a typo in a mode "
            "flag must not silently select a transport.",
        )
    if chosen == "delegated":
        models = chartered_models(charter_path)
        allowed = [m for values in models.values() for m in values]
        if not allowed:
            raise AuthoringRefusal("AUTHORING-NO-CHARTERED-MODEL", "the charter names no model.")
        if len(allowed) > 1:
            raise AuthoringRefusal(
                "AUTHORING-AMBIGUOUS-CHARTER",
                f"the charter names {len(allowed)} models ({allowed}); refusing to guess which one "
                "may author. Name it explicitly.",
            )
        return DelegatedAuthorer(model=allowed[0], agent=agent, executable=executable)

    if config is None:
        from ..pipeline.llm_caller import load_config
        config = load_config()
    return ApiAuthorer(config)


def _cli() -> int:
    """Tiny probe so the seam is reachable and refusable from a shell, for the live walkthrough.

    Exists so "is delegated reachable without a model" is a command with an exit code rather than an
    inspection of the source. `--mode delegated` is the owner request; without it the run is API
    mode and refuses when no endpoint is configured.
    """
    import argparse

    ap = argparse.ArgumentParser(prog="seedsmith-authorer", description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=list(MODES), default=DEFAULT_MODE,
                    help="api (default) or delegated. delegated is the owner's explicit request.")
    ap.add_argument("--agent", default=DEFAULT_DELEGATED_AGENT)
    ap.add_argument("--charter", default="", help=f"path to allowed-models.json (or set ${CHARTER_ENV_VAR})")
    ap.add_argument("--brief", default="Reply with a JSON object and nothing else.")
    args = ap.parse_args()

    try:
        authorer = resolve_authorer(args.mode, agent=args.agent, charter_path=args.charter or None)
        print(f"resolved: {authorer.describe()}")
        text = authorer.answer("", args.brief)
    except AuthoringRefusal as exc:
        print(f"REFUSED {exc.code}\n  {exc.detail}", file=sys.stderr)
        return 3
    print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    sys.exit(_cli())