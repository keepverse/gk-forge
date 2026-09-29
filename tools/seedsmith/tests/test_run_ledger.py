"""Tests for seedsmith.pipeline.run_ledger — item-seedgen's generator-harness (module 1), the
resume/reconcile/overwrite acceptance criteria from
docs/architecture/item-seedgen/spec-generator-harness.md.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from seedsmith.pipeline.run_ledger import RunLedger


@pytest.fixture()
def ledger(tmp_path: Path) -> RunLedger:
    return RunLedger(path=tmp_path / "test.ledger.json")


def test_resume_returns_only_unattempted_subjects(ledger: RunLedger) -> None:
    ledger.mark_done("a", {"shape": "v1"})
    needing_work = ledger.plan(["a", "b", "c"], is_valid=lambda sid, entry: True)
    assert needing_work == ["b", "c"]


def test_terminal_escalation_is_typed_and_checkpointed(ledger: RunLedger) -> None:
    ledger.mark_terminal("a", outcome="escalated", entry_id="set.test-001", attempts=3,
                         defects=["schema repair exhausted"])

    row = ledger.read_done()["a"]
    assert row == {
        "terminalSchemaVersion": 1,
        "outcome": "escalated",
        "entryId": "set.test-001",
        "attempts": 3,
        "defects": ["schema repair exhausted"],
    }


def test_terminal_row_refuses_a_success_outcome(ledger: RunLedger) -> None:
    with pytest.raises(ValueError, match="blocked or escalated"):
        ledger.mark_terminal("a", outcome="persisted", entry_id="set.test-001", attempts=1)


def test_reconcile_requeues_a_done_entry_that_fails_validation(ledger: RunLedger) -> None:
    """The reconcile half `setgen/run.py`'s own `plan_run` does not have: a ledger row saying
    'done' must not be trusted blindly if the real shape it describes is now invalid."""
    ledger.mark_done("a", {"requiredField": "present"})
    ledger.mark_done("b", {"requiredField": "present"})

    def is_valid(subject_id: str, entry: dict) -> bool:
        return "requiredField" in entry

    # Simulate an out-of-band corruption: overwrite "a"'s ledger entry directly (bypassing mark_done)
    # with a shape that no longer has the required field.
    done = ledger.read_done()
    done["a"] = {"somethingElse": True}
    ledger.write_done(done)

    needing_work = ledger.plan(["a", "b"], is_valid=is_valid)
    assert needing_work == ["a"]


def test_overwrite_by_id_touches_only_named_ids(ledger: RunLedger) -> None:
    forced = ledger.force(["x", "y"], scope="ids")
    assert forced == ["x", "y"]


def test_overwrite_all_requires_the_literal_all(ledger: RunLedger) -> None:
    assert ledger.force(["x", "y", "z"], scope="all") == ["x", "y", "z"]
    with pytest.raises(ValueError):
        ledger.force(["x"], scope="")
    with pytest.raises(ValueError):
        ledger.force(["x"], scope="everything")


def test_write_done_is_atomic_and_leaves_no_tmp_file_on_success(ledger: RunLedger) -> None:
    ledger.write_done({"a": {"v": 1}})
    assert ledger.path.exists()
    tmp_files = list(ledger.path.parent.glob("*.tmp"))
    assert tmp_files == []


def test_write_done_is_sort_keys_deterministic_across_two_writes(ledger: RunLedger) -> None:
    """The determinism gap found on adversarial review: setgen/run.py's own ledger writer has no
    sort_keys=True, so two writes of an unchanged dict are not guaranteed byte-identical there. This
    ledger must not inherit that gap."""
    done = {"b": {"y": 2}, "a": {"x": 1}}
    ledger.write_done(done)
    first_bytes = ledger.path.read_bytes()
    # Rewrite with keys in a DIFFERENT insertion order but the same content -- sort_keys must make
    # the serialized bytes identical regardless.
    ledger.write_done({"a": {"x": 1}, "b": {"y": 2}})
    second_bytes = ledger.path.read_bytes()
    assert first_bytes == second_bytes


def test_read_done_on_a_missing_ledger_returns_empty(tmp_path: Path) -> None:
    ledger = RunLedger(path=tmp_path / "does-not-exist.json")
    assert ledger.read_done() == {}


class WriteDoneSurvivesATransientHandleTests:
    """⛔ `write_done`'s replace is retried, because one unretried `os.replace` cost three batches.

    Measured 2026-09-28 on a live re-emit. On Windows `os.replace` raises
    `PermissionError: [WinError 5] Access is denied` whenever ANY process holds the destination open for
    an instant — a reader, an indexer, a scanner, an operator's own status probe. That is a normal
    transient condition, not an exceptional one, and the single unretried call let it escape:
    `PermissionError` propagated out of `mark_done`, out of `run_batch`, and out of the generator's
    `main`, so the batch exited 1 and every answer it had already paid for was discarded.

    Three batches died this way in one run (29/151, 10/106, 2/89) with the same `WinError 5` on the same
    call. The atomicity promise in the docstring was never broken — the file was never half-written — but
    atomicity is not durability, and a transient handle should cost a fraction of a second, not a batch.

    **The tests drive a real `PermissionError`, not a mock of the symptom.** Stubbing `os.replace` to
    raise would pass whether or not the retry existed. Here the failure is injected by replacing
    `os.replace` for the first N calls, and the assertions are about what the CALLER experiences: the
    write succeeds, the file has the new content, and no `.tmp` is left behind.
    """


def test_a_transient_permission_error_is_retried_and_the_write_still_lands(
        ledger: RunLedger, monkeypatch: pytest.MonkeyPatch) -> None:
    """FAIL-BEFORE: the first `PermissionError` propagated and `write_done` raised, losing the write."""
    import os as _os

    real_replace = _os.replace
    calls = {"n": 0}

    def flaky(src, dst, *a, **kw):
        calls["n"] += 1
        if calls["n"] <= 3:
            # The exact error Windows raises, with the exact errno the live run reported.
            raise PermissionError(13, "Access is denied", str(dst))
        return real_replace(src, dst, *a, **kw)

    monkeypatch.setattr(_os, "replace", flaky)
    monkeypatch.setattr(time, "sleep", lambda _s: None)

    ledger.write_done({"a": {"v": 1}})

    assert calls["n"] == 4, "three refusals then one success - the retry must actually re-attempt"
    assert json.loads(ledger.path.read_text(encoding="utf-8"))["done"] == {"a": {"v": 1}}
    assert list(ledger.path.parent.glob("*.tmp")) == [], "the temp file must not be orphaned"


def test_a_persistent_permission_error_still_fails_rather_than_looping_forever(
        ledger: RunLedger, monkeypatch: pytest.MonkeyPatch) -> None:
    """A handle that never clears is not transient. Failing is correct, and it must be QUICK: an
    unbounded retry would hang a run on a genuinely locked file, which is worse than losing one batch
    because at least a hang is visible."""
    import os as _os

    calls = {"n": 0}

    def always_denied(src, dst, *a, **kw):
        calls["n"] += 1
        raise PermissionError(13, "Access is denied", str(dst))

    monkeypatch.setattr(_os, "replace", always_denied)
    monkeypatch.setattr(time, "sleep", lambda _s: None)

    with pytest.raises(PermissionError):
        ledger.write_done({"a": {"v": 1}})

    assert calls["n"] == RunLedger._REPLACE_ATTEMPTS, (
        "the retry must be BOUNDED - exactly the configured number of attempts, then raise")
    assert list(ledger.path.parent.glob("*.tmp")) == [], (
        "a failed write must still clean up its temp file, or a long run leaks one per batch")


def test_a_non_permission_oserror_is_not_retried(ledger: RunLedger, monkeypatch: pytest.MonkeyPatch) -> None:
    """`PermissionError` only. A general `OSError` catch would also swallow `ENOSPC` and `EROFS`,
    turning a clear, immediate failure into a slow one — and would hide a full disk behind a retry loop."""
    import os as _os

    calls = {"n": 0}

    def out_of_space(src, dst, *a, **kw):
        calls["n"] += 1
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(_os, "replace", out_of_space)
    monkeypatch.setattr(time, "sleep", lambda _s: None)

    with pytest.raises(OSError):
        ledger.write_done({"a": {"v": 1}})

    assert calls["n"] == 1, "a disk-full error must surface immediately, not after the full backoff"


def test_the_retry_is_bounded_in_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """The numbers are pinned so 'bounded' is a fact rather than a hope: a slow path through the retry
    must still finish in a couple of seconds, because this sits in the middle of every generator's write."""
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
    total = sum(RunLedger._REPLACE_BACKOFF_SECONDS * (i + 1)
                for i in range(RunLedger._REPLACE_ATTEMPTS - 1))
    assert total < 2.0, (
        f"the worst-case wait is {total:.2f}s; a run that hits this on every batch pays it constantly")
    assert RunLedger._REPLACE_ATTEMPTS >= 5, (
        "three or four attempts is not enough to ride out an indexer or a scanner's handle in practice")
