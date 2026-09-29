"""seedsmith.workflow.graphs.item_combination — the missing wiring `combination-write-unblock`
(item module 21, `docs/architecture/item-seedgen/spec-combination-write-unblock.md`) exists to add.

⛔ **This is what "the generation graph is not wired" (`report/cli.py`'s own historical `--write`
refusal for `--kind combination`) turned out to mean, precisely.** `combogen/grid.py`,
`catalogue.py`, `schema.py`, `supply.py`, `emit.py`, `brief.py` and `run.py` were all already
complete and correct before this module touched them — `run.plan_run` produces 102 real subjects
with real briefs today. What did not exist anywhere in the tree was the one file that connects a
planned subject's brief to an LLM caller: no `workflow/graphs/item_combination.py`, and therefore no
transport, no batch driver, and nothing for `--write` to invoke. That is the SAME defect class
module 13 recorded before `item_set.py` was written (its own docstring: *"the generation graph is
not wired, and `--write` says so instead of writing nothing"*) — this file is combogen's `item_set.py`.

Mirrors `item_set.py`'s shape deliberately: `call` is injected, so the same graph drives a replayed
answer file today (`combogen/authored.py`) and a live endpoint later without a rewrite — the same
seam `creature_anchor.py` / `effect_affix.py` / `item_set.py` already rely on for their own tests.

⚠ **Only three validators, not five.** `combination_schema()` is a closed enum with no numeric
field and no distributable magnitude to price (`schema.py`'s own P1 note) — there is no
`set_is_distributable`/`charm_is_distributable` analogue here, because there is nothing left for a
distributor to check once the schema itself has closed every enum. `answer_matches_schema` and
`answer_declares_content` are `item_set.py`'s own pattern; `answer_stays_in_vocabulary` is
combogen-specific — D20's banned word can still reach `name`/`flavor` free text even though the
closed-enum fields cannot carry it, mirroring `combogen.brief.build_brief`'s own outbound scan.
"""
from __future__ import annotations

from typing import Any, Callable

from ...adapters.items.combogen.grid import scan_for_banned_word
from ...pipeline.llm_caller import LlmCallerConfig
from ..nodes.generate import make_generate_node
from ..nodes.persist import make_persist_node
from ..nodes.validate import make_validate_node
from ..state import new_state
from .base import build_generation_graph

__all__ = [
    "SYSTEM_PROMPT", "COMBINATION_VALIDATORS", "state_for_combination",
    "build_item_combination_graph", "answer_matches_schema", "answer_declares_content",
    "answer_stays_in_vocabulary", "answer_reuses_a_shipped_idea", "answer_uses_a_legal_name",
]

#: One sentence, matching `item_set.py`'s own reasoning: everything that constrains the answer is
#: already in the brief and the schema's closed lists.
SYSTEM_PROMPT = (
    "You author game content against a brief. Answer with one JSON object matching the schema and "
    "nothing else. Every value you choose must come from the brief's own closed lists."
)

#: `combination_schema()`'s own content fields (`schema.py`'s `_identity_fields` plus the two
#: closed-enum arrays) — deliberately excludes `nameKey`, which is planned, never authored (see
#: `schema.py`'s own correction).
_CONTENT_FIELDS: "tuple[str, ...]" = ("name", "flavor", "ingredients", "grants")


def answer_matches_schema(draft: dict, context: "dict[str, Any]") -> "list[str]":
    """Constrained decoding is a property of the ENDPOINT, not of the schema (`item_set.py`'s own
    reasoning, restated here): a replayed answer gets no such guarantee and must be checked on the
    way in."""
    from ...adapters.items.setgen.answers import schema_defects

    schema = context.get("schema")
    if not isinstance(schema, dict):
        return []
    return schema_defects(draft, schema)


def answer_declares_content(draft: dict, context: "dict[str, Any]") -> "list[str]":  # noqa: ARG001
    """Top-level fields are `required` + nullable (2026-09-09 wire fix). A `blocked` answer is
    legal with null content; what is not legal is an answer that declares neither."""
    if isinstance(draft.get("blocked"), str) and draft["blocked"].strip():
        return []
    missing = [f for f in _CONTENT_FIELDS
               if draft.get(f) is None or f not in draft]
    if missing:
        return [f"the answer declares neither `blocked` nor a complete combination: missing "
                f"{missing}"]
    return []


def answer_stays_in_vocabulary(draft: dict, context: "dict[str, Any]") -> "list[str]":  # noqa: ARG001
    """The schema already closes `ingredients`/`grants`/`hostRole`/`hostFrame` to real enums — this
    exists only for the two FREE-TEXT fields the schema cannot close: D20's banned word can still
    reach `name`/`flavor`, exactly as `combogen.brief.build_brief` already guards on the outbound
    (brief) side. Guarding both directions is what makes the word actually unreachable rather than
    merely absent from the prompt."""
    if draft.get("blocked"):
        return []
    defects: "list[str]" = []
    for field in ("name", "flavor"):
        value = draft.get(field)
        if isinstance(value, str):
            banned = scan_for_banned_word(value)
            if banned:
                defects.append(f"{field}: contains {banned} — D20 bans that word outright")
    return defects


def answer_reuses_a_shipped_idea(draft: dict, context: "dict[str, Any]") -> "list[str]":
    """Two names are the same idea when the validator's own `NameNormalizer` gives them one key
    ("Ferocity Bulwark" / "Bulwark of Ferocity"). The normalizer is NOT forked here: `keyOf` is
    `name_repair.validator_keys`, which asks `gk-forge/tools/ItemSeedValidator --normalize-names`, and
    `takenKeys` is the shipped corpus's key set. Measured 2026-09-21: without this, a
    `--retry-blocked` run minted `Bastion of Ferocity` beside the shipped `Ferocity Bastion`, and
    the fresh repair minted `Ferocity Bulwark` beside the shipped set `Bulwark of Ferocity` — the
    validator caught both, after the write. A generated row may not force a shipped name to move."""
    if draft.get("blocked"):
        return []
    name = draft.get("name")
    key_of = context.get("keyOf")
    taken = context.get("takenKeys")
    if not isinstance(name, str) or not name.strip() or key_of is None or not taken:
        return []
    key = key_of([name.strip()]).get(name.strip(), "")
    if key and key in taken:
        return [f"name: {name!r} normalizes to {key!r}, the same idea as a name the shipped corpus "
                f"already uses — choose a different idea, not the same words in another order"]
    return []


def answer_uses_a_legal_name(draft: dict, context: "dict[str, Any]") -> "list[str]":
    """The C# validator's OWN naming grammar, on the authored name — never a Python copy of the patterns
    (SSH5.13-P1). `nameDefects` is `name_repair.name_defects`, which asks
    `gk-forge/tools/ItemSeedValidator --check-names`; without it the check is off (a unit fixture), with it a
    single-word fusion that does not decompose into two pool words is refused BY NAME before the write.

    Measured 2026-09-21: the R11 re-run persisted `Ironstead` and then `Ironheart` for
    `combo.strain-ferocity-balance`, both `FusionNotDecomposable`, and the C# gate caught them only after
    they were written. The brief already states the grammar (`NAMING_GRAMMAR_RULES`, `brief.py:108`), so
    the missing half was the check and its heal feedback."""
    if draft.get("blocked"):
        return []
    name = draft.get("name")
    defects_of = context.get("nameDefects")
    if not isinstance(name, str) or not name.strip() or defects_of is None:
        return []
    return list(defects_of([name.strip()]).get(name.strip(), []))


COMBINATION_VALIDATORS = (answer_matches_schema, answer_declares_content,
                          answer_stays_in_vocabulary, answer_reuses_a_shipped_idea,
                          answer_uses_a_legal_name)


def state_for_combination(subject, *, schema: "dict[str, Any]",
                          taken_keys: "set[str] | None" = None,
                          key_of: "Callable[[list[str]], dict[str, str]] | None" = None,
                          name_defects: "Callable[[list[str]], dict[str, list[str]]] | None" = None) -> dict:
    """Built from a `combogen.run.Subject`, whose brief `plan_run` already assembled — never
    re-rendered here, the same discipline `item_set.py`'s own `state_for_item` states for
    `build_brief`. `taken_keys`/`key_of` arm `answer_reuses_a_shipped_idea`; a caller that cannot
    supply them (a unit fixture) leaves the check off rather than guessing a key."""
    context = {
        "entryId": subject.entry_id, "shape": subject.shape,
        "themeKey": subject.theme_key, "aptitudes": subject.aptitudes,
        "archetype": subject.archetype, "schema": schema,
    }
    if taken_keys is not None and key_of is not None:
        context["takenKeys"] = taken_keys
        context["keyOf"] = key_of
    if name_defects is not None:
        context["nameDefects"] = name_defects
    return new_state(subject.subject_id, brief=subject.brief, context=context)


def build_item_combination_graph(
    *,
    schema: "dict[str, Any]",
    on_persist: "Callable[[str, dict], None] | None" = None,
    config: LlmCallerConfig | None = None,
    call: "Callable[..., str] | None" = None,
    checkpointer: "Any | None" = None,
):
    return build_generation_graph(
        generate=make_generate_node(system=SYSTEM_PROMPT, schema=schema, config=config, call=call),
        validate=make_validate_node(COMBINATION_VALIDATORS),
        persist=make_persist_node(on_persist),
        checkpointer=checkpointer,
    )
