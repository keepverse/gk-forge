"""seedsmith.adapters.trees.review — `tree-review`'s own package (spec-tree-review.md).

Task H7 lands the first module here: `census_gate` (§5.5's `sheetRead` refusal mechanism). The
spec's own "Project structure" section additionally names `sample.py` (the three sampling tiers)
and `fingerprint.py`/`verdict.py` (the acceptance ladder) as siblings — those are later tasks'
(§3, §6) and are not built yet; this package exists now so `census_gate` has a home, the same
"foundation before every consumer" shape `adapters.trees.targets` used for A2.
"""
from __future__ import annotations
