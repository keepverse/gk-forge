"""seedsmith.workflow.runner — resume and bounded fan-out (spec-workflow-runtime.md §2.4-2.6).

⛔ **Engine-free, deliberately.** This module drives a compiled app through duck-typed `.invoke()`
and imports NOTHING from LangGraph — the checkpointer factory lives in `graphs/checkpoint.py`
instead. The seam test caught an earlier draft importing the engine here; rather than widen the
rule, the dependency was removed.

⛔ **Two retry intents, never conflated (§2.4).** Documented failure: "idempotency breaks when
outputs are stochastic", and a $50 batch retried 3x on a network blip costs $200.

  * TRANSIENT (endpoint down, timeout, 5xx) -> `resume()`: replay from checkpoint, **no new model
    call**. The previous answer is still wanted.
  * QUALITY (a validator rejected the draft) -> the graph's own `validate -> generate` edge: a
    genuinely NEW generation with the defect named.

They are different code paths on purpose. Regenerating on a network blip burns budget and churns
output; replaying a cached bad answer loops forever.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Sequence

from .state import RECURSION_LIMIT

__all__ = ["run_one", "resume", "run_many", "MAX_WORKERS"]

#: Structural constant with a reason, not a tunable: it trades local-queue saturation against
#: wall-clock. `llm_caller`'s own note applies — hammering a wedged local queue makes it worse.
#: One local model serves one request at a time; a small pool keeps it fed without stampeding it.
MAX_WORKERS = 4


def _cfg(thread_id: str, *, recursion_limit: "int | None" = None) -> dict:
    return {"configurable": {"thread_id": thread_id},
            "recursion_limit": recursion_limit or RECURSION_LIMIT}


def run_one(app, state: dict, *, thread_id: "str | None" = None,
            recursion_limit: "int | None" = None) -> dict:
    """Run one subject. `thread_id` keys the checkpoint, so resume targets exactly this subject."""
    tid = thread_id or state.get("subject_id") or "default"
    return app.invoke(state, _cfg(tid, recursion_limit=recursion_limit))


def resume(app, thread_id: str, *, recursion_limit: "int | None" = None) -> dict:
    """TRANSIENT retry (§2.4). Passing `None` as input resumes from the last checkpoint — nodes
    that already completed are NOT re-executed, so no new model call is made for them."""
    return app.invoke(None, _cfg(thread_id, recursion_limit=recursion_limit))


def run_many(app, states: "Sequence[dict]", *, max_workers: int = MAX_WORKERS,
             on_error: "Callable[[str, Exception], None] | None" = None) -> "dict[str, dict]":
    """Bounded fan-out. Results are keyed by `subject_id`, so output is deterministic per subject
    regardless of completion order — the ordering of a dict comprehension over sorted keys, not of
    whichever worker happened to finish first."""
    results: "dict[str, dict]" = {}

    def _one(st: dict):
        sid = st.get("subject_id", "")
        try:
            return sid, run_one(app, st)
        except Exception as e:  # a failing subject must not abort the batch
            if on_error is not None:
                on_error(sid, e)
            return sid, {"subject_id": sid, "outcome": "escalated", "defects": [f"runner error: {e}"]}

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        for sid, res in pool.map(_one, states):
            results[sid] = res
    return {k: results[k] for k in sorted(results)}
