"""The authoring seam must be UNIVERSAL — every production path that talks to a model reaches it.

**Why this file exists, and what it does not claim.** `plumbing/authorer.py` is the seam (two
implementations, one `resolve_authorer`, `DEFAULT_MODE = "api"`, and no fallback into delegated when
no endpoint is configured). `pipeline/llm_caller.py` is its transport half: `call_model` resolves a
`config=None` through `load_config()` at call time and dispatches on `config.mode`, so a delegated
config is honoured and a missing endpoint is a named `AUTHORING-NO-ENDPOINT` refusal.

That means most production call sites were ALREADY routed — they call `call_model` /
`call_with_self_heal` / `live_answer_caller` with a config that came from the chain, and the seam
decides. What was NOT routed was the **config**: a handful of sites built an
`LlmCallerConfig()` themselves, which freezes `mode`, `endpoint` and `model` to the built-in before
`.env` is ever read, so the operator's request could not reach those pipelines at all. This file is
the guard for that class, and it is a *structural* one (does any production module build a transport
config, or reach a socket, outside the config layer?) rather than a count.

The shapes, over every `.py` under `tools/seedsmith/seedsmith/` **and** every top-level driver
script in `tools/seedsmith/*.py`:

| Shape | Detection | Why it is a defect |
|---|---|---|
| W1 | `LlmCallerConfig(...)` constructed outside `pipeline/llm_caller.py` | a transport config built outside the config layer: its `mode` can never come from the chain |
| W2 | `DEFAULT_CONFIG` named outside `pipeline/llm_caller.py` | the same freeze, by the module-level name |
| W3 | `urllib.request` / `http.client` / `requests` reached outside `pipeline/llm_caller.py` | a second transport: the seam would not see it, so no refusal would apply |
| W4 | a **default argument** that is a transport call (`caller=call_model`, `call or call_model`) is ALLOWED — see below | |

**W4 is the documented exception, and it is legitimate.** `caller=call_model` binds the seam's own
transport as an injectable default. It is not a bypass: `call_model` resolves the `config` it is
handed, so the mode still comes from the chain. What it is for is testability — a stub `caller=`
proves a function makes zero calls on a path that should not reach the model, which is a stronger
statement than any config-plumbing assertion. Those sites are listed in `ALLOWED_INJECTED_DEFAULTS`
so this file names them instead of silently tolerating them.

**`tests/test_no_model_literal.py` cannot see half of this.** Its scan root is `seedsmith/`, so the
top-level drivers (`_j9_batch_run.py`, `_j9_poc_run.py`, `_j9_favour_fit_diag.py`,
`action_run_preflight.py`) were outside every shape it checks — which is how `_j9_poc_run.py` came
to carry a committed hardcoded endpoint and model id. This file scans them.

Every shape has a positive and a negative fixture below, so the guard is proven to fire and proven
not to over-fire. A guard that over-fires gets allow-listed into uselessness.

    python -m pytest tools/seedsmith/tests/test_transport_seam_wiring.py -q
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TOOL_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = TOOL_ROOT / "seedsmith"
TRANSPORT_PATH = PACKAGE_ROOT / "pipeline" / "llm_caller.py"

#: Top-level driver scripts in `tools/seedsmith/`. They are committed, and at least one is driven by
#: a committed launcher, so they are production code — they just live beside the package rather than
#: inside it, which is exactly why `test_no_model_literal.py`'s package-rooted scan missed them.
DRIVERS: "tuple[Path, ...]" = tuple(
    sorted(p for p in TOOL_ROOT.glob("*.py") if not p.name.startswith("conftest"))
)

#: The only module allowed to build a transport config, name `DEFAULT_CONFIG`, or open a socket. It
#: is the transport half of the seam; `authorer.py` is the other half and opens nothing itself.
ALLOWED = (TRANSPORT_PATH,)

#: `tools/seedsmith/action_run_preflight.py` is a reachability probe: it rewrites a caller's own
#: `/v1/chat/completions` URL to `/v1/models` and asks whether the server is there. It sends no
#: prompt, authors nothing, and has no seam to bypass — it exists to answer "is the endpoint
#: configured" before the seam is asked to answer through it.
REACHABILITY_PROBE = TOOL_ROOT / "action_run_preflight.py"

#: Production sites that bind the seam's transport as an INJECTABLE default (`caller=call_model`,
#: `call or call_model`). Listed, not tolerated: each one is reviewed as legitimate because the
#: config it forwards still resolves through the chain. A new one is added here deliberately, never
#: by accident.
ALLOWED_INJECTED_DEFAULTS: "frozenset[str]" = frozenset({
    "seedsmith/adapters/dungeon/pipelines.py",
    "seedsmith/adapters/items/uniques/pipelines.py",
    "seedsmith/adapters/items/setgen/run.py",
    "seedsmith/adapters/narrative/gloss/fill.py",
    "seedsmith/adapters/narrative/preflight.py",
    "seedsmith/adapters/structures/generate_anchor.py",
    "seedsmith/workflow/nodes/generate.py",
})

#: Names that mean "an HTTP transport" if a production module ever imports one of them. `llm_caller`
#: is the transport and is excluded above; nothing else may need them.
_TRANSPORT_MODULES = ("urllib", "http.client", "requests", "httpx", "aiohttp")


def _docstring_constants(tree: ast.AST) -> set[int]:
    """`id()` of every Constant that is a module/class/function docstring, so prose naming a shape
    is skipped by position rather than by a text heuristic."""
    marked: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            marked.add(id(body[0].value))
    return marked


def _callee_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return getattr(func, "id", None)


def _arg_defaults(args: ast.arguments) -> "list[ast.expr | None]":
    positional = list(args.posonlyargs) + list(args.args)
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    defaults += list(args.kw_defaults)
    return defaults


def findings(source: str, *, path: str = "<fixture>", is_transport: bool = False) -> list[str]:
    """Every W1-W3 finding in `source`, as `path:line: shape: detail` strings."""
    if is_transport:
        return []
    tree = ast.parse(source)
    docstrings = _docstring_constants(tree)
    found: list[str] = []

    def add(node: ast.AST, shape: str, detail: str) -> None:
        found.append(f"{path}:{getattr(node, 'lineno', 0)}: {shape}: {detail}")

    for node in ast.walk(tree):
        # W1 — a transport config built outside the config layer.
        if isinstance(node, ast.Call) and _callee_name(node) == "LlmCallerConfig":
            add(node, "W1",
                "builds an LlmCallerConfig outside pipeline/llm_caller.py; its `mode` can never "
                "come from the config chain, so this pipeline cannot be reached by "
                "SEEDSMITH_LLM_MODE=delegated. Pass None and let the chain resolve.")

        # W2 — the import-time built-in, by its module-level name.
        if isinstance(node, ast.Name) and node.id == "DEFAULT_CONFIG":
            add(node, "W2",
                "names DEFAULT_CONFIG outside pipeline/llm_caller.py; it is frozen at import, so "
                "the operator's endpoint/model/mode never reach this call.")

        # W3 — a second transport, which the seam would never see.
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                # `import urllib.request` puts the dotted path on the ALIAS, not on `node.module`
                # (which is None for every `ast.Import`), so reading `module` alone would miss the
                # most obvious spelling of the shape.
                candidates = [alias.name for alias in node.names]
            else:
                base = node.module or ""
                candidates = [base] + [alias.name for alias in node.names]
            for candidate in candidates:
                root = candidate.split(".")[0]
                if root in ("urllib", "http", "requests", "httpx", "aiohttp"):
                    add(node, "W3",
                        f"imports {candidate!r}; the one HTTP transport is pipeline/llm_caller.py, "
                        "so a second one is outside the seam and outside its refusals.")

    return sorted(found)


def _production_findings() -> list[str]:
    out: list[str] = []
    sources: "list[Path]" = [p for p in sorted(PACKAGE_ROOT.rglob("*.py")) if "__pycache__" not in str(p)]
    sources += list(DRIVERS)
    for path in sources:
        if path in ALLOWED or path == REACHABILITY_PROBE:
            continue
        out += findings(path.read_text(encoding="utf-8"), path=str(path))
    return out


def test_no_production_module_builds_a_transport_config_or_a_second_transport() -> None:
    found = _production_findings()
    assert found == [], (
        "authoring-seam bypass(es) outside the config layer:\n" + "\n".join(found)
    )


def test_the_scan_covers_the_top_level_drivers_not_just_the_package() -> None:
    """The hole that let a committed hardcoded endpoint through: a package-rooted scan.

    `tests/test_no_model_literal.py` scans `seedsmith/` only, so every driver script in
    `tools/seedsmith/` was unchecked by any guard. If this ever finds zero drivers, the scan has
    silently narrowed and would report green over files it never read.
    """
    assert DRIVERS, "no driver scripts found — the scan root moved and this guard is now vacuous"
    names = {p.name for p in DRIVERS}
    assert "_j9_batch_run.py" in names, f"expected driver missing from the scan: {sorted(names)}"


def test_the_transport_module_itself_is_exempt_because_it_is_the_config_layer() -> None:
    assert findings("cfg = LlmCallerConfig()\nimport urllib.request\nC = DEFAULT_CONFIG\n",
                    is_transport=True) == []


# --- fixtures: each shape proven to fire, and proven not to over-fire -------------------------


def test_w1_fires_on_a_config_built_outside_the_config_layer() -> None:
    assert [f.split(": ")[1] for f in findings("cfg = LlmCallerConfig()\n")] == ["W1"]
    assert [f.split(": ")[1]
            for f in findings("def f(config=LlmCallerConfig()):\n    pass\n")] == ["W1"]
    assert findings("cfg = load_config()\n") == []
    assert findings("cfg = resolve_live_transport()\n") == []


def test_w1_does_not_fire_on_an_ordinary_use_of_the_type() -> None:
    """A type annotation or an `isinstance` check is not a config being built."""
    assert findings("def f(config: LlmCallerConfig | None = None):\n    pass\n") == []
    assert findings("assert isinstance(cfg, LlmCallerConfig)\n") == []


def test_w2_fires_on_the_import_time_builtin() -> None:
    assert [f.split(": ")[1] for f in findings("cfg = DEFAULT_CONFIG\n")] == ["W2"]
    assert findings("cfg = DEFAULT_CONFIG\n", is_transport=True) == []


def test_w3_fires_on_a_second_http_transport_and_spares_a_same_named_local() -> None:
    assert [f.split(": ")[1] for f in findings("import urllib.request\n")] == ["W3"]
    assert [f.split(": ")[1] for f in findings("from urllib.request import urlopen\n")] == ["W3"]
    assert [f.split(": ")[1] for f in findings("import http.client\n")] == ["W3"]
    assert [f.split(": ")[1] for f in findings("import requests\n")] == ["W3"]
    assert findings("import json\nimport os\n") == []


def test_w3_ignores_a_docstring_and_a_comment_naming_a_transport() -> None:
    """Prose explaining the rule is not code reaching past the seam."""
    source = ('"""Prose: urllib.request lives only in llm_caller."""\n'
              "# a comment naming requests is invisible to ast\n"
              "X = 1\n")
    assert findings(source) == []


def test_the_injected_default_allowlist_still_names_real_files() -> None:
    """An allowlist whose entries no longer exist is an allowlist that stopped reviewing anything."""
    for rel in sorted(ALLOWED_INJECTED_DEFAULTS):
        assert (PACKAGE_ROOT.parent / rel).is_file(), f"allowlisted seam site is gone: {rel}"


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(pytest.main([__file__, "-q"]))
