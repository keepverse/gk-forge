"""seedsmith.metrics.motif_sharing — Distribution/MotifSharing (spec-creature-metrics.md §2.2, A2).

Field-naming contract this metric reads from a "creature" entry, once `motif-derive` (D2.3) is wired
to write its output onto the corpus (not yet built — this metric works today against a corpus that
carries none of these fields, and correctly reports "nothing to measure"):

  entry.data["motifs"]              -> list[str], as `DerivedMotifs.motifs`
  entry.data["motifTautological"]   -> bool, as `DerivedMotifs.tautological` (A2's own flag,
                                        READ here, never re-derived — motif-derive already computed
                                        it, and re-deriving the same fact in a second module is
                                        exactly the drift this repo's own discipline warns against)

`loop = OPEN`: whether a sharing level is GOOD has no machine answer (a tightly-themed roster and
an under-differentiated one produce similar numbers), so every finding here is `Severity.NOTE` —
never `GAP` — and carries no pass/fail field. Asserting one would be the "mark its own homework"
defect `audit_open_loop_schema` refuses for a pipeline schema; the same discipline applies to a
metric's own verdict, even though `audit_open_loop_schema` itself only walks JSON schemas and has
nothing to check here directly.
"""
from __future__ import annotations

from .model import Ctx, Finding, Loop, Metric, Severity


class MotifSharingMetric(Metric):
    id = "Distribution/MotifSharing"
    family = "Distribution"
    loop = Loop.OPEN
    gates = False
    needs = frozenset({"corpus", "adapter"})
    covers: "tuple[str, ...]" = ()

    subject_kind: str = "creature"

    def run(self, ctx: Ctx) -> "list[Finding]":
        subjects = ctx.corpus.by_kind(self.subject_kind)
        if not subjects:
            # No entries of this kind at all — an adapter that was never about `subject_kind`
            # (items, `_stub`) must stay silent, not report "nothing to measure" as if it were a
            # creatures-specific finding that happens to apply here too.
            return []
        # Only creatures that carry motif data at all are "measured" — a creature predating this field
        # (or from an adapter that never wired motif-derive in) is neither included nor excluded,
        # because it was never something this metric could see, not a tautological exclusion.
        with_motifs = [e for e in subjects if e.get("motifs") is not None]
        if not with_motifs:
            return [Finding(
                metric=self.id, severity=Severity.NOTE, subject="(suite)",
                message="no creature entry carries motif data yet — nothing to measure",
                evidence={"creatureCount": len(subjects), "measuredCount": 0},
            )]

        excluded = [e for e in with_motifs if bool(e.get("motifTautological"))]
        included = [e for e in with_motifs if not bool(e.get("motifTautological"))]

        motif_to_creatures: "dict[str, set[str]]" = {}
        for e in included:
            for motif in (e.get("motifs") or []):
                motif_to_creatures.setdefault(motif, set()).add(e.id)

        if not motif_to_creatures:
            # A2's decisive case: every measurable creature was tautological, or none had a motif at
            # all — this is "cannot be measured", NEVER reported as perfect sharing. Without this
            # branch the metric would be worse than absent on exactly the corpus it exists to catch.
            return [Finding(
                metric=self.id, severity=Severity.NOTE, subject="(suite)",
                message="cannot be measured — every creature with motif data was tautological "
                        "(A2: name-derived motifs and name-derived family are the same string read "
                        "twice) or none had a motif at all",
                evidence={
                    "creatureCount": len(subjects),
                    "measuredCount": len(with_motifs),
                    "excludedTautological": len(excluded),
                    "singleUseMotifs": 0,
                },
            )]

        single_use = sorted(m for m, creatures in motif_to_creatures.items() if len(creatures) == 1)
        total_pairs = sum(len(creatures) for creatures in motif_to_creatures.values())
        creatures_per_motif = total_pairs / len(motif_to_creatures)

        return [Finding(
            metric=self.id, severity=Severity.NOTE, subject="(suite)",
            message=f"creatures-per-motif: {creatures_per_motif:.2f} over {len(motif_to_creatures)} motifs "
                    f"({len(single_use)} used by exactly one creature)",
            evidence={
                "creatureCount": len(subjects),
                "measuredCount": len(with_motifs),
                "excludedTautological": len(excluded),
                "creaturesPerMotif": creatures_per_motif,
                "singleUseMotifs": single_use,
                "motifVocabularySize": len(motif_to_creatures),
            },
        )]
