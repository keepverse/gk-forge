"""seedsmith.adapters.items.buildfavor — build-favor label validation
(item/spec-requirement-profiles.md §"Tuning and Seedsmith boundary", species-gear-chain T36).

Seedsmith may classify a CLOSED build-favor label while generating a seed. This module resolves
that label to legal aptitude ids for the catalog content pool — identity only, never a magnitude.
A model never supplies a threshold, weight, share, reserve, cost, period, or runtime input; anything
numeric in a classification answer is `blocked` on sight (LLMs author identity only).

Labels (closed — a new label is a reviewed change here AND in the C# resolver's pool contract):
- the three postures (`force`, `finesse`, `bastion`) → their four aptitudes each;
- each of the twelve aptitude ids → itself (a focused single-aptitude favor).

`blocked` follows the pipeline's validate-before-accept rule: invalid classification writes no
seed, it records a reason instead (droptablegen/run.py's own outcome vocabulary).
"""
from __future__ import annotations

APTITUDES: "tuple[str, ...]" = (
    "Might", "Fortitude", "Vigor", "Onslaught",
    "Agility", "Composure", "Pierce", "Focus",
    "Bulwark", "Retribution", "Precision", "Ferocity",
)

POSTURES: "dict[str, tuple[str, ...]]" = {
    "force": ("Might", "Fortitude", "Vigor", "Onslaught"),
    "finesse": ("Agility", "Composure", "Pierce", "Focus"),
    "bastion": ("Bulwark", "Retribution", "Precision", "Ferocity"),
}

#: The closed label vocabulary: postures plus every aptitude id (a focused single favor).
LABELS: "frozenset[str]" = frozenset(list(POSTURES) + list(APTITUDES))


class Blocked(Exception):
    """Invalid classification — writes no seed, records a reason (pipeline `blocked` outcome)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def resolve(label: str) -> "tuple[str, ...]":
    """A closed label to its legal aptitude ids, ordinally sorted. Unknown labels are `blocked`."""
    if label in POSTURES:
        return POSTURES[label]
    if label in APTITUDES:
        return (label,)
    raise Blocked(f"unknown build-favor label '{label}' — the label vocabulary is closed")


def check_classification(answer: dict) -> "tuple[str, ...]":
    """Validate one classification answer (`{"buildFavor": <label>}`): the label must be closed and
    the answer must carry no balance magnitude anywhere — numbers are never classification output.
    Returns the resolved pool; raises `Blocked` otherwise, writing no seed."""
    if not isinstance(answer, dict):
        raise Blocked("classification answer is not an object")
    for key, value in answer.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            raise Blocked(
                f"classification carries a balance magnitude at '{key}' — "
                "models author identity only, never numbers")
        if isinstance(value, dict) and any(
                isinstance(v, (int, float)) and not isinstance(v, bool)
                for v in value.values()):
            raise Blocked(
                f"classification carries a balance magnitude under '{key}' — "
                "models author identity only, never numbers")
    label = answer.get("buildFavor")
    if not isinstance(label, str):
        raise Blocked("classification names no build-favor label")
    return resolve(label)
