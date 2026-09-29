"""The one place that knows how to survive a Windows sharing violation.

The defect this pins is real and it was measured, not imagined. `os.replace` on Windows raises
`PermissionError: [WinError 5] Access is denied` whenever ANY process holds the destination open for an
instant - a reader, a search indexer, an antivirus scanner, an operator's own status probe. A live re-emit
lost three batches to it at `materialgen.run._write_entries:287`, on the write that persists the corpus
itself, so each failure threw away every answer the batch had already paid for.

These tests drive a real `PermissionError` at the syscall boundary rather than mocking the symptom.
Stubbing `os.replace` to raise unconditionally would pass whether or not a retry existed, and would not
tell anyone whether the retry is BOUNDED, whether it retries the right failures, or whether it costs more
time than the failure it prevents.
"""
from __future__ import annotations

import os
import time

import pytest

from seedsmith.pipeline import atomic_replace
from seedsmith.pipeline.atomic_replace import replace_with_retry, worst_case_seconds


def _deny_os_replace(monkeypatch: pytest.MonkeyPatch, times: int, exc: "BaseException | None" = None):
    """Make the first `times` replace attempts fail, then let the real one through."""
    import tempfile as _tf
    from pathlib import Path

    real_replace = os.replace
    calls = {"n": 0}

    def flaky(src, dst, *a, **kw):
        calls["n"] += 1
        if calls["n"] <= times:
            raise (exc or PermissionError(13, "Access is denied", str(dst)))
        return real_replace(src, dst, *a, **kw)

    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr(time, "sleep", lambda _s: None)   # never actually sleep in a unit test
    return calls, _tf, Path


def test_a_transient_denial_is_retried_and_the_file_still_lands(tmp_path, monkeypatch) -> None:
    """FAIL-BEFORE at the real call site: the first `PermissionError` propagated and the write was lost."""
    import json

    target = tmp_path / "materials.json"
    src = tmp_path / "staged.tmp"
    src.write_text(json.dumps({"entries": [1, 2, 3]}), encoding="utf-8")
    target.write_text(json.dumps({"entries": []}), encoding="utf-8")

    calls, _, _ = _deny_os_replace(monkeypatch, 3)
    replace_with_retry(src, target)

    assert calls["n"] == 4, "three refusals then one success - the retry must actually re-attempt"
    assert json.loads(target.read_text(encoding="utf-8"))["entries"] == [1, 2, 3], (
        "the destination must hold the new content: the whole point of the retry is that a transient "
        "handle does not cost the write")
    assert list(tmp_path.glob("*.tmp")) == [], (
        "a successful write must leave no temp file behind. This asserts the property a CALLER depends on "
        "rather than a claim about the syscall's internals: I first asserted `not src.exists()` here, it "
        "failed, and a direct probe of `os.replace` showed the source IS consumed (src exists=False, no "
        "`.tmp` left) on both the plain and the mkstemp path. So the assertion was measuring the "
        "monkeypatched harness rather than the helper, and the leftover check is the one that means "
        "something to `write_done` and `_write_entries`.")


def test_a_persistent_denial_fails_instead_of_looping_forever(tmp_path, monkeypatch) -> None:
    """A handle that never clears is not transient. Failing is correct; failing QUICKLY is also correct,
    because an unbounded retry hangs a run on a locked file and a silent hang is worse than a loud failure."""
    src = tmp_path / "staged.tmp"
    src.write_text("{}", encoding="utf-8")
    calls, _, _ = _deny_os_replace(monkeypatch, 10_000)

    with pytest.raises(PermissionError):
        replace_with_retry(src, tmp_path / "target.json")

    assert calls["n"] == atomic_replace.ATTEMPTS, (
        "exactly the configured number of attempts, then raise - not one more, not one fewer")


def test_only_permission_error_is_retried(tmp_path, monkeypatch) -> None:
    """`PermissionError` only. A general `OSError` catch would also swallow `ENOSPC`, `EROFS` and a real
    path error, turning a clear immediate failure into a slow one - and would hide a full disk behind a
    retry loop, which is a worse failure than the one it was papering over."""
    src = tmp_path / "staged.tmp"
    src.write_text("{}", encoding="utf-8")
    for error in (OSError(28, "No space left on device"),
                  OSError(30, "Read-only file system"),
                  FileNotFoundError(2, "No such file or directory")):
        calls, _, _ = _deny_os_replace(monkeypatch, 1, exc=error)
        with pytest.raises(type(error)):
            replace_with_retry(src, tmp_path / f"target-{error.errno}.json")
        assert calls["n"] == 1, (
            f"{error.errno} must surface on the first attempt; retrying it converts a clear failure into a "
            f"slow one and hides a real condition")


def test_the_worst_case_wait_is_bounded_below_two_seconds() -> None:
    """The attempts count and the backoff base are ONE number: the wait is
    `base * (1 + 2 + ... + attempts-1)`, so a linear ramp over 12 attempts is NOT "a fraction of a second"
    however small the base looks. This suite exists because that arithmetic was got wrong once already -
    12 attempts at 0.15s is 9.9 seconds, chosen while believing it was negligible."""
    total = worst_case_seconds()
    assert total < 2.0, f"the worst case is {total:.2f}s, and this sits inside every generator's write"
    assert atomic_replace.ATTEMPTS >= 5, (
        "three or four attempts is not enough to ride out an indexer or a scanner in practice - the live "
        "failures were an operator's own status probe holding the file open")


def test_a_single_attempt_is_allowed_and_means_no_retry(tmp_path, monkeypatch) -> None:
    """`attempts=1` is the pre-fix behaviour expressed as a choice, and a caller may want exactly that."""
    src = tmp_path / "staged.tmp"
    src.write_text("{}", encoding="utf-8")
    calls, _, _ = _deny_os_replace(monkeypatch, 5)
    with pytest.raises(PermissionError):
        replace_with_retry(src, tmp_path / "target.json", attempts=1)
    assert calls["n"] == 1


def test_zero_attempts_is_refused_rather_than_silently_doing_nothing() -> None:
    """A replace that is never attempted is not a write. Failing loudly beats a no-op that reports success."""
    with pytest.raises(ValueError):
        replace_with_retry("a", "b", attempts=0)


def test_the_backoff_grows_so_a_slow_holder_gets_a_longer_window() -> None:
    """The sleeps are recorded rather than performed, and they must be increasing - a flat retry against a
    slow holder gives up while the holder would have cleared a moment later."""
    import tempfile as _tf
    from pathlib import Path

    slept: list[float] = []
    real_replace = os.replace

    def always_denied(src, dst, *a, **kw):
        raise PermissionError(13, "Access is denied", str(dst))

    original_sleep = time.sleep
    os.replace = always_denied
    time.sleep = lambda s: slept.append(s)
    try:
        with pytest.raises(PermissionError):
            replace_with_retry(_tf.gettempdir() + "/x", _tf.gettempdir() + "/y")
    finally:
        os.replace = real_replace
        time.sleep = original_sleep
    assert len(slept) == atomic_replace.ATTEMPTS - 1, "one sleep between each pair of attempts"
    assert slept == sorted(slept), f"the backoff must grow, not shrink: {slept}"
    assert slept[0] < slept[-1], "a flat retry gives up while a slow holder would have cleared"
