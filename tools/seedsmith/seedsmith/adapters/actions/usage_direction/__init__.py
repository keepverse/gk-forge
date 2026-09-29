"""seedsmith.adapters.actions.usage_direction — FC3 `usage-direction` (roster-balance program).

Feeds FC1's real per-family usage history back into the three propose pipelines as an optional
rendering bias — under-used families are shown with a legible cue, never made the pool's only
option. See `weights.py`'s own module docstring and
`docs/architecture/roster-balance/spec-usage-direction.md` for the full design.
"""
from __future__ import annotations
