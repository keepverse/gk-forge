"""Running a repo tool (`dotnet run --project tools/...`) from seedsmith.

Seedsmith reads its authoritative vocabularies and findings from the C# tools rather than
re-implementing them (`ItemSeedValidator --findings-json`, `--collision-groups`,
`--combo-budget-dump`, `--normalize-names`, `CreatureCorpusDump`, ...). Every adapter that does so
documents the same contract — *"Raises `RepairRefused` if the tool cannot run, because a repair
planned against a guessed list is worse than no repair"*.

**That contract was not actually delivered.** `subprocess.run(["dotnet", ...])` raises
`FileNotFoundError` (Windows `WinError 2`) *before* any caller's own `returncode` guard can run, so on
a machine without `dotnet` on `PATH` the caller got a bare `OSError` instead of the named refusal it
promises. Measured 2026-09-23: six seedsmith rows (`test_combogen` x3, `test_item_name_repair` x3)
report `FAILED` with exactly that opaque error, indistinguishable from a content defect, while all six
pass once `dotnet` is on `PATH` — the same hazard lane sgc-5 recorded on 2026-09-22 ("the wrapper
replaces the child PATH with 10 entries and hides `dotnet`, which alone 'fails' six rows that pass
without it").

`run_tool` is the one place that gap is closed: the executable is named in the refusal, and the
caller's own refusal type is preserved, so a tool-less machine reads a diagnosis rather than a
traceback. It deliberately does NOT skip or soften anything — a missing tool is still a failure.
"""
from __future__ import annotations

import subprocess
from typing import Any, Sequence

__all__ = ["run_tool"]


def run_tool(args: Sequence[str], *, cwd: str, refusal: "type[Exception]" = RuntimeError,
             what: "str | None" = None, **kwargs: Any) -> "subprocess.CompletedProcess[str]":
    """`subprocess.run(args, ...)` with a MISSING EXECUTABLE reported as `refusal`.

    `args[0]` is the executable. Every other `subprocess.run` keyword is passed through
    (`capture_output`/`text` default on, matching every call site this replaces).

    `stdin=DEVNULL` is the default because seedsmith is also driven from an MCP pipe, and a child that
    inherits that stdin can consume the caller's protocol stream — every existing call site already
    passed it. It is deliberately NOT forced when the caller supplies `input=`, since
    `subprocess.run` refuses `stdin` and `input` together.

    `refusal` is the caller's own exception type (`RepairRefused` in the repair adapters,
    `RuntimeError` where that is what the module documents), so the raised error stays the one the
    module's docstring promises.
    """
    if not args:
        raise refusal("run_tool needs an argv; got none")
    if "input" not in kwargs:
        kwargs.setdefault("stdin", subprocess.DEVNULL)
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    try:
        return subprocess.run(list(args), cwd=cwd, **kwargs)
    except FileNotFoundError as exc:
        detail = exc.strerror or str(exc)
        raise refusal(
            f"{args[0]!r} is not runnable here ({detail}) — install it, or put it on PATH"
            + (f"; needed for: {what}" if what else "")
        ) from exc
