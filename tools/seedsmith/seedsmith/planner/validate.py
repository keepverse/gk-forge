"""The exemplar gate: nothing is dispatched against a pattern that is already wrong (plan P3).

An exemplar is the most-read file in a corpus during authoring, so a wrong one is indistinguishable
from a wrong contract — and it propagates. `ExemplarConformance`'s own docstring records three
historical cases, including a set exemplar teaching members-by-role-alone that produced **30
uncompletable sets in one wave**.

The gate is therefore placed *before* dispatch rather than after generation. A bad exemplar caught
afterwards has already been copied into everything the order produced; caught here it costs one
refusal.

**The metric is reused, never reimplemented.** `ExemplarConformance` (S7) already encodes what a
valid exemplar is. A second copy of that judgement here would be a rule stated twice, and the copy
nobody updates is the one that decides — which is the same defect class `planner.ordering` exists to
remove for stage labels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from ..metrics.exemplar import ExemplarConformance
from ..metrics.model import Ctx, Finding

__all__ = ["ExemplarGateResult", "EXIT_EXEMPLAR_REFUSED", "gate_exemplars"]

#: spec-foundation.md §7.3's CLI contract. Named rather than inlined at the call site so the
#: contract has one home; a bare `3` at a `sys.exit` is a number nobody can grep for.
EXIT_EXEMPLAR_REFUSED = 3


@dataclass(frozen=True)
class ExemplarGateResult:
    """Whether an order may be dispatched, and if not, exactly which exemplars stopped it.

    `refused` is deliberately not merely `bool(findings)`: the gate is scoped to the exemplars an
    order would actually reference, so a corpus can hold a broken exemplar for a kind this order
    never touches and still dispatch. Refusing on unrelated breakage would make the gate something
    people route around.
    """

    refused: bool
    findings: tuple[Finding, ...] = ()
    checked: tuple[str, ...] = ()
    exit_code: int = 0

    @property
    def ok(self) -> bool:
        return not self.refused

    def explain(self) -> str:
        if not self.refused:
            return f"exemplar gate passed: {len(self.checked)} exemplar(s) conform"
        lines = [
            f"exemplar gate REFUSED the order — {len(self.findings)} finding(s) across "
            f"{len({f.subject for f in self.findings})} exemplar(s):"
        ]
        for finding in self.findings:
            lines.append(f"  - {finding.subject}: {finding.message}")
        return "\n".join(lines)


def gate_exemplars(
    ctx: Ctx,
    referenced_kinds: "Iterable[str] | None" = None,
) -> ExemplarGateResult:
    """Run `ExemplarConformance` and refuse the whole order if anything it would reference is bad.

    `referenced_kinds` scopes the gate to the kinds an order actually generates. `None` means "gate
    everything", which is the right default for a whole-corpus run and the wrong one for a single
    partition — so the caller states it rather than inheriting it.

    **Refusal is all-or-nothing.** A partially emitted order is the worst outcome available: some
    jobs dispatched against a known-bad pattern, and no single artifact showing which. The plan's
    acceptance says "refused, not partially emitted", and that is a property of this function
    returning before anything is written, not of a caller remembering to check.
    """
    findings = tuple(ExemplarConformance().run(ctx))

    if referenced_kinds is not None:
        wanted = frozenset(referenced_kinds)
        by_id = ctx.corpus.exemplars
        findings = tuple(
            f for f in findings
            if (f.subject in by_id and by_id[f.subject].kind in wanted)
        )
        checked = tuple(sorted(e.id for e in by_id.values() if e.kind in wanted))
    else:
        checked = tuple(sorted(ctx.corpus.exemplars))

    if findings:
        return ExemplarGateResult(
            refused=True,
            findings=findings,
            checked=checked,
            exit_code=EXIT_EXEMPLAR_REFUSED,
        )

    return ExemplarGateResult(refused=False, checked=checked)
