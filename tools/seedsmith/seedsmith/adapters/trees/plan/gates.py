"""seedsmith.adapters.trees.plan.gates — R-G1's checked-in evidence row (spec-tree-plan.md §7,
§7.1, task C2).

**The planner never resolves whether a `gateQuantity` has a production carrier.** It reads one
committed file, `gk-data/packs/fusion/data/seed/passive-tree/gate-evidence.v1.json`, that names the state
(`carrier` | `pending`) per `gateIndexKind` — never per tree, never per individual `gateQuantity`
instance. A tree's own `gateQuantity` string still varies per roster entry
(`aptitude.Might@Commander` vs `aptitude.Ferocity@Commander`), but its STATE is shared by every
tree of the same `gateIndexKind`, which is exactly why the evidence file is keyed by kind: the day
`gate-counters` lands `element_mastery`'s counter, ONE row here flips and every elemental tree's
`gateState` changes with it — "one evidence row moves and 240 nodes become generable without a
spec edit" (spec-tree-plan.md §7.1).

`resolve_gate_state` is the ONLY function anywhere in this program allowed to turn a
`gateIndexKind` into a `gateState`. A `TreeSpec` builder (e.g. `emit.might_tree_spec`) must call it
— never hand-write `"carrier"` or `"pending"` as a literal, which is the exact defect this module
exists to close.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[6]

LEGAL_GATE_STATES = ("carrier", "pending")


class GateEvidenceError(ValueError):
    """The evidence file is missing, malformed, or lacks a row a caller asked for.
    `EXIT_CANNOT_RUN` — never a default `gateState`; an unlisted kind is a data gap, not a guess."""


@dataclass(frozen=True)
class GateEvidenceRow:
    gate_index_kind: str
    gate_state: str
    evidence: str


def evidence_path(seed_root: "Path | None" = None) -> Path:
    root = seed_root or (REPO_ROOT / "data" / "seed")
    return root / "passive-tree" / "gate-evidence.v1.json"


def load_gate_evidence(seed_root: "Path | None" = None) -> "dict[str, GateEvidenceRow]":
    """Reads every row, keyed by `gateIndexKind`. Refuses on a missing file, a malformed row, an
    illegal `gateState` value, or a duplicate kind — never silently keeps the first/last one."""
    path = evidence_path(seed_root)
    if not path.exists():
        raise GateEvidenceError(f"missing checked-in gate evidence file: {path}")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as ex:
        raise GateEvidenceError(f"{path} did not parse: {ex}") from ex

    rows: "dict[str, GateEvidenceRow]" = {}
    for row in doc.get("rows", []):
        kind = row["gateIndexKind"]
        state = row["gateState"]
        if state not in LEGAL_GATE_STATES:
            raise GateEvidenceError(
                f"{path}: row {kind!r} has gateState={state!r}, must be one of {LEGAL_GATE_STATES}")
        if kind in rows:
            raise GateEvidenceError(f"{path}: duplicate gateIndexKind row {kind!r}")
        rows[kind] = GateEvidenceRow(gate_index_kind=kind, gate_state=state,
                                     evidence=row.get("evidence", ""))
    return rows


def resolve_gate_state(gate_index_kind: str, evidence: "dict[str, GateEvidenceRow]") -> str:
    """The ONLY place a tree's `gateState` may come from. Raises rather than defaulting to
    `"pending"` (the "safe-looking" choice) for an unknown kind — an unlisted `gateIndexKind` is a
    row nobody has committed yet, not a state anybody has verified."""
    if gate_index_kind not in evidence:
        raise GateEvidenceError(
            f"no checked-in gate evidence row for gateIndexKind={gate_index_kind!r} — add one to "
            f"{evidence_path()} before planning a tree that gates on it")
    return evidence[gate_index_kind].gate_state
