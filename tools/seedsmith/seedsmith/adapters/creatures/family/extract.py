"""seedsmith.adapters.creatures.family.extract — candidate family labels from name + description
(spec-family-extract.md).

Not built on `briefkit.render_brief`: that function's shape is "author N new entries against a
target", carrying a `Job`/budget/id-template — this pipeline reads EXISTING text and proposes
labels, a genuinely different job (§2.1's own words). The brief-building here is bespoke, but the
inlining discipline is not: it is checked against the SAME `briefkit.CITATION_PATTERNS`, not a
re-invented pattern set, so the two disciplines cannot drift apart.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from ....briefkit.render import CITATION_PATTERNS
from ....corpus.model import Entry
from ....pipeline.llm_caller import LlmCallerConfig
from ....pipeline.model import BLOCKED_FIELD, Pipeline
from ....pipeline.run import run_pipeline
from .schema import FAMILY_EXTRACTION_SCHEMA

__all__ = [
    "BATCH_SIZE",
    "FamilyCandidate",
    "form_batches",
    "build_brief",
    "extract_family_candidates",
]

# Structural constant, not a tunable (spec-family-extract.md §2.2): trades context against call
# count, and changing it changes which creatures see each other, which is a decision about the
# EXTRACTION, not a balance-pass number. 8 is a starting point pending measurement against the
# real ~84-creature roster (spec §9 Q2, decided 2026-08-31) — revisit with data, not by feel.
BATCH_SIZE = 8


def form_batches(entries: Sequence[Entry]) -> list[list[Entry]]:
    """Sort by `speciesId`, slice into fixed windows. Same corpus -> same batches, always; a creature
    appears in exactly one batch (§2.2) — no overlap, so no creature can receive conflicting labels
    from two different sibling contexts."""
    ordered = sorted(entries, key=lambda e: e.id)
    return [ordered[i:i + BATCH_SIZE] for i in range(0, len(ordered), BATCH_SIZE)]


def build_brief(batch: Sequence[Entry], *, creature_expression_rule: str) -> str:
    """Inline the batch's own name/description and the per-kind expression rule. Cites nothing —
    checked below, against `briefkit`'s own citation patterns, not a local re-implementation."""
    lines = [
        "# Family extraction batch",
        "",
        f"How a shared motif is expressed for this kind: {creature_expression_rule}",
        "",
        "Creatures in this batch (propose a shared family label where names/descriptions suggest kinship;",
        "a creature with neither text nor a suggestive name gets no candidate):",
        "",
    ]
    for e in batch:
        lines.append(f"- speciesId: {e.id}")
        lines.append(f"  name: {e.get('name')}")
        info = e.get("flavorInfo")
        intro = e.get("flavorIntroduce")
        if info:
            lines.append(f"  flavorInfo: {info}")
        if intro:
            lines.append(f"  flavorIntroduce: {intro}")
    text = "\n".join(lines) + "\n"
    for pattern in CITATION_PATTERNS:
        if pattern.search(text):
            raise ValueError(f"family-extract brief contains citation-shaped text: {pattern.pattern!r}")
    return text


def _response_format_instructions(batch_key: str) -> str:
    """Real defect found running this against a real local model, not a mock (2026-08-31): the
    brief alone carries no output-shape instructions, and `MockModelServer` in tests never notices
    because it returns a canned response regardless of prompt content. A real model needs to be
    told the exact JSON shape — the self-heal loop can correct a malformed first attempt, but
    starting from an unspecified format wastes a heal round teaching the model something this
    function already knows."""
    return (
        "\n\nRespond with ONLY a JSON object, no prose, no markdown code fences. Exact shape:\n"
        f'{{"{batch_key}": {{"candidates": [{{"speciesId": "<one of the ids above>", '
        '"label": "kebab-case-english-family-name", "nativeLabel": "<as read from the text above>", '
        '"basis": "text"|"name"}}]}}}}\n'
        "`basis` is \"text\" only when the label is genuinely supported by flavorInfo/flavorIntroduce "
        "content, not merely the name. `label` is always English kebab-case even when `nativeLabel` "
        "is Chinese. Omit a creature from `candidates` entirely if neither its name nor its text "
        "suggests a shared family with anything else in this batch — do not invent one. A creature may "
        "appear more than once with different labels if it plausibly belongs to more than one family."
    )


@dataclass(frozen=True)
class FamilyCandidate:
    species_id: str
    label: str
    native_label: str
    basis: str  # "text" | "name" | "blocked"


def extract_family_candidates(
    entries: Sequence[Entry],
    *,
    creature_expression_rule: str,
    config: LlmCallerConfig | None = None,
    model_response_for_batch: "Callable[[int, list[Entry]], None] | None" = None,
) -> "dict[str, list[FamilyCandidate]]":
    """Run one pipeline call per batch (§2.2). Returns `speciesId -> [FamilyCandidate]`; a creature
    with no candidate at all is `blocked` (present as an empty list, per §2.3 — 'blocked' is an
    answer, recorded, not an absence to be re-derived by a caller checking for a missing key).

    `model_response_for_batch` exists only so tests can observe/queue against the real
    `MockModelServer` per batch without this function needing to know about HTTP at all — it is
    called (if given) immediately before each batch's `run_pipeline` call.
    """
    batches = form_batches(entries)
    result: "dict[str, list[FamilyCandidate]]" = {e.id: [] for e in entries}

    for batch_index, batch in enumerate(batches):
        batch_ids = {e.id for e in batch}
        if model_response_for_batch is not None:
            model_response_for_batch(batch_index, batch)

        brief = build_brief(batch, creature_expression_rule=creature_expression_rule)
        batch_key = f"batch-{batch_index:04d}"
        accepted_here: "list[tuple[str, dict[str, Any]]]" = []

        pipeline = Pipeline(
            metric="Coverage/CreatureUncovered",  # closes toward D3's per-creature coverage check
            scope=batch_key,
            schema=FAMILY_EXTRACTION_SCHEMA,
            gate=lambda value, _ids=batch_ids: _gate_candidates(value, _ids),
            on_persist=lambda _key, value, _sink=accepted_here: _sink.append((_key, value)),
            max_retries=2,
        )

        run_pipeline(
            pipeline,
            {batch_key: {"batch": [e.id for e in batch]}},
            system=(
                "You classify existing PvZ creature names/descriptions into shared family labels. "
                "You never invent a family a creature's own text does not support."
            ),
            build_user=lambda _items, _brief=brief, _key=batch_key: _brief + _response_format_instructions(_key),
            config=config,
        )

        for _key, value in accepted_here:
            for raw in value.get("candidates", []):
                sid = raw["speciesId"]
                if sid not in batch_ids:
                    # §6's own test row: a label for a creature outside the batch is rejected, not
                    # recorded — the gate already refuses it, this is the belt to that suspenders.
                    continue
                result[sid].append(FamilyCandidate(
                    species_id=sid, label=raw["label"],
                    native_label=raw["nativeLabel"], basis=raw["basis"],
                ))

    return result


def _gate_candidates(value: Mapping[str, Any], batch_ids: "set[str]") -> list[str]:
    """Domain rule the schema cannot express: every candidate's `speciesId` must be a creature that
    was actually IN this batch. A model naming a creature from a different batch — or one that does
    not exist — must not silently enter the record (§6's own test row)."""
    problems: list[str] = []
    if value.get(BLOCKED_FIELD):
        return problems
    for raw in value.get("candidates", []):
        sid = raw.get("speciesId")
        if sid not in batch_ids:
            problems.append(f"candidate speciesId {sid!r} is not in this batch")
    return problems
