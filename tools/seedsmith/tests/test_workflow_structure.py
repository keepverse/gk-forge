"""G2.1 — structural assertions about the workflow package. NO model, NO network, and (mostly)
no LangGraph. These are the tests that keep the seam real.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parent.parent / "seedsmith" / "workflow"


def _py_files(*subdirs: str) -> "list[Path]":
    out: "list[Path]" = []
    for d in subdirs:
        base = WORKFLOW / d if d else WORKFLOW
        out.extend(p for p in base.glob("*.py"))
    return out


# ---- The seam: the single most important constraint in spec-workflow-runtime.md §2.1 ----------


def test_nodes_and_state_never_import_langgraph():
    """⛔ THE DELIVERABLE. LangGraph shipped 10 releases in one month; if it must ever be replaced,
    every node must survive unchanged and only `graphs/` be rewritten. A framework that has spread
    through the codebase cannot be removed — so this is enforced by grep, not by discipline."""
    offenders = []
    for path in _py_files("", "nodes", "validators"):
        # Parse the AST rather than grepping text: the rule is "must not IMPORT the engine", not
        # "must not mention it" — these modules legitimately discuss the seam in their docstrings.
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            if any(m.split(".")[0] == "langgraph" for m in mods):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], f"LangGraph imported outside graphs/: {offenders}"


def test_no_second_authoring_pipeline_shape_exists():
    """T5.0 (`shared-authoring-shape`) — `base.py` is the ONE place `StateGraph` is instantiated.
    Every other module under `graphs/` must wire `build_generation_graph`, never construct its own
    `StateGraph(...)` — a second construction call IS a forked pipeline shape, the exact defect this
    task's own ⛔ audit finding names ("T7.1 forks or refactors" if extraction does not precede
    first use). Parsed via AST, not grepped, so a `StateGraph` mentioned only in a docstring or a
    comment is never a false positive."""
    offenders = []
    for path in _py_files("graphs"):
        if path.name in ("base.py", "__init__.py"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "StateGraph":
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], f"a second pipeline shape constructs its own StateGraph: {offenders}"


def test_graphs_package_is_the_only_langgraph_importer():
    found = False
    for path in _py_files("graphs"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                    else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            found = found or any(m.split(".")[0] == "langgraph" for m in mods)
    assert found, "graphs/ should be where the engine lives"


def test_state_has_no_message_accumulator():
    """The context-overflow failure mode is intermediate output accumulating across steps."""
    from seedsmith.workflow.state import GenerationState

    assert "messages" not in GenerationState.__annotations__
    for field in GenerationState.__annotations__:
        assert not field.endswith("_history"), f"{field} looks like an accumulator"


def test_importing_the_workflow_package_does_not_require_langgraph():
    """The measurement half of seedsmith must keep working without the `workflow` extra."""
    import seedsmith.workflow as wf

    assert wf.new_state("d0")["outcome"] == "pending"


# ---- Nodes are plain functions ------------------------------------------------------------------


def test_a_node_is_callable_with_a_plain_dict():
    from seedsmith.workflow.nodes.persist import escalate_node

    assert escalate_node({"subject_id": "d0"}) == {"outcome": "escalated"}


def test_generate_node_appends_named_defects_on_a_repair_pass():
    from seedsmith.workflow.nodes.generate import make_generate_node

    seen: "list[str]" = []

    def fake_call(system, user, *, config=None, schema=None):
        seen.append(user)
        return '{"ok": true}'

    node = make_generate_node(system="sys", call=fake_call)
    node({"brief": "BRIEF", "defects": ["uses no motif"], "attempts": 1})
    assert "uses no motif" in seen[0], "a bare retry teaches the model nothing"


def test_generate_node_increments_attempts():
    from seedsmith.workflow.nodes.generate import make_generate_node

    node = make_generate_node(system="s", call=lambda *a, **k: '{"a": 1}')
    assert node({"brief": "b", "attempts": 2})["attempts"] == 3


# ---- Bounded loops: stop #1 (routing) -----------------------------------------------------------


def test_route_persists_when_clean():
    lg = pytest.importorskip("seedsmith.workflow.graphs.base")
    assert lg.route_after_validate({"defects": [], "attempts": 1}) == "persist"


def test_route_repairs_while_budget_remains():
    lg = pytest.importorskip("seedsmith.workflow.graphs.base")
    assert lg.route_after_validate({"defects": ["x"], "attempts": 1}) == "generate"


def test_route_escalates_when_budget_is_spent():
    """Exhausting retries is an OUTCOME, never a silent give-up."""
    lg = pytest.importorskip("seedsmith.workflow.graphs.base")
    assert lg.route_after_validate({"defects": ["x"], "attempts": 3}) == "escalate"


# ---- Graph shape, asserted offline ---------------------------------------------------------------


def test_graph_structure_is_inspectable_without_a_model_or_network():
    pytest.importorskip("langgraph.graph")
    from seedsmith.workflow.graphs.base import build_generation_graph

    app = build_generation_graph(
        generate=lambda s: {"draft": {}, "attempts": s.get("attempts", 0) + 1},
        validate=lambda s: {"defects": []},
        persist=lambda s: {"outcome": "persisted"},
    )
    nodes = set(app.get_graph().nodes)
    assert {"generate", "validate", "persist", "escalate"} <= nodes
    assert "mermaid" in app.get_graph().draw_mermaid().lower() or app.get_graph().draw_mermaid()
