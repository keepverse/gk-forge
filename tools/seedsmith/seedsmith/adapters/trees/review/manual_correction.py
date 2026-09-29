"""seedsmith.adapters.trees.review.manual_correction — the ONE sanctioned exception to "a rejection
regenerates, never edits" (task J3, spec-tree-review.md §6.1).

§6.1, restated: *"Nothing here mutates the draft into legality. A draft that broke a rule is
REFUSED with the rule named, because silently repairing it teaches the next call nothing... The one
sanctioned exception exists and keeps its discipline: the `manualCorrection` block, which records
`from` / `to` / `by` / `why`. A hand correction is legal, must be provenance-stamped, and its rate
is itself a metric. Above a declared threshold it means the prompt is wrong and the batch should
have been rejected."*

**Scope, stated rather than assumed.** This module builds the record shape and the rate
computation §6.1 names — both real, both pure, both testable today. It does NOT build a "stamp a
correction onto a committed node" CLI verb or wire a new field onto `NodeSeedRecord`: nothing in
this program has a reviewer surface that would ever CALL such a thing yet (no UI, no CLI verb reads
or writes a correction) — inventing that call site now would be building for a caller that does not
exist, which this repo's own engineering discipline treats as a defect, not diligence. The day a
real reviewer surface exists, it constructs a `ManualCorrection` and calls
`manual_correction_rate_permille` over whatever set it collects — this module is ready for that
caller without needing to change; only the caller is missing, which is a wiring gap
(`AGENTS.md`'s own rule), never an architectural wall.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class ManualCorrection:
    """§6.1's own four fields, verbatim — no fifth field invented, no field renamed. `node_id`
    identifies WHICH node's draft was hand-corrected (not itself one of the spec's four, but
    required to stamp a correction onto anything at all — every real record needs a subject)."""

    node_id: str
    from_text: str
    to_text: str
    by: str
    why: str

    def __post_init__(self) -> None:
        if not self.why.strip():
            raise ValueError(
                f"{self.node_id}: a manualCorrection with an empty 'why' is refused — §6.1's own "
                f"discipline is that a hand correction is legal only when provenance-stamped, and "
                f"an unstated reason is not provenance")
        if self.from_text == self.to_text:
            raise ValueError(
                f"{self.node_id}: manualCorrection.from equals .to — a correction that changes "
                f"nothing is not a correction, and would silently inflate the rate metric below "
                f"for zero real edits")


def manual_correction_rate_permille(corrections: "Sequence[ManualCorrection]", total_nodes: int) -> int:
    """§6.1's own "its rate is itself a metric" — corrections per thousand nodes IN THE SAME LOT,
    never per corrections-file or per some other denominator (a rate against the wrong denominator
    both over- and under-states how much of the corpus needed a human hand, in opposite directions
    depending on lot size). `total_nodes == 0` is a refusal, never a silent zero: a rate with no
    denominator is not a rate, and a corpus this module was never told the size of must not be
    reported as "0‰ corrected" — the same "an absent check is never a pass" discipline named
    elsewhere in this program applies to a rate with no real denominator too."""
    if total_nodes <= 0:
        raise ValueError(
            f"manual_correction_rate_permille: total_nodes must be positive, got {total_nodes} — "
            f"a rate with no real denominator is not measured, not zero")
    return (len(corrections) * 1000) // total_nodes
