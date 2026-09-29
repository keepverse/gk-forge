"""seedsmith.pipeline.run_ledger — the shared resume/append/reconcile/overwrite base every
item-seedgen generator builds on (docs/architecture/item-seedgen/spec-generator-harness.md).

Generalizes `adapters.items.setgen.run`'s own proven ~1,800-entry-scale ledger (atomic write,
idempotent resume) and adds the one thing that ledger does not do: validate an existing entry's
actual shape before trusting a "done" hit, so a corpus a hand edit broke out of band gets reconciled
on the next run rather than silently skipped forever.

**Deterministic by construction.** Nothing in this module makes a model/LLM call. `write_done`
canonicalizes with `sort_keys=True` — `setgen/run.py`'s own `write_ledger` does not do this
(confirmed by reading it directly), so two runs of THAT ledger are not guaranteed byte-identical.
This module does not inherit that gap.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from . import atomic_replace


@dataclass
class RunLedger:
    """One ledger file, one corpus. `path` is the caller's own choice — each generator module gets
    its own ledger under `gk-data/packs/fusion/data/seed/items/_runs/<module-id>.ledger.json`, matching `setgen`'s own
    convention (`set-charm-gen.ledger.json`)."""

    path: Path

    def read_done(self) -> "dict[str, dict]":
        if not self.path.exists():
            return {}
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        return dict(doc.get("done") or {})

    def write_done(self, done: "dict[str, dict]") -> Path:
        """Atomic replace via temp-file-then-os.replace — a killed process leaves either the old
        ledger or the new one, never half of one. `sort_keys=True` is load-bearing: it is what makes
        two writes of an unchanged `done` dict byte-identical, which `setgen/run.py`'s own writer does
        not guarantee (no `sort_keys` there).

        ⛔ Real defect, measured 2026-09-28 on a live re-emit: the replace is now RETRIED.

        A single `os.replace` was not enough on Windows. `os.replace` fails with
        `PermissionError: [WinError 5] Access is denied` whenever ANY process holds the destination
        open for a moment — a reader, a search indexer, an antivirus scanner, another agent's status
        probe — and that is a NORMAL, transient condition on this platform, not an exceptional one. The
        exception propagated out of `mark_done`, out of `run_batch`, and out of the generator's `main`,
        so the whole batch exited 1 **and every answer it had already paid for was discarded**.

        Three batches were lost this way in one run (29 of 151, 10 of 106, 2 of 89), each with the same
        `WinError 5` on the same `os.replace`. In two of those the operator's own monitoring was reading
        this very file on a timer, which is the most likely holder — a tool that watches a run must not
        be able to stop it.

        **Atomicity is not durability.** The method already promised "either the old ledger or the new
        one, never half of one", and that promise was kept — the file was never left half-written. What
        was missing is that a *transient handle* should cost a fraction of a second rather than the
        batch. The retry is bounded and short: a handle that has not cleared in a couple of seconds is
        not transient, and failing then is correct, because an unbounded retry would hang a run forever
        on a genuinely locked file.

        Only the replace is retried. The temp file's own write is not, because a failed write is a real
        error and re-rolling it would paper over a full disk.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"schemaVersion": 1, "done": done}, ensure_ascii=False, sort_keys=True, indent=2,
        ) + "\n"
        handle, tmp_name = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                fh.write(payload)
            self._replace_with_retry(tmp_name)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return self.path

    #: Kept as class attributes so anything that reached for them still works, but the values now LIVE in
    #: `atomic_replace` — there must be exactly one place that knows the backoff, and this module was a
    #: second one. `eaef29aa6` added the retry HERE, and
    #: `materialgen.run._write_entries` — documented as mirroring this function — kept dying batches, which
    #: is the entire reason the shared helper exists.
    _REPLACE_ATTEMPTS = atomic_replace.ATTEMPTS
    _REPLACE_BACKOFF_SECONDS = atomic_replace.BACKOFF_SECONDS

    def _replace_with_retry(self, tmp_name: str) -> None:
        """Delegate to the one implementation. The retry, its bounds and its reasoning live in
        `pipeline/atomic_replace.py`; keeping a second copy here is how the two writers drifted apart and
        why one of them kept costing a batch of paid-for answers."""
        atomic_replace.replace_with_retry(tmp_name, self.path)

    def mark_done(self, subject_id: str, entry: dict) -> None:
        done = self.read_done()
        done[subject_id] = entry
        self.write_done(done)

    @staticmethod
    def terminal_row(*, outcome: str, entry_id: str, attempts: int,
                     blocked_reason: str = "", defects: "list[str] | None" = None) -> dict:
        """A non-persisted terminal subject record.

        A bounded model failure is terminal for normal resume, but it is not a successful corpus
        write. Keeping this shape in the shared harness prevents each graph adapter from inventing
        an incompatible pseudo-"done" row.
        """
        if outcome not in {"blocked", "escalated"}:
            raise ValueError(f"terminal outcome must be blocked or escalated, got {outcome!r}")
        if not isinstance(entry_id, str) or not entry_id:
            raise ValueError("terminal outcome requires a non-empty intended entry id")
        if attempts < 0:
            raise ValueError("terminal outcome attempts must be non-negative")
        row: dict = {
            "terminalSchemaVersion": 1,
            "outcome": outcome,
            "entryId": entry_id,
            "attempts": attempts,
        }
        if blocked_reason:
            row["blockedReason"] = blocked_reason
        if defects:
            row["defects"] = list(defects)
        return row

    def mark_terminal(self, subject_id: str, *, outcome: str, entry_id: str, attempts: int,
                      blocked_reason: str = "", defects: "list[str] | None" = None) -> None:
        """Checkpoint a non-persisted terminal result without labelling it successful content."""
        self.mark_done(subject_id, self.terminal_row(
            outcome=outcome, entry_id=entry_id, attempts=attempts,
            blocked_reason=blocked_reason, defects=defects))

    def plan(
        self,
        subject_ids: Iterable[str],
        is_valid: Callable[[str, dict], bool],
    ) -> "list[str]":
        """Returns exactly the subject ids needing work: never-attempted ones, AND ones whose ledger
        row claims "done" but whose real, current shape (whatever `is_valid` actually checks — the
        caller decides what "current" means: re-reading a corpus file, checking a stored hash, etc.)
        fails validation. This is the reconcile half `setgen/run.py`'s own `plan_run` does not have —
        it only ever checks "is there a ledger row", never "is the thing the row describes still
        real." Order-preserving over `subject_ids` so a caller controls report/log ordering; this
        function itself makes the same decision regardless of dict iteration order internally.
        """
        done = self.read_done()
        needing_work: "list[str]" = []
        for subject_id in subject_ids:
            entry = done.get(subject_id)
            if entry is None or not is_valid(subject_id, entry):
                needing_work.append(subject_id)
        return needing_work

    def force(self, subject_ids: Iterable[str], scope: str) -> "list[str]":
        """The explicit `--overwrite` path — bypasses `is_valid`/ledger state entirely for the named
        ids. `scope` must be either `"ids"` (named ids only) or the literal `"all"` (every id in
        `subject_ids`) — a bare, unscoped overwrite is refused rather than silently defaulting to
        "all", per the harness's own boundary ("a typo'd --overwrite fails loudly")."""
        ids = list(subject_ids)
        if scope == "all":
            return ids
        if scope == "ids":
            return ids
        raise ValueError(f"force() scope must be 'ids' or the literal 'all', got {scope!r}")
