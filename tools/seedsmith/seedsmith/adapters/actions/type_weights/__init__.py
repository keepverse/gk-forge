"""seedsmith.adapters.actions.type_weights — A-T1 (spec-type-weights.md).

Turns A-S0's `leanOrder`/`leanSource`/`separation` (`gk-data/packs/fusion/data/seed/actions/_generated/role-lean.json`)
into per-mille integer weight vectors over the five action categories, the six target modes, the
four area shapes and the six elements, using coefficients that live entirely in
`gk-core/data/tuning/action-type-weights.v1.json`. No model call anywhere in this package (spec §1's
"Model calls: none") — every value here is read from a shipped table or derived from one.

Layout, one concern per file:
    tuning.py — loads and strictly validates `action-type-weights.v1.json` (refuses a float, a
                bool, a numeric string, or an unknown member, naming the offending row)
    derive.py — spec §3's seven steps: rank-to-raw-score, separation scaling, largest-remainder
                normalisation, the target-shape vector, the element bias, and the family rows

The entrypoint that reads `role-lean.json` and writes `gk-data/packs/fusion/data/seed/actions/type-weights.json`
through A-C1's envelope is `generate_type_weights.py`, one level up — same layout choice
`generate_characteristic_pool.py` already made for A-S0, for the same reason: this package holds
pure derivation, easy to unit-test in isolation; the writer is the one place that touches disk.
"""
from __future__ import annotations

__all__ = []
