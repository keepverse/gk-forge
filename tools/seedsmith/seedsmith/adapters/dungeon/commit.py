"""`commit_event_draws` — the thin event committer (spec-dungeon-generator-repair.md §9, NS12).

A repaired event run writes through the existing dungeon writer (`emit.write_corpus`) with
`_provenance` stamped from the RESOLVED transport config, and stamps each event's `nameKey`/`flavorKey`
beside its text. Those keys are DERIVED at commit from the string itself — the runtime's codegen bridge
reads legacy and storylet keys the same way, so the rule is `narrative-contract` §4's:
`ns.event.<eventId body>.<field>.<h8>`. **No model-facing schema carries a key**: a generated key in a
call schema would be a field the model is invited to author, which is the defect
`schema.DERIVED_FIELDS_BY_KIND` names.

Only RESOLVED draws are written: an `unresolved` slot has nothing correct to write, and the run report
is where it is listed.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Sequence

from ...pipeline.llm_caller import LlmCallerConfig, resolve_live_transport
from . import emit as _emit
from .briefs import EVENT_PROMPT_VERSION
from .pipelines import EventDrawResult

__all__ = ["EVENT_KEY_PREFIX", "EVENT_SCHEMA_VERSION", "KEY_FIELDS", "text_key", "commit_event_draws"]

EVENT_KEY_PREFIX = "ns.event"

#: Labels the EVENT ENTRY's SHAPE (not the prompt — that is `EVENT_PROMPT_VERSION`). Bumped when a
#: committed entry's shape changes; it is the `schemaVersion` of the `_provenance` block.
EVENT_SCHEMA_VERSION = "dungeon-event/1"

#: The prose fields that carry a key, in the order a committed file shows them.
KEY_FIELDS: "tuple[str, ...]" = ("name", "flavor")

#: `narrative-contract` §4's key charset: lower-case letters, digits, dots and hyphens only.
_KEY_RE = re.compile(r"^[a-z0-9.-]+$")


def text_key(event_id: str, field: str, text: str) -> str:
    """`ns.event.<eventId body>.<field>.<h8>` — `h8` is the first eight hex digits of the string's
    SHA-256, so a changed string is a NEW key by construction and an unchanged one keeps its key.
    The eventId's own namespace prefix (`event.`) is dropped: the key's prefix already names it."""
    if field not in KEY_FIELDS:
        raise ValueError(f"{field!r} carries no text key — keyed fields are {list(KEY_FIELDS)}")
    if not event_id:
        raise ValueError("a text key needs an eventId")
    body = event_id.split(".", 1)[1] if "." in event_id else event_id
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    key = f"{EVENT_KEY_PREFIX}.{body}.{field}.{digest}"
    if not _KEY_RE.match(key):
        raise ValueError(f"text key {key!r} is outside the allowed charset {_KEY_RE.pattern}")
    return key


def commit_event_draws(results: "Sequence[EventDrawResult]", out_dir: Path, *,
                       config: "LlmCallerConfig | None" = None,
                       schema_version: str = EVENT_SCHEMA_VERSION) -> "list[Path]":
    """Write every resolved draw as `<eventId>.json` (plus the directory's `_index.json`), each with
    its two text keys and its `_provenance`.

    `config` is the RESOLVED transport config (this module never constructs one): `_provenance.modelId`
    records the model that actually ran. An `unresolved` draw writes nothing.
    """
    config = config or resolve_live_transport()
    entries: "dict[str, dict]" = {}
    provenance: "dict[str, dict]" = {}
    for result in results:
        if result.entry is None:
            continue
        entry = dict(result.entry)
        event_id = str(entry["eventId"])
        for field in KEY_FIELDS:
            entry[f"{field}Key"] = text_key(event_id, field, str(entry.get(field, "")))
        entries[event_id] = entry
        provenance[event_id] = _emit.build_provenance(
            brief_hash=result.brief_hash, prompt_version=EVENT_PROMPT_VERSION,
            schema_version=schema_version, model_id=config.model)
    if not entries:
        # A run that resolved nothing writes NOTHING — not even an empty index or directory.
        return []
    return _emit.write_corpus(Path(out_dir), entries, provenance_by_id=provenance)
