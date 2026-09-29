"""seedsmith.pipeline.backfill — the generalized backfill loop
(spec-content-completeness-core.md §3, `seedsmith-content-standard` Task 4).

Not a new ledger — a thin, documented calling convention over the already-real, already-adopted
`RunLedger` (`pipeline/run_ledger.py`, nine real item generators depend on it today), standardizing
how every domain calls it for the resolved automatic/manual split (§3):

- **Automatic (a resumed run, no flags):** `plan_missing` — "needing work" means **no entry exists
  at all**. A record's staleness key is never consulted here; an existing entry is always a no-op,
  which is the whole point of keeping this path safe to run unattended.
- **Manual (`--force`, a person invokes it by hand):** `force_regenerate` — a thin pass-through to
  `RunLedger.force(subject_ids, scope)`. `scope="all"` regenerates every targeted subject
  unconditionally; there is no selectively-diffed "regenerate only the stale ones" automatic mode
  (§3's own reasoning: trusting a stochastic model to know its own prior output was "close enough"
  is exactly the risk `generate_commander_effects.py`'s own comment warns against).

Staleness itself (`pipeline/staleness.py`) is computed and reported (`metrics/content_completeness.
py`'s `Content/FieldStale`) entirely independently of this loop — a caller who wants to see what's
stale reads that metric, then decides whether to invoke `force_regenerate` themselves. Nothing here
reads a staleness key.
"""
from __future__ import annotations

from typing import Iterable

from .run_ledger import RunLedger

__all__ = ["plan_missing", "force_regenerate"]


def _exists(_subject_id: str, entry: dict) -> bool:
    return entry is not None


def plan_missing(ledger: RunLedger, subject_ids: Iterable[str]) -> "list[str]":
    """The automatic path: subjects with no ledger entry at all. `RunLedger.plan`'s own `is_valid`
    callback normally lets a caller reconcile a corpus a hand-edit broke out of band — here it is
    given the constant-true-if-present check, so staleness (however real) never feeds this
    decision, matching the resolved automatic-backfill contract exactly."""
    done = ledger.read_done()
    return [sid for sid in subject_ids if not _exists(sid, done.get(sid))]


def force_regenerate(ledger: RunLedger, subject_ids: Iterable[str], *, scope: str) -> "list[str]":
    """The manual path: `scope="all"` (every targeted subject, missing or not) or `scope="ids"`
    (only the named ones) — `RunLedger.force`'s own already-real contract, unchanged. A caller
    reaches this only from an explicit `--force` CLI flag, never from a resumed run's own default
    behavior."""
    return ledger.force(subject_ids, scope)
