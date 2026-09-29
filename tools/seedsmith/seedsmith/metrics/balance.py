"""seedsmith.metrics.balance — Balance/LadderInversion, Balance/OutOfEnvelope
(spec-numerics.md §3.3, spec-analytics.md §5; S5, tasks/seedsmith-todo.md).

`ctx.numerics` is a `numerics.NumericsContext` (tuning + progression bundled — `resolve()` needs
both, `Ctx` has one generic `numerics` slot).
"""
from __future__ import annotations

from ..numerics.model import OpWeight, TIER_COUNT
from ..numerics.pava import pava
from ..numerics.resolve import CalibrationLevelError, UnsharedChannelError, resolve
from .model import Ctx, Finding, Loop, Metric, Severity


class LadderInversion(Metric):
    """Rarity ordinal should predict resolved power monotonically (spec-analytics.md §5 — the
    `verdant-graft-90` reading flatter than `verdant-graft-50` incident). PAVA names exactly
    which rung is wrong, not just that the ladder is imperfect.

    `content_ladder()` returning `None` (true of `BattleRulesetProgression` while progression is
    a stub, spec-numerics.md §6.2) means this cannot be checked at all — NOT_MEASURED, never a
    pass, so the absence of the check never reads as a healthy ladder.
    """

    id = "Balance/LadderInversion"
    family = "Balance"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"numerics"})  # everything it reads comes from content_ladder()
    covers: tuple[str, ...] = ("appendix-a:15",)

    def run(self, ctx: Ctx) -> list[Finding]:
        ladder = ctx.numerics.progression.content_ladder()
        if ladder is None:
            return [Finding(
                metric=self.id, severity=Severity.NOT_MEASURED, subject="(suite)",
                message="content_ladder() is None — progression is a stub, so rarity-vs-power "
                        "monotonicity cannot be checked; this is not a passing ladder",
                evidence={"reason": "progression_is_stub"})]

        rung_ids = [rung_id for rung_id, _ in ladder]
        values = [float(power) for _, power in ladder]
        blocks = pava(values)

        findings = []
        for block in blocks:
            if not block.pooled:
                continue
            lo_rung, hi_rung = rung_ids[block.start], rung_ids[block.end]
            findings.append(Finding(
                metric=self.id, severity=Severity.GAP, subject=f"{lo_rung}..{hi_rung}",
                message=f"'{hi_rung}' does not resolve stronger than '{lo_rung}' — the power "
                        f"ladder is not monotone across this range "
                        f"(observed {values[block.start]:g}..{values[block.end]:g}, "
                        f"PAVA fit {block.fitted_value:g})",
                evidence={"observed": values[block.start:block.end + 1],
                         "fittedValue": block.fitted_value},
                assertion=f"resolved power at '{hi_rung}' > resolved power at '{lo_rung}'"))
        return findings


class OutOfEnvelope(Metric):
    """Every (channel, op, tier) the current tuning authors a share for must resolve without
    tripping `numerics`' own guardrails (monotonicity, band containment, OD4 overlap). A tuning
    edit that breaks this for one channel should be caught here, at measurement time, rather than
    surfacing as a mysterious downstream failure the first time that channel is actually used.
    """

    id = "Balance/OutOfEnvelope"
    family = "Balance"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"numerics"})
    covers: tuple[str, ...] = ()

    def run(self, ctx: Ctx) -> list[Finding]:
        tuning = ctx.numerics.tuning
        progression = ctx.numerics.progression
        point = _first_non_calibration_point(progression)

        findings = []
        unresolvable: "list[str]" = []
        for channel in sorted(tuning.channel_weight_permille):
            for op in OpWeight:
                for tier in range(1, TIER_COUNT + 1):
                    try:
                        resolve(channel, op, tier, tuning, progression, point)
                    except (UnsharedChannelError, CalibrationLevelError):
                        continue  # not what this check is for
                    except KeyError:
                        # The tuning authors a share for a channel the PROGRESSION MODEL has no
                        # reference base for. Since tier-bands v2 (item-content T10) that is the
                        # normal case, not an error: the file now authors a weight for all 109
                        # affix-family stems so `FamilyExpansion` stops refusing them, while
                        # `adapters.items.channels` still only carries the 14 primary channels with
                        # a transcribed `BattleRuleset` curve. Reported once per channel as
                        # NOT_MEASURED -- this metric is about envelope violations, and a channel it
                        # cannot resolve at all is a thing it did not measure, never a pass and never
                        # a crash (spec-metrics.md's own third severity exists for exactly this).
                        if channel not in unresolvable:
                            unresolvable.append(channel)
                        break
                    except AssertionError as e:
                        findings.append(Finding(
                            metric=self.id, severity=Severity.GAP,
                            subject=f"{channel}/{op.value}/t{tier}",
                            message=str(e),
                            evidence={"channel": channel, "op": op.value, "tier": tier}))

        for channel in unresolvable:
            findings.append(Finding(
                metric=self.id, severity=Severity.NOT_MEASURED, subject=channel,
                message=f"'{channel}' has an authored channelWeight but the progression model has "
                        f"no reference base for it — envelope not checked",
                evidence={"channel": channel}))
        return findings


def _first_non_calibration_point(progression):
    from ..numerics.model import REFERENCE_LEVEL, ProgressionPoint
    return ProgressionPoint(level=REFERENCE_LEVEL + 1)
