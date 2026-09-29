"""seedsmith.metrics.quality — Quality/FlavourMissing (CLOSED), Quality/FlavourGeneric (OPEN)
(spec-analytics.md §7; S8, tasks/seedsmith-todo.md).

Missing is trivially checkable and is the one that actually mattered historically (60
consumables, 30 of 70 charms — confirmed unchanged on the live corpus 2026-08-23). "Is it any
good" has no machine answer, so `FlavourGeneric` never reports a pass — it writes a stratified
review queue and always reports `needsReview`, per P3's OPEN-loop discipline
(`Metric.__init_subclass__`/`MetricRegistry.register` reject `gates=True` on it structurally).
"""
from __future__ import annotations

from ..sampling import corpus_revision, stratified_sample
from .model import Ctx, Finding, Loop, Metric, Severity

# Player-facing kinds only — deliberately excludes machinery (affix-family, curve,
# display-template, drop-table, enhancement-milestone, recipe, socket-word: never seen by a
# player) and material (100% lack flavour today with no historical claim that they should carry
# it — including it would flood every run with an expected absence rather than a real gap). A
# scoped, human judgement call, not mechanically derived — easy to widen if that judgement is
# wrong.
FLAVOR_EXPECTED_KINDS = frozenset({"base-type", "unique", "charm", "consumable", "gem", "set"})


class FlavourMissing(Metric):
    id = "Quality/FlavourMissing"
    family = "Quality"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"corpus"})
    covers: tuple[str, ...] = ("appendix-a:17",)

    def run(self, ctx: Ctx) -> list[Finding]:
        findings = []
        for kind in sorted(FLAVOR_EXPECTED_KINDS):
            entries = ctx.corpus.by_kind(kind)
            if not entries:
                continue
            missing = [e for e in entries if not e.get("flavor")]
            if not missing:
                continue
            sample = ", ".join(e.id for e in missing[:3])
            more = f", +{len(missing) - 3} more" if len(missing) > 3 else ""
            findings.append(Finding(
                metric=self.id, severity=Severity.GAP, subject=kind,
                message=f"{len(missing)} of {len(entries)} '{kind}' entries have no flavour "
                        f"text ({sample}{more})",
                evidence={"missingCount": len(missing), "totalCount": len(entries)}))
        return findings


class FlavourGeneric(Metric):
    """Is the writing any good — has no machine answer, so this NEVER reports a pass/fail. It
    writes a stratified sample (by kind) into a review queue, always as `NOT_MEASURED`-shaped
    "needs review", per spec-metrics.md's P3 discipline for OPEN-loop metrics."""

    id = "Quality/FlavourGeneric"
    family = "Quality"
    loop = Loop.OPEN
    gates = False
    needs = frozenset({"corpus"})
    covers: tuple[str, ...] = ("appendix-a:18",)

    def __init__(self, sample_size: int = 12) -> None:
        self.sample_size = sample_size

    def run(self, ctx: Ctx) -> list[Finding]:
        by_kind = {
            kind: [e for e in ctx.corpus.by_kind(kind) if e.get("flavor")]
            for kind in FLAVOR_EXPECTED_KINDS
        }
        by_kind = {k: v for k, v in by_kind.items() if v}
        if not by_kind:
            return []

        revision = corpus_revision(ctx.corpus)
        sampled = stratified_sample(by_kind, self.sample_size, metric_id=self.id,
                                    revision=revision)

        findings = []
        # Sorted, not raw dict iteration: Python randomizes string hashing per process
        # (PYTHONHASHSEED), so a `frozenset`/dict built from one (FLAVOR_EXPECTED_KINDS above)
        # iterates in a different order across separate runs even though the SAMPLED SET is
        # identical — proven live: two CLI runs produced set-equal but list-unequal JSON until
        # this sort was added. "The same sample is reproducible" should mean byte-identical
        # output, not merely set-equal.
        for kind in sorted(sampled):
            for entry in sampled[kind]:
                findings.append(Finding(
                    metric=self.id, severity=Severity.NOTE, subject=entry.id,
                    message=f"'{entry.id}' ({kind}) sampled for flavour-quality review: "
                            f"{entry.get('flavor')!r}",
                    evidence={"needsReview": True, "kind": kind, "revision": revision,
                             "flavor": entry.get("flavor")}))
        return findings
