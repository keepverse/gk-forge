"""seedsmith.metrics.corpus_coverage — CorpusCoverage/DumpCompleteness,
CorpusCoverage/BasisHistogram (spec-corpus-dump.md, spec-power-parse.md; creature-seed `seed-to-
concrete` T1.10).

Both metrics need `ctx.creature_dump` (a `CreatureDumpCtx`, T1.10's own loader) rather than
`ctx.corpus`/`ctx.adapter` — the creature dump is a pre-corpus artifact (JSON captured straight from
the DAL, not seedsmith content entries), so it gets its own `Ctx` slot rather than being forced
through the generic `Corpus.load()` shape it was never structured to fit.

**Every target here is declared in tuning, never a literal in this file (P2).** A metric without a
target is an opinion; `gk-core/data/tuning/creature-corpus-targets.v1.json` is the balance surface these two
metrics read from.
"""
from __future__ import annotations

import json
from pathlib import Path

from .model import Ctx, Finding, Loop, Metric, Severity

TUNING_DIR = Path(__file__).resolve().parents[4] / "data" / "tuning"


def _load_targets(version: "int | str" = 1) -> dict:
    path = TUNING_DIR / f"creature-corpus-targets.v{int(version)}.json"
    return json.loads(path.read_text(encoding="utf-8"))


class DumpCompletenessMetric(Metric):
    """CLOSED — a mismatch is fixed by re-running `CreatureCorpusDump`, mechanically verifiable
    (spec-corpus-dump.md's own `--check`/`--verify`). Registers as a metric, distinct from
    `dump-preflight`'s check 3: preflight answers "can a run start right now", this answers "is
    the committed dump's own health tracked over time, with a target and a gate".
    """

    id = "CorpusCoverage/DumpCompleteness"
    family = "CorpusCoverage"
    loop = Loop.CLOSED
    gates = False   # W1 discipline: every metric starts measure-only; promoted later (spec-metrics.md §4)
    needs = frozenset({"creature_dump"})
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        targets = _load_targets()
        max_mismatches = targets["dumpCompleteness"]["maxCountMismatches"]

        dump = ctx.creature_dump
        manifest = dump.manifest
        by_side = {"plant": 0, "zombie": 0}
        for seed in dump.seeds:
            by_side[seed.side] = by_side.get(seed.side, 0) + 1

        mismatches = []
        if by_side.get("plant", 0) != manifest.get("plantCount"):
            mismatches.append(("plantCount", manifest.get("plantCount"), by_side.get("plant", 0)))
        if by_side.get("zombie", 0) != manifest.get("zombieCount"):
            mismatches.append(("zombieCount", manifest.get("zombieCount"), by_side.get("zombie", 0)))

        if len(mismatches) <= max_mismatches:
            return []

        return [
            Finding(
                metric=self.id, severity=Severity.GAP, subject=key,
                message=f"manifest declares {key}={declared}, dump actually has {actual}",
                evidence={"declared": declared, "actual": actual, "targetMaxMismatches": max_mismatches},
                assertion=f"{key} in the manifest equals the actual row count",
                remedy="re-run CreatureCorpusDump and commit the result",
            )
            for key, declared, actual in mismatches
        ]


class BasisHistogramMetric(Metric):
    """OPEN — the basis distribution is a fact about the game's own captured data, not something
    this metric (or any mechanical fix) can close by itself; classify-pipelines improving
    `inferred` coverage moves it, this metric only observes. Per P3, an OPEN-loop metric may
    never gate (enforced by `MetricRegistry.register`, not by convention here)."""

    id = "CorpusCoverage/BasisHistogram"
    family = "CorpusCoverage"
    loop = Loop.OPEN
    gates = False
    needs = frozenset({"creature_dump"})
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        targets = _load_targets()["basisHistogram"]
        min_observed_or_stated_permille = targets["minObservedOrStatedSharePermille"]
        max_blocked_permille = targets["maxBlockedSharePermille"]

        dump = ctx.creature_dump
        total = dump.total
        if total == 0:
            return [Finding(
                metric=self.id, severity=Severity.NOT_MEASURED, subject="(suite)",
                message="creature dump has zero species — nothing to classify",
                evidence={})]

        counts = {"observed": 0, "stated": 0, "inferred": 0, "blocked": 0}
        for seed in dump.seeds:
            counts[seed.basis] += 1

        # widen before multiplying, divide by 1000 once, last (docs/architecture/numeric-types.md rules 3-4) — the C#
        # port of this same ratio must do the same; Python ints are already arbitrary-width, but
        # the shape is kept identical so a port is a straight line-for-line translation.
        observed_or_stated = counts["observed"] + counts["stated"]
        observed_or_stated_permille = (observed_or_stated * 1000) // total
        blocked_permille = (counts["blocked"] * 1000) // total

        findings: "list[Finding]" = []
        if observed_or_stated_permille < min_observed_or_stated_permille:
            findings.append(Finding(
                metric=self.id, severity=Severity.GAP, subject="observed+stated share",
                message=f"observed+stated is {observed_or_stated_permille}‰ of {total} species, "
                        f"below the {min_observed_or_stated_permille}‰ target",
                evidence={"counts": counts, "total": total,
                         "observedOrStatedPermille": observed_or_stated_permille},
                remedy="classify-pipelines: improve inferred/blocked coverage, or re-check power-parse's patterns"))
        if blocked_permille > max_blocked_permille:
            findings.append(Finding(
                metric=self.id, severity=Severity.GAP, subject="blocked share",
                message=f"blocked is {blocked_permille}‰ of {total} species, "
                        f"above the {max_blocked_permille}‰ target",
                evidence={"counts": counts, "total": total, "blockedPermille": blocked_permille},
                remedy="corpus-dump: check whether the almanac capture itself is missing text for these species"))
        return findings
