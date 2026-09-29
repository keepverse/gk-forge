"""seedsmith.adapters.items.gemgen — item module 4, `sockets-gen`
(docs/architecture/item-seedgen/spec-sockets-gen.md).

Authors the gem/insert corpus (`gk-data/packs/fusion/data/seed/items/gems/*.json`) — the fixed containers a socket
grants an existing effect family at, per `docs/architecture/item/entry-shapes.md` §1. This module
does **not** touch the `sockets` tuning or a base type's own `socketMax` field; those are
`base-types-gen`'s own territory (the spec's own boundary).

**Scope note, repeated from the spec because it is easy to get backwards:** a gem entry references
an existing, shipped `atom.*` affix-family id — it never invents one. `brief.py` is the only place
that reads the 109-family registry; `emit.py` mints ids and assembles the final entry shape;
`schema.py` is the (deliberately tiny) answer contract a model — or, for this module's own first
run, a hand-authored-and-validated answer table — is held to; `run.py` wires all three to
`pipeline.run_ledger.RunLedger`, generalizing `setgen/run.py`'s own proven resume discipline rather
than inventing a second one.
"""
from __future__ import annotations
