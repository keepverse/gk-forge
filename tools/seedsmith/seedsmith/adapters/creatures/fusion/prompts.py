"""The bounded, deficit-only `fusion-recipe-propose` prompt (creature-seed module 17,
spec-fusion-recipe-generator.md §2). Shows a deficit output plus its nearest 2-3 POPULATED rungs
below (never the whole corpus) and every pair already claimed, so the model proposes into the one
remaining hole rather than guessing at an unbounded roster or duplicating a taken pair.

**Bounding this is not an optimization — it is mechanically enforced here**, not left as a caller
convention: `build_fusion_proposal_brief` refuses a candidate whose `rung_distance` falls outside
1-3, the same way `anchor-contract`'s closed enums refuse an out-of-vocabulary value. An unbounded
prompt is unauditable and untunable (spec §2's own reasoning, echoing why `classify-pipelines`
scopes each prompt per-field rather than showing the whole anchor schema at once).
"""
from __future__ import annotations

from dataclasses import dataclass

#: Nearest 2-3 populated rungs below the output — spec §2's own bound. A candidate further than
#: this was walked past by mistake (or a caller forgot to stop widening the search).
MAX_RUNG_DISTANCE = 3


@dataclass(frozen=True)
class FusionCandidate:
    """One species the model may pick as an input. `acquisition` is shown so a `CaptureOnly`
    candidate (owner lock 6, unconditional) is never proposed in the first place, even though §3
    would refuse it regardless — showing it is a cheap way not to waste a proposal.
    `rung_distance` is 1 for the nearest populated rung below the output, 2 for the next populated
    rung down, 3 for the one after that — never a raw enum-ordinal gap, since an unpopulated rung
    does not count as a step (the same walk `CreatureRecipeCatalog.InputPoolBelow` already performs).
    """
    species_id: str
    element_primary: str
    rarity: str
    acquisition: "tuple[str, ...]"
    rung_distance: int


@dataclass(frozen=True)
class DeficitOutput:
    species_id: str
    element_primary: str
    rarity: str


SYSTEM_PROMPT = (
    "You propose a fusion recipe for ONE creature species that the deterministic pairing pass could "
    "not resolve on its own. Two DIFFERENT species from the shown candidate list combine to make "
    "the output. You are not choosing a number and not deciding whether the pairing is valid — a "
    "separate deterministic step does that; you only propose which two candidates make the most "
    "sense together. Prefer a candidate that shares the output's own element when one is "
    "available, but a pairing across elements is fine when nothing better fits — this pass exists "
    "specifically for the cases the deterministic search already exhausted its exact-element "
    "options for."
)


def build_fusion_proposal_brief(
    output: DeficitOutput,
    candidates: "list[FusionCandidate]",
    claimed_pairs: "list[tuple[str, str]]",
) -> str:
    """One call, one deficit output. Raises if a candidate is further than the bounded 2-3
    populated rungs below (spec §2), or if fewer than 2 candidates are offered at all (no pair is
    possible). `claimed_pairs` is shown so the model does not waste a proposal on a pair another
    recipe (deterministic or another gap-fill) already owns — `usedPairs` is one shared set across
    both sources at reconciliation time (§3), but showing it here avoids a wasted round-trip.
    """
    if len(candidates) < 2:
        raise ValueError(f"need at least 2 candidates to propose a pair for {output.species_id!r}, got {len(candidates)}")
    for c in candidates:
        if not (1 <= c.rung_distance <= MAX_RUNG_DISTANCE):
            raise ValueError(
                f"fusion candidate {c.species_id!r} is {c.rung_distance} populated rungs below "
                f"{output.species_id!r} — spec §2 bounds the shown pool to the nearest "
                f"{MAX_RUNG_DISTANCE} populated rungs, never more, so the prompt never grows "
                f"unaudited as the corpus does"
            )

    lines = [
        f"Output species needing a recipe: {output.species_id} "
        f"(element: {output.element_primary}, rarity: {output.rarity}).",
        "",
        "Candidate inputs (id / element / rarity / acquisition):",
    ]
    for c in candidates:
        lines.append(f"  - {c.species_id} / {c.element_primary} / {c.rarity} / {', '.join(c.acquisition)}")

    if claimed_pairs:
        lines.append("")
        lines.append("Already claimed by another recipe — do not propose these exact pairs again:")
        for a, b in claimed_pairs:
            lines.append(f"  - {a} + {b}")

    lines.append("")
    lines.append(
        f"Propose exactly two DIFFERENT candidates from the list above that best fuse into "
        f"{output.species_id}, with a one-sentence reason."
    )
    return "\n".join(lines)
