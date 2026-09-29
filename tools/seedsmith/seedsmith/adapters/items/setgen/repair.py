"""Deterministic repairs for legacy set rows that predate member binding.

The original set pipeline emitted only ``role``/``frame`` members.  That shape passes the Python
dependency check but cannot be imported by Core, whose ``SetCorpus`` requires a concrete base type.
This module is an explicit, idempotent migration: it binds missing members by lookup and refuses to
rewrite an existing binding that no longer matches its role/frame.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .seedfile import ITEM_SEED_ROOT, bind_member_base_types, load_base_type_candidates


@dataclass(frozen=True)
class SetRepairFile:
    path: Path
    changed_entries: int
    total_entries: int


def repair_set_corpus(*, sets_dir: "Path | None" = None,
                      base_types_dir: "Path | None" = None,
                      write: bool = False) -> "tuple[SetRepairFile, ...]":
    """Plan or apply member bindings for every production set partition.

    ``write=False`` is a read-only plan. When writing, each changed file is replaced atomically and
    untouched files are not rewritten. No ids, thresholds, names, or flavours are modified.
    """
    target = Path(sets_dir or (ITEM_SEED_ROOT / "sets")).resolve()
    corpus_root = Path(base_types_dir).resolve() if base_types_dir is not None else None
    candidates = load_base_type_candidates(corpus_root=corpus_root)
    # Existing trial rows may already pin a unique's base type. Preserve those rows so the repair
    # remains a binding migration; the validator still reports the separate UniqueSetMembership
    # design defect instead of this tool silently changing authored identity.
    all_candidates = load_base_type_candidates(corpus_root=corpus_root, include_unique=True)
    result: list[SetRepairFile] = []
    for path in sorted(target.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("kind") != "set":
            continue
        changed = 0
        entries = document.get("entries") or []
        for entry in entries:
            entry_id = entry.get("id")
            if not isinstance(entry_id, str) or not entry_id:
                raise ValueError(f"{path}: set entry has no string id")
            old_members = entry.get("members") or []
            new_members = bind_member_base_types(entry_id, old_members, candidates,
                                                 existing_candidates=all_candidates)
            if new_members != old_members:
                entry["members"] = new_members
                changed += 1
        if changed and write:
            payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
            fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                              dir=str(path.parent), text=True)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        if changed:
            result.append(SetRepairFile(path=path, changed_entries=changed,
                                        total_entries=len(entries)))
    return tuple(result)


def repair_report(files: "tuple[SetRepairFile, ...]", *, write: bool) -> dict[str, Any]:
    return {
        "write": write,
        "files": [{"path": str(f.path), "changedEntries": f.changed_entries,
                   "totalEntries": f.total_entries} for f in files],
        "changedFiles": len(files),
        "changedEntries": sum(f.changed_entries for f in files),
    }
