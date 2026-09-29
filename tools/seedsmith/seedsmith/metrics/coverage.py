"""seedsmith.metrics.coverage — Coverage/EmptyPartition (spec-analytics.md §2.1) and
Coverage/HostRoleDiversity (spec-combination-regen "The helm joins the host set").

The check that would have caught all nine known-empty item partitions on day one: set difference
between allocated partitions and partitions holding >=1 entry. O(n), and its absence in the
agentic build cost three authoring waves.

"Allocated" is adapter knowledge, not corpus knowledge (corpus only ever sees partitions that
already hold something) — so this metric reads the allocated set from the adapter's own
`registries().vocabularies["partitions"]`, a convention any adapter can publish without the core
knowing what a partition even represents semantically.
"""
from __future__ import annotations

from .model import Ctx, Finding, Loop, Metric, Severity

#: The synthetic role key for "this entry pins no host role". Not a role id — a `null`/absent
#: `hostRole` means "any chassis", and it must be visible as its own bucket rather than folded into
#: a role the entry never named.
NO_ROLE = "(none)"


class EmptyPartitionMetric(Metric):
    id = "Coverage/EmptyPartition"
    family = "Coverage"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"corpus", "adapter"})
    covers: tuple[str, ...] = ("appendix-a:13",)

    def run(self, ctx: Ctx) -> list[Finding]:
        allocated = ctx.adapter.registries().vocabularies.get("partitions", frozenset())
        occupied = ctx.corpus.partitions
        empty = sorted(allocated - occupied)
        return [
            Finding(
                metric=self.id,
                severity=Severity.GAP,
                subject=partition,
                message=f"partition '{partition}' is allocated but holds no entries",
                evidence={"allocated": True, "occupiedEntryCount": 0},
                assertion=f"len(corpus.by_partition({partition!r})) > 0",
                remedy="planner: schedule generation for this partition",
            )
            for partition in empty
        ]


class HostRoleDiversityMetric(Metric):
    """`Coverage/HostRoleDiversity` — the R11 reading, report-only (spec-combination-regen
    "The helm joins the host set", step 2).

    ⛔ **A READING, NEVER A GATE.** It prints, per shape, the share of entries pinned to each host
    role the tuning currently offers the model — the helm included the day `sockets.v2.json` lifts
    `head-guard` to four (R11) — and the share pinned to NO role. It asserts no share: a share is a
    property of today's corpus, and pinning one would fail the day content ships with its natural
    "fix" being to bump the number (validation-ssot's own rule). What a caller may rely on is the
    envelope: every entry lands in exactly one bucket, the shares share one denominator, and the
    same corpus yields the same reading.

    The offered set is read from the TUNING ceilings, never from the corpus — the whole point of
    the reading is to tell the owner whether the model is choosing a role the tuning OFFERS. A pin
    to a role the tuning no longer offers is reported too (so a stale pin is visible), still at
    NOTE severity: this metric never fails a gate.
    """

    id = "Coverage/HostRoleDiversity"
    family = "Coverage"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"corpus"})
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        entries = [e for e in ctx.corpus.by_kind("combination")]
        if not entries:
            return [Finding(
                metric=self.id, severity=Severity.NOT_MEASURED, subject="(suite)",
                message="no `combination` entries in this corpus — an empty population is not a "
                        "diversity reading",
                evidence={"code": "EmptyPopulation"})]
        try:
            from ..adapters.items.combogen.tuning import load as load_combo_tuning
            offered = load_combo_tuning().host_roles()
        except (FileNotFoundError, ValueError) as exc:
            return [Finding(
                metric=self.id, severity=Severity.NOT_MEASURED, subject="(suite)",
                message=f"combogen tuning unreadable ({exc}) — refusing to read host diversity "
                        f"against an assumed offered set",
                evidence={"code": "HostRolesUnavailable"})]

        by_shape: "dict[str, list]" = {}
        for entry in entries:
            by_shape.setdefault(str(entry.data.get("shape") or "(no shape)"), []).append(entry)

        findings: "list[Finding]" = []
        for shape in sorted(by_shape):
            rows = by_shape[shape]
            total = len(rows)
            counts: "dict[str, int]" = {}
            for entry in rows:
                pinned = entry.data.get("hostRole")
                key = str(pinned) if pinned else NO_ROLE
                counts[key] = counts.get(key, 0) + 1
            # Every offered role is printed even at zero — "the helm is never chosen" is exactly
            # the reading this metric exists to make visible.
            for role in offered:
                counts.setdefault(role, 0)
            for role in sorted(counts):
                pinned = counts[role]
                share = pinned * 1000 // total
                is_none = role == NO_ROLE
                if is_none:
                    message = (f"{shape}: {pinned}/{total} entries pin no host role "
                               f"({share}permille)")
                else:
                    offered_note = "" if role in offered else " (NOT offered by the current ceilings)"
                    message = (f"{shape}: {pinned}/{total} entries pin host role {role} "
                               f"({share}permille){offered_note}")
                findings.append(Finding(
                    metric=self.id, severity=Severity.NOTE,
                    subject=f"{shape}:{role}", message=message,
                    evidence={"shape": shape, "hostRole": None if is_none else role,
                              "offered": None if is_none else role in offered,
                              "pinned": pinned, "entries": total,
                              "sharePermille": share},
                ))
        return findings
