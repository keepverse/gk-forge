"""`lead-relabel-pass` stage L — pass 2's pipeline spec (spec-lead-relabel-pass.md, stage L).

One judgement per species: **which aptitude should it lead?** The answer is a label, never a number —
the schema is pass 1's exact shape (one property, an enum of the twelve aptitude ids,
`additionalProperties: False`) wrapped in `_blocked_variant`, so a model that cannot judge declines with
a reason instead of inventing one. Staying put is legal: the current primary is one of the twelve ids.

**Deliberately not a member of `PIPELINES`.** Pass 2 is a separate pass, not a ninth classifier, and that
dict's eight-member pin (`anchor/prompts.py`'s own `assert`, plus `test_classify_pipelines.py`) is a
closed vocabulary that must not move. The relead spec is therefore defined here and handed to the pass-2
runner directly (EP2.12).

Votes: three samples, resolved by `resolve_relead_vote`. A sample whose `blocked` is non-empty is *not a
vote* (spec stage L), and fewer than two real votes resolves as `unresolved` — stage A then keeps the
current primary. The full three-real-vote case is handed to the anchor module's own `resolve_vote`, so
there is one implementation of 3-0 / 2-1 / 1-1-1 wherever it applies; the reduced case is stated here
because `resolve_vote` requires exactly three values by contract.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..anchor.prompts import PipelineSpec, SpeciesLore, _blocked_variant, _lore_block
from ..anchor.schema import APTITUDES
from ..anchor.vote import resolve_vote

#: The pass-2 spec id. Not a `PIPELINES` key, and pinned as such by test: pass 2 is a separate pass.
RELEAD_ID = "build-favour-relead"

#: Confidence values this resolver can return. Same closed vocabulary as pass 1's votes
#: (`anchor/vote.py`) — `unresolved` is a real answer ("nobody agreed"), never an error.
CONFIDENCES = ("high", "split", "unresolved")


@dataclass(frozen=True)
class ReleadVote:
    """One species' pass-2 vote.

    `value` is the winning aptitude id, or `None` when the vote is unresolved. `votes` always carries the
    REAL votes in sample order — the blocked samples are dropped, never recorded as empty strings, so the
    provenance block cannot report a declination as a vote for nothing.
    """

    value: "str | None"
    confidence: str
    votes: "tuple[str, ...]"


def _brief_relead(lore: SpeciesLore, context: dict) -> str:
    """The pass-2 brief: the measured crowding is shown (a corpus statistic the model may not change),
    the creature's own magnitudes are not — the same rule pass 1 lives under."""
    current = context.get("current") or "(unresolved)"
    lead_count = context.get("leadCount")
    species_count = context.get("speciesCount")
    target = context.get("capCount")
    crowding = ""
    if lead_count is not None and species_count is not None:
        crowding = (
            f"\n\nIt currently leads {current}, and {lead_count} of {species_count} creatures "
            f"already lead that role."
        )
        if target is not None:
            crowding += (
                f" The corpus is trying to bring every role down to about {target}; this one is over. "
                f"So if the description supports a DIFFERENT role for this creature, name that one."
            )
    return (
        "Judge the COMBAT ROLE this creature should lead: what is it good at? A fighting style "
        "(offence, mitigation, evasion, control, ...) — NOT an element, and NOT a measure of raw "
        "power. A fragile, fast creature can still be Agility even if its hits are weak, because "
        "Agility is about evasion, not damage output.\n\n"
        + _lore_block(lore) + crowding
        + f"\n\nChoose one: {', '.join(context.get('order', APTITUDES))}. "
        "Choosing the role it already leads is allowed when no other role fits."
    )


RELEAD = PipelineSpec(
    id=RELEAD_ID,
    attributes=("aptitudePrimary",),
    judgement="which combat role should this creature lead?",
    system_prompt=(
        "You re-judge a creature's dominant combat aptitude — its fighting role — from its captured "
        "lore. The twelve aptitudes are combat roles (offence, mitigation, evasion, guard, control, "
        "...), never elements and never a power ranking. You are shown how crowded the corpus already "
        "is: prefer a role that fits the lore and is not the crowded one, and keep the current role "
        "when nothing else genuinely fits."
    ),
    schema=_blocked_variant({
        "type": "object",
        "properties": {"aptitudePrimary": {"type": "string", "enum": list(APTITUDES)}},
        "required": ["aptitudePrimary"],
        "additionalProperties": False,
    }),
    build_brief=_brief_relead,
)


def resolve_relead_vote(samples: "Sequence[Mapping[str, Any]]") -> ReleadVote:
    """Three samples in, one label or an abstention out.

    A sample counts as a vote only when it answered. A **genuine** declination is a non-empty `blocked`
    reason that is not itself a label; an empty answer is not an answer. A non-empty answer outside the
    twelve ids is a defect (the schema's enum should have prevented it) and raises, rather than becoming
    a species' primary.

    A `blocked` value that IS one of the twelve ids is not a declination: it is the model echoing the
    answer it just gave into the escape field. The field's own description already warns against
    exactly this (`anchor/prompts._blocked_variant`'s "do not put a side, a category, or any other real
    answer here") and a real local model still does it — measured 2026-09-20 on
    `google/gemma-4-26b-a4b-qat`: three samples answered `Onslaught`/`Precision`/`Onslaught` and all
    three carried `blocked: "Onslaught"`. Reading that as three abstentions would have made every
    candidate `unresolved`, so the pass could never re-label anything while the model was answering
    perfectly well. An echo is therefore metadata, not a veto; a reason that names no label ("no
    description captured") still is.

    Threshold: a majority of the samples ASKED is the bar (two of three) — with only one real vote left
    there is no majority to resolve, so the vote is `unresolved` and stage A keeps the current primary.
    """
    if len(samples) != 3:
        raise ValueError(f"resolve_relead_vote needs exactly 3 samples, got {len(samples)}")

    real: "list[str]" = []
    for sample in samples:
        blocked = str(sample.get("blocked") or "").strip()
        if blocked and blocked not in APTITUDES:
            continue
        answer = str(sample.get("aptitudePrimary") or "").strip()
        if not answer:
            continue
        if answer not in APTITUDES:
            raise ValueError(
                f"relead vote {answer!r} is not one of the twelve aptitude ids; the schema's closed "
                "enum should have prevented this"
            )
        real.append(answer)

    votes = tuple(real)
    if len(real) == 3:
        # One implementation: pass 1's own resolver, unmodified, for the full case.
        resolved = resolve_vote(real)
        return ReleadVote(resolved.value, resolved.confidence, votes)
    if len(real) < 2:
        return ReleadVote(None, "unresolved", votes)

    top, top_count = Counter(real).most_common(1)[0]
    return ReleadVote(top, "high", votes) if top_count == 2 else ReleadVote(None, "unresolved", votes)
