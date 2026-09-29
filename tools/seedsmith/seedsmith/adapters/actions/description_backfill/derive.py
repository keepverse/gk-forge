"""seedsmith.adapters.actions.description_backfill.derive — pure functions only; the sibling
entrypoint `../generate_action_descriptions.py` owns every disk read/write and the one model call,
matching every `derive.py` in this adapter family (see `innate_picker/derive.py`'s own module
docstring for the same split).
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from ....pipeline.provenance import PROVENANCE_FIELD

__all__ = ["stamp_description", "group_ids_by_path", "apply_updates_to_doc", "canonical_dump"]


def stamp_description(data: Mapping[str, Any], *, description: str,
                      provenance: Mapping[str, Any]) -> dict:
    """A copy, never an in-place mutation (matching `pipeline.provenance.stamp`'s own reasoning:
    the pre-stamp row is still useful to a caller comparing before/after)."""
    return {**data, "description": description, PROVENANCE_FIELD: dict(provenance)}


def group_ids_by_path(entries: "list[Any]") -> "dict[str, list[str]]":
    """`entries` is a list of `corpus.Entry` — groups subject ids by the committed file each one
    was loaded from (`Entry.path`, relative to `actions_root`), so the caller rewrites exactly the
    files that actually changed rather than re-scanning every committed file for every id."""
    by_path: "dict[str, list[str]]" = {}
    for entry in entries:
        by_path.setdefault(entry.path, []).append(entry.id)
    return by_path


def apply_updates_to_doc(doc: Mapping[str, Any], updates_by_id: "dict[str, dict]") -> dict:
    """Replaces exactly the entries named in `updates_by_id`, leaving every other row AND every
    top-level key (`_meta`, `kind`, `schemaVersion`) byte-identical. Deliberately does not
    recompute `_meta.corpusHash` — that field is `ip.corpus_hash(all_accepted)` over the FULL
    cross-file accepted set as of `generate_innate_picker.py`'s own last run
    (`innate_picker/derive.py:425`), not a hash of this one file's own entries; verified 2026-09-08
    that it already does not equal `corpus_hash` of this file's own current entries even before
    this module's own change (a real, pre-existing staleness this module does not attempt to fix,
    since recomputing it correctly needs that generator's own full cross-file input, which this
    module does not own)."""
    new_entries = []
    for row in doc.get("entries", []):
        row_id = row.get("id")
        if row_id in updates_by_id:
            new_entries.append(updates_by_id[row_id])
        else:
            new_entries.append(row)
    return {**doc, "entries": new_entries}


def canonical_dump(doc: Mapping[str, Any]) -> str:
    """Byte-identical formatting convention to every other writer in this adapter family
    (`innate_picker/derive.py:439-440`, transcribed rather than imported cross-package to keep
    this package's own dependency surface to `pipeline`/`corpus` only)."""
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
