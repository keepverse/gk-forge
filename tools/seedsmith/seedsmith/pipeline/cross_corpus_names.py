"""One implementation of "whose name is this?", shared by the generator and the re-emit runner.

⛔ **Real gap, found 2026-09-28 while a converged re-emit refused to go green.** The materials name gate
(`adapters/items/materialgen/run.py`) compared an authored name only against the MATERIALS corpus, and the
re-emit runner (`gk-core/scripts/reemit-colliding-item-names.py`) walked the other corpora in a private copy of that
walk. So the child that authors a name could not see a charm already holding it, and the runner that could
see it had no way to make the child act on it. Measured consequence: 4 entries whose names are held verbatim
by a `charm.*` or a `droptable.*` survived every pass. Re-asking did not help, and could not - the re-ask is
answered from a brief that never mentions the other corpora, so the model returns the same name, and the
gate that validates it is blind to the collision and persists it.

Two implementations is how that stayed invisible: each side was correct about its own question. This module
is the single owner of the OTHER corpora's names, and of the normalisation used to compare them, so a fix on
one side cannot leave the other answering a different question.

**Normalisation lives here, not in the gate.** `name_key()` is `materialgen._name_key` verbatim (whitespace
collapsed, casefolded). The gate's own docstring is explicit that case- and spacing-variants are the same
collision for a player reading a list, and an owner map keyed any other way silently matches nothing - a
cross-corpus check that cannot fire looks exactly like a clean tree. `materialgen._name_key` now delegates
here so there is one form, not two that agree today.
"""
from __future__ import annotations

import json
from pathlib import Path

__all__ = ["name_key", "other_corpus_names", "cross_corpus_conflict"]


def name_key(name: "str | None") -> str:
    """The comparison form of an authored name: whitespace collapsed, casefolded.

    Shared deliberately. See the module docstring - a second normalisation is a check that finds nothing.
    """
    return " ".join((name or "").split()).casefold()


def other_corpus_names(items_dir: Path, skip: Path) -> "dict[str, list[str]]":
    """Map normalised name -> the ids in the OTHER corpora that hold it.

    Walks every `.json` under `items_dir` uniformly and skips exactly one path, by `resolve()` equality.
    The corpora share the shape `{entries: [{id, nameKey, name}]}`, and a run ledger has no such list, so it
    is skipped by SHAPE rather than by name - a file called `materials.json` that is not an entry list is
    simply not one.

    `skip` must be the file the caller is about to WRITE, resolved. The call site that got this wrong passed
    `items_dir / "gk-data/packs/fusion/data/seed/items/materials/materials.json"` - a repo-relative constant joined onto the items
    root, a path that cannot exist - so the exclusion was a silent no-op, all 3,633 material names joined
    `owners`, and the KEPT half of every within-corpus duplicate pair was reported as colliding with its own
    refused twin: 181 reported against 13 real. A skip path that does not exist is worse than no skip path,
    because the result still looks like a measurement.
    """
    owners: "dict[str, list[str]]" = {}
    try:
        skip_resolved = Path(skip).resolve()
    except OSError:
        skip_resolved = Path(skip)
    for path in sorted(Path(items_dir).rglob("*.json")):
        try:
            if path.resolve() == skip_resolved:
                continue
        except OSError:
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            # A corpus this collector cannot read is a corpus whose names are unknown, and an unknown
            # corpus must not read as a clean one. Skipping keeps the collector total, so the caller
            # reports the count of unreadable files alongside the count of collisions.
            continue
        if not isinstance(doc, dict):
            continue
        entries = doc.get("entries")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            key = name_key(entry.get("name") or entry.get("nameKey"))
            if not key:
                continue
            # An id-less entry still has to be NAMED in a refusal, so it falls back to the file it came
            # from rather than to an empty string - "already used by " with nothing after it is not
            # actionable, and the whole repair is the model learning which name is unavailable.
            owners.setdefault(key, []).append(str(entry.get("id") or path.stem))
    return owners


def cross_corpus_conflict(name: "str | None", owners: "dict[str, list[str]]",
                          own_id: "str | None" = None) -> "list[str]":
    """The ids OUTSIDE this corpus holding `name`, or `[]`.

    `own_id` exempts a holder that is this entry itself, so re-authoring an entry never collides with the row
    it is about to replace. A cross-corpus collision by definition names something that is not a material,
    so in practice the exemption never fires for the materials corpus - which is why it is a parameter rather
    than an assumption: the collector is shared, and a future caller that does not skip its own file needs it.
    """
    key = name_key(name)
    if not key:
        return []
    return [i for i in owners.get(key, []) if not own_id or i != own_id]
