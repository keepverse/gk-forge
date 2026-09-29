"""seedsmith.adapters.dungeon.completeness — adopting `content-completeness-core` for dungeon
(spec-content-completeness-dungeon.md, `seedsmith-content-standard` Task 12).

Two real, separate gaps this module closes — both confirmed by reading the code, not assumed:

1. **`corpus.model.Corpus.load()` cannot see dungeon's own real content at all.** It only
   recognises a file whose TOP-LEVEL JSON has both a `kind` string and an `entries` LIST
   (`corpus/model.py:183-186`: `if not kind or not isinstance(raw_entries, list): continue`).
   Dungeon's own `emit.py` docstring states the deliberate opposite convention: "One object per
   file... unlike the creatures anchor's per-family list" (`emit.py:1-5`) — every real file under
   `gk-data/packs/fusion/data/seed/dungeon/<dir>/*.json` (bar each directory's own `_index.json`) IS one bare entry
   object, no `kind`/`entries` wrapper. So `Corpus.load()` silently skips every dungeon file today:
   registering a `CompletenessSpec` for dungeon alone would be reachable in the registry and inert
   in practice, because `ctx.corpus.by_kind("dungeon-event")` would return `[]` even against the
   real, full `gk-data/packs/fusion/data/seed/dungeon` root. `load_dungeon_corpus` below is dungeon's OWN local corpus
   builder — it reuses the real `Corpus`/`Entry` classes UNCHANGED (`content-completeness-core`'s
   own boundary: a shared module is never edited for one domain's storage convention) and walks the
   one-object-per-file directories per `kinds.KINDS`'s own `directory -> kind` map.
2. **There is no committed orchestrator that ever calls the real writer on generated content.**
   `pipelines.py`'s `run_event_draws` (and every sibling `run_*_draws`) returns a raw model-parsed
   `dict` with no `_provenance` and no caller anywhere in this repo passes that dict to
   `emit.write_entry`/`write_corpus` — confirmed by grep: `report/cli.py`'s own subcommands name
   creatures/items/effects/structures/trees/numerics, never `dungeon`. `DungeonProvenance`/`stale_ids`
   (`provenance.py`) being dead code (only a test importer) is one symptom of this deeper gap, not
   the whole of it: there is no "dungeon generate"/"dungeon commit" step in this codebase for
   provenance to ride along with in the first place. This module cannot invent that missing
   orchestrator without exceeding this task's own scope (spec §2) — what it DOES do is fix `emit.py`
   itself (see that module) so any future orchestrator gets `_provenance` for free the moment it
   calls the real writer, and registers the completeness check now so a person running `check`
   against the real corpus sees the gap today, not only after an orchestrator someday exists.
"""
from __future__ import annotations

import json
from pathlib import Path

from ...corpus.model import Corpus, Entry
from ...metrics.content_completeness import CompletenessSpec, register_completeness, registered_specs
from .kinds import KINDS

__all__ = ["load_dungeon_corpus", "ensure_completeness_registered", "DUNGEON_EVENT_KIND"]

#: The one kind this task's own acceptance criteria name explicitly ("register a CompletenessSpec
#: for dungeon events" — todo.md Task 12). `dungeon-room`/`dungeon-domain`/`dungeon-quest` carry the
#: same `flavor` field shape (`kinds.py`'s own `required` sets) and are a natural one-line extension
#: later — deliberately NOT added here, to keep this task's own scope matched to what it was asked
#: to prove (the real, already-found event defect), not silently widened.
DUNGEON_EVENT_KIND = "dungeon-event"

#: `kinds.py`'s own per-kind id field name — each is `f"{namespace}Id"` except the one kind whose
#: own identity IS a cross-corpus reference (`dungeon-supply-ext`'s `consumableRef`, confirmed by
#: reading a real committed file: `gk-data/packs/fusion/data/seed/dungeon/supplies/consumable.k1-001.json` has no
#: `supply-extId` field at all, only `consumableRef`).
_ID_FIELD_BY_KIND: "dict[str, str]" = {
    "dungeon-domain": "domainId",
    "dungeon-room": "roomId",
    "dungeon-layout": "layoutId",
    "dungeon-event": "eventId",
    "dungeon-quest": "questId",
    "dungeon-encounter": "encounterId",
    "dungeon-supply-ext": "consumableRef",
}


def load_dungeon_corpus(root: Path) -> Corpus:
    """Read every real dungeon seed file under `root` (e.g. `gk-data/packs/fusion/data/seed/dungeon`) into a `Corpus`,
    bridging the one-object-per-file convention `corpus.model.Corpus.load()` cannot parse (see the
    module docstring's finding 1). `_index.json` is an id->filename lookup table, never content —
    skipped by name, matching `emit.write_index`'s own contract for what it writes."""
    corpus = Corpus()
    for kind_spec in KINDS:
        dir_path = root / kind_spec.directory
        if not dir_path.is_dir():
            continue
        id_field = _ID_FIELD_BY_KIND[kind_spec.kind]
        for path in sorted(dir_path.glob("*.json")):
            if path.name == "_index.json":
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            entry_id = data.get(id_field)
            if not entry_id:
                continue
            corpus.add(Entry(
                id=entry_id, kind=kind_spec.kind, partition=kind_spec.directory,
                path=path.relative_to(root).as_posix(), data=data,
                provenance=data.get("_provenance") or {},
            ))
    return corpus


def ensure_completeness_registered() -> None:
    """Idempotent: a real `check` invocation may call this more than once in one process (e.g. a
    test suite running several checks), and `register_completeness` itself has no dedup — appending
    the same spec twice would double-count every finding. Guards on `(domain, field)` rather than
    object identity so a second call after `clear_registry()` (every `content_completeness` test's
    own isolation pattern) still re-registers correctly rather than silently staying empty."""
    if any(s.domain == "dungeon" and s.field == "flavor" for s in registered_specs()):
        return
    register_completeness(CompletenessSpec(
        domain="dungeon", kinds=frozenset({DUNGEON_EVENT_KIND}), field="flavor"))
