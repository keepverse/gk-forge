"""seedsmith.adapters.actions.description_backfill — actions' own adoption of
`content-completeness-core` (`spec-content-completeness-actions.md`, `seedsmith-content-standard`
Task 8). Actions is the domain with NOTHING today (confirmed 2026-09-08:
`gk-data/packs/fusion/data/seed/actions/committed-round-1.json` had zero `_provenance` occurrences and
`kinds.py`'s `action-seed` schema had no player-facing text field at all beyond `name` — see
`kinds.py`'s own comment on `description`, added by this same task) — this package builds the
ledger/provenance/metric adoption from scratch, on `core`'s shape, rather than migrating an
existing bespoke one (contrast items' `flavor`/`flavorKey`, which already existed before
`content-completeness-core` did).

`ACTIONS_COMPLETENESS_SPEC` is registered into `report/cli.py`'s own `build_registry()` — one line,
`register_completeness(ACTIONS_COMPLETENESS_SPEC)`, matching the shape `content-completeness-items`
already established there for `FLAVOR_EXPECTED_KINDS`/`"flavor"`. `register_completeness` is
idempotent by equality (`metrics/content_completeness.py:57-71`, fixed for exactly this reason
while `content-completeness-items` was built), so this constant is safe to register from
`build_registry()` on every call in a process, including after a test's own `clear_registry()`.
"""
from __future__ import annotations

from ....metrics.content_completeness import CompletenessSpec

__all__ = ["ACTIONS_COMPLETENESS_SPEC"]

#: `spec-content-completeness-actions.md` §2 — "missing" for an action-seed entry is exactly
#: `not entry.get("description")`, the default falsy-check `CompletenessSpec.missing` already
#: implements (no `is_missing` override): a real action never has a legitimate reason to carry an
#: intentionally-empty description the way, say, a null `scopeKey` is legitimate for a
#: general-scope action — every accepted action-seed is meant to reach a player, so an empty
#: string here is a gap, not a distinct value.
ACTIONS_COMPLETENESS_SPEC = CompletenessSpec(
    domain="actions", kinds=frozenset({"action-seed"}), field="description")
