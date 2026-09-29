"""NS6 — the static guard that ends the hard-coded model (owner ruling R6, spec-model-config-resolve.md §4).

A model id belongs in exactly one place: the config layer (`pipeline/llm_caller.py`'s
`LlmCallerConfig` default, overridden by `.env` / `seedsmith.toml`). No adapter, helper or CLI flag
carries one, and no provenance stamp names a model nobody resolved.

Five shapes are detected over every `.py` file under `gk-forge/tools/seedsmith/seedsmith/`, excluding
`pipeline/llm_caller.py` itself. Parsing is `ast`, so a comment is invisible and a docstring is
skipped by position.

| Shape | Detection |
|---|---|
| S1 | a code string constant naming a model (a vendor stem at a TOKEN boundary) |
| S2 | a parameter named `model`/`model_id` with a string default |
| S3 | `add_argument("--model", default=X)` with X not `""`/`"unrecorded"` |
| S4 | any reference to `DEFAULT_CONFIG` outside `llm_caller.py` |
| S5 | `LlmCallerConfig(model=<string constant>)` |

Each shape has a positive and a negative fixture below, so the guard is proven to fire and proven
not to over-fire: a guard that over-fires gets allow-listed into uselessness.

    python -m pytest gk-forge/tools/seedsmith/tests/test_no_model_literal.py -q
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "seedsmith"
TRANSPORT_PATH = PACKAGE_ROOT / "pipeline" / "llm_caller.py"

#: DECLARATION, not a contract: the vendor families known today. The structural shapes S2-S5 catch
#: the defect without any list at all — this one exists to catch a *string literal* a future author
#: pastes in, and a new vendor is a reviewed one-line addition here. Matched at a token boundary
#: only: a bare substring match fires on unrelated words (`autographi-x`, `dollama`) and a guard that
#: over-fires gets allow-listed into uselessness.
VENDOR_STEMS = ("gemma", "claude", "gpt-", "qwen", "llama", "mistral", "deepseek", "kimi",
                "gemini", "phi-")

#: A vendor stem counts only at the start of the string or right after one of these.
_TOKEN_BOUNDARY = frozenset(" \t\n/\\-_:.")

#: `--model` CLI defaults that are legitimate: the empty flag (falls through to the config layer)
#: and the replay sentinel `unrecorded`.
_ALLOWED_CLI_DEFAULTS = ("", "unrecorded")


def _stem_at_boundary(text: str) -> str | None:
    """The first vendor stem in `text` that starts at a token boundary, if any."""
    lowered = text.lower()
    for stem in VENDOR_STEMS:
        start = 0
        while True:
            idx = lowered.find(stem, start)
            if idx == -1:
                break
            if idx == 0 or lowered[idx - 1] in _TOKEN_BOUNDARY:
                return stem
            start = idx + 1
    return None


def _docstring_constants(tree: ast.AST) -> set[int]:
    """`id()` of every Constant node that is a module/class/function docstring — a docstring may
    name a model (it is prose explaining the rule), and skipping it by position is what makes that
    true without a text heuristic."""
    marked: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            marked.add(id(body[0].value))
    return marked


def _arg_defaults(args: ast.arguments) -> list[tuple[ast.arg, ast.expr | None]]:
    positional = list(args.posonlyargs) + list(args.args)
    paired: list[tuple[ast.arg, ast.expr | None]] = list(
        zip(positional[len(positional) - len(args.defaults):], args.defaults))
    paired += list(zip(args.kwonlyargs, args.kw_defaults))
    return paired


def findings(source: str, *, path: str = "<fixture>", is_transport: bool = False) -> list[str]:
    """Every S1–S5 finding in `source`, as `path:line: shape: detail` strings."""
    tree = ast.parse(source)
    docstrings = _docstring_constants(tree)
    found: list[str] = []

    def add(node: ast.AST, shape: str, detail: str) -> None:
        found.append(f"{path}:{getattr(node, 'lineno', 0)}: {shape}: {detail}")

    for node in ast.walk(tree):
        # S1 — a code string constant naming a model.
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docstrings:
            stem = _stem_at_boundary(node.value)
            if stem is not None:
                add(node, "S1", f"string constant contains vendor stem {stem!r}: {node.value!r}")

        # S2 — a parameter named model/model_id with a string default.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg, default in _arg_defaults(node.args):
                if arg.arg in ("model", "model_id") and isinstance(default, ast.Constant) \
                        and isinstance(default.value, str):
                    add(default, "S2", f"parameter {arg.arg!r} defaults to a string "
                                       f"({default.value!r}) in {node.name}()")

        # S3 — a CLI --model default that is neither "" nor "unrecorded".
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "add_argument" and node.args \
                and isinstance(node.args[0], ast.Constant) and node.args[0].value == "--model":
            default = next((kw.value for kw in node.keywords if kw.arg == "default"), None)
            if default is None:
                continue
            if isinstance(default, ast.Constant) and default.value in _ALLOWED_CLI_DEFAULTS:
                continue
            add(default, "S3", f"--model default is {ast.unparse(default)!r}")

        # S4 — any reference to DEFAULT_CONFIG outside the transport module.
        if isinstance(node, ast.Name) and node.id == "DEFAULT_CONFIG" and not is_transport:
            add(node, "S4", "references DEFAULT_CONFIG outside pipeline/llm_caller.py")

        # S5 — LlmCallerConfig(model=<string constant>).
        if isinstance(node, ast.Call):
            callee = node.func
            name = callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", None)
            if name == "LlmCallerConfig":
                model_kw = next((kw for kw in node.keywords if kw.arg == "model"), None)
                if model_kw is not None and isinstance(model_kw.value, ast.Constant) \
                        and isinstance(model_kw.value.value, str):
                    add(model_kw.value, "S5",
                        f"LlmCallerConfig(model={model_kw.value.value!r})")

    return sorted(found)


def _package_findings() -> list[str]:
    out: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "__pycache__" in str(path) or path == TRANSPORT_PATH:
            # The transport is where the model id is ALLOWED to live: it is the config layer's own
            # built-in default (spec §1). The rest of the package may not name one.
            continue
        out += findings(path.read_text(encoding="utf-8"), path=str(path))
    return out


def test_package_has_no_model_literal():
    found = _package_findings()
    assert found == [], "model literal(s) outside the config layer:\n" + "\n".join(found)


# ---------------------------------------------------------------------------------------------
# Positive / negative fixture pairs — one per shape.
# ---------------------------------------------------------------------------------------------


def test_s1_fires_on_code_string_and_skips_docstring_and_comment():
    source = (
        '"""A module docstring naming gemma-4 on purpose — prose, not code."""\n'
        "# a comment naming claude-sonnet-5 is invisible to ast\n"
        "MODEL = 'google/gemma-4-26b-a4b-qat'\n"
    )
    shapes = [f.split(": ")[1] for f in findings(source)]
    assert shapes == ["S1"]


def test_s1_matches_stems_on_token_boundaries_only():
    assert [f.split(": ")[1] for f in findings("X = 'google/gemma-4'\n")] == ["S1"]
    assert [f.split(": ")[1] for f in findings("X = 'claude-sonnet'\n")] == ["S1"]
    # a stem inside a longer word is not a model id
    assert findings("X = 'autographi-x'\n") == []
    assert findings("X = 'dollama'\n") == []


def test_s2_fires_on_model_param_string_default():
    assert [f.split(": ")[1] for f in findings("def f(*, model: str = 'x'):\n    pass\n")] == ["S2"]
    assert findings("def f(*, model: str | None = None):\n    pass\n") == []
    assert findings("def f(*, model: str):\n    pass\n") == []


def test_s3_fires_on_cli_default_literal_and_on_default_config_attribute():
    assert [f.split(": ")[1]
            for f in findings("import argparse\n"
                              "p.add_argument('--model', default='combogen-reemit/1')\n")] == ["S3"]
    assert [f.split(": ")[1]
            for f in findings("import argparse\n"
                              "p.add_argument('--model', default=CONFIG.model)\n")] == ["S3"]
    assert findings("import argparse\np.add_argument('--model', default='')\n") == []
    assert findings("import argparse\np.add_argument('--model', default='unrecorded')\n") == []


def test_s4_fires_on_default_config_outside_the_transport():
    assert [f.split(": ")[1] for f in findings("C = DEFAULT_CONFIG\n")] == ["S4"]
    assert findings("C = DEFAULT_CONFIG\n", is_transport=True) == []


def test_s5_fires_on_config_built_from_a_literal():
    assert [f.split(": ")[1]
            for f in findings("cfg = LlmCallerConfig(model='combogen-reemit/1')\n")] == ["S5"]
    assert findings("cfg = LlmCallerConfig(model=resolved_model)\n") == []
    assert findings("cfg = LlmCallerConfig(model=None)\n") == []


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(pytest.main([__file__, "-q"]))
