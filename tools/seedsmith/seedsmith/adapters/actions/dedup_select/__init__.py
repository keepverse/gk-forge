"""seedsmith.adapters.actions.dedup_select — A-S3 (spec-dedup-select.md), the mechanical
survivor-selection pass over one action-corpus round: tier 1 (exact fingerprint, hard reject),
tier 2 (near-duplicate within an anchor, hard reject), tier 3 (token-overlap prose similarity,
advisory only, never gates).
"""
from __future__ import annotations
