"""seedsmith.adapters.items.charmgen — the charm generator (item module 13, `set-charm-gen`).

Same shape as `setgen`, different rules: `Flat` only, one band below equipment, no family shared
with a `jewel-minor` base type, and a signet that rolls nothing and carries a drawback
(`ssot-charms.md` 3.4, 3.6). Everything a charm shares with a set — the tuning parser, the pick
vocabulary, the brief builder, the theme bridge, the run plan — is IMPORTED from `setgen` rather
than forked, so the two cannot drift on the half they genuinely have in common.
"""
from __future__ import annotations
