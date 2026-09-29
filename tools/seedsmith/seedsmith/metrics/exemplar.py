"""seedsmith.metrics.exemplar — ExemplarConformance (spec-planner.md §4; S7,
tasks/seedsmith-todo.md).

An exemplar is the most-read file in a corpus during authoring, and a wrong one is
indistinguishable from a wrong contract — three separate historical defects propagated this way:
`powerAxis` missing from a unique exemplar, and a set exemplar teaching members-by-role-alone
(no base type pinned), which is what produced 30 uncompletable sets in one wave. Every exemplar
must validate as real content of its own kind, through the same gates as shipping content.
"""
from __future__ import annotations

from .model import Ctx, Finding, Loop, Metric, Severity


def _pinned_set_members(members: "list") -> "list":
    return [m for m in members if isinstance(m, dict)
           and (m.get("baseType") or m.get("containerId") or m.get("container_id"))]


class ExemplarConformance(Metric):
    id = "ExemplarConformance/InvalidShape"
    family = "ExemplarConformance"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"corpus", "adapter"})
    covers: tuple[str, ...] = ("appendix-a:9",)

    def run(self, ctx: Ctx) -> list[Finding]:
        kind_specs = {k.kind: k for k in ctx.adapter.kinds()}
        findings = []

        for entry in ctx.corpus.exemplars.values():
            spec = kind_specs.get(entry.kind)
            if spec is None:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=entry.id,
                    message=f"exemplar '{entry.id}' declares kind '{entry.kind}', which no "
                            f"KindSpec defines",
                    evidence={"code": "UnknownKind", "kind": entry.kind}))
                continue

            missing = sorted(f for f in spec.required if f not in entry.data)
            if missing:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=entry.id,
                    message=f"exemplar '{entry.id}' ({entry.kind}) is missing required field(s) "
                            f"{missing} — an author copying this pattern inherits the gap",
                    evidence={"code": "RequiredFieldMissing", "missing": missing}))

            allowed = spec.required | spec.optional
            unknown = sorted(f for f in entry.data if f not in allowed)
            if unknown:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=entry.id,
                    message=f"exemplar '{entry.id}' ({entry.kind}) carries field(s) {unknown} "
                            f"that no KindSpec allows for this kind",
                    evidence={"code": "UnknownField", "unknown": unknown}))

            if entry.kind == "set":
                members = entry.get("members") or []
                if members and not _pinned_set_members(members):
                    findings.append(Finding(
                        metric=self.id, severity=Severity.GAP, subject=entry.id,
                        message=f"exemplar '{entry.id}' declares {len(members)} set members by "
                                f"role only; every author copying it ships an uncompletable set",
                        evidence={"code": "SetUncompletable", "memberCount": len(members)}))
        return findings
