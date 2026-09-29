"""Shared resume and merge rules for the three action proposal partitions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Sequence

__all__ = ["load_resume_entries", "merge_entries", "select_brief_batch"]

_TERMINAL_OUTCOMES = frozenset(("accepted", "blocked", "escalated"))


def load_resume_entries(path: Path, *, partition: str, round_no: int,
                        briefs_corpus_hash: str | None) -> "list[dict]":
    """Load an existing partition only when it belongs to the same planned run."""
    if not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: cannot resume from invalid JSON") from exc
    if not isinstance(doc, dict) or doc.get("kind") != "action-candidate":
        raise ValueError(f"{path}: resume requires an action-candidate envelope")
    meta = doc.get("_meta")
    if not isinstance(meta, dict) or meta.get("partition") != partition or meta.get("round") != round_no:
        raise ValueError(f"{path}: resume metadata does not match partition={partition!r}, round={round_no}")
    if briefs_corpus_hash is not None and meta.get("briefsCorpusHash") != briefs_corpus_hash:
        raise ValueError(f"{path}: briefsCorpusHash does not match the current plan")
    entries = doc.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"{path}: action-candidate envelope has no entries list")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("briefId"), str):
            raise ValueError(f"{path}: every resumed entry needs a string briefId")
        brief_id = entry["briefId"]
        if brief_id in seen:
            raise ValueError(f"{path}: duplicate resumed briefId {brief_id!r}")
        seen.add(brief_id)
    return [dict(entry) for entry in entries]


def select_brief_batch(briefs: Sequence[Mapping[str, object]], *, count: int,
                       existing_entries: Sequence[Mapping[str, object]] = ()) -> "list[dict]":
    """Select the next batch; unresolved rows remain eligible for a later retry."""
    terminal = {
        str(entry["briefId"])
        for entry in existing_entries
        if isinstance(entry.get("briefId"), str)
        and entry.get("outcome") in _TERMINAL_OUTCOMES
    }
    pending = [dict(brief) for brief in briefs
               if isinstance(brief.get("briefId"), str) and brief["briefId"] not in terminal]
    return pending[:max(0, count)]


def merge_entries(existing: Sequence[Mapping[str, object]],
                  replacement: Sequence[Mapping[str, object]]) -> "list[dict]":
    """Replace retried briefs and return one deterministic partition."""
    by_brief: dict[str, dict] = {}
    for entry in [*existing, *replacement]:
        brief_id = entry.get("briefId")
        if not isinstance(brief_id, str):
            raise ValueError("candidate entry needs a string briefId")
        by_brief[brief_id] = dict(entry)
    return [by_brief[brief_id] for brief_id in sorted(by_brief)]
