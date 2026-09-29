"""LangGraph checkpoint wiring — engine layer, so `runner.py` stays engine-free (the seam).

Owner decision 2026-09-01: `guard-dal`'s "SQL only in FusionRpg.Data" invariant protects the
SHIPPED GAME's data layer; `gk-forge/tools/seedsmith/` is dev tooling that never ships. **Scope is pinned:
sqlite3 here is checkpoint state only.** Python still never reads the game's SQLite (`types`,
`almanac_seed`, `recipes`) — that stays C#-through-the-DAL, for a reason shipping does not affect.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

__all__ = ["WorkflowEngineMissing", "open_checkpointer"]


class WorkflowEngineMissing(RuntimeError):
    """The optional `workflow` extra (or the checkpointer package inside it) is not importable.

    Declared as an extra in `gk-forge/tools/seedsmith/pyproject.toml` (`workflow = [langgraph,
    langgraph-checkpoint-sqlite]`) and pinned in `requirements.lock`, so the sanctioned environment
    always has it — but a partial install used to surface as a bare `ModuleNotFoundError: No module
    named 'langgraph.checkpoint.sqlite'` from inside a nested import, which reads as a code defect
    rather than a missing extra (measured 2026-09-23: `test_workflow_runtime`'s two checkpoint cases).
    """


def open_checkpointer(db_path: "str | Path"):
    """Returns `(saver, connection)`. The caller closes the connection.

    Raises `WorkflowEngineMissing` naming the extra when the checkpointer package cannot be imported
    — the module's own precondition, stated where it fails rather than as an opaque `ImportError`.
    """
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as exc:
        raise WorkflowEngineMissing(
            "the workflow engine's checkpointer is not importable — install this package's `workflow` "
            "extra (`python -m pip install -r tools/seedsmith/requirements.lock`, or "
            "`pip install 'seedsmith[workflow]'`): " + str(exc)
        ) from exc

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    return SqliteSaver(conn), conn
