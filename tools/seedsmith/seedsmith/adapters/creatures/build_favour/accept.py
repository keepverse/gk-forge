"""`lead-relabel-pass` stage A — the deterministic quota that bounds pass 2's re-labelling.

Spec: `docs/architecture/empire-progression/spec-lead-relabel-pass.md` (stage A, R-Q6). Pure: no IO, no
model, no clock, no C#. The caller hands in the candidates (species whose current lead is over the cap,
each with its resolved vote), the running lead counts READ FROM the favour measure, and the cap count
derived from `leadCapPermille`; stage A returns one `Decision` per candidate and nothing else.

Why a quota and not a prompt: the ideal's warning is that a model asked "make this one different" 904
times, one creature at a time, can converge on a NEW dominant answer (Doshi and Hauser: individual
novelty up, inter-item similarity up 10.7%). Acceptances therefore run in ordinal `speciesId` order
against running counts, and a re-label is accepted only while its source is still over the cap and its
target stays at or below it — so no pass can create a new over-cap lead, by construction.

Determinism is a contract, not an accident: candidates are processed in ordinal order, the counts are a
fresh copy of the caller's, and every outcome is recorded in a CLOSED vocabulary. The same inputs give
byte-identical decisions whatever order they arrive in.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from seedsmith.adapters.creatures.anchor.schema import SPECIES_KIND

#: Stage A's closed outcome vocabulary. Declared once here, pinned by test with its reason: it is a
#: code-owned set a human changes by review (every consumer switches on it, the run report counts it,
#: and the provenance block records one of these per read species) — never a population.
OUTCOMES = ("accepted", "kept-by-vote", "unresolved", "source-under-cap", "target-full")

#: R-CS4's mark, read here through the vocabulary's own declaration. A row carrying it is NOT a
#: creature: "never spawn, never draw, never count as roster" — so it is never a candidate for a
#: re-label and never contributes to the counts a cap is judged on (test 1b).
EXCLUDED_KIND = "excluded"


@dataclass(frozen=True)
class Candidate:
    """One species pass 2 asked about: the lead it carries today, and what the vote resolved to.

    `voted is None` means the vote was `unresolved` (a 1-1-1 split, or fewer than a majority of real
    votes) — kept as its own state, never silently treated as "stay put by consent".
    """

    species_id: str
    current: str
    voted: str | None


@dataclass(frozen=True)
class Decision:
    """One species' fate in stage A: the lead it keeps (or gains) and the closed outcome that says why."""

    species_id: str
    primary: str
    outcome: str

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome {self.outcome!r}; the closed set is {OUTCOMES}")


def accept(
    candidates: Iterable[Candidate],
    lead_counts: Mapping[str, int],
    cap_count: int,
) -> "list[Decision]":
    """Stage A. Pure and deterministic: ordinal order, running counts, every outcome recorded.

    `lead_counts` is the measured corpus' lead count per aptitude (read from `favour-detector`'s
    artifact), so the cap is judged on the same population the measure counted — a row outside that
    population is not a candidate and is never counted. Counts are copied, never mutated in place: the
    caller's mapping is an input, not scratch space.
    """
    counts = dict(lead_counts)
    decisions: "list[Decision]" = []
    for c in sorted(candidates, key=lambda c: c.species_id):
        if c.voted is None:
            decisions.append(Decision(c.species_id, c.current, "unresolved"))
        elif c.voted == c.current:
            decisions.append(Decision(c.species_id, c.current, "kept-by-vote"))
        elif counts.get(c.current, 0) <= cap_count:
            decisions.append(Decision(c.species_id, c.current, "source-under-cap"))
        elif counts.get(c.voted, 0) + 1 > cap_count:
            decisions.append(Decision(c.species_id, c.current, "target-full"))
        else:
            counts[c.current] = counts[c.current] - 1
            counts[c.voted] = counts.get(c.voted, 0) + 1
            decisions.append(Decision(c.species_id, c.voted, "accepted"))
    return decisions


def over_cap_sources(lead_counts: Mapping[str, int], cap_count: int) -> "tuple[str, ...]":
    """The aptitudes whose lead count is over the cap — the only source aptitudes pass 2 may move a
    species out of, and therefore the only ones it is asked about. Ordinal, so a run's prompt batch is
    reproducible. Nothing here is a floor: an aptitude led by zero species is simply not a source (R-Q6
    rejects a floor outright)."""
    return tuple(sorted(a for a, n in lead_counts.items() if n > cap_count))


def candidates_from(rows: Iterable[Mapping], votes: Mapping[str, str | None]) -> "list[Candidate]":
    """Stage A's candidate list from anchor rows and pass-2 votes.

    A row outside the measured population — `speciesKind: excluded`, R-CS4's "never count as roster" —
    is **never a candidate**: it is dropped here, before any vote is read, so it can be neither
    re-labelled nor counted by the quota. `votes` may be keyed by species id; a row with no vote is a
    candidate with `voted=None` (the pipeline's own "not a vote" state), never a `KeyError`.

    Ordinal order, so the list stage A processes does not depend on the caller's iteration order.
    """
    candidates = [
        Candidate(
            species_id=row["speciesId"],
            current=row["aptitudePrimary"],
            voted=votes.get(row["speciesId"]),
        )
        for row in rows
        if row.get("speciesKind") != EXCLUDED_KIND
    ]
    return sorted(candidates, key=lambda c: c.species_id)
