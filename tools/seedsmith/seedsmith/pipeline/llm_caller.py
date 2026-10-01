"""seedsmith.pipeline.llm_caller — local-model transport with reasoning disabled.

Ported from `D:\\Works\\source\\lore-weave\\scripts\\i18n_translate.py`, proven in production on
that project's translate pipeline (spec-pipeline.md §5.1). Two pieces are copied close to as-is
(`call_model`, `extract_json`); the self-heal loop is generalized — `translate_chunk()`'s
translation-specific verify is replaced by a `verify_fn` parameter, so any future seedsmith
pipeline (flavour text, set headers, …) supplies its own hard/soft rule and reuses this loop
unchanged.

No import from `seedsmith.corpus`, `seedsmith.adapters`, or `seedsmith.metrics`, in either
direction. This module has no position in that dependency chain (tasks/seedsmith-plan.md, S0) —
it is buildable and testable before any of those exist, and must stay that way.
"""
from __future__ import annotations

import dataclasses
import json
import re
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

VerifyFn = Callable[[dict, dict], tuple[dict, dict]]
BuildUserFn = Callable[[dict], str]
BuildHealUserFn = Callable[[dict, dict, dict], str]
DefaultForFn = Callable[[str, object], object]

#: `gk-forge/tools/seedsmith/` — parent of the `seedsmith` package. Used when CWD has no `.env` so a
#: repo-root `python -m seedsmith` still finds the machine-local file operators keep next to
#: `.env.example`.
_PACKAGE_TOOL_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class LlmCallerConfig:
    """Every number here is adjustable per call — none is a hidden constant.

    Defaults match the ported script's LM Studio setup; a different local server, model, or
    heal budget is a config change, not a code change.
    """

    endpoint: str = "http://localhost:1234/v1/chat/completions"
    model: str = "google/gemma-4-26b-a4b-qat"
    timeout: float = 420.0          # a 26B model at high context is slow; be patient
    attempts: int = 2               # hammering a wedged local queue with retries makes it worse
    retry_delay: float = 3.0
    max_heal: int = 3
    #: ⛔ Real incident, 2026-09-08: a quantized local model degenerated into a repeated-token
    #: loop inside a schema field whose only constraint was a `pattern` (JSON Schema `pattern` is
    #: not supported by llama.cpp's grammar-from-schema converter, so it is unenforced at decode
    #: time — see `call_model`'s own `schema` docstring) and no `maxLength` — every request before
    #: this field existed had NO upper bound on response length at all, so the loop ran past 20K+
    #: tokens with nothing to stop it short of the model's full context window. This is a second,
    #: independent safety net at the transport layer — it bounds every call regardless of whether
    #: a caller's own schema happens to cap every field.
    max_tokens: int = 16384


DEFAULT_CONFIG = LlmCallerConfig()


#: `.env` key -> `LlmCallerConfig` field, and the type each value parses as. `.env` is the
#: per-machine override layer (gitignored, spec below) — it wins over `seedsmith.toml`, which
#: wins over `LlmCallerConfig`'s own built-in defaults.
_ENV_KEYS: "dict[str, tuple[str, type]]" = {
    "SEEDSMITH_LLM_ENDPOINT": ("endpoint", str),
    "SEEDSMITH_LLM_MODEL": ("model", str),
    "SEEDSMITH_LLM_TIMEOUT": ("timeout", float),
    "SEEDSMITH_LLM_ATTEMPTS": ("attempts", int),
    "SEEDSMITH_LLM_RETRY_DELAY": ("retry_delay", float),
    "SEEDSMITH_LLM_MAX_HEAL": ("max_heal", int),
    "SEEDSMITH_LLM_MAX_TOKENS": ("max_tokens", int),
}


def _parse_dotenv(path: Path) -> "dict[str, str]":
    """`KEY=value` lines, `#` comments, blank lines skipped — deliberately not the full dotenv
    spec (no quoting, no multi-line, no export). seedsmith's own values are all bare scalars
    (a URL, a model id, small numbers), so the minimal parser is honest about what it supports
    rather than depending on `python-dotenv` for six key names.
    """
    out: "dict[str, str]" = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        out[key.strip()] = value.strip()
    return out


def resolve_dotenv_path(dotenv_path: Path | None = None) -> Path:
    """Pick the `.env` file to read.

    - Explicit `dotenv_path` always wins (tests pass a guaranteed-absent path for hermeticity).
    - Else CWD `.env` if it exists (operator ran from `gk-forge/tools/seedsmith`).
    - Else `tools/seedsmith/.env` next to the package (repo-root / other CWD still finds it).
    - Else CWD `.env` as a non-existent placeholder — `load_config` treats a missing file as
      "no override," same as before.
    """
    if dotenv_path is not None:
        return dotenv_path
    cwd = Path(".env")
    if cwd.exists():
        return cwd
    packaged = _PACKAGE_TOOL_ROOT / ".env"
    if packaged.exists():
        return packaged
    return cwd


def read_dotenv_values(dotenv_path: Path | None = None) -> "dict[str, str]":
    """Raw `KEY=value` map from the resolved `.env`, or `{}` when the file is absent."""
    path = resolve_dotenv_path(dotenv_path)
    if not path.exists():
        return {}
    return _parse_dotenv(path)


def load_config(toml_path: Path | None = None, *, dotenv_path: Path | None = None) -> LlmCallerConfig:
    """Read `[pipeline.llm_caller]` from `seedsmith.toml`, then layer `.env` on top (`.env` is
    per-machine and wins — a real endpoint/model override belongs there, never hand-edited into
    the committed toml). Falls back to `DEFAULT_CONFIG` for any key neither file sets, including
    every key when NEITHER file exists (spec-foundation §7.3: every seedsmith flag has a config
    equivalent, but nothing in seedsmith requires either file to exist today).

    A missing file or a missing table/key is a legitimate default. A *malformed* TOML file is
    not — matching this program's running rule that a wrong value silently treated as absent is
    the defect class this whole audit exists to catch; `tomllib.TOMLDecodeError` propagates
    uncaught. A malformed `.env` line is silently skipped (`_parse_dotenv`'s own minimal-parser
    contract) since a stray comment or blank line is normal, not a defect.
    """
    toml_path = toml_path or Path("seedsmith.toml")
    section: dict = {}
    if toml_path.exists():
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        section = data.get("pipeline", {}).get("llm_caller", {})
        if not isinstance(section, dict):
            section = {}

    base = DEFAULT_CONFIG
    resolved = {
        "endpoint": section.get("endpoint", base.endpoint),
        "model": section.get("model", base.model),
        "timeout": section.get("timeout", base.timeout),
        "attempts": section.get("attempts", base.attempts),
        "retry_delay": section.get("retry_delay", base.retry_delay),
        "max_heal": section.get("max_heal", base.max_heal),
        "max_tokens": section.get("max_tokens", base.max_tokens),
    }

    env_file = resolve_dotenv_path(dotenv_path)
    if env_file.exists():
        env_values = _parse_dotenv(env_file)
        for env_key, (field, caster) in _ENV_KEYS.items():
            if env_key in env_values and env_values[env_key] != "":
                resolved[field] = caster(env_values[env_key])

    return LlmCallerConfig(**resolved)


def resolve_live_transport(
    cli_endpoint: str = "",
    cli_model: str = "",
    *,
    toml_path: Path | None = None,
    dotenv_path: Path | None = None,
) -> LlmCallerConfig:
    """Merge CLI `--endpoint`/`--model` onto `load_config()` — empty CLI falls through to
    `.env` / toml / built-in defaults. Spec-foundation §7.3: every flag has a config equivalent;
    the flag wins when the operator actually passed a non-empty value.

    Callers that previously refused `--write` when `args.endpoint` was empty should refuse only
    when *this* helper's `.endpoint` is empty (CLI and config both blank).
    """
    base = load_config(toml_path, dotenv_path=dotenv_path)
    endpoint = (cli_endpoint or "").strip() or base.endpoint
    # LM Studio operators commonly paste the API root (`http://localhost:1234/v1`) while the
    # OpenAI-compatible completion route is `/v1/chat/completions`. Normalize that shorthand so
    # a reachable root cannot produce an empty/HTML response that looks like a model failure.
    if endpoint.rstrip("/").endswith("/v1"):
        endpoint = endpoint.rstrip("/") + "/chat/completions"
    model = (cli_model or "").strip()
    if not model or model == "unrecorded":
        model = base.model
    return dataclasses.replace(base, endpoint=endpoint, model=model)


class DegenerateGenerationError(RuntimeError):
    """⛔ Real incident, 2026-09-08: a quantized local model (reproduced independently on both
    `meta/muse-glimmer` and `google/gemma-4-26b-a4b-qat` — not one bad model, a transport gap)
    degenerated into a short repeating token cycle inside a single JSON string field and never
    recovered on its own. `max_tokens` alone only bounds the WORST case (it still burns the WHOLE
    budget, tens of minutes, generating garbage); a schema `maxLength` does not help either — LM
    Studio's grammar-from-JSON-Schema conversion enforces `type`/`enum`/structural keys but not
    string-length bounds (confirmed live: a `nameKey` field with `maxLength: 96` still ran to
    16384 tokens of repeated garbage). The only real fix is catching the loop WHILE STREAMING and
    aborting the connection immediately — see `_has_repetition_loop` and `call_model`'s own
    streaming loop below."""


class EmptyModelResponseError(RuntimeError):
    """The endpoint completed an SSE stream without emitting assistant content."""


def _has_repetition_loop(text: str, *, tail: int = 400, min_period: int = 2, max_period: int = 80,
                         min_repeats: int = 6) -> bool:
    """True if the trailing `tail` characters of `text` are `min_repeats` or more consecutive,
    BYTE-IDENTICAL copies of some short unit (`min_period`..`max_period` characters) — the exact
    shape of the 2026-09-08 incident (a ~50-char unit repeated hundreds of times in a row inside
    one JSON string value). Checked against only the tail, never the whole accumulated response,
    so this stays cheap to call after every streamed chunk regardless of how long the response
    has already grown. `min_repeats=6` is deliberately generous — legitimate JSON content
    essentially never repeats an identical 2-80 character unit six times in a row, but a real,
    short, structurally-repeated legal value (unlikely at this scale in this pipeline's own
    schemas) would still need to clear this bar before being mistaken for a loop.
    """
    s = text[-tail:]
    for period in range(min_period, max_period + 1):
        window = period * min_repeats
        if len(s) < window:
            continue
        chunk = s[-window:]
        unit = chunk[:period]
        if unit * min_repeats == chunk:
            return True
    return False


def _stream_once(config: LlmCallerConfig, body: bytes) -> str:
    """One HTTP attempt, read incrementally over an OpenAI-compatible SSE stream (`data: {...}`
    lines, terminated by `data: [DONE]`). Aborts the connection (raising `DegenerateGenerationError`,
    caught by `call_model`'s own retry loop exactly like a transport failure) the moment
    `_has_repetition_loop` fires on the accumulated text — this is what actually stops a
    degenerate generation in real time, not just bounds its worst case.

    **Observability**: a progress line every 5 real seconds (`[model] N chars received so far`)
    so a long call is visible in whatever log this process's stdout is redirected to, not only in
    the model server's own separate console — the 2026-09-08 incident's own first symptom was a
    completely silent, unreadable log file for over an hour of real, in-flight generation.
    """
    req = urllib.request.Request(config.endpoint, data=body,
                                 headers={"Content-Type": "application/json"})
    accumulated: "list[str]" = []
    # ⛔ A rolling tail, capped at 2x the detector's own `tail` window, kept SEPARATELY from
    # `accumulated` — checking `_has_repetition_loop` against `"".join(accumulated)` on every
    # chunk would re-join the WHOLE response every time (O(n) per chunk, O(n^2) total), exactly
    # the kind of cost a fast-abort mechanism must not have once a response is already thousands
    # of characters long.
    tail = ""
    total_len = 0
    started = time.monotonic()
    last_log = started
    with urllib.request.urlopen(req, timeout=config.timeout) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data:"):
                continue
            data_str = line[len("data:"):].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            piece = (choices[0].get("delta") or {}).get("content")
            if not piece:
                continue
            accumulated.append(piece)
            total_len += len(piece)
            tail = (tail + piece)[-800:]
            now = time.monotonic()
            if now - last_log >= 5.0:
                print(f"seedsmith.llm_caller: [{config.model}] {total_len} chars received so far "
                     f"({now - started:.0f}s elapsed)", flush=True)
                last_log = now
            if _has_repetition_loop(tail):
                raise DegenerateGenerationError(
                    f"[{config.model}] repetition loop detected after {total_len} chars "
                    f"({now - started:.0f}s) -- aborting this attempt rather than burning the "
                    f"full max_tokens budget on it")
    result = "".join(accumulated)
    if not result.strip():
        raise EmptyModelResponseError(
            f"[{config.model}] endpoint returned no assistant content; refusing to parse an empty response"
        )
    return result


def call_model(system: str, user: str, *, config: LlmCallerConfig | None = None,
               temperature: float = 0.2, schema: "dict | None" = None) -> str:
    """Call a local OpenAI-compatible chat endpoint with reasoning disabled, streaming the
    response so a degenerate generation can be caught and aborted in real time (see
    `_stream_once`/`_has_repetition_loop`/`DegenerateGenerationError`).

    `config=None` — the default — resolves through `load_config()` **at call time**, so the
    operator's `.env` (`SEEDSMITH_LLM_MODEL`) and `seedsmith.toml` are respected by every caller
    that does not thread a config through. The defect this shape prevents: a parameter default
    bound to `DEFAULT_CONFIG` snapshots the built-in value at import time, so a call site that
    omitted `config` silently ignored the per-machine override — the same defect class the guard
    in `tests/test_no_model_literal.py` rejects statically (NS3, spec-model-config-resolve §3.1).
    `DEFAULT_CONFIG` is now referenced only as `load_config`'s bottom layer in this module.

    `max_tokens` (`config.max_tokens`, default 16384) is still sent as a hard backstop for
    whatever the repetition detector's own heuristic misses, but it is no longer the FIRST line of
    defense — see `DegenerateGenerationError`'s own docstring for why a schema `maxLength` and
    `max_tokens` alone were not enough (the 2026-09-08 incident happened with both already in
    place).

    Two redundant fields are sent on every call because different servers/templates read
    different keys: `reasoning_effort` is the OpenAI-style field some servers honor directly;
    `chat_template_kwargs` is passed straight through to the model's own Jinja chat template,
    where a reasoning-capable model usually gates a <think> block on a variable named
    `enable_thinking`/`thinking`. Sending both is harmless — an OpenAI-compatible server or
    template ignores whichever key it doesn't recognize.

    `schema` (optional, spec-dependency-baseline.md §2.4) turns on CONSTRAINED DECODING: LM Studio
    enforces a JSON Schema's STRUCTURAL keys (`type`/`enum`/`properties`/`required`) at decode time
    via llama.cpp's GBNF grammar sampling for GGUF models, so a token that would break one of those
    is never sampleable. It does NOT enforce `pattern` or, confirmed 2026-09-08, `minLength`/
    `maxLength` — grammar-from-JSON-Schema conversion commonly skips string-length bounds because
    expressing "at most N characters" as a context-free grammar production is a much harder
    problem than a structural or enum check. `extract_json` stays as defense-in-depth regardless.

    **Optional on purpose.** `schema=None` produces a byte-identical request body to before this
    parameter existed, so every existing caller is unaffected — asserted by test.
    """
    if config is None:
        config = load_config()
    payload = {
        "model": config.model, "temperature": temperature,
        "max_tokens": config.max_tokens,
        "stream": True,
        "reasoning_effort": "none",
        "chat_template_kwargs": {"enable_thinking": False, "thinking": False},
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }
    if schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "seedsmith_response", "strict": True, "schema": schema},
        }
    body = json.dumps(payload).encode("utf-8")
    last_err: Exception | None = None
    for attempt in range(config.attempts):
        try:
            started = time.monotonic()
            result = _stream_once(config, body)
            print(f"seedsmith.llm_caller: [{config.model}] call complete, {len(result)} chars, "
                 f"{time.monotonic() - started:.1f}s", flush=True)
            return result
        except EmptyModelResponseError:
            # An empty assistant stream is a deterministic content/configuration failure (for
            # example, a reasoning-only template), not a transport hiccup. Retrying spends the
            # same model budget and cannot repair the request, so fail immediately.
            raise
        except (urllib.error.URLError, TimeoutError, KeyError,
                DegenerateGenerationError) as e:
            last_err = e
            print(f"seedsmith.llm_caller: [{config.model}] attempt {attempt + 1}/{config.attempts} "
                 f"failed ({type(e).__name__}: {e}); "
                 f"{'retrying' if attempt + 1 < config.attempts else 'giving up'}", flush=True)
            if attempt + 1 < config.attempts:
                time.sleep(config.retry_delay)
    raise RuntimeError(f"model call failed after {config.attempts} attempts: {last_err}")


def extract_json(text: str) -> dict:
    """Strip ```json fences / prose and parse the first {...} object.

    Tolerates the single most common LLM-JSON slip: an unescaped double-quote inside a value.
    Callers are expected to use quote-free dotted/plain identifiers as keys, so a flat regex
    extraction (value = everything up to a `"` followed by `,` or `}`) recovers the pairs when
    strict `json.loads` chokes.
    """
    t = text.strip()
    if "```" in t:
        t = re.sub(r"^```[a-zA-Z]*\n?|```$", "", t.strip("`\n ")).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    blob = t[start:end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        pairs = re.findall(r'"([^"\n]+)"\s*:\s*"(.*?)"(?=\s*[,}])', blob, re.DOTALL)
        if pairs:
            return {k: v for k, v in pairs}
        raise


AnswerCallFn = Callable[[str, dict], dict]
AnswerValidator = Callable[[dict, dict], list[str]]

# Structural retry bound: one repair prompt distinguishes a formatting lapse from an unavailable
# model without turning a malformed response into an unbounded second generation loop.
_JSON_REPAIR_ATTEMPTS = 1


def live_answer_caller(config: LlmCallerConfig | None, *,
                       validator: AnswerValidator | None = None,
                       mode: "str | None" = None,
                       charter_path: "str | Path | None" = None,
                       authorer=None) -> AnswerCallFn:
    """A `call(brief, schema) -> dict` bound to an authorer through the one seam.

    `mode`/`charter_path` select the transport and are how delegated mode becomes reachable at all:
    they are absent by default, so every existing caller gets API mode without being edited, and
    passing `mode="delegated"` is a deliberate act. `authorer=` injects a ready-made one (tests use
    this to drive both modes with no model and no network).

    The shape `basetypegen.run.run_draws`, `milestonegen.run.run_draws`,
    `recipegen.run.run_draws`, and `droptablegen.run.run_draws` all already declare and test against
    (`Callable[[str, dict], dict]`) — each module's own brief embeds its full instructions as a
    single user-role message (there is no separate system prompt to manage, unlike `setgen`'s own
    `live_caller`, which is a different shape for a different, graph-based caller convention).
    Lifted here, generic and shared, rather than reimplemented once per module — the four modules
    above each carried a `main()` that explicitly refused to run for exactly this missing piece
    (`"REFUSING TO RUN: no model call is wired into this CLI entrypoint yet"`) until this existed.

    Schema-constrained decoding is honored (via `call_model`'s own `schema` parameter) whenever the
    caller's own schema dict is non-empty, but it is never the only guard: local type/enum checks
    run after parsing and a caller may supply domain validation. One repair prompt names a parse or
    validation defect before the error reaches the per-subject batch boundary. In delegated mode that
    local check matters MORE, not less: there is no server-side grammar sampling to enforce the
    schema, so `extract_json` plus these checks are the whole of the enforcement.
    """
    from ..plumbing.authorer import DEFAULT_MODE, resolve_authorer
    authorer = authorer if authorer is not None else resolve_authorer(
        mode if mode is not None else DEFAULT_MODE, config=config, charter_path=charter_path)

    def _validate_schema(answer: dict, schema: dict) -> list[str]:
        if not schema:
            return []
        defects: list[str] = []
        properties = schema.get("properties") or {}
        for field in schema.get("required") or ():
            if field not in answer:
                defects.append(f"missing required field {field!r}")
        type_map = {"string": str, "boolean": bool, "object": dict, "array": list,
                    "number": (int, float), "integer": int}
        for field, value in answer.items():
            spec = properties.get(field)
            if not isinstance(spec, dict):
                if properties:
                    defects.append(f"field {field!r} is not in the schema")
                continue
            declared = spec.get("type")
            types = (declared,) if isinstance(declared, str) else tuple(declared or ())
            if value is None:
                if "null" not in types and types:
                    defects.append(f"field {field!r} is null but schema does not allow null")
                continue
            concrete = next((t for t in types if t != "null"), None)
            expected = type_map.get(concrete) if concrete else None
            if expected is not None:
                if concrete in ("number", "integer") and isinstance(value, bool):
                    defects.append(f"field {field!r} is a boolean, not {concrete}")
                elif not isinstance(value, expected):
                    defects.append(f"field {field!r} should be {concrete}")
            allowed = spec.get("enum")
            if allowed is not None and value not in allowed:
                defects.append(f"field {field!r} value {value!r} is not one of {list(allowed)}")
        return defects

    def _parse_and_validate(raw: str, schema: dict) -> dict:
        answer = extract_json(raw)
        defects = _validate_schema(answer, schema)
        if validator is not None:
            defects.extend(validator(answer, schema))
        if defects:
            raise ValueError("local validation failed: " + "; ".join(defects))
        return answer

    def _repair_prompt(error: ValueError, brief: str) -> str:
        if "no JSON object" in str(error):
            return (
                "Your previous response was not a JSON object. Return exactly one JSON object "
                "that satisfies the requested schema, with no prose or Markdown.\n\n"
                "Original authoring brief:\n"
                f"{brief}"
            )
        return (
            "Your previous JSON response failed local validation:\n"
            f"- {error}\n\n"
            "Return exactly one corrected JSON object that satisfies the requested schema, "
            "with no prose or Markdown.\n\n"
            "Original authoring brief:\n"
            f"{brief}"
        )

    def _call(brief: str, schema: dict) -> dict:
        # Through the ONE seam (`plumbing.authorer`), not straight to `call_model`. The seam picks
        # WHO answers; everything below it -- `extract_json`, `_parse_and_validate`, the repair loop,
        # and `ItemSeedValidator` outside -- is unchanged and shared, so an API answer and a
        # delegated answer are judged by identical code and their outputs are comparable. In API
        # mode the resolved authorer calls `call_model` with the same arguments as before, so the
        # default request body is byte-identical.
        raw = authorer.answer("", brief, schema=schema or None)
        try:
            return _parse_and_validate(raw, schema)
        except ValueError as error:
            repair = _repair_prompt(error, brief)
            for _ in range(_JSON_REPAIR_ATTEMPTS):
                # In delegated mode this continues the SAME sub-agent session rather than starting
                # a cold one, so a repair prompt has the original exchange in front of it.
                raw = authorer.answer("", repair, schema=schema or None)
                try:
                    return _parse_and_validate(raw, schema)
                except ValueError:
                    continue
            raise error

    return _call


def _default_heal_user(items: dict, out: dict, hard: dict) -> str:
    defects = "\n".join(f"- {k}: {r}" for k, r in list(hard.items())[:40])
    need = {k: items[k] for k in hard if k in items}
    return (f"Your output had these problems:\n{defects}\n\n"
            f"Fix them. Return the COMPLETE corrected JSON object (all keys). "
            f"Source for the affected keys:\n{json.dumps(need, ensure_ascii=False)}\n\n"
            f"Full source:\n{json.dumps(items, ensure_ascii=False)}")


def call_with_self_heal(
    items: dict,
    system: str,
    build_user: BuildUserFn,
    verify_fn: VerifyFn,
    *,
    config: LlmCallerConfig | None = None,
    max_heal: int | None = None,
    build_heal_user: BuildHealUserFn | None = None,
    default_for: DefaultForFn | None = None,
    schema: "dict | None" = None,
) -> tuple[dict, dict]:
    """Call the model, verify the parsed output, and self-heal on named defects.

    `config=None` — the default — resolves through `load_config()` at call time, exactly like
    `call_model` (NS3). Heal rounds keep the one resolved config, so a loop never re-reads a
    different `.env` mid-flight.

    Generalized from `translate_chunk()`: that function hardcoded a translation-specific
    `verify_chunk`; here `verify_fn(items, out) -> (hard, soft)` is supplied by the caller, so
    a flavour-text pipeline, a set-header pipeline, or any future one reuses this exact loop
    with its own rule.

    `hard` failures block acceptance and trigger a re-prompt naming the exact defect per key —
    a bare retry teaches the model nothing; naming the reason is what fixes it (spec-pipeline.md
    §3.6). `soft` failures are reported but never retried automatically.

    On exhausted heal rounds, `default_for(key, original_value)` supplies the no-silent-drop
    fallback (default: the original item's own value) and the returned `soft` dict records
    every such key as `"FAILED:<reason>"` — never blank, never silently dropped.

    Never raises on a model or parse failure — a dead attempt re-prompts for valid JSON and is
    caught uniformly by the next round's `verify_fn`, exactly like any other named defect.

    `schema` (optional, default `None` — every existing caller is byte-for-byte unaffected)
    passes straight through to every `call_model` attempt this loop makes, including heal
    re-prompts: `call_model`'s own constrained-decoding contract (measured 2026-09-01 against
    `google/gemma-4-26b-a4b-qat`) makes a schema-violating token unsampleable, which is strictly
    stronger than a post-hoc `verify_fn` re-prompt and is why a caller with a real JSON Schema for
    its draft shape should supply one here rather than relying on the heal loop alone to talk the
    model into a required key it keeps omitting.
    """
    if config is None:
        config = load_config()
    heal_budget = config.max_heal if max_heal is None else max_heal
    build_heal_user = build_heal_user or _default_heal_user
    default_for = default_for or (lambda key, original: original)

    user = build_user(items)
    out: dict = {}
    for _ in range(heal_budget + 1):
        try:
            out = extract_json(call_model(system, user, config=config, schema=schema))
        except (ValueError, json.JSONDecodeError, RuntimeError) as e:
            user = (f"Your previous output could not be parsed as valid JSON ({e}). "
                    f"Re-emit ONLY a strictly-valid JSON object for:\n"
                    f"{json.dumps(items, ensure_ascii=False)}")
            continue
        hard, soft = verify_fn(items, out)
        if not hard:
            return out, soft
        user = build_heal_user(items, out, hard)

    hard, soft = verify_fn(items, out)
    for key in hard:
        out[key] = default_for(key, items.get(key, out.get(key)))
    return out, {**soft, **{k: f"FAILED:{r}" for k, r in hard.items()}}
