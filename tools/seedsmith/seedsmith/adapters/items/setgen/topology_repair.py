"""seedsmith.adapters.items.setgen.topology_repair — species-gear-chain T27, the `setClass` half's
backward pass (`set-species-binding` a, spec-set-species-binding.md rev 2 § The set-planning system).

Deterministic, model-free re-plan: every shipped `set` entry gets a `setClass` resolved from its OWN
declared topology — the count of DISTINCT member roles and its threshold list — through
`topology.stamp_class`, the same function `seedfile.set_entry` uses forward. There is no second
opinion about an entry's shape, because there is only one resolver.

⛔ **A shape no class admits refuses the WHOLE run**, naming the file and the entry. It is never
written as `general`, and no fourth `legacy`/`unclassified` class is invented for it — the owner's
2026-09-21 ruling refused exactly that bucket. This is the same posture `species_repair` takes for a
`creature.*` themeKey that does not resolve.

⛔ **Two phases, so a refusal writes nothing.** The first pass resolves and validates every partition
in memory; only when the whole corpus is classifiable does the second pass write. A single-pass
repair would leave the first half of a 885-file corpus rewritten when file 700 turned out to be
unclassifiable — a partial migration that no ledger describes.

Idempotent by construction: an entry already carrying the correct class is left byte-identical, so a
second run reports zero changed entries and writes nothing.
"""
from __future__ import annotations

import collections
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import topology
from .seedfile import ITEM_SEED_ROOT
from .species_repair import plan_set_partitions, write_document
from .topology import SetTopologyError, SetTopologyTuning


@dataclass(frozen=True)
class TopologyRepairFile:
    path: Path
    changed_entries: int
    total_entries: int


@dataclass(frozen=True)
class TopologyRepairResult:
    files: "tuple[TopologyRepairFile, ...]"
    #: class id -> how many entries the run resolved to it. A READING: it moves whenever content
    #: ships, and the tests print it rather than pinning it (`validation-ssot.md`).
    tally: "dict[str, int]"
    entries: int

    @property
    def changed_entries(self) -> int:
        return sum(f.changed_entries for f in self.files)

    @property
    def changed_files(self) -> int:
        return len(self.files)


def repair_set_classes(*, sets_dir: "Path | None" = None,
                       tuning: "SetTopologyTuning | None" = None,
                       write: bool = False) -> TopologyRepairResult:
    """Plan, or apply, `setClass` for every production `set` partition.

    `write=False` is a read-only plan — the contract `repair_species_ids` and `repair_set_corpus`
    already established. The tuning is loaded once for the whole run (both reads — the class file and
    the set-shape file it borrows the mandatory threshold from — happen once, not once per entry).
    """
    target = Path(sets_dir or (ITEM_SEED_ROOT / "sets")).resolve()
    resolved_tuning = tuning if tuning is not None else topology.load()

    tally: "collections.Counter[str]" = collections.Counter()
    pending: "list[tuple[Path, dict, int, int]]" = []      # (path, document, changed, entries)
    entries = 0

    for path, document in plan_set_partitions(target):
        partition_entries = document.get("entries") or []
        changed = 0
        for entry in partition_entries:
            if not isinstance(entry, dict):
                raise SetTopologyError(f"{path}: set partition holds a non-object entry")
            existing = entry.get("setClass")
            try:
                class_id = topology.stamp_class(entry, resolved_tuning)
            except SetTopologyError as error:
                # The whole run refuses: an unclassifiable shape is a defect to report, never a
                # class to guess. `stamp_class` has not mutated the entry when it raises.
                raise SetTopologyError(f"{path.name}: {error}") from None
            tally[class_id] += 1
            # Idempotence is counted, not assumed: an entry already carrying its correct class leaves
            # a byte-identical document and is NOT reported as a change, so a second run over a
            # repaired corpus writes nothing at all.
            if existing != class_id:
                changed += 1
        entries += len(partition_entries)
        if changed:
            pending.append((path, document, changed, len(partition_entries)))

    # Phase 2 — every entry above was classifiable, so the corpus can be written as one unit.
    if write:
        for path, document, _changed, _total in pending:
            write_document(path, document)

    return TopologyRepairResult(
        files=tuple(TopologyRepairFile(path=path, changed_entries=changed,
                                       total_entries=total)
                    for path, _document, changed, total in pending),
        tally=dict(sorted(tally.items())),
        entries=entries,
    )


def repair_report(result: TopologyRepairResult, *, write: bool) -> "dict[str, Any]":
    """The run's own numbers. `resolvedByClass` is printed and never asserted — it is how a human
    reads which classes the shipped corpus actually lands on (spec rev 2's re-plan table)."""
    return {
        "write": write,
        "entries": result.entries,
        "changedEntries": result.changed_entries,
        "changedFiles": result.changed_files,
        "resolvedByClass": result.tally,
        "files": [{"path": str(f.path), "changedEntries": f.changed_entries,
                   "totalEntries": f.total_entries} for f in result.files],
    }
