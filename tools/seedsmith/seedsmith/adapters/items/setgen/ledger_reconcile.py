"""seedsmith.adapters.items.setgen.ledger_reconcile — drop set/charm ledger rows whose emitted row is not
on disk, so the subjects they claim become schedulable again.

⛔ **Why this exists, measured on the real corpus (2026-09-28).** A run ledger is a resume CONTRACT: it
records that a subject was emitted so a later run does not pay for it again. That only works while the
ledger is true. When it is not, the failure is silent and total, because every consumer trusts it:

  * `setgen/run.py:247` skips any subject the ledger claims, **before** the `_set_entry_on_disk` check at
    `:258` can run, so the corpus is never consulted for a ledgered subject;
  * `items fill --kind set --full --dry-run` therefore reported `toGenerate 0 | held 0 | ledgered 937 |
    complete true` — no work at all;
  * while `tasks/reports/ISG-gap-2-per-partition.json` independently counted the same partitions empty.

  Two views, flatly contradictory, and neither pointing at the ledger. Measured: **all 60**
  `species-no-set-entry` subjects are claimed in `gk-data/packs/fusion/data/seed/items/sets/set-charm-gen.ledger.json` as
  `set-species-creature.<slug>`, and **0** of their 60 entry ids (`set.cherrybomb-001` and 59 others)
  appear in any of the 885 shipped sets files, which hold 910 entry rows. So 60 real, themed species —
  `cherrybomb`, `cornpult`, `seashroom`, `sunflower` — were claimed and never written, permanently
  unschedulable.

**Why the filesystem is the authority and not the ledger.** Verbatim reuse, a stale claim, and a
duplicated entry are three different questions; only one of them is answered by the corpus. And the
corpus check `_set_entry_on_disk` already exists, with a docstring stating the intent this module
finally gives it a way to reach: *"Corpus presence wins — same discipline materialgen uses for
hand-authored rows without a ledger record."*

**Every row is checked, whatever its `outcome`.** The real ledger holds 876 rows with no `outcome` key,
**59 `escalated`** and **2 `blocked`**. Rather than interpret those words — and `escalated` in particular
may or may not have written — the filesystem decides: a row is stale exactly when its `entryId` is absent
from the corpus. The outcome breakdown of whatever is dropped is in the report, so an operator can see
whether escalations were involved rather than being told.

**Dry-run by default**, and the CLI wrapper refuses a production write without `--allow-production-tree`,
matching `repair-set-roles`. A ledger rewrite is destructive and irreversible from the ledger's own
contents, so the safe direction has to be the default one.

**This repairs the CLAIM, not the corpus.** It drops rows; it never writes, moves, or invents a set row.
`plan_run(..., reconcile=True)` in the same package is the read-side counterpart — it declines to believe
a stale claim without changing anything — and the two are complementary: this fixes the ledger once,
that keeps a caller honest per run.
"""
from __future__ import annotations

import collections
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from . import run as run_mod

__all__ = [
    "LedgerReconcileError",
    "LedgerReconcileResult",
    "reconcile_ledger",
    "reconcile_report",
]


class LedgerReconcileError(ValueError):
    """Mirrors `SetRoleRepairError` in refusing loudly rather than silently dropping a ledger row."""


@dataclass(frozen=True)
class LedgerReconcileResult:
    """What the run found. `stale_subjects` is the actionable list; the rest is context a reader needs
    before acting, because "60 stale rows" alone does not say whether 60 real sets are missing or 60
    bookkeeping artefacts are lying."""

    ledger_path: Path
    sets_dir: Path
    rows_total: int
    checked: int
    kept: int
    stale_subjects: "tuple[str, ...]" = ()
    stale_by_outcome: "Mapping[str, int]" = field(default_factory=dict)
    unchecked: "tuple[str, ...]" = ()
    write: bool = False

    @property
    def changed(self) -> int:
        return len(self.stale_subjects)


def _outcome_of(row: Mapping[str, Any]) -> str:
    """The row's own outcome word, or the literal the real ledger implies by omitting it. Reported rather
    than interpreted — this module never branches on it."""
    value = row.get("outcome")
    return str(value) if value else "persisted(implicit)"


#: `_entry_id`'s own placeholder spelling for a charm whose axis group the model has not chosen yet
#: (*"the axis group is not known until the model picks the axis, so a charm's id is minted at persist
#: time, not at plan time"*). It CONTAINS A DOT — `charm.(axis-group)-NNN for apple` — so a
#: dot-presence test does not exclude it, and the first version of this module classified it STALE and
#: would have dropped a charm from its own ledger. Caught by
#: `test_a_row_with_no_usable_entry_id_is_reported_and_left_alone`.
CHARM_PLACEHOLDER_MARKER = "(axis-group)"


def _is_judgeable(subject_id: str, row: Mapping[str, Any]) -> bool:
    """Whether this row makes a claim about a file that must exist.

    False for a `charm-*` row (this repair reconciles a SETS ledger, and a charm's row is not its
    business) and for a placeholder `entryId`, which is not a claim about any file. Both are REPORTED in
    `unchecked`, never dropped: an unjudged row left alone is a visible gap, and an unjudged row deleted
    is silent data loss.
    """
    if subject_id.startswith("charm-"):
        return False
    entry_id = row.get("entryId") if isinstance(row, Mapping) else None
    if not isinstance(entry_id, str) or not entry_id:
        return False
    if CHARM_PLACEHOLDER_MARKER in entry_id:
        return False
    return "." in entry_id


def reconcile_ledger(*, ledger_path: "Path | None" = None,
                     sets_dir: "Path | None" = None,
                     write: bool = False) -> LedgerReconcileResult:
    """Report — and with `write=True`, drop — every ledger row whose `entryId` is absent from the corpus.

    Deterministic, no model call, and reversible only by re-running the generation the rows were
    claiming: which is precisely why `write` defaults to False.
    """
    ledger_file = Path(ledger_path) if ledger_path else run_mod.DEFAULT_LEDGER
    corpus_dir = Path(sets_dir) if sets_dir else run_mod.DEFAULT_SETS_DIR

    if not corpus_dir.is_dir():
        raise LedgerReconcileError(
            f"sets corpus directory {corpus_dir} does not exist — refusing to judge {len(run_mod.read_ledger(ledger_file))}"
            f" ledger rows against a tree that is not there, because every row would look stale")
    if not ledger_file.exists():
        raise LedgerReconcileError(
            f"run ledger {ledger_file} does not exist — there is nothing to reconcile, and reporting an "
            f"empty result would read as 'the ledger is clean' when it has never existed")

    done = run_mod.read_ledger(ledger_file)
    if not done:
        return LedgerReconcileResult(ledger_path=ledger_file, sets_dir=corpus_dir, rows_total=0,
                                     checked=0, kept=0, write=bool(write))

    stale: "list[str]" = []
    unchecked: "list[str]" = []
    by_outcome: "collections.Counter[str]" = collections.Counter()
    kept = 0

    for subject_id in sorted(done):
        row = done[subject_id]
        if not isinstance(row, Mapping) or not _is_judgeable(subject_id, row):
            # Not a usable claim — a charm row, a placeholder id, or a row with no id at all. Left alone
            # and REPORTED, never dropped on a guess and never silently skipped.
            unchecked.append(subject_id)
            continue
        entry_id = row["entryId"]
        if run_mod._set_entry_on_disk(entry_id, sets_dir=corpus_dir):
            kept += 1
            continue
        stale.append(subject_id)
        by_outcome[_outcome_of(row)] += 1

    result = LedgerReconcileResult(
        ledger_path=ledger_file, sets_dir=corpus_dir, rows_total=len(done),
        checked=kept + len(stale), kept=kept, stale_subjects=tuple(stale),
        stale_by_outcome=dict(by_outcome), unchecked=tuple(unchecked), write=bool(write))

    if write and stale:
        survivors = {k: v for k, v in done.items() if k not in set(stale)}
        run_mod.write_ledger(survivors, ledger_file)
    return result


def reconcile_report(result: LedgerReconcileResult, *, write: bool) -> "dict[str, Any]":
    """The run's own numbers. `staleSubjects` is printed and never asserted — it is how a human reads
    which species were claimed and never written. `uncheckedSubjects` is printed for the same reason:
    an exclusion that is not reported is a blind spot."""
    return {
        "write": write,
        "ledger": str(result.ledger_path),
        "setsDir": str(result.sets_dir),
        "rowsTotal": result.rows_total,
        "rowsChecked": result.checked,
        "rowsKept": result.kept,
        "staleRows": result.changed,
        "staleByOutcome": dict(result.stale_by_outcome),
        "uncheckedRows": len(result.unchecked),
        "uncheckedSubjects": list(result.unchecked),
        "staleSubjects": list(result.stale_subjects),
    }
