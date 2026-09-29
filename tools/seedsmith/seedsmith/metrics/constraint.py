"""seedsmith.metrics.constraint — Constraint (spec-metrics.md §3; S7, tasks/seedsmith-todo.md).

Not a re-implementation of any individual rule — it owns the *class*: a rule stated in a lane
document with no corresponding check in either tool. Expressed as a manifest of
rule -> check bindings; a documented rule with no binding anywhere is the finding.

The manifest below is real, not illustrative: eight rule codes verified live against
`gk-forge/tools/ItemSeedValidator/Checks/UniqueRuleCheck.cs`/`SetRuleCheck.cs`
(`grep -n "AddFinding|const string" ...`), plus two verified against
`seedsmith.metrics.linkage`. Building this manifest is what caught spec-metrics.md's own wrong
claim that all five historically-prose-only rules "now ship as C#" — the hybrid-core requirement
ships only in `seedsmith`, not C#, and the spec text said otherwise until this task corrected it
(see spec-metrics.md's own correction note, dated the same day).
"""
from __future__ import annotations

from dataclasses import dataclass

from .model import Ctx, Finding, Loop, Metric, Severity


@dataclass(frozen=True)
class RuleBinding:
    rule_id: str
    description: str
    source_doc: str
    bound_in: "frozenset[str]"    # subset of {"csharp", "seedsmith"} — empty means UNBOUND


# Verified 2026-08-23 against gk-forge/tools/ItemSeedValidator/Checks/{UniqueRuleCheck,SetRuleCheck}.cs
# and seedsmith.metrics.linkage.SetCompletability — not transcribed from spec prose.
KNOWN_RULES: "tuple[RuleBinding, ...]" = (
    RuleBinding("UniqueRoleForbidden", "uniques barred from jewel-minor roles",
               "ssot-uniques.md", frozenset({"csharp"})),
    RuleBinding("UniqueRoleQuota", "8-of-15 role quota for uniques",
               "ssot-uniques.md", frozenset({"csharp"})),
    RuleBinding("UniqueAxisCollision", "one unique per (role, band, axis)",
               "ssot-uniques.md §3.7", frozenset({"csharp"})),
    RuleBinding("SetRoleCap", "a set may claim at most 6 roles",
               "ssot-sets.md", frozenset({"csharp"})),
    RuleBinding("SetNoTwoPieceThreshold", "a set's thresholds may not start at 2 pieces alone",
               "ssot-sets.md", frozenset({"csharp"})),
    RuleBinding("SetGrandMissingStep", "a set with a grand bonus needs a 4-piece step",
               "ssot-sets.md", frozenset({"csharp"})),
    RuleBinding("SetThresholdUnreachable", "a set's top threshold must not exceed its role cap",
               "ssot-sets.md", frozenset({"csharp"})),
    RuleBinding("UniqueSetMembership", "a unique claimed by a set must exist and match",
               "ssot-sets.md", frozenset({"csharp"})),
    RuleBinding("SetRoleNotHybridCore",
               "a set's member roles must all be in the hybrid role core (excludes "
               "ward-array/jewel-minor-b)",
               "ssot-sets.md §3.7", frozenset({"seedsmith"})),
    RuleBinding("SetUncompletable", "a set member must pin a specific base type, not just a role",
               "ssot-sets.md §3.1", frozenset({"seedsmith"})),
)


class Constraint(Metric):
    id = "Constraint/UnboundRule"
    family = "Constraint"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset()   # the manifest is static data, not corpus/adapter-dependent
    covers: tuple[str, ...] = ("appendix-a:7",)

    def __init__(self, rules: "tuple[RuleBinding, ...]" = KNOWN_RULES) -> None:
        self.rules = rules

    def run(self, ctx: Ctx) -> list[Finding]:
        findings = []
        for rule in self.rules:
            if not rule.bound_in:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=rule.rule_id,
                    message=f"'{rule.rule_id}' ({rule.description}, {rule.source_doc}) has no "
                            f"binding in either tool",
                    evidence={"sourceDoc": rule.source_doc, "boundIn": []}))
        return findings
