"""seedsmith.corpus.model — Entry, Edge, Corpus.

Three things this module must get right, each learned the hard way building the item corpus
by hand (spec-foundation §1):

- Edges are discovered, not declared — `discover_edges()` takes an id-shaped pattern from
  whichever adapter calls it and records every matching string as an edge, whether or not it
  resolves, so a broken reference is visible rather than silently absent from the graph.
- Minted runtime ids are first-class — `register_minted_ids()` lets a caller tell the corpus
  about ids that exist but were never an entry's own `id` (a milestone-minted atom id, say), so
  `resolves()` consults both.
- Exemplars load but are flagged — `is_exemplar` is true for anything under a top-level
  `_exemplars/` directory; they stay in the graph (so they can themselves be validated) but never
  occupy a slot in a cross-row ledger, a rule a metric can check for by testing this flag.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Pattern


class CorpusLoadError(Exception):
    """A `.json` file under the corpus root could not be parsed at all.

    Distinct from "this file isn't a seed file" (silently skipped — a stray registry document,
    for instance) and distinct from any content-level Finding: this is "the tool could not run,"
    which the CLI must report as exit code 2, never as a GAP-severity finding (exit 1).
    """

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


@dataclass(frozen=True)
class Entry:
    id: str
    kind: str
    partition: str
    path: str            # relative to the corpus root, forward-slash, for stable messages
    data: dict
    provenance: dict = field(default_factory=dict)  # the file's `_meta`, partition included
    is_exemplar: bool = False

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    @property
    def name(self) -> str:
        return self.data.get("name", self.id)


@dataclass(frozen=True)
class Edge:
    from_id: str
    to_id: str
    via: str  # dotted/bracketed field path within the source entry's data, e.g. "members[0].ref"


def _iter_string_leaves(value, path: str):
    """Yield (field_path, string) for every string leaf reachable inside `value`, recursing
    through dicts and lists so a reference three levels deep in an array is still discovered."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _iter_string_leaves(v, f"{path}.{k}" if path else k)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _iter_string_leaves(v, f"{path}[{i}]")


@dataclass
class Corpus:
    entries: dict[str, Entry] = field(default_factory=dict)
    exemplars: dict[str, Entry] = field(default_factory=dict)
    by_kind_index: dict[str, list[Entry]] = field(default_factory=dict)
    by_partition_index: dict[str, list[Entry]] = field(default_factory=dict)
    _minted_ids: set[str] = field(default_factory=set)

    def add(self, entry: Entry) -> None:
        """An exemplar and real content routinely share an id on purpose — an exemplar's whole
        job is to show the shape of a real, shipped row, and this corpus genuinely has four
        base-type, one set, and one unique exemplar doing exactly that (confirmed 2026-08-23).
        So exemplars go into their OWN ledger, never `entries` — the literal reading of
        spec-foundation §1's "must never occupy a slot in any cross-row ledger." A real id
        colliding with ANOTHER real id is a different and genuinely serious defect (two shipped
        rows silently overwriting each other on lookup), so THAT case still raises.
        """
        if entry.is_exemplar:
            self.exemplars[entry.id] = entry
            return
        if entry.id in self.entries:
            raise CorpusLoadError(
                Path(entry.path),
                f"duplicate id {entry.id!r} — already loaded from "
                f"{self.entries[entry.id].path!r}",
            )
        self.entries[entry.id] = entry
        self.by_kind_index.setdefault(entry.kind, []).append(entry)
        self.by_partition_index.setdefault(entry.partition, []).append(entry)

    def by_id(self, entry_id: str) -> Entry | None:
        return self.entries.get(entry_id)

    def by_exemplar_id(self, entry_id: str) -> Entry | None:
        return self.exemplars.get(entry_id)

    def by_kind(self, kind: str) -> list[Entry]:
        return self.by_kind_index.get(kind, [])

    def by_partition(self, partition: str) -> list[Entry]:
        return self.by_partition_index.get(partition, [])

    @property
    def kinds(self) -> frozenset[str]:
        return frozenset(self.by_kind_index)

    @property
    def partitions(self) -> frozenset[str]:
        return frozenset(self.by_partition_index)

    def register_minted_ids(self, ids: "list[str] | set[str] | frozenset[str]") -> None:
        """Tell the corpus about ids that exist but are not — and will never be — any entry's
        own `id` (spec-foundation §1's four-defect tracking-id-vs-runtime-id split)."""
        self._minted_ids.update(ids)

    @property
    def minted_ids(self) -> frozenset[str]:
        return frozenset(self._minted_ids)

    def resolves(self, ref: str) -> bool:
        """True if `ref` is a real entry id OR a registered minted runtime id."""
        return ref in self.entries or ref in self._minted_ids

    def discover_edges(self, id_pattern: Pattern[str],
                       skip_fields: "frozenset[str] | set[str]" = frozenset()) -> list[Edge]:
        """Walk every entry's data and record every string matching `id_pattern` as an edge,
        whether or not it resolves. `skip_fields` excludes leaf field names that legitimately
        hold id-shaped prose (a `name`/`nameKey` that happens to look like a namespaced id) —
        supplied by the caller, since which fields those are is adapter knowledge, not the
        corpus's."""
        edges: list[Edge] = []
        for entry in self.entries.values():
            for path, value in _iter_string_leaves(entry.data, ""):
                # the entry's OWN `id` is identity, never an outgoing reference — the same
                # `IsKeyField` exclusion the C# validator applies, caught here by a test that
                # deliberately fed an id-shaped `id` field back through discover_edges.
                if path == "id" or path.rsplit(".", 1)[-1].split("[")[0] in skip_fields:
                    continue
                if id_pattern.match(value):
                    edges.append(Edge(entry.id, value, path))
        return edges

    @classmethod
    def load(cls, root: Path) -> "Corpus":
        """Load every seed file under `root`. Pure: no network, no database, no mutation of
        anything outside the returned graph.

        A file is a seed file iff its top-level JSON object has both a non-empty `kind` and an
        `entries` list — anything else (a registry document, a stray non-seed JSON file) is
        silently not corpus content, exactly as the C# validator's `SeedFile.Kind`/`Entries`
        already treat it. A file that fails to PARSE at all raises `CorpusLoadError` naming the
        file — that is a "the tool could not run" condition, not a content Finding.
        """
        corpus = cls()
        for path in sorted(root.rglob("*.json")):
            rel = path.relative_to(root)
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as e:
                raise CorpusLoadError(rel, f"unreadable: {e}") from e
            try:
                doc = json.loads(text)
            except json.JSONDecodeError as e:
                raise CorpusLoadError(rel, f"invalid JSON: {e}") from e

            if not isinstance(doc, dict):
                continue
            kind = doc.get("kind")
            raw_entries = doc.get("entries")
            if not kind or not isinstance(raw_entries, list):
                continue

            is_exemplar = rel.parts[0] == "_exemplars" if rel.parts else False
            provenance = doc.get("_meta") or {}
            partition = provenance.get("partition", "(none)")
            rel_posix = rel.as_posix()

            for row in raw_entries:
                if not isinstance(row, dict) or not row.get("id"):
                    continue
                corpus.add(Entry(
                    id=row["id"], kind=kind, partition=partition, path=rel_posix,
                    data=row, provenance=provenance, is_exemplar=is_exemplar,
                ))
        return corpus
