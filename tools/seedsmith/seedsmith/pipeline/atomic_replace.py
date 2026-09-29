"""`os.replace` that survives a transient Windows handle — the one place that knows how.

⛔ **Real defect, measured 2026-09-28 on a live re-emit, at two call sites in the same run.**

`os.replace` on Windows raises `PermissionError: [WinError 5] Access is denied` whenever ANY process holds
the destination open for an instant: a reader, a search indexer, an antivirus scanner, another agent's
status probe. That is a **normal, transient condition on this platform, not an exceptional one.** Treated
as exceptional, it is fatal — and in a generator it is fatal *after* the work is done, so the caller loses
everything the run just paid for:

    PermissionError: [WinError 5] Access is denied:
      '...\\data\\seed\\items\\materials\\tmp27lz4xai.tmp' -> '...\\materials.json'
      at adapters/items/materialgen/run.py:287 in _write_entries

That killed batches 4, 10 and 29 of the same pass. An earlier fix in this programme had already added a
retry to `pipeline/run_ledger.py` — **and that is what makes this module necessary rather than optional.**
The two functions were documented as mirroring each other; `write_done`'s docstring said "mirroring
`RunLedger.write_done`'s own temp-file-then-`os.replace` discipline", and `_write_entries` said the same
thing back. One got the retry, one did not, and the one that did not is the one that kept costing batches.
A second pasted retry loop would reproduce the drift on schedule. So the retry lives here, once.

**There are 19 unretired call sites in this package.** This module is the mechanism; converting the rest is
tracked with exact locations in the session record rather than swept into a change made mid-run, because
they belong to other programs' generators.

## Why the retry is as narrow as it is

* **`PermissionError` only.** A general `OSError` catch would also swallow `ENOSPC`, `EROFS` and a genuine
  path error, turning a clear immediate failure into a slow one. Retrying everything is a defect in the
  other direction, and it is the same mistake as a bare retry: not asking which failure you are papering
  over.
* **The attempt count and the backoff base are ONE number.** The worst-case wait is
  `base * (1 + 2 + ... + attempts-1)`, so a linear ramp over 12 attempts is not "a fraction of a second"
  however small the base looks. The first constants chosen in this programme were 12 and 0.15s, which is
  **9.9 seconds**, and a test caught it. `test_atomic_replace.py` pins the PRODUCT, not either half.
* **Bounded.** A handle that has not cleared in a couple of seconds is not transient. An unbounded retry
  would hang a run forever on a genuinely locked file, which is worse than losing one write, because at
  least a hang is visible and a silent loop is not.
* **Only the replace is retried, never the temp file's own write.** A failed write is a real error —
  re-rolling it would paper over a full disk. The caller keeps ownership of temp-file cleanup, because
  that is where the caller's own `except` already lives and moving it would change every call site's
  cleanup semantics.
"""
from __future__ import annotations

import os
import time

#: Attempts, and the linear backoff base. See the module docstring: the PRODUCT of these is the number
#: that matters. 0.025s over 12 attempts is 1.65s, asserted below 2.0s by the suite.
ATTEMPTS = 12
BACKOFF_SECONDS = 0.025


def replace_with_retry(tmp_name: "str | os.PathLike[str]", path: "str | os.PathLike[str]", *,
                      attempts: int = ATTEMPTS, backoff: float = BACKOFF_SECONDS) -> None:
    """`os.replace(tmp_name, path)`, retried on the Windows sharing violation only.

    Raises the last `PermissionError` if every attempt is refused, so a genuinely locked file fails
    loudly and promptly instead of hanging.
    """
    if attempts < 1:
        raise ValueError(f"attempts must be at least 1, not {attempts!r}: a replace that is never "
                         f"attempted is not a write")
    last: "BaseException | None" = None
    for attempt in range(attempts):
        try:
            os.replace(tmp_name, path)
            return
        except PermissionError as exc:
            last = exc
            if attempt + 1 == attempts:
                break
            time.sleep(backoff * (attempt + 1))
    assert last is not None, "the loop either returns or records the exception that stopped it"
    raise last


def worst_case_seconds(attempts: int = ATTEMPTS, backoff: float = BACKOFF_SECONDS) -> float:
    """The total wall-clock a fully-refused replace can cost. Exposed so the suite pins the product
    instead of restating the arithmetic, and so a caller raising `attempts` can see the cost it bought."""
    return backoff * sum(range(1, max(1, attempts)))
