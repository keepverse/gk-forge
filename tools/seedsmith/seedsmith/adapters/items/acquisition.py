"""seedsmith.adapters.items.acquisition — every way a player can come to hold a thing.

Ported from `tools/seed_graph/seedgraph/corpus.py`'s `Acquisition` (S3, tasks/seedsmith-todo.md).
Two shapes, and conflating them is how a false finding appears in both directions:

* **Specific** — a drop table names `gem.g3-001`, a recipe outputs `item.plant-stem-a-004`.
  Exactly one row becomes reachable.
* **Categorical** — a drop table says `{entryKind: equipment, role: girdle, frame: plant}`, which
  yields *any* base type in that role and frame. Hundreds of base types are reachable this way and
  not one of them is named anywhere.

Checking only specific grants would report every base type as unobtainable, which is both alarming
and wrong. Checking only categorically would miss that some gems really are unreachable, because
inserts are granted by id and nothing grants them by category.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ...corpus import Corpus, Entry


@dataclass
class Acquisition:
    specific: set[str] = field(default_factory=set)
    equipment_slots: set[tuple[str, str]] = field(default_factory=set)  # (role, frame)
    material_runtime_ids: set[str] = field(default_factory=set)

    @classmethod
    def build(cls, corpus: Corpus) -> "Acquisition":
        acq = cls()

        for table in corpus.by_kind("drop-table"):
            for group in table.get("groups") or []:
                for row in group.get("entries") or []:
                    kind = row.get("entryKind")
                    ref = row.get("ref")
                    if kind == "equipment":
                        role, frame = row.get("role"), row.get("frame")
                        if role and frame:
                            acq.equipment_slots.add((role, frame))
                    elif kind == "material" and ref:
                        acq.material_runtime_ids.add(ref)
                        acq.specific.add(ref)
                    elif ref:
                        acq.specific.add(ref)

        for recipe in corpus.by_kind("recipe"):
            ref = recipe.get("outputRef")
            if ref:
                acq.specific.add(ref)

        return acq

    def reaches(self, entry: Entry) -> bool:
        if entry.id in self.specific:
            return True
        runtime = entry.get("runtimeId")
        if runtime and runtime in self.specific:
            return True
        if entry.kind == "base-type":
            return (entry.get("role"), entry.get("frame")) in self.equipment_slots
        return False
