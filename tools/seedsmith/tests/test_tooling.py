"""Tests for `seedsmith.tooling.run_tool` — the one place a missing tool becomes a NAMED refusal.

Measured 2026-09-23: six seedsmith rows (`test_combogen` x3, `test_item_name_repair` x3) reported
`FAILED` with a bare `FileNotFoundError: [WinError 2]` when `dotnet` was not on `PATH`, and all six
passed once it was. Every adapter that shells out to a C# tool documents "raises X if the tool cannot
run"; `subprocess.run` defeated that contract by raising before the caller's own `returncode` guard
could fire. These cases pin the fix.

    python -m pytest gk-forge/tools/seedsmith/tests/test_tooling.py -q
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402

import pytest  # noqa: E402

from seedsmith import tooling  # noqa: E402
from seedsmith.tooling import run_tool  # noqa: E402


class RepairRefused(RuntimeError):
    """Stands in for the repair adapters' own refusal type."""


def _missing(_args, **_kwargs):
    raise FileNotFoundError(2, "The system cannot find the file specified")


def test_a_missing_executable_raises_the_callers_own_refusal_type_naming_it(monkeypatch):
    monkeypatch.setattr(tooling.subprocess, "run", _missing)
    with pytest.raises(RepairRefused) as ctx:
        run_tool(["dotnet", "run", "--project", "x"], cwd=".", refusal=RepairRefused,
                 what="the validator's authoritative findings")
    message = str(ctx.value)
    assert "'dotnet' is not runnable here" in message
    assert "put it on PATH" in message
    assert "the validator's authoritative findings" in message


def test_the_default_refusal_is_a_runtime_error(monkeypatch):
    monkeypatch.setattr(tooling.subprocess, "run", _missing)
    with pytest.raises(RuntimeError):
        run_tool(["dotnet", "run"], cwd=".")


def test_the_completed_process_is_returned_unchanged(monkeypatch):
    completed = subprocess.CompletedProcess(args=["dotnet"], returncode=0, stdout='{"ok": true}')
    monkeypatch.setattr(tooling.subprocess, "run", lambda *a, **k: completed)
    assert run_tool(["dotnet", "run"], cwd=".") is completed


def test_input_and_stdin_are_never_passed_together(monkeypatch):
    # `subprocess.run` refuses `stdin` and `input` together, so the helper must not add the default
    # DEVNULL when the caller supplies input -- three real call sites pass a JSON payload that way.
    seen = {}

    def capture(*_args, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(args=["dotnet"], returncode=0, stdout="{}")

    monkeypatch.setattr(tooling.subprocess, "run", capture)
    run_tool(["dotnet", "run"], cwd=".", input="payload")
    assert "stdin" not in seen and seen["input"] == "payload"
    run_tool(["dotnet", "run"], cwd=".")
    assert seen["stdin"] is subprocess.DEVNULL


def test_capture_and_text_default_on_for_every_call_site(monkeypatch):
    seen = {}
    monkeypatch.setattr(tooling.subprocess, "run",
                        lambda *a, **k: (seen.update(k),
                                         subprocess.CompletedProcess(args=["dotnet"], returncode=0,
                                                                     stdout="{}"))[1])
    run_tool(["dotnet", "run"], cwd=".")
    assert seen["capture_output"] is True and seen["text"] is True


def test_no_argv_is_a_named_refusal_not_an_index_error():
    with pytest.raises(RuntimeError) as ctx:
        run_tool([], cwd=".", refusal=RepairRefused)
    assert isinstance(ctx.value, RepairRefused)
    assert "needs an argv" in str(ctx.value)
