"""seedsmith.adapters.items.consumablegen.emit — an answer -> a real, corpus-shaped `consumable`
entry (the exact fields `kinds.py:98-101`'s `KindSpec` declares legal, matching the shape
`k1.json`/`k2.json`/`k3.json` already ship).

**What the model answered vs. what code resolves — the split acceptance criterion 1 draws.** Only
`classId`, `useContext`, `family`, `element`, `tags`, `name`, `nameKey`, `notes` come from the
answer; `powerBand` and `manifestCost` are resolved here, deterministically, from a partition
sequence number — never from the model's own judgment of a magnitude (the same discipline
`setgen/brief.py` states for a set's threshold ladder: "never choose a number... those are resolved
after you answer").

**The powerBand/manifestCost policy is this module's OWN new-content default, not a retrofit rule.**
Measured against the real 60-row corpus: `manifestCost` is not a pure function of `powerBand` there
(nine `high`-band rows split 5-of-1 vs 4-of-2, e.g. `k2.json`'s `k2-009`/`k2-017` are `high`/1 while
`k1.json`'s `k1-019`/`k1-020` are `high`/2) — so this policy is stated as what THIS module does for
newly generated rows, not as a rule the shipped 60 already follow.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import schema

#: The rotation newly generated rows cycle through -- `extreme` is legal (bands.v1.json) but never
#: used by the shipped 60, so it is left out of the default rotation; a caller wanting it passes
#: `bands=schema.load_power_bands()` explicitly.
DEFAULT_BAND_ROTATION: "tuple[str, ...]" = ("trivial", "low", "medium", "high")

#: `manifestCost` for a `high`/`extreme` row. Every band below costs 1 -- the majority shape in the
#: real corpus (11 of 20 `_registry`-adjacent... measured directly: of the 9 `high`-band rows across
#: k1-k3, 5 cost 1 and 4 cost 2; no `trivial`/`low`/`medium` row costs more than 1). Picking the
#: majority-consistent, monotonic rule rather than inventing a finer one this module has no data to
#: justify.
HIGH_BAND_MANIFEST_COST = 2


def resolve_power_band(seq: int, *, rotation: "tuple[str, ...]" = DEFAULT_BAND_ROTATION) -> str:
    """Deterministic, order-preserving band assignment -- the Nth generated row (0-based) always
    gets the same band across runs, which is what makes a resumed/reconciled run reproducible."""
    if not rotation:
        raise ValueError("rotation must not be empty")
    return rotation[seq % len(rotation)]


def resolve_manifest_cost(power_band: str) -> int:
    bands = schema.load_power_bands()
    if power_band not in bands:
        raise ValueError(f"powerBand {power_band!r} is not one of {bands}")
    return HIGH_BAND_MANIFEST_COST if power_band in ("high", "extreme") else 1


@dataclass(frozen=True)
class AnswerDefect:
    field: str
    reason: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.field}: {self.reason}"


def validate_answer(answer: dict) -> "list[AnswerDefect]":
    """Schema-shaped defects only -- the closed-vocabulary checks a brief's own construction should
    have already made unreachable, kept here as a backstop (the same relationship `setgen`'s own
    `SetRoleNotUniversal` load-time check has to its brief-side cap). The `family` EXTERNAL check is
    deliberately NOT here -- that is `run.py`'s job, via `dependency_validator`, so the EXTERNAL
    reference kind's "never auto-backfilled" contract stays visible at the call site that owns it.
    """
    defects: "list[AnswerDefect]" = []
    class_id = answer.get("classId")
    if class_id not in schema.AUTHORABLE_CLASS_IDS:
        defects.append(AnswerDefect(
            "classId", f"{class_id!r} is not one of {sorted(schema.AUTHORABLE_CLASS_IDS)}"))

    use_context = answer.get("useContext")
    if not isinstance(use_context, list) or not use_context:
        defects.append(AnswerDefect("useContext", "must be a non-empty list"))
    else:
        bad = [c for c in use_context if c not in schema.AUTHORABLE_USE_CONTEXTS]
        if bad:
            defects.append(AnswerDefect(
                "useContext", f"{bad} is not a subset of {sorted(schema.AUTHORABLE_USE_CONTEXTS)}"))

    family = answer.get("family")
    if not isinstance(family, str) or not family:
        defects.append(AnswerDefect("family", "must be a non-empty string"))

    element = answer.get("element")
    if element is not None:
        if family not in ("atom.elemental-power", "atom.elemental-defense"):
            defects.append(AnswerDefect(
                "element", f"only legal when family is elemental-power/elemental-defense, got "
                           f"family={family!r}"))

    tags = answer.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        defects.append(AnswerDefect("tags", "must be a list of strings"))

    for required in ("name", "nameKey"):
        value = answer.get(required)
        if not isinstance(value, str) or not value:
            defects.append(AnswerDefect(required, "must be a non-empty string"))

    return defects


def build_entry(answer: dict, *, entry_id: str, seq: int,
                 rotation: "tuple[str, ...]" = DEFAULT_BAND_ROTATION) -> dict:
    """Answer + a resolved sequence -> one entry, in the exact field order/shape the real corpus
    ships (`id`, `nameKey`, `name`, `classId`, `useContext`, `family`, optional `element`,
    `powerBand`, `manifestCost`, `tags`, optional `notes`). Raises if `validate_answer` would report
    a defect -- call that first if a caller wants defects reported rather than raised."""
    defects = validate_answer(answer)
    if defects:
        raise ValueError(f"cannot emit {entry_id!r}: {[str(d) for d in defects]}")

    power_band = resolve_power_band(seq, rotation=rotation)
    entry = {
        "id": entry_id,
        "nameKey": answer["nameKey"],
        "name": answer["name"],
        "classId": answer["classId"],
        "useContext": list(answer["useContext"]),
        "family": answer["family"],
        "powerBand": power_band,
        "manifestCost": resolve_manifest_cost(power_band),
        "tags": list(answer.get("tags", [])),
    }
    if answer.get("element") is not None:
        entry["element"] = answer["element"]
    if answer.get("notes"):
        entry["notes"] = answer["notes"]
    return entry
