"""seedsmith.adapters.trees.review.verdict_queue — the committed artifact J3's own second
acceptance bullet names (spec-tree-review.md §6.1, §6.2, project structure's own
`data/seed/passive-tree/_review/<lot>.json`): "a review producing no artifact did not happen."

Schema matches `sample.census_review_queue`'s own already-established read shape exactly
(`{lot, entries: [...]}`) — that function was built first (task J2) and already commits to reading
this shape; this module is the WRITER half, never a second, incompatible schema.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: §6.2's own ladder, by rung number — used to validate a queue entry's `rung` rather than accept
#: any integer.
RUNGS: "tuple[int, ...]" = (0, 1, 2, 3, 4, 5)


@dataclass(frozen=True)
class VerdictQueueEntry:
    """One rejection, at whatever rung it landed on (§6.2's own table). `subject_id` is a node id
    for rungs 0-1, a tree id for rung 2, a quota-cell key (`sample.quota_cell_key`'s own shape) for
    rung 3, `"(corpus)"` for rung 4 (batch reject has no single subject), and a free-text question
    for rung 5 (owner escalation — `legitimateSkew`, or any decision the plan cannot make).
    `reason` is the reviewer's own stated objection (§6.2 rung 1: "the reviewer's reason appended to
    the brief as an anti-motif") — never a raw system exception string; a rung-0 auto-repair's own
    `FAILED:<reason>` is a DIFFERENT, already-existing record (H2's own `_normalize_blocked`/gate
    machinery), not this queue's concern, which starts at rung 1 (a human or a corpus-level
    decision, never an in-run auto-repair)."""

    subject_id: str
    rung: int
    reason: str

    def __post_init__(self) -> None:
        if self.rung not in RUNGS:
            raise ValueError(f"{self.subject_id}: rung must be one of {RUNGS}, got {self.rung}")
        if not self.reason.strip():
            raise ValueError(
                f"{self.subject_id}: an empty reason is refused — §6.1's own rule (\"a rejection "
                f"names the rule\") applies to every rung, not only the auto-repair one")

    def to_dict(self) -> dict:
        return {"subjectId": self.subject_id, "rung": self.rung, "reason": self.reason}

    @classmethod
    def from_dict(cls, doc: dict) -> "VerdictQueueEntry":
        return cls(subject_id=str(doc["subjectId"]), rung=int(doc["rung"]), reason=str(doc["reason"]))


def write_verdict_queue(review_dir: "Path | str", lot: str,
                        entries: "tuple[VerdictQueueEntry, ...]") -> Path:
    """§6.1: "a review producing no artifact did not happen" — called EVERY TIME a review completes,
    even when `entries` is empty (an empty, committed `{lot, entries: []}` file is the honest record
    of "this lot was reviewed and rejected nothing," distinct from "this lot was never reviewed at
    all," which `sample.census_review_queue`'s own missing-file case already represents)."""
    path = Path(review_dir) / f"{lot}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"lot": lot, "entries": [e.to_dict() for e in entries]}
    path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    return path


def read_verdict_queue(review_dir: "Path | str", lot: str) -> "tuple[VerdictQueueEntry, ...]":
    """The read half — a missing file is an honest `()`, matching
    `sample.census_review_queue`'s own "declared absence, not fabricated" reading exactly (this
    module never re-derives that distinction a second way)."""
    path = Path(review_dir) / f"{lot}.json"
    if not path.exists():
        return ()
    doc = json.loads(path.read_text(encoding="utf-8"))
    return tuple(VerdictQueueEntry.from_dict(e) for e in doc.get("entries", ()))


def anti_motifs_for_node(entries: "tuple[VerdictQueueEntry, ...]", node_id: str, *,
                         tree_id: "str | None" = None) -> "tuple[str, ...]":
    """§6.1/§6.2 rung 1: "the reviewer's reason appended to the brief as an anti-motif. Never
    hand-write it" — every queue entry naming EXACTLY this node (rung 0/1) or this node's OWN tree
    (rung 2 — a tree reject regenerates every node in it, so the tree-level reason applies to all of
    them) becomes one anti-motif line for the node's next regeneration brief. Rung 3/4/5 entries
    (cell/batch/owner) are deliberately NOT included here — §6.2's own table routes those through a
    PLAN or PROMPT change, not a per-node anti-motif; folding them in here would silently duplicate
    a fix `nodegen/quota.py`'s own permitted-subset or `brief.py`'s own template already carries.
    Order is the queue's own commit order (never re-sorted), so a rerun over an unchanged queue
    renders an identical brief.
    """
    motifs: "list[str]" = []
    for entry in entries:
        if entry.subject_id == node_id and entry.rung in (0, 1):
            motifs.append(entry.reason)
        elif tree_id is not None and entry.subject_id == tree_id and entry.rung == 2:
            motifs.append(entry.reason)
    return tuple(motifs)
