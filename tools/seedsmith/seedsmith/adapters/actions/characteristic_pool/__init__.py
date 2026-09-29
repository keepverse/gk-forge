"""seedsmith.adapters.actions.characteristic_pool — A-S0 (spec-characteristic-pool.md).

Owns the closed characteristic pool every later `action-corpus` stage draws its brief fields
from, and the species **role lean**: a family-level floor, a deterministic derivation that
differentiates within (or without) a family, and a measured residue where the derivation does
not separate. No model call anywhere in this package — everything here is a pure function of
committed, offline inputs (spec §1's "Model calls: none").

Layout, one concern per file:
    catalog.py  — the live species roster, parsed from gk-data/packs/fusion/data/seed/creatures/species/**/*.json
                  (element, rarity, traits); the generated C# catalog is legacy-only
    anchors.py  — the classified species anchor tree (posture/reach/targetPreference), joined by
                  lowercased id; robust to the tree's own data-quality gaps (an index entry whose
                  file has no matching row, a missing file) rather than raising on them
    derive.py   — steps 3-5 of spec §3: the family floor, the per-species score, the ranking, the
                  residue measurement (Checkpoint 2)
    pool.py     — the six closed groups (A-F) `characteristic-pool.json` ships, spec §2's inlined
                  table (never `action-corpus-ideal.md` §12 — that table is stale, see the spec)

The entrypoint that reads these, writes both `gk-data/packs/fusion/data/seed/actions/_generated/role-lean.json` and
`.../characteristic-pool.json` through A-C1's envelope, is `generate_characteristic_pool.py`, one
level up (module docstring there explains why the writer lives outside this package).
"""
from __future__ import annotations

__all__ = []
