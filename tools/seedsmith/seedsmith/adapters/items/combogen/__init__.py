"""seedsmith.adapters.items.combogen — the combination generator (item module 21,
`strain-splice-gen`).

⛔ **Never the word "runeword"**, in ids, names, prompts, tests or comments (D20 —
`enrichment-contract.md` §1's "one word, four meanings" defect). `grid.BANNED_WORD` is the constant
and `grid.scan_for_banned_word` is the check; it is applied to every brief and to every emitted id.

⛔ **P1, unamended from module 13: the model writes identity, deterministic code writes magnitude.**
Every module here sits on one side of that line and says which:

| module | side | what it owns |
|---|---|---|
| `grid` | deterministic | 12 aptitudes x 3 archetypes -> 36; C(12,2) -> 66; ids sorted by ordinal |
| `tuning` | deterministic | the pure parser over BOTH tuning files, and the ownership split |
| `supply` | deterministic | the PRECHECK — every ingredient family a live gem supplies |
| `schema` | the boundary | closed-enum output, `audit_schema`-clean by construction |
| `brief` | the boundary | aptitude semantics carried verbatim from the roster; never a number |
| `emit` | deterministic | `combo.strain-*` / `combo.splice-*`, `min_tier`, `min_sockets` |
| `catalogue` | deterministic | the 127-against-45 learnability report |
| `migrate` | deterministic | what retiring the `socket-word` corpus actually touches, computed |
| `run` | deterministic | the run plan and the dry run |

⚠ **Two things this package deliberately does NOT contain.**

- **No aptitude -> element mapping.** Nothing in the repo maps the twelve aptitudes to the six
  concrete elements, and D22-as-amended needs none: the enhanced tier keys on each ingredient gem's
  own element matching its socket's affinity (RULED 2026-09-04). Inventing a 12 -> 6 bridge here
  would be a design decision smuggled in as an implementation detail.
- **No second copy of module 16's socket numbers.** `attunedTierBonus` and D20's ingredient count
  live in the current `sockets` revision and are read from there.
"""
from __future__ import annotations
