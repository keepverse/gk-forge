"""seedsmith.adapters.actions.candidate_assembly — the stage this program never named: turns one
ACCEPTED propose-pipeline candidate (A-P1/A-P2/A-P3's own round output, `candidateId`/`briefId`/
`pipelineId`/`scope`/`draft`) plus its originating brief (A-S1's `distribution_planner`, or A-S2's
`brief_assembly` for signature scope) into the real `action-seed` row A-S3 (`dedup_select`) and
`kinds.py` (A-C1) actually require: mints `id`, and merges the draft's own answer fields with the
brief's own planner-owned mechanical fields (`category`/`targetMode`/`areaShape`/`relation`/
`rungBand`/`pairingRole`/`pairedPayoffFamily`).

Found missing 2026-09-04 by the first real smoke batch: `generate_dedup_select.py`'s own docstring
already calls its `--candidates` input "A-S4's accepted output for this round, an A-C1 `action-seed`
envelope" -- but nothing between A-P1/A-P2/A-P3 and A-S4/A-S3 has ever produced that shape. This
module is that missing piece, not a redesign of anything upstream or downstream of it.
"""
from __future__ import annotations
