"""Idempotence and provenance (spec-pipeline.md, plan G2).

Two questions this makes answerable about any generated row:

- **"Why does this row exist?"** — the finding it was generated to close.
- **"Which prompt version produced it?"** — so a bad batch is scoped by version rather than by
  eyeballing dates.

And one it makes unnecessary: **"will re-running duplicate everything?"** A pipeline checks whether
its finding is already closed *before* generating. Re-running over unchanged input writes nothing,
which is what makes the whole loop safe to run on a schedule rather than only by hand.

**The clock is injected.** A timestamp is the one field that would otherwise make provenance
non-reproducible, and a test that cannot pin it either asserts nothing about it or becomes flaky.
Same discipline as the kernel drive's injected `Stopwatch`.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

__all__ = [
    "Provenance",
    "ProvenanceLedger",
    "PROVENANCE_FIELD",
    "PROVENANCE_MODEL_SENTINELS",
    "provenance_model",
    "SkipReason",
    "should_generate",
]

#: The closed non-id stamp vocabulary for a provenance `model` field (spec-model-config-resolve
#: §3.4). A stamp is either a *resolved* model id (whatever the call actually used — an open set no
#: code can enumerate) or exactly one of these two, and the distinction is load-bearing:
#: `unrecorded` means "a replayed answer whose model was not recorded", `none` means "a
#: deterministic generator made this row with no model call". Neither is "unknown" and neither is
#: ever sent to a transport. This tuple is a DECLARATION: adding a third spelling is a reviewed
#: change, not a convenience.
PROVENANCE_MODEL_SENTINELS: "tuple[str, ...]" = ("unrecorded", "none")


def provenance_model(model: str) -> str:
    """Validate and return a provenance `model` stamp.

    Refuses an empty or whitespace-only stamp — the defect class this whole contract exists to end
    is a provenance field holding a value nobody resolved (`seedsmith-basetypegen`, `gemgen/1`,
    `claude-sonnet-5`), and a blank string is the same defect with nothing to grep for. A resolved
    model id passes through unchanged; so do the two closed sentinels in
    `PROVENANCE_MODEL_SENTINELS`.
    """
    if not isinstance(model, str) or not model.strip():
        raise ValueError(
            "provenance model must be a resolved model id, 'unrecorded' or 'none' — "
            f"got {model!r}")
    return model

#: The key a generated entry carries its provenance under. Underscore-prefixed to match the corpus's
#: existing `_meta` convention for non-content metadata.
PROVENANCE_FIELD = "_provenance"


@dataclass(frozen=True)
class Provenance:
    """Why one generated row exists, and what produced it."""

    pipeline: str
    model: str
    prompt_version: str
    budget_version: int
    finding: str                    # "metric:subject" — the finding this row was generated to close
    generated_utc: str

    def to_dict(self) -> dict:
        return {
            "pipeline": self.pipeline,
            "model": self.model,
            "promptVersion": self.prompt_version,
            "budgetVersion": self.budget_version,
            "finding": self.finding,
            "generatedUtc": self.generated_utc,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Provenance":
        return cls(
            pipeline=data["pipeline"],
            model=data["model"],
            prompt_version=data["promptVersion"],
            budget_version=data["budgetVersion"],
            finding=data["finding"],
            generated_utc=data["generatedUtc"],
        )


class SkipReason:
    """Why a run generated nothing. Named constants rather than free text, because these are read by
    the grader as well as by a human."""

    FINDING_ALREADY_CLOSED = "finding-already-closed"
    ALREADY_GENERATED = "already-generated-by-this-pipeline"


def should_generate(
    finding: str,
    *,
    open_findings: Iterable[str],
    ledger: "ProvenanceLedger | None" = None,
) -> tuple[bool, str]:
    """Decide before spending anything.

    Order matters: the **finding** is checked first, not the ledger. A finding that a *human* closed,
    or that another pipeline closed, must stop this one too — checking only "did I already run"
    would regenerate content whose reason for existing had gone away.

    Returns `(generate, reason)`; `reason` is empty when generating.
    """
    if finding not in set(open_findings):
        return False, SkipReason.FINDING_ALREADY_CLOSED
    if ledger is not None and ledger.rows_for_finding(finding):
        return False, SkipReason.ALREADY_GENERATED
    return True, ""


@dataclass
class ProvenanceLedger:
    """Every generated row's provenance, queryable by finding.

    Deliberately an index rather than a scan: "which rows did this finding produce" is the question
    asked when a batch turns out bad, and at that moment nobody wants to grep a corpus.
    """

    _by_row: dict[str, Provenance] = field(default_factory=dict)
    _by_finding: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def record(self, row_id: str, prov: Provenance) -> None:
        if row_id in self._by_row:
            # Re-recording a row is a real defect: it means two runs both believed they created it,
            # which is exactly the duplicate-write G2 exists to prevent. Loud, not last-write-wins.
            raise ValueError(
                f"row {row_id!r} already has provenance from pipeline "
                f"{self._by_row[row_id].pipeline!r} — a second write means idempotence failed"
            )
        self._by_row[row_id] = prov
        self._by_finding[prov.finding].append(row_id)

    def of(self, row_id: str) -> "Provenance | None":
        return self._by_row.get(row_id)

    def rows_for_finding(self, finding: str) -> tuple[str, ...]:
        return tuple(self._by_finding.get(finding, ()))

    def rows_for_prompt_version(self, version: str) -> tuple[str, ...]:
        """Scope a bad batch by what produced it, rather than by when it happened."""
        return tuple(sorted(r for r, p in self._by_row.items() if p.prompt_version == version))

    def __len__(self) -> int:
        return len(self._by_row)


def stamp(
    entry: Mapping[str, Any],
    prov: Provenance,
) -> dict:
    """Attach provenance to a generated entry without mutating the caller's object.

    A copy, not an in-place write: the entry usually came from the model's parsed output, and
    mutating it makes the pre-stamp value unavailable for comparison — which is precisely what an
    idempotence check needs.
    """
    return {**entry, PROVENANCE_FIELD: prov.to_dict()}
