"""D1.10 (spec-dungeon-seed-contract.md §1, "Pipelines with permuted enums and majority vote") --
the boundary. `call` is always injected, never imported directly, matching every other pipeline in
this program (`items/uniques/pipelines.py`'s own established contract): a test proves zero real
model calls happen on a schema-only or dry-run path.

**Quest votes THREE fields, not one -- a real difference from the uniques pipeline, not an
oversight.** `spec-dungeon-seed-contract.md` §1.5's own field table marks `name`, `countBand` AND
`rewardBand` all "AUTHORED, voted" (uniques votes only `name`). `countBand`/`rewardBand` are
abstract MECHANICAL parameters with no narrative coupling to `flavor` -- unlike a unique's
`baseType`, voting them independently of which sample's `name` won carries no "recombined,
incoherent flavor" risk (`items/uniques/pipelines.py`'s own documented reason for keeping a
winning sample's other fields together). `flavor` stays tied to whichever sample's `name` won the
vote, since it IS narrative prose about that specific name.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ..creatures.anchor.permute import order_for
from ..creatures.anchor.vote import resolve_vote
from ...briefkit.gloss import GlossTable, load_glosses
from ...metrics.dedup import canonical_words
from ...pipeline.llm_caller import LlmCallerConfig, call_model, extract_json
from ...pipeline.staleness import brief_hash
from ...workflow.validators.motif import anti_motif_violation, motif_coverage
from ...workflow.validators.scripts import script_policy
from . import registries as _reg
from .briefs import (
    DOMAIN_SYSTEM_PROMPT,
    ENCOUNTER_SYSTEM_PROMPT,
    EVENT_SCRIPT_POLICY,
    EVENT_SYSTEM_PROMPT,
    QUEST_SYSTEM_PROMPT,
    ROOM_SYSTEM_PROMPT,
    SLOT_COUNT_BY_FORMATION,
    SUPPLY_EXT_SYSTEM_PROMPT,
    build_domain_brief,
    build_domain_schema_for_cell,
    build_encounter_brief,
    build_encounter_schema_for_cell,
    build_event_brief,
    build_event_schema_for_cell,
    build_quest_brief,
    build_quest_schema_for_cell,
    build_room_brief,
    build_room_schema_for_cell,
    build_supply_ext_brief,
    build_supply_ext_schema_for_consumable,
    room_palette_for_climate,
)
from .planner import Cell, assign_event_climates, motif_brief_for_slot, posture_multisets_for
from .schema import ENTRANCE_HINT, EVENT_KIND, EVENT_REPEAT_SCOPE, THREAT_BAND

SAMPLES_PER_DRAW = 3
MAX_PARSE_HEAL = 2

CallFn = Callable[..., str]   # (system, user, *, config, schema) -> raw text -- call_model's own shape


@dataclass(frozen=True)
class DrawResult:
    cell_key: str
    entry: "dict[str, Any] | None"   # None iff unresolved
    reason: "str | None" = None      # set iff entry is None
    vote_confidence: "str | None" = None


def _permute_schema_enums(schema: dict, *, draw_id: str, sample_index: int) -> dict:
    """Identical shape to `items/uniques/pipelines.py`'s own function -- not imported from there
    (that module is items-adapter-local, matching this program's own established "each generator
    keeps its own local copy of a small orchestration helper" precedent, `combogen`/`setgen`'s own
    already-cited reason). Walks `out` (the deepcopy), never `schema` -- the exact mutate-the-input
    bug `items/uniques/pipelines.py` self-caught 2026-09-06, guarded against here from the start
    rather than re-discovering it."""
    out = copy.deepcopy(schema)

    def walk(node: Any, field_hint: "str | None") -> None:
        if isinstance(node, dict):
            if isinstance(node.get("enum"), list) and field_hint is not None:
                node["enum"] = order_for(draw_id, field_hint, sample_index, node["enum"])
            for key, sub in node.get("properties", {}).items():
                walk(sub, key)
            items = node.get("items")
            if isinstance(items, dict):
                walk(items, field_hint)

    for field, sub in out.get("properties", {}).items():
        walk(sub, field)
    return out


def _call_and_parse(call: CallFn, system: str, user: str, *, schema: dict, config: LlmCallerConfig) -> dict:
    """Identical shape to `items/uniques/pipelines.py`'s own function -- see that module's own
    doc comment for why a sample that never parses raises rather than being silently dropped."""
    for attempt in range(MAX_PARSE_HEAL + 1):
        raw = call(system, user, config=config, schema=schema)
        try:
            return extract_json(raw)
        except (ValueError, json.JSONDecodeError):
            user = ("Your previous output could not be parsed as valid JSON. "
                    "Re-emit ONLY a strictly-valid JSON object matching the schema, nothing else.")
    raise RuntimeError(f"model never returned parseable JSON after {MAX_PARSE_HEAL} heal attempt(s)")


def run_quest_draws(
    cells: "list[Cell]",
    planned_ids_by_cell: "Mapping[str, str]",
    *,
    call: "CallFn | None" = None,
    config: LlmCallerConfig | None = None,
    objective_templates: "dict[str, dict] | None" = None,
    room_kinds: "frozenset[str] | None" = None,
    event_kinds: "tuple[str, ...] | None" = None,
    reward_bands: "frozenset[str] | None" = None,
    count_bands: "frozenset[str] | None" = None,
    repeat_scopes: "tuple[str, ...] | None" = None,
    attempt: int = 0,
    existing_names: "Mapping[str, Any] | None" = None,
) -> "list[DrawResult]":
    """One draw per cell: `SAMPLES_PER_DRAW` (3) permuted calls; `name`, `countBand` and
    `rewardBand` EACH majority-voted independently; a 1-1-1 split on ANY of the three, or fewer
    than 3 samples ever parsing, is `unresolved` for the whole entry -- never a partial guess
    (AI-native contract: "1-1-1 -> unresolved, never the first option", applied per vote, and a
    quest with only two of its three load-bearing fields resolved is not a quest this pipeline
    will ship). `flavor`/`targetRef`/`prereqRefs`/`chainRef` come from whichever sample's `name`
    won its own vote -- the narratively-coupled fields stay with the sample that wrote them.

    `objective_templates`/`room_kinds`/`event_kinds`/`reward_bands`/`count_bands`/`repeat_scopes`
    default to a fresh registry read (`registries.py`) when omitted -- explicit parameters exist so
    a test can supply a small fixture instead of the real, larger corpus.
    """
    call = call or call_model
    objective_templates = objective_templates if objective_templates is not None else _reg.load_objective_templates()
    room_kinds = room_kinds if room_kinds is not None else frozenset(_reg.load_room_kinds())
    event_kinds = event_kinds if event_kinds is not None else EVENT_KIND
    reward_bands = reward_bands if reward_bands is not None else _reg.load_bands()["rewardBand"]
    count_bands = count_bands if count_bands is not None else _reg.load_bands()["countBand"]
    repeat_scopes = repeat_scopes if repeat_scopes is not None else EVENT_REPEAT_SCOPE

    used_names: "set[frozenset[str]]" = {canonical_words(n) for n in (existing_names or ())}
    results: "list[DrawResult]" = []

    for cell in cells:
        draw_id = f"quest-draw-{cell.cell_key}" if attempt == 0 else f"quest-draw-{cell.cell_key}-retry{attempt}"
        quest_id = planned_ids_by_cell[cell.cell_key]
        template_id, scope = cell.dimension_values
        target_kind = objective_templates[template_id]["targetKind"]
        base_schema = build_quest_schema_for_cell(
            cell, quest_id, objective_templates=objective_templates, room_kinds=room_kinds,
            event_kinds=event_kinds, reward_bands=reward_bands, count_bands=count_bands,
            repeat_scopes=repeat_scopes)
        brief = build_quest_brief(cell, template_id, scope, target_kind)

        samples: "list[dict]" = []
        for sample_index in range(SAMPLES_PER_DRAW):
            schema = _permute_schema_enums(base_schema, draw_id=draw_id, sample_index=sample_index)
            try:
                out = _call_and_parse(call, QUEST_SYSTEM_PROMPT, brief, schema=schema, config=config)
            except RuntimeError:
                continue
            samples.append(out)

        if len(samples) != SAMPLES_PER_DRAW:
            results.append(DrawResult(cell.cell_key, None, reason="insufficient_valid_samples"))
            continue

        name_vote = resolve_vote([s.get("name", "") for s in samples])
        if name_vote.value is None:
            results.append(DrawResult(cell.cell_key, None, reason="vote_unresolved:name", vote_confidence=name_vote.confidence))
            continue

        name_words = canonical_words(name_vote.value)
        if name_words in used_names:
            results.append(DrawResult(cell.cell_key, None,
                                      reason=f"name_collision: {name_vote.value!r} normalizes to an already-used name",
                                      vote_confidence=name_vote.confidence))
            continue

        count_band_vote = resolve_vote([s.get("countBand", "") for s in samples])
        if count_band_vote.value is None:
            results.append(DrawResult(cell.cell_key, None, reason="vote_unresolved:countBand", vote_confidence=count_band_vote.confidence))
            continue

        reward_band_vote = resolve_vote([s.get("rewardBand", "") for s in samples])
        if reward_band_vote.value is None:
            results.append(DrawResult(cell.cell_key, None, reason="vote_unresolved:rewardBand", vote_confidence=reward_band_vote.confidence))
            continue

        used_names.add(name_words)
        winner = next(s for s in samples if s.get("name") == name_vote.value)
        entry = dict(winner)
        entry["name"] = name_vote.value
        entry["countBand"] = count_band_vote.value
        entry["rewardBand"] = reward_band_vote.value

        results.append(DrawResult(cell.cell_key, entry, vote_confidence=name_vote.confidence))

    return results


@dataclass(frozen=True)
class SupplyExtDrawResult:
    consumable_id: str
    entry: "dict[str, Any] | None"   # None iff unresolved
    reason: "str | None" = None


def run_supply_ext_draws(
    consumables: "list[tuple[str, str, str, str]]",
    *,
    call: "CallFn | None" = None,
    config: LlmCallerConfig | None = None,
) -> "list[SupplyExtDrawResult]":
    """One call per consumable, no vote -- neither `overrideTags` (fixed empty here, see
    `briefs.py`'s own `SUPPLY_EXT_ELIGIBLE_CLASSES` doc comment) nor `useContextAdds` (a real closed
    enum, already constrained-decoding-safe under a single sample, matching uniques' own `baseType`/
    `tags` treatment) is marked "voted" anywhere in the seed contract, so a 3-sample vote here would
    just be spending three times the tokens to re-confirm what one already-constrained call proves.

    `consumables` is `[(consumableId, name, classId, family), ...]` -- the caller's own filtered,
    eligible-class subset (`briefs.py`'s `SUPPLY_EXT_ELIGIBLE_CLASSES`), read from the real item
    corpus, never re-derived here (this module owns no consumable-corpus reading of its own).
    """
    call = call or call_model
    results: "list[SupplyExtDrawResult]" = []

    for consumable_id, name, class_id, family in consumables:
        schema = build_supply_ext_schema_for_consumable(consumable_id)
        brief = build_supply_ext_brief(consumable_id, name, class_id, family)
        try:
            out = _call_and_parse(call, SUPPLY_EXT_SYSTEM_PROMPT, brief, schema=schema, config=config)
        except RuntimeError:
            results.append(SupplyExtDrawResult(consumable_id, None, reason="insufficient_valid_samples"))
            continue
        results.append(SupplyExtDrawResult(consumable_id, out))

    return results


MAX_QUALITY_RETRY = 2  # bound repairs at two -- the AI-native contract's own rule, distinct from
                       # MAX_PARSE_HEAL: a validator rejection is a QUALITY defect, never transient.


@dataclass(frozen=True)
class EventDrawResult:
    cell_key: str
    slot_index: int
    entry: "dict[str, Any] | None"   # None iff unresolved
    reason: "str | None" = None      # set iff entry is None
    #: Anti-motif words dropped because the slot's own assignment already requires the same gloss
    #: (spec-dungeon-generator-repair §2) — recorded, never silent.
    droppedAntiMotifs: "tuple[str, ...]" = ()
    #: `pipeline.staleness.brief_hash` of the rendered user brief this entry was drawn from (NS10).
    #: Empty only for a slot refused before any brief was rendered (an unglossed motif).
    brief_hash: str = ""


@dataclass(frozen=True)
class EventMotifWords:
    """One slot's motif brief resolved into target-language words (NS9)."""

    motifs: "tuple[str, ...]"
    antiMotifs: "tuple[str, ...]"
    droppedAntiMotifs: "tuple[str, ...]" = ()


def glossed_motif_words(motif_brief: "Mapping[str, list[str]]",
                        glosses: "GlossTable") -> "tuple[EventMotifWords | None, tuple[str, ...]]":
    """Resolve a slot's motif brief into glosses, or name every unglossed motif.

    Returns `(words, ())` when every motif AND anti-motif has a gloss, or `(None, missing)` — the
    caller must then spend NO model call for that slot (spec-dungeon-generator-repair.md §2: a raw
    motif never reaches a brief, so there is nothing correct to ask the model for).

    **Anti-motifs minus motifs.** Two distinct motifs can share one English gloss; if a gloss lands in
    both lists, it is removed from the anti-motifs (the slot's own assignment wins) and recorded, so a
    slot can never be told to use and avoid the same word — which is unsatisfiable.
    """
    positives = list(motif_brief["motifs"])
    antis = list(motif_brief["antiMotifs"])
    missing = glosses.missing(positives + antis)
    if missing:
        return None, missing
    motif_words = glosses.gloss_all(positives)
    anti_words: "list[str]" = []
    dropped: "list[str]" = []
    for anti in antis:
        word = glosses.gloss(anti)
        if word in motif_words:
            dropped.append(word)
            continue
        anti_words.append(word)
    return EventMotifWords(motif_words, tuple(anti_words), tuple(dropped)), ()


def run_event_draws(
    cells: "list[Cell]",
    planned_ids_by_cell: "Mapping[str, list[str]]",
    *,
    call: "CallFn | None" = None,
    config: LlmCallerConfig | None = None,
    glosses: "GlossTable | None" = None,
    themes: "Mapping[str, dict] | None" = None,
    grantable_atom_families: "frozenset[str] | None" = None,
    power_bands: "frozenset[str] | None" = None,
    override_tags: "frozenset[str] | None" = None,
    existing_names: "Mapping[str, Any] | None" = None,
    climates: "Mapping[str, str] | None" = None,
    committed_chain_refs: "Mapping[str, str] | None" = None,
) -> "list[EventDrawResult]":
    """One call per (cell, slot) -- no cross-sample vote (see `briefs.EVENT_OUTCOME_COUNT`'s own
    doc comment for why array-positional voting is out of scope this pass, and `motif_brief_for_
    slot`'s own doc comment for why a cell with `target=2` gets two INDEPENDENT slots, never a
    shared draw). The real quality gate is the planner's own motif brief
    (`planner.motif_brief_for_slot`), enforced by `workflow.validators.motif`'s `motif_coverage`/
    `anti_motif_violation` -- the SAME two checks the seed contract's own §4 step 2 names as "the
    mechanism that forced attempt 2 in the measured run" -- plus a name-collision check
    (`canonical_words`, `run_quest_draws`'s own established mechanism): a real 50-entry batch
    measured 5/50 name collisions concentrated on themes whose flavor concept is strong enough that
    different KINDS still converge on the same title (e.g. a stage-performer theme producing "The
    Crimson Stage" for its curio, encounter-event AND trap entries) -- `_EVENT_KIND_HINT` alone
    did not prevent this, so a collision is now treated as one more named QUALITY defect the model
    is asked to fix, exactly like a motif violation. A validator OR collision rejection is a QUALITY
    retry (the defect is named back to the model in the next attempt's own brief), bounded at
    `MAX_QUALITY_RETRY` attempts before the slot is `unresolved` -- never a silent first guess kept
    despite a named defect, and never a silently-shipped duplicate title either.

    `planned_ids_by_cell[cell.cell_key]` is a LIST (unlike quest's single id per cell) since an
    event cell may carry `target` 1 or 2 (`planner.allocate_event_targets`) -- this is exactly
    `planner.plan_ids_for_cells`'s own output shape, fed here unmodified. `existing_names` seeds the
    collision set from names already shipped in an earlier batch (`run_quest_draws`'s own precedent).
    """
    call = call or call_model
    glosses = glosses or load_glosses()   # the real registry by default; a fixture table in tests
    themes = themes if themes is not None else _reg.load_themes()
    grantable_atom_families = grantable_atom_families if grantable_atom_families is not None else _reg.load_grantable_atom_families()
    power_bands = power_bands if power_bands is not None else _reg.load_power_bands()
    override_tags = override_tags if override_tags is not None else _reg.load_override_tags()

    used_names: "set[frozenset[str]]" = {canonical_words(n) for n in (existing_names or ())}
    results: "list[EventDrawResult]" = []
    # NS11 (spec-dungeon-generator-repair.md §5-§6): the climate is PLANNED for every event, and the
    # legacy chain forge is DELETED. The legacy contract cannot express a chain's last link without a
    # dangling id, so this adapter generates no NEW `story` events: a `story` cell is refused unless the
    # caller supplies that event's own COMMITTED `chainRef` (the §8 regeneration run does, for the four
    # already-committed story events — owner ruling 2026-09-20).
    climates = dict(climates) if climates is not None else assign_event_climates(planned_ids_by_cell)
    committed_chain_refs = committed_chain_refs or {}
    for cell in cells:
        if cell.dimension_values[0] != "story":
            continue
        uncommitted = [eid for eid in planned_ids_by_cell.get(cell.cell_key, [])
                       if eid not in committed_chain_refs]
        if uncommitted:
            raise ValueError(
                f"{cell.cell_key}: story events are arc links under the narrative adapter "
                f"(arc-shapes); the legacy contract cannot express a chain's last link without a "
                f"dangling chainRef (no committed chainRef supplied for {uncommitted})")

    for cell in cells:
        _kind, theme = cell.dimension_values
        ids = planned_ids_by_cell.get(cell.cell_key, [])
        theme_row = themes[theme]

        for slot_index, event_id in enumerate(ids):
            motif_brief = motif_brief_for_slot(theme_row, slot_index, len(ids))
            # NS9 (spec-dungeon-generator-repair §2): gloss BEFORE the brief, and refuse a slot with
            # any unglossed motif without spending a call.
            words, missing_motifs = glossed_motif_words(motif_brief, glosses)
            if words is None:
                results.append(EventDrawResult(cell.cell_key, slot_index, None,
                                               reason=f"gloss_missing: {', '.join(missing_motifs)}"))
                continue
            schema = build_event_schema_for_cell(
                cell, event_id, grantable_atom_families=grantable_atom_families,
                power_bands=power_bands, override_tags=override_tags,
                assigned_chain_ref=committed_chain_refs.get(event_id),
                climate=climates.get(event_id))
            glossed_brief = {"motifs": list(words.motifs), "antiMotifs": list(words.antiMotifs)}
            user_brief = build_event_brief(cell, glossed_brief)
            slot_brief_hash = brief_hash(user_brief)
            # The validators now check the SAME English words the brief asked for (§2).
            context = {"motifs": list(words.motifs), "antiMotifs": list(words.antiMotifs)}

            entry: "dict[str, Any] | None" = None
            reason: "str | None" = None
            for _attempt in range(MAX_QUALITY_RETRY + 1):
                try:
                    draft = _call_and_parse(call, EVENT_SYSTEM_PROMPT, user_brief, schema=schema, config=config)
                except RuntimeError:
                    reason = "insufficient_valid_samples"
                    break
                problems = (motif_coverage(draft, context) + anti_motif_violation(draft, context)
                            + script_policy(draft, {"scriptPolicy": EVENT_SCRIPT_POLICY}))
                name_words = canonical_words(draft.get("name", ""))
                if name_words in used_names:
                    problems = problems + [f"the name {draft.get('name')!r} is already used by another event -- write a genuinely different title"]
                if not problems:
                    used_names.add(name_words)
                    entry = draft
                    break
                reason = f"quality_retry: {'; '.join(problems)}"
                user_brief = (f"{user_brief}\n\nYour previous attempt was rejected: {'; '.join(problems)}. "
                              f"Write a new attempt that fixes this, meeting every other requirement too.")

            results.append(EventDrawResult(cell.cell_key, slot_index, entry,
                                           reason=None if entry else reason,
                                           droppedAntiMotifs=words.droppedAntiMotifs,
                                           brief_hash=slot_brief_hash))

    return results


@dataclass(frozen=True)
class EncounterDrawResult:
    cell_key: str
    slot_index: int
    entry: "dict[str, Any] | None"   # None iff unresolved
    reason: "str | None" = None      # set iff entry is None


def _rankOrder_problems(entry: "dict[str, Any]", n_slots: int) -> "list[str]":
    order = entry.get("rankOrder") or []
    if sorted(order) != list(range(n_slots)):
        return [f"rankOrder {order!r} is not a permutation of every slot index 0..{n_slots - 1} exactly once"]
    return []


def _threatWindow_problems(entry: "dict[str, Any]", threat_band: "tuple[str, ...]") -> "list[str]":
    """A real defect caught by the FIRST live smoke test against the real model, before any batch
    ran: `floorRung`/`ceilRung` are two independent enum picks, and nothing in the JSON Schema
    stops the model from naming a floor ordinally ABOVE its own ceiling (`ThreatWindow.Contains`
    is `rung >= floor && rung <= ceil` -- an inverted pair is satisfiable by no rung at all, which
    `SlotFilter.Candidates` would refuse outright as "unfillable"). `threat_band` is ordered lowest
    to highest (`nuisance` first) by construction (`schema.THREAT_BAND`, `creature-threat.v1.json`'s
    own rung order), so ordinal INDEX comparison is exactly rung comparison."""
    window = entry.get("threatWindow") or {}
    floor_rung, ceil_rung = window.get("floorRung"), window.get("ceilRung")
    if floor_rung not in threat_band or ceil_rung not in threat_band:
        return [f"threatWindow {window!r} names a band outside the real ten threat nouns"]
    if threat_band.index(floor_rung) > threat_band.index(ceil_rung):
        return [f"threatWindow floorRung {floor_rung!r} is ordinally ABOVE ceilRung {ceil_rung!r} -- "
                f"the window would match no real anchor at all; floor must be <= ceil"]
    return []


def run_encounter_draws(
    cells: "list[Cell]",
    planned_ids_by_cell: "Mapping[str, list[str]]",
    *,
    call: "CallFn | None" = None,
    config: LlmCallerConfig | None = None,
    threat_band: "tuple[str, ...] | None" = None,
    zomboss_pattern_ids: "frozenset[str] | None" = None,
    existing_names: "Mapping[str, Any] | None" = None,
) -> "list[EncounterDrawResult]":
    """One call per (cell, slot) -- no cross-sample vote, the same reasoning `run_event_draws`
    already established (`briefs.SLOT_COUNT_BY_FORMATION`'s own doc comment): array-positional
    voting needs a count/order guarantee this program has never verified, so this batch fixes the
    slot count per formation and drops cross-sample voting for the whole entry instead.

    **Posture is assigned by this function, never asked of the model.** A first design DID ask for
    it with a same-cell collision retry (`run_quest_draws`'s own name-collision shape, generalized
    to a posture multiset): a real 40-entry batch resolved only 12/40 because the model defaulted to
    the SAME posture combination for a cell's every sibling slot. Per-attempt enum permutation
    (`_permute_schema_enums`, seeded by `(cell, slot, attempt)`) plus a strengthened, explicit retry
    message ("here is every shape already taken, pick a genuinely different one") were BOTH tried
    next and STILL resolved only 1/4 on a retested cell -- the model's own content prior for a small
    team's shape (one tank, one support) is strong enough that neither debiasing technique moved it,
    the exact "enum selection is the most bias-prone task shape" failure the AI-native contract
    names, at a severity past what a retry can fix. The structural replacement, matching
    `unique-pipeline`'s own precedent for a field a model provably cannot honor no matter how it is
    asked (`tags` -> five single-value fields after an ~85% violation rate): `planner.
    posture_multisets_for(n_slots)` enumerates every DISTINCT posture shape a formation's own slot
    count can express (3 for boss, 6 for pack, 10 for party -- `PostureMultiset` is order-
    independent, `EncounterCoverage.cs`'s own real coverage key), cycled deterministically per
    sibling slot index within a cell so two siblings are NEVER assigned the same shape unless the
    caller's own `planned_ids_by_cell` asks for more entries in one cell than that formation's real
    ceiling can express (a caller error `planner.allocate_encounter_targets` exists specifically to
    prevent). `_SLOT_ITEM_SCHEMA`'s own doc comment has the schema-side half of this story.

    `rankOrder` still gets its own structural quality check (JSON Schema's `uniqueItems` alone
    cannot express "covers the full range", only "no duplicates among whatever was listed") and
    `threatWindow` its own ordinal-inversion check (`_threatWindow_problems`, a SEPARATE real defect
    a live smoke test caught) -- both real model choices, retried in the SAME bounded loop
    `run_event_draws` established, since neither showed the severe, un-retry-able bias posture did.

    No motif brief here, unlike event: `kinds.py`'s own `motif_expression` for this kind is "the
    shape of the opposition, never which species fill it" -- an abstract design register the brief
    conveys in prose (`build_encounter_brief`), not a literal-word constraint `motif_coverage` could
    check against.

    **Name collision retry, added after the posture fix shipped 40/40 but a canonical-word scan
    measured 24/40 (60%) sharing a name with a sibling** -- a real rate, WORSE than event's own
    measured 10%: encounter's `name` has less to differentiate on than event's own theme-grounded
    motifs (formation/elementSpread/posture are generic, repeatable concepts -- "Swarming
    Skirmishers" is a natural name for almost any `pack` cell). The SAME `used_names`/
    `canonical_words` mechanism `run_event_draws`/`run_room_draws` already established.
    """
    call = call or call_model
    threat_band = threat_band if threat_band is not None else THREAT_BAND
    zomboss_pattern_ids = zomboss_pattern_ids if zomboss_pattern_ids is not None else _reg.load_zomboss_pattern_ids()
    used_names: "set[frozenset[str]]" = {canonical_words(n) for n in (existing_names or ())}

    results: "list[EncounterDrawResult]" = []
    for cell in cells:
        formation, _element_spread = cell.dimension_values
        n_slots = SLOT_COUNT_BY_FORMATION[formation]
        ids = planned_ids_by_cell.get(cell.cell_key, [])
        shapes = posture_multisets_for(n_slots)
        if shapes and len(ids) > len(shapes):
            raise ValueError(
                f"cell {cell.cell_key!r} was asked for {len(ids)} entries but a {n_slots}-slot "
                f"formation only has {len(shapes)} real distinct posture shapes -- use "
                f"planner.allocate_encounter_targets, which caps every cell at its own real ceiling")

        for slot_index, encounter_id in enumerate(ids):
            slot_postures = shapes[slot_index % len(shapes)]
            schema = build_encounter_schema_for_cell(
                cell, encounter_id, threat_band=threat_band, zomboss_pattern_ids=zomboss_pattern_ids)
            user_brief = build_encounter_brief(cell, slot_postures)

            entry: "dict[str, Any] | None" = None
            reason: "str | None" = None
            for _attempt in range(MAX_QUALITY_RETRY + 1):
                try:
                    draft = _call_and_parse(call, ENCOUNTER_SYSTEM_PROMPT, user_brief, schema=schema, config=config)
                except RuntimeError:
                    reason = "insufficient_valid_samples"
                    break
                problems = _rankOrder_problems(draft, n_slots) + _threatWindow_problems(draft, threat_band)
                name_words = canonical_words(draft.get("name", ""))
                if name_words in used_names:
                    problems = problems + [f"the name {draft.get('name')!r} is already used by another encounter -- write a genuinely different title"]
                if not problems:
                    used_names.add(name_words)
                    for slot, posture in zip(draft["slots"], slot_postures):
                        slot["posture"] = posture
                    entry = draft
                    break
                reason = f"quality_retry: {'; '.join(problems)}"
                user_brief = (f"{user_brief}\n\nYour previous attempt was rejected: {'; '.join(problems)}. "
                              f"Write a new attempt that fixes this, meeting every other requirement too.")

            results.append(EncounterDrawResult(cell.cell_key, slot_index, entry, reason=None if entry else reason))

    return results


@dataclass(frozen=True)
class RoomDrawResult:
    cell_key: str
    slot_index: int
    entry: "dict[str, Any] | None"   # None iff unresolved
    reason: "str | None" = None      # set iff entry is None


def run_room_draws(
    cells: "list[Cell]",
    planned_ids_by_cell: "Mapping[str, list[str]]",
    *,
    call: "CallFn | None" = None,
    config: LlmCallerConfig | None = None,
    room_kind_rows: "dict[str, dict]",
    hazard_band: "frozenset[str]",
    sight_band: "frozenset[str]",
    disposition: "frozenset[str]",
    tags: "frozenset[str]",
    encounter_ids_by_formation: "dict[str, frozenset[str]]",
    event_ids_by_kind: "dict[str, frozenset[str]]",
    existing_names: "Mapping[str, Any] | None" = None,
) -> "list[RoomDrawResult]":
    """One call per (cell, slot) -- no cross-sample vote, no motif brief (room's own cell axis is
    (kind, climate), not (kind, theme): no theme registry to hang a motif allocation on, matching
    encounter's own identical absence of one). The one real quality mechanism reused from
    `run_event_draws` is the name-collision retry (`canonical_words`) -- a real, general risk for
    ANY free-text `name` field, not theme-specific, and event's own first batch measured it at a
    real 10% rate.

    `build_room_schema_for_cell` itself raises `ValueError` (never a per-entry `unresolved`) when a
    cell structurally cannot be built yet (e.g. a `wild`-kind cell with no real `story`-kind event
    to reference) -- that is a CALLER error (the cell should never have been included in `cells`),
    not a quality defect a retry could fix, so it is deliberately let through here rather than
    caught and silently skipped.

    All of `room_kind_rows`/`hazard_band`/`sight_band`/`disposition`/`tags`/
    `encounter_ids_by_formation`/`event_ids_by_kind` are required, explicit, real-data parameters
    (no silent registry read here) -- `pipelines.py` owns orchestration, not room's own vocabulary
    resolution, matching `run_encounter_draws`'s optional-defaulting precedent where a real registry
    read makes sense, and diverging from it here because the caller MUST already have resolved the
    real encounter/event id sets to decide which cells are even legal to include.
    """
    call = call or call_model
    used_names: "set[frozenset[str]]" = {canonical_words(n) for n in (existing_names or ())}
    results: "list[RoomDrawResult]" = []
    sorted_dispositions = sorted(disposition)
    wild_slot_counter = 0  # cycles across EVERY wild (cell, slot), not reset per cell -- a real
    # live batch measured all 12 first wild rooms picking `hostile` uniformly (build_room_schema_
    # for_cell's own doc comment has the full finding); global cycling spreads the 4 real values
    # across the whole wild sub-corpus rather than repeating one value per climate.

    for cell in cells:
        kind = cell.dimension_values[0]
        ids = planned_ids_by_cell.get(cell.cell_key, [])
        schema = None  # built once per cell for non-wild kinds -- every slot shares the identical
        # schema; wild kinds rebuild per slot below since dispositionBase must vary per slot.
        for slot_index, room_id in enumerate(ids):
            if kind == "wild":
                assigned = sorted_dispositions[wild_slot_counter % len(sorted_dispositions)]
                wild_slot_counter += 1
                schema = build_room_schema_for_cell(
                    cell, room_id, room_kind_rows=room_kind_rows, hazard_band=hazard_band,
                    sight_band=sight_band, disposition=disposition, tags=tags,
                    encounter_ids_by_formation=encounter_ids_by_formation, event_ids_by_kind=event_ids_by_kind,
                    assigned_disposition=assigned)
            elif schema is None:
                schema = build_room_schema_for_cell(
                    cell, room_id, room_kind_rows=room_kind_rows, hazard_band=hazard_band,
                    sight_band=sight_band, disposition=disposition, tags=tags,
                    encounter_ids_by_formation=encounter_ids_by_formation, event_ids_by_kind=event_ids_by_kind)
            else:
                schema = dict(schema, properties=dict(schema["properties"], roomId={"type": "string", "const": room_id}))
            user_brief = build_room_brief(cell)

            entry: "dict[str, Any] | None" = None
            reason: "str | None" = None
            for _attempt in range(MAX_QUALITY_RETRY + 1):
                try:
                    draft = _call_and_parse(call, ROOM_SYSTEM_PROMPT, user_brief, schema=schema, config=config)
                except RuntimeError:
                    reason = "insufficient_valid_samples"
                    break
                # `uniqueItems: true` is NOT reliably enforced by the local model's constrained
                # decoding -- confirmed by a real, pre-existing defect this exact dedup fix found in
                # the ALREADY-SHIPPED corpus (`room.rest-none-002.json`'s own `eventPool` repeated the
                # same id three times). Deduplicating is a deterministic, always-correct fix (the
                # room's real event pool is the same events minus the redundant repeats, `minItems: 1`
                # still holds since the pre-dedup list was already >= 1) -- never a retry, since a
                # retry could just as easily reproduce the same defect.
                if "eventPool" in draft and isinstance(draft["eventPool"], list):
                    draft["eventPool"] = list(dict.fromkeys(draft["eventPool"]))
                name_words = canonical_words(draft.get("name", ""))
                problems = ([f"the name {draft.get('name')!r} is already used by another room -- write a genuinely different title"]
                            if name_words in used_names else [])
                if not problems:
                    used_names.add(name_words)
                    entry = draft
                    break
                reason = f"quality_retry: {'; '.join(problems)}"
                user_brief = (f"{user_brief}\n\nYour previous attempt was rejected: {'; '.join(problems)}. "
                              f"Write a new attempt that fixes this, meeting every other requirement too.")

            results.append(RoomDrawResult(cell.cell_key, slot_index, entry, reason=None if entry else reason))

    return results


@dataclass(frozen=True)
class DomainDrawResult:
    cell_key: str
    slot_index: int
    entry: "dict[str, Any] | None"   # None iff unresolved
    reason: "str | None" = None      # set iff entry is None


def run_domain_draws(
    cells: "list[Cell]",
    planned_ids_by_cell: "Mapping[str, list[str]]",
    *,
    call: "CallFn | None" = None,
    config: LlmCallerConfig | None = None,
    theme_ids: "frozenset[str]",
    boss_species_by_climate: "dict[str, frozenset[str]]",
    retinue_families: "frozenset[str]",
    layout_ids: "list[str]",
    room_kind_rows_by_id: "dict[str, dict]",
    quest_ids: "list[str]",
    existing_names: "Mapping[str, Any] | None" = None,
) -> "list[DomainDrawResult]":
    """One call per (cell, slot) -- domain's own cell axis is climate alone (six first-ship cells,
    one domain each, spec-domain-catalog.md §7). `roomPalette`/`questPool`/`lootBinding`/
    `layoutTemplateId`/`entranceHint` are ALL planner-computed here, never asked of the model (see
    the module-level note on `build_domain_schema_for_cell` in `briefs.py` for the full reasoning --
    the same structural-fix-over-retry lesson `run_encounter_draws` already proved once this
    session; `entranceHint` joined this list only after a live batch measured a real single-value
    bias, not by design up front). `layoutTemplateId`/`entranceHint` both cycle through their own
    real, sorted candidate list by cell index -- a layout carries no climate/kind field at all
    (confirmed by reading all six real shipped `layouts/*.json` directly, D4.30's own pre-read
    finding) and `entranceHint` has no stated coverage requirement of its own either, so any
    assignment is equally legal; cycling rather than repeating one value for all six is a free,
    harmless choice, not a requirement.

    The only reused quality mechanism is the name-collision retry (`canonical_words`) -- the same
    general free-text-`name` risk this program has now found real at least twice (event 10%,
    encounter 60%).
    """
    call = call or call_model
    used_names: "set[frozenset[str]]" = {canonical_words(n) for n in (existing_names or ())}
    results: "list[DomainDrawResult]" = []
    sorted_layout_ids = sorted(layout_ids)
    sorted_entrance_hints = sorted(ENTRANCE_HINT)

    for cell_index, cell in enumerate(cells):
        climate = cell.dimension_values[0]
        ids = planned_ids_by_cell.get(cell.cell_key, [])
        boss_candidates = boss_species_by_climate.get(climate, frozenset())
        room_palette_ids = room_palette_for_climate(climate, room_kind_rows_by_id)
        layout_template_id = sorted_layout_ids[cell_index % len(sorted_layout_ids)]
        entrance_hint = sorted_entrance_hints[cell_index % len(sorted_entrance_hints)]

        schema = None  # built once per cell -- every slot in a cell shares the identical schema
        for slot_index, domain_id in enumerate(ids):
            if schema is None:
                schema = build_domain_schema_for_cell(
                    cell, domain_id, theme_ids=theme_ids, boss_species_candidates=boss_candidates,
                    retinue_families=retinue_families, layout_template_id=layout_template_id,
                    room_palette_ids=room_palette_ids, quest_pool_ids=sorted(quest_ids),
                    entrance_hint=entrance_hint)
            else:
                schema = dict(schema, properties=dict(schema["properties"], domainId={"type": "string", "const": domain_id}))
            user_brief = build_domain_brief(cell, boss_candidates)

            entry: "dict[str, Any] | None" = None
            reason: "str | None" = None
            for _attempt in range(MAX_QUALITY_RETRY + 1):
                try:
                    draft = _call_and_parse(call, DOMAIN_SYSTEM_PROMPT, user_brief, schema=schema, config=config)
                except RuntimeError:
                    reason = "insufficient_valid_samples"
                    break
                name_words = canonical_words(draft.get("name", ""))
                problems = ([f"the name {draft.get('name')!r} is already used by another domain -- write a genuinely different title"]
                            if name_words in used_names else [])
                if not problems:
                    used_names.add(name_words)
                    entry = draft
                    break
                reason = f"quality_retry: {'; '.join(problems)}"
                user_brief = (f"{user_brief}\n\nYour previous attempt was rejected: {'; '.join(problems)}. "
                              f"Write a new attempt that fixes this, meeting every other requirement too.")

            results.append(DomainDrawResult(cell.cell_key, slot_index, entry, reason=None if entry else reason))

    return results
