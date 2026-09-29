"""G2.2-G2.4 — workflow behaviour: bounded loops, checkpoint/resume, the two retry intents, fan-out.

Zero real model calls: every generate node is an injected fake.
"""
from __future__ import annotations

import pytest
import sys

pytest.importorskip("langgraph.graph")

from seedsmith.workflow.graphs.base import build_generation_graph  # noqa: E402
from seedsmith.workflow.graphs.checkpoint import (  # noqa: E402
    WorkflowEngineMissing, open_checkpointer,
)
from seedsmith.workflow.nodes.generate import MAX_ATTEMPTS, make_generate_node  # noqa: E402
from seedsmith.workflow.nodes.persist import make_persist_node  # noqa: E402
from seedsmith.workflow.nodes.validate import make_validate_node  # noqa: E402
from seedsmith.workflow.runner import resume, run_many, run_one  # noqa: E402
from seedsmith.workflow.state import new_state  # noqa: E402


def _app(*, replies, validators=(), persisted=None, calls=None):
    """Build a graph whose generate node replays `replies` in order."""
    seq = list(replies)

    def fake_call(system, user, *, config=None, schema=None):
        if calls is not None:
            calls.append(user)
        return seq.pop(0) if seq else seq_last

    seq_last = replies[-1] if replies else "{}"
    return build_generation_graph(
        generate=make_generate_node(system="sys", call=fake_call),
        validate=make_validate_node(validators),
        persist=make_persist_node(
            (lambda k, v: persisted.__setitem__(k, v)) if persisted is not None else None),
    )


def _reject_unless(word):
    def v(draft, ctx):
        return [] if word in str(draft.get("doctrine", "")) else [f"doctrine must mention {word!r}"]
    return v


# ---- Bounded loops ------------------------------------------------------------------------------


def test_a_clean_draft_persists_on_the_first_attempt():
    persisted = {}
    app = _app(replies=['{"doctrine": "uses nut"}'], validators=[_reject_unless("nut")],
               persisted=persisted)
    out = run_one(app, new_state("d0"))
    assert out["outcome"] == "persisted"
    assert out["attempts"] == 1
    assert persisted["d0"] == {"doctrine": "uses nut"}


def test_a_defective_draft_repairs_and_the_second_prompt_names_the_defect():
    calls, persisted = [], {}
    app = _app(replies=['{"doctrine": "empty"}', '{"doctrine": "uses nut"}'],
               validators=[_reject_unless("nut")], persisted=persisted, calls=calls)
    out = run_one(app, new_state("d0", brief="BRIEF"))
    assert out["outcome"] == "persisted"
    assert out["attempts"] == 2
    assert "must mention" in calls[1], "a bare retry teaches the model nothing"


def test_a_draft_that_never_clears_escalates_and_writes_nothing():
    persisted = {}
    app = _app(replies=['{"doctrine": "no"}'] * 6, validators=[_reject_unless("nut")],
               persisted=persisted)
    out = run_one(app, new_state("d0"))
    assert out["outcome"] == "escalated"
    assert out["attempts"] == MAX_ATTEMPTS
    assert persisted == {}, "nothing may be written when the gate never passed"


def test_recursion_limit_still_stops_a_deliberately_broken_router():
    """⛔ Stop #2 exercised, not merely configured. A router that never escalates would loop
    forever; the engine-level backstop must terminate it anyway."""
    import seedsmith.workflow.graphs.base as base

    original = base.route_after_validate
    base.route_after_validate = lambda state: "persist" if not state.get("defects") else "generate"
    try:
        app = _app(replies=['{"doctrine": "no"}'] * 200, validators=[_reject_unless("nut")])
        with pytest.raises(Exception) as excinfo:
            run_one(app, new_state("d0"), recursion_limit=8)
        assert "recursion" in str(excinfo.value).lower()
    finally:
        base.route_after_validate = original


# ---- Checkpoint / resume: the TRANSIENT retry intent (§2.4) --------------------------------------


def test_resume_replays_from_checkpoint_without_calling_the_model_again(tmp_path):
    """TRANSIENT retry: the previous answer is still wanted. Completed nodes must NOT re-run —
    conflating this with a quality retry is what turns a $50 batch into $200."""
    calls, persisted = [], {}
    saver, conn = open_checkpointer(tmp_path / "ckpt.sqlite")
    try:
        app = build_generation_graph(
            generate=make_generate_node(
                system="s",
                call=lambda sys_, user, *, config=None, schema=None: (
                    calls.append(user) or '{"doctrine": "uses nut"}')),
            validate=make_validate_node([_reject_unless("nut")]),
            persist=make_persist_node(lambda k, v: persisted.__setitem__(k, v)),
            checkpointer=saver,
        )
        run_one(app, new_state("d0"), thread_id="t1")
        assert len(calls) == 1

        resumed = resume(app, "t1")
        assert resumed["outcome"] == "persisted"
        assert len(calls) == 1, "resume must not re-invoke the model for completed nodes"
    finally:
        conn.close()


def test_checkpoints_are_written_and_replayable(tmp_path):
    saver, conn = open_checkpointer(tmp_path / "ckpt.sqlite")
    try:
        app = build_generation_graph(
            generate=make_generate_node(system="s",
                                        call=lambda *a, **k: '{"doctrine": "uses nut"}'),
            validate=make_validate_node([_reject_unless("nut")]),
            persist=make_persist_node(),
            checkpointer=saver,
        )
        run_one(app, new_state("d0"), thread_id="t1")
        history = list(app.get_state_history({"configurable": {"thread_id": "t1"}}))
        assert len(history) >= 3, "a crash mid-run must have something to resume from"
    finally:
        conn.close()


# ---- Fan-out --------------------------------------------------------------------------------------


def test_run_many_is_deterministic_per_subject_regardless_of_completion_order():
    app = _app(replies=['{"doctrine": "uses nut"}'] * 50, validators=[_reject_unless("nut")])
    states = [new_state(f"d{i:02d}") for i in range(12)]
    results = run_many(app, states, max_workers=4)
    assert list(results) == sorted(results)
    assert all(r["outcome"] == "persisted" for r in results.values())


def test_a_failing_subject_does_not_abort_the_batch():
    def explode(system, user, *, config=None, schema=None):
        raise RuntimeError("endpoint down")

    app = build_generation_graph(
        generate=make_generate_node(system="s", call=explode),
        validate=make_validate_node(()),
        persist=make_persist_node(),
    )
    seen = []
    results = run_many(app, [new_state("d0"), new_state("d1")], max_workers=2,
                       on_error=lambda sid, e: seen.append(sid))
    assert sorted(results) == ["d0", "d1"]
    assert all(r["outcome"] == "escalated" for r in results.values())
    assert sorted(seen) == ["d0", "d1"]


def test_a_missing_checkpointer_package_is_a_named_error_not_a_bare_import_error(monkeypatch, tmp_path):
    """The optional `workflow` extra is declared (`pyproject.toml`'s `workflow` extra,
    `requirements.lock`), so a PARTIAL install must say so where it fails. Before this,
    `open_checkpointer` raised a bare `ModuleNotFoundError: No module named
    'langgraph.checkpoint.sqlite'` from inside a nested import — measured 2026-09-23, and
    indistinguishable from a code defect. Still a failure (nothing is skipped), but a diagnosis."""
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.sqlite", None)
    with pytest.raises(WorkflowEngineMissing) as ctx:
        open_checkpointer(tmp_path / "ckpt.sqlite")
    message = str(ctx.value)
    assert "workflow" in message
    assert "requirements.lock" in message
