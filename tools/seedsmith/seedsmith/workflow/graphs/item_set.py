"""`set-charm-gen` (item module 13, spec-set-charm-gen.md). Thin wiring only, matching
`effect_affix.py`'s own shape exactly — this module carries no `StateGraph(` call of its own, only
`build_generation_graph`.

⛔ **This is the file module 13 named as missing.** Its own deferred entry reads: *"The generation
graph is not wired, and `--write` says so instead of writing nothing. A `workflow/graphs/item_set.py`
(mirroring `workflow/graphs/effect_affix.py`) is what connects `plan_run`'s subjects to
`llm_caller`."* This is that file. The one deviation from the sentence: `call` is **injected**, so
the same graph drives a live endpoint, a recorded answer file, or a raising stub in a test — the
contract `effect_affix.py` already states in as many words (*"so a test — or `--dry-run` — can prove
zero model calls happen"*).

⚠ **The validators are the ALREADY-BUILT distributors, not a second copy of the rules.**
`setgen.distribute.distribute_set` and `charmgen.rules.distribute_charm` each return every violation
with the rule named, which is exactly the shape `make_validate_node` wants: a defect string becomes
the repair prompt. Re-stating any of those rules here would be a second source of truth for
ssot-sets §3.5, which is the failure mode this program keeps writing down.
"""
from __future__ import annotations

from typing import Any, Callable

from ...adapters.items.charmgen.rules import distribute_charm, ring_layer_families
from ...adapters.items.setgen.answers import schema_defects
from ...adapters.items.setgen.distribute import distribute_set
from ...adapters.items.setgen.seedfile import resolve_capability, resolve_pick
from ...adapters.items.setgen.tuning import SetCharmTuningError
from ...pipeline.llm_caller import LlmCallerConfig
from ..nodes.generate import make_generate_node
from ..nodes.persist import make_persist_node
from ..nodes.validate import make_validate_node
from ..state import new_state
from .base import build_generation_graph

__all__ = [
    "SYSTEM_PROMPT", "SET_VALIDATORS", "CHARM_VALIDATORS",
    "state_for_item", "build_item_set_graph",
    "answer_declares_content", "answer_matches_schema",
    "set_is_distributable", "charm_is_distributable",
    "plan_for_set", "plan_for_charm",
]

#: One sentence, because everything that constrains the answer is already IN the brief — the
#: closed vocabularies, the role cap and the "never a number" rule. A system prompt that repeats
#: them is a second place they go stale.
SYSTEM_PROMPT = (
    "You author game content against a brief. Answer with one JSON object matching the schema and "
    "nothing else. Every value you choose must come from the brief's own closed lists."
)


# --------------------------------------------------------------------------------------------
# Validators. Each returns defect strings naming the field AND the offending value.
# --------------------------------------------------------------------------------------------

def answer_matches_schema(draft: dict, context: "dict[str, Any]") -> "list[str]":
    """Constrained decoding is a property of the ENDPOINT, not of the schema, so a replayed answer
    has to be checked against the schema on the way in (`answers.py`'s own header states why)."""
    schema = context.get("schema")
    if not isinstance(schema, dict):
        return []
    return schema_defects(draft, schema)


#: A real refusal names a concrete conflict with the brief (ssot-sets/ssot-charms rule, motif
#: clash, closed-list gap); a garbage placeholder is a bare word repeating the field's own name
#: (`"blocked"`) or a one-word non-answer (`"none"`). 10 characters clears both observed
#: placeholders with room to spare while staying well under the shortest legitimate reason this
#: brief has produced in practice (15+ characters) — a floor, not a quality bar.
_BLOCKED_MIN_LENGTH = 10


def answer_declares_content(draft: dict, context: "dict[str, Any]") -> "list[str]":
    """A `blocked` answer is legal and carries none of the content fields. What is NOT legal is an
    answer that declares neither.

    ⛔ 2026-09-08: every field in `set_schema`/`charm_schema` is now `required` (a concession the
    live endpoint's constrained-decoding sampler needed — see that module's own docstring), typed
    `[X, "null"]` for whatever used to be optional-by-omission. So `field not in draft` no longer
    means anything here: the model always emits the key now, just possibly `null`. Checked by
    truthiness instead — `not draft.get(field)` is true for both an absent key (replayed/hand-
    authored answers, which still omit optional keys exactly as before) and an explicit `null`
    (the live endpoint's own new shape), so this reads identically against either source.

    ⛔ Real incident, 2026-09-08, first live `charm` run: a real model answer came back
    `{"blocked": "blocked", ...}` — a bare, meaningless placeholder that trivially satisfies
    `_blocked()`'s schema (no `minLength`, and even if there were one, `maxLength`/length bounds
    are confirmed unenforced by LM Studio's grammar sampler — see `llm_caller`'s own incident
    docstring). Accepted as a legitimate refusal, this silently drops real, generatable content —
    the model gave up mid-answer rather than either finishing it or explaining why it couldn't.
    Guarded here, in code, since the schema cannot: a `blocked` string too short to be a real
    explanation is reported as its own named defect and re-prompted, exactly like any other
    malformed field.
    """
    blocked = draft.get("blocked")
    if isinstance(blocked, str) and blocked.strip():
        if len(blocked.strip()) < _BLOCKED_MIN_LENGTH:
            return [f"blocked: {blocked!r} is too short to be a real reason — either explain "
                    f"concretely why the brief cannot be satisfied, or answer it instead"]
        return []
    kind = context.get("kind")
    # ⛔ `nameKey` removed 2026-09-08 — it is no longer a field the model is ever asked for
    # (`setgen.schema._identity_fields`'s own docstring), so it can never be "missing" from a
    # real answer; checking for it here would refuse every well-formed response.
    wanted = (("name", "flavor", "capability", "members", "thresholds")
              if kind == "set" else ("name", "flavor", "charmClass", "axis", "families"))
    missing = [field for field in wanted if not draft.get(field)]
    if missing:
        return [f"the answer declares neither `blocked` nor a complete {kind}: missing {missing}"]
    return []


def _resolved_stats(draft: dict, vocabulary) -> "tuple[dict[int, tuple], list[str]]":
    thresholds = [t for t in (draft.get("thresholds") or ()) if isinstance(t, dict)]
    # ⛔ Real incident, 2026-09-08: EVEN AFTER the brief-truncation and `resolve_capability` fixes
    # closed two other defects, a live run kept escalating every subject on the SAME remaining
    # shape — the model reused its own `capability` pick inside the LOWEST threshold's `families`,
    # the exact field `build_set_brief` tells it "takes no families — it carries the capability".
    # Nothing downstream ever reads that threshold's families (`by_threshold` only feeds
    # non-lowest thresholds into the distributor), so validating it against the STAT vocabulary
    # only punishes a field that was never going to carry real content — the model isn't wrong
    # about anything the distributor uses, it just didn't take the (now schema-legal) `null` this
    # field always meant. Determined from the draft's OWN `pieces` values, not re-derived from
    # `tuning` here, because a malformed `pieces` value is a separate, already-reported defect and
    # must not change which threshold this skip applies to.
    valid_pieces = [t.get("pieces") for t in thresholds
                    if isinstance(t.get("pieces"), int) and not isinstance(t.get("pieces"), bool)]
    lowest = min(valid_pieces) if valid_pieces else None
    by_threshold: "dict[int, tuple]" = {}
    defects: "list[str]" = []
    for threshold in thresholds:
        pieces = threshold.get("pieces")
        # ⛔ Real bug, found 2026-09-08 on a live run (a model that returned a threshold with no
        # `pieces` at all — an omission `google/gemma-4-26b-a4b-qat`'s own answers never happened
        # to produce, but nothing here ever guarded against it): `int(None)` raised uncaught,
        # crashing the WHOLE batch (every remaining subject, not just this one draft) instead of
        # reporting a named defect for the self-heal loop to re-prompt against — the exact
        # "validate before accept" contract this function's own caller exists to enforce.
        if not isinstance(pieces, int) or isinstance(pieces, bool):
            defects.append(
                f"thresholds[?].pieces: {pieces!r} is not a legal integer piece-count — every "
                f"threshold must name one of the brief's own offered `pieces` values")
            continue
        if pieces == lowest:
            continue
        picks = []
        for token in threshold.get("families") or ():
            pick = resolve_pick(vocabulary.stat, token) if isinstance(token, str) else None
            if pick is None:
                defects.append(
                    f"thresholds[{pieces}].families: {token!r} is not a stat family in the brief's "
                    f"closed list — copy an id from the list exactly as printed")
            else:
                picks.append(pick)
        if picks:
            by_threshold[pieces] = tuple(picks)
    return by_threshold, defects


def set_is_distributable(draft: dict, context: "dict[str, Any]") -> "list[str]":
    """Runs the SHIPPED distributor. Every message it returns already names its own rule and its
    ssot-sets section, so nothing is re-worded here."""
    if draft.get("blocked"):
        return []
    tuning, vocabulary = context.get("tuning"), context.get("vocabulary")
    if tuning is None or vocabulary is None:
        return []
    capability_node = draft.get("capability")
    capability = (resolve_capability(vocabulary, capability_node)
                  if isinstance(capability_node, dict) else None)
    defects: "list[str]" = []
    if isinstance(capability_node, dict) and capability is None:
        defects.append(
            f"capability: {capability_node!r} names no family in the brief's closed capability "
            f"list — an element-generated family takes `family` plus `variant`")
    stats, stat_defects = _resolved_stats(draft, vocabulary)
    defects.extend(stat_defects)
    roles = [m.get("role") for m in draft.get("members") or () if isinstance(m, dict)]
    # ⛔ Real bug, found 2026-09-08 on a live run: an empty `members` list (a malformed draft, not
    # yet caught by `answer_declares_content`'s own weaker "field present" check) reached
    # `distribute_set` -> `tuning.set_budget_milli`, which raises `SetCharmTuningError` uncaught —
    # crashing the WHOLE batch instead of reporting one named defect. This module's own docstring
    # states the intended contract ("every message it returns already names its own rule") — the
    # shipped distributor was never actually guaranteed to uphold that for every malformed
    # precondition a real model can produce, only for the ones it happened to be tried against
    # before. Caught here, once, for both distributors, rather than patched precondition by
    # precondition as each new shape gets discovered live.
    try:
        plan = distribute_set(member_roles=roles, capability=capability, stats_by_threshold=stats,
                              tuning=tuning, vocabulary=vocabulary)
    except SetCharmTuningError as exc:
        return defects + [f"members/thresholds: {exc}"]
    return defects + list(plan.problems)


def charm_is_distributable(draft: dict, context: "dict[str, Any]") -> "list[str]":
    if draft.get("blocked"):
        return []
    tuning, vocabulary = context.get("tuning"), context.get("vocabulary")
    if tuning is None or vocabulary is None:
        return []
    defects: "list[str]" = []
    families = []
    # ⚠ Resolved against BOTH buckets, then refused by rule. Resolving against the narrowed pool
    # instead would turn `CharmFamilyOnJewelMinor` — a named §3.6 refusal that tells the author
    # exactly which rule it broke — into "that id is not in the list", which teaches nothing.
    for token in draft.get("families") or ():
        pick = resolve_pick(vocabulary.all_picks, token) if isinstance(token, str) else None
        if pick is None:
            defects.append(
                f"families: {token!r} is not an always-on family in the brief's closed list — copy "
                f"an id from the list exactly as printed")
        else:
            families.append(pick)
    drawback_node = draft.get("drawback")
    drawback = None
    if isinstance(drawback_node, dict):
        drawback = resolve_pick(vocabulary.all_picks, str(drawback_node.get("family", "")))
        if drawback is None:
            defects.append(
                f"drawback.family: {drawback_node.get('family')!r} is not a family in the brief's "
                f"closed list")
    # Same guard as `set_is_distributable` above, same reason: the shipped distributor's own
    # "always returns named problems, never raises" contract is not actually enforced against
    # every malformed precondition a real model can produce.
    try:
        plan = distribute_charm(
            charm_class=str(draft.get("charmClass", "")), axis=str(draft.get("axis", "")),
            families=tuple(families), drawback=drawback, tuning=tuning,
            jewel_minor_families=context.get("jewel_minor_families") or frozenset())
    except SetCharmTuningError as exc:
        return defects + [f"charmClass/axis/families: {exc}"]
    return defects + list(plan.problems)


SET_VALIDATORS = (answer_matches_schema, answer_declares_content, set_is_distributable)
CHARM_VALIDATORS = (answer_matches_schema, answer_declares_content, charm_is_distributable)


# --------------------------------------------------------------------------------------------
# The plans a clean draft produces. Recomputed at persist rather than smuggled through state:
# `GenerationState` carries ids and small structs, never engine objects, and a validator's
# contract is to return defects — not to hand a plan forward.
# --------------------------------------------------------------------------------------------

def plan_for_set(draft: dict, *, tuning, vocabulary):
    capability_node = draft.get("capability")
    capability = (resolve_capability(vocabulary, capability_node)
                  if isinstance(capability_node, dict) else None)
    stats, _ = _resolved_stats(draft, vocabulary)
    roles = [m.get("role") for m in draft.get("members") or () if isinstance(m, dict)]
    return distribute_set(member_roles=roles, capability=capability, stats_by_threshold=stats,
                          tuning=tuning, vocabulary=vocabulary)


def plan_for_charm(draft: dict, *, tuning, vocabulary, jewel_minor_families=frozenset()):
    families = tuple(
        p for p in (resolve_pick(vocabulary.all_picks, t) for t in draft.get("families") or ())
        if p is not None)
    drawback_node = draft.get("drawback")
    drawback = (resolve_pick(vocabulary.all_picks, str(drawback_node.get("family", "")))
                if isinstance(drawback_node, dict) else None)
    return distribute_charm(
        charm_class=str(draft.get("charmClass", "")), axis=str(draft.get("axis", "")),
        families=families, drawback=drawback, tuning=tuning,
        jewel_minor_families=jewel_minor_families)


def jewel_minor_for(tuning, vocabulary) -> "frozenset[str]":
    """ssot-charms §3.6's closed set — the DECLARED ring layer, cross-checked against the corpus.

    ⚠ This read the corpus's `roles` column until 2026-09-06, which is a role × **group** matrix and
    therefore excluded 84 of 98 families — every one §3.6 names as a charm family included. See
    `charmgen.rules.families_on_jewel_minor` for the measurement and `ring_layer_families` for the
    rule that replaced it.
    """
    return ring_layer_families(tuning, vocabulary.all_picks)


# --------------------------------------------------------------------------------------------
# State and graph.
# --------------------------------------------------------------------------------------------

def state_for_item(subject, *, tuning, vocabulary, schema) -> dict:
    """Built from a `setgen.run.Subject`, whose brief `plan_run` already assembled — never
    re-rendered here, the same discipline `state_for_affix` states for `build_brief`."""
    context = {
        "kind": subject.kind,
        "population": subject.population,
        "themeKey": subject.theme_key,
        "entryId": subject.entry_id,
        "tuning": tuning,
        "vocabulary": vocabulary,
        "schema": schema,
        "jewel_minor_families": (jewel_minor_for(tuning, vocabulary) if subject.kind == "charm"
                                 else frozenset()),
    }
    return new_state(subject.subject_id, brief=subject.brief, context=context)


def build_item_set_graph(
    *,
    kind: str,
    schema: "dict[str, Any]",
    on_persist: "Callable[[str, dict], None] | None" = None,
    config: LlmCallerConfig | None = None,
    call: "Callable[..., str] | None" = None,
    checkpointer: "Any | None" = None,
):
    if kind not in ("set", "charm"):
        raise ValueError(f"kind must be 'set' or 'charm', got {kind!r}")
    validators = SET_VALIDATORS if kind == "set" else CHARM_VALIDATORS
    return build_generation_graph(
        generate=make_generate_node(system=SYSTEM_PROMPT, schema=schema, config=config, call=call),
        validate=make_validate_node(validators),
        persist=make_persist_node(on_persist),
        checkpointer=checkpointer,
    )
