"""Assemble one brief per job: allocation + budget + literal vocabularies + constraints + assertion.

Three properties, each with a check rather than a convention behind it:

1. **Inlined, never cited.** `CITATION_PATTERNS` is grepped over the rendered text; a match refuses
   the brief. "Tags come from `tags.v1.json`" cost 51 invented tags historically — an agent cannot
   follow a filename, so it fills the gap.
2. **Content-addressed and pure.** The hash covers the inputs, and nothing time- or order-dependent
   reaches it: vocabularies are sorted, mappings are rendered in sorted key order.
3. **Gated.** A job whose exemplar failed P3 never produces a brief at all — a brief built on a
   known-bad pattern is worse than no brief, because it looks authoritative.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from ..budget.model import BudgetRow
from ..planner.schedule import Job
from ..planner.validate import ExemplarGateResult

__all__ = ["Brief", "BriefRefusal", "CITATION_PATTERNS", "render_brief", "render_briefs"]

#: Phrases that mean "go and look somewhere else". A brief containing one of these is refused.
#: Deliberately matches the *shape* of a citation rather than a list of filenames — a new registry
#: file must not silently become a legal thing to cite.
CITATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsee\s+[\w./-]+\.(?:json|md|cs|py)\b", re.IGNORECASE),
    re.compile(r"\b(?:from|in|per|refer to|defined in|listed in)\s+[\w./-]+\.(?:json|md|cs)\b",
               re.IGNORECASE),
    re.compile(r"\bconsult\b|\blook (?:it )?up\b|\bas documented in\b", re.IGNORECASE),
)


class BriefRefusal(Exception):
    """A brief that must not be emitted. Raised rather than returned: a caller that ignores a
    refusal ships the exact artifact the refusal exists to prevent."""


@dataclass(frozen=True)
class Brief:
    job: str
    kind: str
    text: str
    content_hash: str
    vocabularies: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "job": self.job,
            "kind": self.kind,
            "contentHash": self.content_hash,
            "vocabularies": {k: list(v) for k, v in sorted(self.vocabularies.items())},
            "text": self.text,
        }


def _hash_inputs(payload: dict) -> str:
    """A pure function of the inputs.

    `sort_keys=True` is load-bearing, not tidiness: without it the hash depends on dict insertion
    order, so the same brief hashes differently depending on how it was assembled — and the whole
    point is that identical inputs are provably identical output.
    """
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _check_no_citations(text: str, job: str) -> None:
    for pattern in CITATION_PATTERNS:
        found = pattern.search(text)
        if found:
            raise BriefRefusal(
                f"brief for {job!r} cites {found.group(0)!r} instead of inlining it — a generating "
                f"agent cannot follow a reference, so it invents (51 tags, historically)"
            )


def render_brief(
    job: Job,
    *,
    vocabularies: Mapping[str, Iterable[str]],
    budget: BudgetRow | None = None,
    assertion: str | None = None,
    remedy: str | None = None,
    id_template: str | None = None,
    sequence_start: int = 1,
) -> Brief:
    """One brief. Every vocabulary is written out in full, sorted.

    `vocabularies` is supplied by the caller (read from the adapter's registries at generation
    time) rather than fetched here, because *which* vocabularies a kind depends on is adapter
    knowledge — the same reason `corpus.discover_edges` takes `skip_fields` from its caller.
    """
    vocab = {name: tuple(sorted(values)) for name, values in sorted(vocabularies.items())}

    lines: list[str] = [
        f"# Brief: {job.partition}",
        "",
        f"- kind: {job.kind}",
        f"- entries to author: {job.entries}",
        f"- model tier: {job.model}",
    ]
    if id_template:
        lines.append(f"- id template: {id_template} (sequence starts at {sequence_start:03d})")
    if job.constraints:
        lines.append("")
        lines.append("## Constraints (every authored entry must satisfy all of these)")
        for key, value in sorted(job.constraints.items()):
            lines.append(f"- {key} = {value}")

    if budget is not None:
        lines += [
            "",
            "## Target",
            f"- dimension: {budget.dimension}",
            f"- target: {budget.target} (tolerance {budget.tolerance.low}..{budget.tolerance.high})"
            if hasattr(budget.tolerance, "low") else f"- target: {budget.target}",
            f"- rationale: {budget.rationale}",
        ]

    if vocab:
        lines += ["", "## Legal values — these are the complete lists. Do not invent members."]
        for name, values in vocab.items():
            lines.append("")
            lines.append(f"### {name} ({len(values)} legal values)")
            lines.append(", ".join(values) if values else "(none — this vocabulary is empty)")

    if assertion or remedy:
        lines += ["", "## What must become true"]
        if assertion:
            lines.append(f"- assertion: {assertion}")
        if remedy:
            lines.append(f"- remedy: {remedy}")
    if job.closes:
        lines.append(f"- closes: {', '.join(job.closes)}")

    text = "\n".join(lines) + "\n"
    _check_no_citations(text, job.partition)

    content_hash = _hash_inputs({
        "partition": job.partition,
        "kind": job.kind,
        "entries": job.entries,
        "model": job.model,
        "constraints": dict(job.constraints),
        "closes": list(job.closes),
        "vocabularies": {k: list(v) for k, v in vocab.items()},
        "budget": None if budget is None else {
            "dimension": budget.dimension,
            "target": budget.target,
            "rationale": budget.rationale,
        },
        "assertion": assertion,
        "remedy": remedy,
        "idTemplate": id_template,
        "sequenceStart": sequence_start,
    })

    return Brief(job=job.partition, kind=job.kind, text=text,
                 content_hash=content_hash, vocabularies=vocab)


def render_briefs(
    jobs: Sequence[Job],
    *,
    gate: ExemplarGateResult,
    vocabularies_for: "Mapping[str, Mapping[str, Iterable[str]]]",
    budgets: "Mapping[str, BudgetRow] | None" = None,
) -> tuple[Brief, ...]:
    """Every job's brief, or none at all.

    **The gate is checked once, up front, for the whole batch.** Emitting the briefs whose own
    exemplar happened to pass would leave a half-batch built against a corpus whose pattern set is
    known-broken — and no artifact saying which half. P3 refuses orders whole; so does this.
    """
    if gate.refused:
        raise BriefRefusal(
            f"exemplar gate refused the order; no brief is emitted.\n{gate.explain()}"
        )

    budgets = budgets or {}
    return tuple(
        render_brief(
            job,
            vocabularies=vocabularies_for.get(job.kind, {}),
            budget=budgets.get(job.kind),
        )
        for job in jobs
    )
