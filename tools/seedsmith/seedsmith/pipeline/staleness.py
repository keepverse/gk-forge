"""seedsmith.pipeline.staleness — the shared staleness-key function
(spec-content-completeness-core.md §4, `seedsmith-content-standard` Task 2).

Generalizes `adapters/dungeon/provenance.py`'s own `DungeonProvenance`/`staleness_key`/`stale_ids`
shape (`briefHash + promptVersions + registryVersions + motifSubsetHash`) into a domain-agnostic
form: `brief_hash + prompt_version + schema_version + model_id`. `registryVersions` and
`motifSubsetHash` were dungeon-specific vocabulary-freshness signals; folded here into
`schema_version` + `brief_hash`, since a brief that inlines a vocabulary (per `spec-pipeline.md`
§3.3) already changes `brief_hash` when that vocabulary changes.

**This key is for REPORTING only** (spec §3/§4) — a domain calls `is_stale` to populate a
`Content/FieldStale` finding (metrics/content_completeness.py), never to decide what an automatic
resumed run regenerates. The automatic path only ever asks "does an entry exist" (`RunLedger.plan`
with an exists-only `is_valid`); staleness never gates that decision. Regenerating a stale-but-
existing record is always the human-invoked `--force` path (`RunLedger.force`).
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

__all__ = ["staleness_key", "is_stale", "brief_hash"]


def brief_hash(text: str) -> str:
    """Hash the rendered brief text itself — the model's actual input, not the template that
    produced it. Two subjects with different data but identical rendered text collide on purpose:
    the model would receive the same input either way."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def staleness_key(*, brief_hash: str, prompt_version: str, schema_version: str,
                  model_id: str) -> str:
    """A stable hash of everything that would make a freshly-generated record differ from an
    already-generated one. All four inputs are plain strings already — no internal sorting is
    needed (contrast `dungeon/provenance.py`'s own `staleness_key`, which sorts dict items because
    two of its four fields are mappings; every input here is a scalar by construction, so a
    caller cannot pass an order-ambiguous value in the first place)."""
    digest = hashlib.sha256()
    for part in (brief_hash, prompt_version, schema_version, model_id):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")  # separator — prevents "ab"+"c" colliding with "a"+"bc"
    return digest.hexdigest()


def is_stale(recorded: "Mapping[str, Any] | None", current_key: str) -> bool:
    """A record with no recorded staleness key at all predates tracking and is reported stale —
    cannot be proven current, matching `dungeon/provenance.py:59-61`'s own rule for a record with
    no `_provenance`."""
    if recorded is None:
        return True
    return recorded.get("stalenessKey") != current_key
