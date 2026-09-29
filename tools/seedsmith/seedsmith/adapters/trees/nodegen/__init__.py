"""seedsmith.adapters.trees.nodegen — `tree-language`, Stage 2 of the passive-tree generator
(task H1, spec-tree-language.md). **The only model calls in the whole pipeline, and it never
writes a number** (spec Objective / §2.1) — every schema in this package is `audit_schema`-clean
by construction, the same P1 discipline `adapters/items/setgen/` and the `*_propose/` modules
already ship under.

Twelve modules in the `setgen` mould (spec-tree-language.md's own "Project structure" section
names this precedent by date; 12 -> 13, 2026-09-19: see `migrate_retired_atk` below), each labelled
below by which side of the no-numbers line it sits on and, where its live behaviour is not yet
wired, which later task closes the gap:

| module | side | what it owns |
|---|---|---|
| `tuning` | deterministic | thin re-export of A2's `passive-tree-targets.v2.json` parser — one loader, not two |
| `vocab` | deterministic | the affix pick vocabulary (98 families, 3 tag values), **counted** fresh from `gk-data/packs/fusion/data/seed/items/affix-families/` |
| `quota` | the boundary | axis-marginal apportionment via the shared `largest_remainder_count`, PLUS (task H3) the per-slot cell walk, hard-constraint override and step-5 return-to-pool rebalance (spec §4.2 steps 4-5 / spec-tree-plan.md §8), refusing an overdrawn cell (`OverdrawnQuota`) rather than rebalancing it silently; `quota_for_plan`/`permitted_ids_for_cell` wire a real `plan_read.TreePlan` straight through |
| `plan_read` | deterministic | reads `tree-plan`'s committed plan for one tree; refuses an unfilled hole rather than defaulting |
| `brief` | the boundary | the per-node §6.2 brief text; permutation seeded from ``nodeId|field|sampleIndex``, reusing `creatures.anchor.permute.order_for` |
| `schema` | the boundary | the closed-enum §6.3 response schema, `audit_schema`-clean by construction; `schema_for_call` fills the enum per call |
| `run` | the boundary | `plan_run` (H1) over one tree's committed plan → `RunPlan{subjects, held, already_done}`, plus H2's real gate runner on top: `generate_node` (one node — base call, the `affixIds` vote, persist-time re-gate) and `run_language_stage` (a whole tree, idempotent, byte-identical on a forced rerun) |
| `emit` | the boundary | writes `gk-data/packs/fusion/data/seed/passive-tree/nodes/<treeId>.json`; refuses a malformed `nameKey` or a within-tree id collision rather than sanitising one; composes `printedText` (task H3) from the accepted response's own `exclusion` object |
| `dedup` | deterministic | local exact Jaccard over TIER SIBLINGS (never the shared MinHash — same over-report defect `items/setgen/dedup.py` measured) |
| `exclusion` | deterministic | the form ladder and `propertyKeys` membership against the plan's own `propertyVocabulary`; `compose_printed_text` (task H3) makes "both sides name the same winner" a property of a pure `(form, propertyKeys, role)` template rather than a runtime cross-node check — the real cross-node CENSUS is `tree-review`'s (spec-tree-review.md §6.4 rule 2), not this stage's |
| `verdict` | deterministic | wraps A2's `GATING_METRICS`/`missing_thresholds` with the `items/setgen/verdict.py`-shaped `RunReport`; H2 adds `hard_gate_ids`/`assert_exactly_one_hard_gate` (§7.1, read off a real `MetricRegistry`, never off `GATING_METRICS`); the real corpus metrics that feed it are H4's `metrics/passive_tree.py` |
| `migrate_retired_atk` | deterministic | **12 -> 13 (solid-enforcement `retire-atk` R5, 2026-09-19).** A mechanical, no-model-call rewrite of an already-accepted node's persisted `quotaCell.channelFamily` through `quota.RETIRED_FAMILY_SUCCESSOR` — the same shape `items/recipegen/migrate_legacy_shards.py` established; never a re-quota (`quota_for_plan` is never called here) |

Every model call is one node (spec §6.1 — the only unit at which the permitted subset is exact).
Nothing here mints a magnitude, a coefficient, a tier or a channel — those are `tree-binder`'s.
"""
from __future__ import annotations
