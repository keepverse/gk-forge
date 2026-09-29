"""seedsmith.adapters.trees.nodegen.run — `plan_run` over one tree's committed plan ->
`RunPlan{subjects, held, already_done}` (task H1, spec-tree-language.md §6.1, §6.4); task H2 adds
the real multi-gate RUNNER on top: `generate_node` (one node, base call + the `affixIds` vote) and
`run_language_stage` (a whole tree, idempotent, byte-identical on a forced rerun).

⚠ **What H1 built vs what H2 adds.** H1 assembles the unit-of-work list *deterministically* — one
`Subject` per node, the only unit at which the permitted subset is exact (§6.1's own table) — and
the idempotence ledger's read/write halves. **H2 is the part that actually calls a model**: gates
6-14 (preflight, contract, brief conformance, text style, vote resolution, bounded repair,
persist-time re-gate, idempotence) plus gates 2, 23, 24 (description audit, run verdict, offline
guarantee), wired around H1's own `Subject`/`RunPlan`/ledger rather than replacing them.

**Nothing here reimplements a gate the repo already ships generically** (the todo's own instruction
— reuse, never invent a parallel shape): gate 7 is `actions.validate_heal.gates.run_g1` (schema-
generic, no `atomFamilies`-specific code in it); gate 6 is
`actions.validate_heal.preflight.run_preflight` verbatim; gate 10 is
`workflow.validators.field_echo`/`language` verbatim; gate 11 is
`actions.validate_heal.derive.resolve_set_vote_field`/`verify_permutation` verbatim (`affixIds` is
set-valued, so the SET vote — per-member majority — is the correct aggregation, not the scalar one);
gate 12 is `pipeline.llm_caller.call_with_self_heal` verbatim. Only gate 9's tree-specific half (an
affix outside the permitted set is already a gate-7 enum violation; what gate 7 cannot see is an
affix whose OWN tags collide with this node's anti-motifs) and gate 13 (the persist-time re-gate
over the base response with the VOTED `affixIds` substituted in — a combination gate 7/9 never
checked as a whole, because the vote can pick a set none of the three individual calls returned)
are new code.

**The offline transport stub, precisely.** This module makes no attempt to inject a transport
parameter through `call_with_self_heal` — that function already calls the real
`seedsmith.pipeline.llm_caller.call_model` internally, and the established pattern this whole repo
already uses four times over (`test_classify_pipelines.py`, `test_family_propose.py`,
`test_general_propose.py`, `test_signature_propose.py`) is `unittest.mock.patch
("seedsmith.pipeline.llm_caller.call_model", raising_call)`, where `raising_call(*a, **kw): raise
AssertionError(...)`. §7 gate 24 reuses that exact pattern rather than inventing a second one; the
trees test suite's own copy lives in `_nodegen_fixtures.py` so every test file here shares it.
"""
from __future__ import annotations

import itertools
import json
import os
import re
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Collection, Mapping, Sequence

from ....pipeline.llm_caller import LlmCallerConfig, call_with_self_heal, resolve_live_transport
from ....pipeline.model import BLOCKED_FIELD
from ...actions.validate_heal.derive import (VoteSample, canonical_set_key, resolve_set_vote_field,
                                             verify_permutation)
from ...actions.validate_heal.gates import run_g1
from ...actions.validate_heal.preflight import PreflightResult
from ...actions.validate_heal.preflight import run_preflight as _shared_run_preflight
from ...actions.validate_heal.schema_audit import audit_descriptions
from ...creatures.anchor.permute import order_for
from ....workflow.validators.field_echo import field_echo, name_collision, subject_name_echo
from ....workflow.validators.language import language_consistency
from . import brief as brief_mod
from . import plan_read
from .emit import (NodeSeedRecord, build_node_record, build_seed_document, tree_content_hash,
                   write_seed_document)
from .exclusion import ExclusionClaim, validate_exclusion
from .schema import NODE_RESPONSE_SCHEMA, schema_for_call
from .vocab import AffixOption, AffixVocabulary, AffixVocabularyError

REPO_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_LEDGER = REPO_ROOT / "data" / "seed" / "passive-tree" / "_runs" / "tree-language.ledger.json"

#: The three §6.1 vote samples: sample 0 IS the base call (its `affixIds` is both the node's other
#: seven fields' only source AND vote sample 0), samples 1-2 are the two extra "vote calls" the
#: 4,680 arithmetic counts (§6.1: "vote calls 1,560 x 1 voted field x (3 - 1) = 3,120").
VOTE_SAMPLE_COUNT = 3


def calls_for(total_subjects: int, *, vote_sample_count: int = VOTE_SAMPLE_COUNT) -> "dict[str, int]":
    """§6.1's own cost table (D29's corpus, re-derived from doc 03's 7-tier figures), computed from
    `total_subjects` rather than hardcoded — at the generic corpus's real size (1,560 subjects: 39
    trees x 40 nodes) this returns exactly the spec's own cited 4,680:

        base calls     total_subjects x 1 pipeline                =  1,560
        vote calls     total_subjects x 1 voted field x (3 - 1)   =  3,120
                                                                      -----
                                                                      4,680 calls

    The dry run (`trees generate --dry-run`, §Commands) prints this BEFORE spending a single call —
    that is the whole point of it being a pure function of a count, never of a live run."""
    base_calls = total_subjects
    vote_calls = total_subjects * (vote_sample_count - 1)
    return {"baseCalls": base_calls, "voteCalls": vote_calls, "totalCalls": base_calls + vote_calls}


class UnexpectedTransportCall(RuntimeError):
    """§7 gate 24: raised by `offline_transport_stub` — a callable with the exact
    `(system, user, schema) -> str` shape `preflight.CallModelFn`/`llm_caller.call_model` share —
    when something reaches it. Nothing in this module calls it directly (the module makes its real
    calls through `call_with_self_heal`, which reaches `llm_caller.call_model` on its own); it
    exists so a caller wiring `preflight.run_preflight`'s own `call_model_fn` parameter for a
    dry-run has a loud, named stub to pass instead of `None`, rather than inventing a fresh one
    per call site."""


def offline_transport_stub(system: str, user: str, schema: "Mapping[str, Any] | None" = None) -> str:
    raise UnexpectedTransportCall(
        "the offline transport stub was called — a dry-run or a test path reached a model "
        "transport, which must never happen (spec-tree-language.md §7 gate 24)")


def audit_node_schema_descriptions() -> "list":
    """§7 gate 2, run once before any call: the shipped `NODE_RESPONSE_SCHEMA`'s own properties
    each carry a negative-clause description. `schema_audit.audit_descriptions` is Stage 0's own
    check (`actions.validate_heal.schema_audit`), reused verbatim rather than forked — deliberately
    NOT folded into `pipeline.model.audit_schema` (that module's own docstring: doing so would fire
    on every OTHER seedsmith schema the moment this package imports it)."""
    return audit_descriptions(NODE_RESPONSE_SCHEMA)


def run_preflight(*, skip: bool, transport: "Callable[[str, str, dict], str] | None" = None,
                  endpoint: "str | None" = None, model_id: "str | None" = None) -> PreflightResult:
    """§7 gate 6, delegating verbatim to `actions.validate_heal.preflight.run_preflight` — the
    SAME single-member-enum probe, not a tree-specific copy of it (constrained decoding is a
    property of the SERVER, not of this schema)."""
    return _shared_run_preflight(skip=skip, call_model_fn=transport, endpoint=endpoint,
                                 model_id=model_id)


def brief_conformance_defects(response: "Mapping[str, Any]", *, permitted_affix_ids: "Sequence[str]",
                              anti_motif_tags: "Sequence[str]",
                              affix_vocab: AffixVocabulary) -> "dict[str, str]":
    """§7 gate 9's tree-specific half. An affix outside the permitted set is ALREADY a gate-7 enum
    violation (`run_g1` walks `affixIds.items.enum`) — what gate 7 cannot see is an affix whose own
    `tags` (`vocab.AffixOption.tags`) collide with this node's anti-motifs, since that is a property
    of the VOCABULARY, not of the schema's enum shape."""
    defects: "dict[str, str]" = {}
    affix_ids = response.get("affixIds")
    if not isinstance(affix_ids, list) or not anti_motif_tags:
        return defects
    hit_tags: "set[str]" = set()
    for affix_id in affix_ids:
        if affix_id not in permitted_affix_ids:
            continue  # already named by gate 7; never double-reported under a different key
        try:
            option = affix_vocab.get(affix_id)
        except AffixVocabularyError:
            continue
        hit_tags.update(option.tags)
    collision = hit_tags & set(anti_motif_tags)
    if collision:
        defects["affixIds"] = (
            f"picks an affix tagged {sorted(collision)} — this node's own anti-motifs — even "
            f"though no single affixId is itself forbidden")
    return defects


def build_response_gate(*, schema: "Mapping[str, Any]", permitted_affix_ids: "Sequence[str]",
                        permitted_property_keys: "Sequence[str]", anti_motif_tags: "Sequence[str]",
                        affix_vocab: AffixVocabulary,
                        property_vocabulary: "Mapping[str, tuple[str, ...]] | Sequence[str]",
                        tree_display_name: str,
                        motifs: "Sequence[str]",
                        taken_names: "Sequence[str] | Collection[str]" = (),
                        permitted_exclusion_forms: "Sequence[str] | None" = None,
                        ) -> "Callable[[Mapping[str, Any]], list[str]]":
    """The one `gate` callable §6.3's response is checked against, composed from gates 7, 9, 10 and
    the per-response half of 18 (exclusion) — never five separate call sites, so a caller
    (`generate_node`, or a future H4 harness) has exactly one function to run twice (verify-time,
    then persist-time re-gate, gate 13).

    **`taken_names` — gate 21's generation-time half, closed 2026-09-11.** Spec-tree-language.md §7
    gate 21 and spec-species-tree.md §5.1 both name `name_collision` against `takenNames` as a
    GENERATION-TIME check, but this gate used to call `field_echo` only and leave
    `name_collision` (the shared primitive `workflow.validators.field_echo.name_collision`)
    unreachable from node generation at all — the corpus metric
    (`PassiveTree/NameCollision`, metrics/passive_tree.py) kept finding 646 real cross-tree
    collisions post-hoc that no per-item check ever rejected. The name is checked against every
    OTHER subject's committed name, corpus-wide (the same shape the validator's own docstring
    measures from the commander-effect corpus), never just this tree's — a same-name draft from a
    different tree is exactly the measured defect. Every draft is re-checked at persist time (gate
    13) against the set INCLUDING any name accepted since the base call, so a name that collides
    only after the vote is still refused there.

    **`permitted_exclusion_forms` (2026-09-11, A2)** is the quota cell's own `exclusionForm`
    allocation as a form list — `("none",)` for a `none` cell, `(form, "none")` for a designated
    one — checked here so the NARROWED enum is enforced even where the schema enum cannot reach:
    the persist-time re-gate (gate 13) validates the VOTED composite through this same callable, so
    the cell's allocation holds at both ends. `None` keeps the full ladder, matching
    `schema_for_call`'s additive contract; a cell-bearing caller that forgets the argument widens
    its own gate — `generate_node` always passes it.
    """

    taken_names_set = frozenset(taken_names)
    # A2 (2026-09-11): the cell's allocation as a set, for the per-response check below. An
    # unknown non-none form in a designated cell is a caller defect — it is checked, not widened.
    form_set = frozenset(permitted_exclusion_forms) if permitted_exclusion_forms is not None else None

    def gate(response: "Mapping[str, Any]") -> "list[str]":
        problems: "list[str]" = []
        contract_defects = dict(run_g1(response, schema))
        # ⚠ `run_g1` carries ONE hardcoded, actions-specific assumption: "`blocked` must be a
        # boolean" — literal, unconditional, regardless of the schema it is handed. §6.3's own
        # design is deliberately the OPPOSITE (schema.py's own docstring: "`blocked` is an
        # empty-string sentinel, not a boolean... a boolean let a real local model fill the field
        # with something plausible-but-wrong"), so this one false positive is dropped whenever the
        # value actually matches the SCHEMA's own declared type (a real wrong-type `blocked` —
        # an int, say — still fails `run_g1`'s own generic per-field type check above, unaffected).
        if isinstance(response.get(BLOCKED_FIELD), str):
            contract_defects.pop(BLOCKED_FIELD, None)
        problems.extend(f"{field}: {reason}" for field, reason in contract_defects.items())

        # §6.3's own field description for `affinity`, verbatim: "in the same order as `affixIds`
        # and the same length" — `run_g1` checks each array against its OWN enum, never a
        # cross-field length agreement, so this is the one place that requirement is enforced. It
        # matters most exactly where gate 13 (persist-time re-gate) needs it: the base call's own
        # `affinity` was sized for the base call's own `affixIds`, and the vote (§7 gate 11) may
        # substitute a DIFFERENT-length set in before persisting.
        affix_ids, affinity = response.get("affixIds"), response.get("affinity")
        if isinstance(affix_ids, list) and isinstance(affinity, list) and len(affix_ids) != len(affinity):
            problems.append(
                f"affinity: has {len(affinity)} entries but affixIds has {len(affix_ids)} — §6.3 "
                f"requires the same length, in the same order")

        # Deeper, semantic checks only make sense once the shape itself is sound — a response that
        # already failed gate 7 (e.g. `affixIds` is not even a list) has nothing coherent for gate 9
        # or the exclusion ladder to check.
        if not contract_defects:
            brief_defects = brief_conformance_defects(
                response, permitted_affix_ids=permitted_affix_ids, anti_motif_tags=anti_motif_tags,
                affix_vocab=affix_vocab)
            problems.extend(f"{field}: {reason}" for field, reason in brief_defects.items())

            exclusion = response.get("exclusion")
            if isinstance(exclusion, dict):
                claim = ExclusionClaim.from_response(exclusion)
                problems.extend(str(d) for d in validate_exclusion(claim, property_vocabulary))
                # A2 (2026-09-11): the cell's own allocation, enforced per response — a `none` cell
                # accepts only `none`, a designated cell accepts only its own rung (plus `none`,
                # the honest default the §6.3 field description already describes). Beyond the
                # schema enum (which already says the same thing) because gate 13's persist-time
                # re-gate runs the VOTED composite through this callable too.
                if form_set is not None and claim.form not in form_set:
                    problems.append(
                        f"exclusion.form: {claim.form!r} is not what this node's quota cell "
                        f"allocated {sorted(form_set)} — §4.2 step 6: the cell is what the "
                        f"schema's enum says, and the gate holds the response to it")
        problems.extend(field_echo(response, {}))
        # Gate 21's generation-time half: the draft's name against every other subject's committed
        # name, corpus-wide — the check the spec names and the metric measures, wired at last.
        # `subjectKind` names what is colliding. Both shared validators used to hardcode "commander
        # effect" in the message, so every refusal here mislabelled a passive-tree node; and because
        # the message carries the noun, that mislabelling is part of what made a 12.5 MB failure
        # ledger read as 984 distinct shapes.
        node_context = {"subjectKind": "passive-tree node"}
        problems.extend(name_collision(response, {"takenNames": taken_names_set, **node_context}))
        problems.extend(subject_name_echo(response,
                                          {"displayName": tree_display_name, **node_context}))
        problems.extend(language_consistency(response, {"motifs": motifs}))
        return problems

    return gate


@dataclass(frozen=True)
class Subject:
    """One unit of work: one node, in one tree, at one call granularity (§6.1).

    `brief`/`schema` stay `None` until the caller supplies this node's resolved quota cell — H1's
    `plan_run` enumerates WHICH nodes need a call; it does not itself resolve what any one of them
    may say, because that resolution is H3's (`quota.permitted`) composed with `brief.render_brief`
    and `schema.schema_for_call` (H2's graph wiring calls both, per node, per the todo's own
    dependency line `H2: Depends on: A2, H1`).
    """

    subject_id: str
    tree_id: str
    node_id: str
    node_key: str
    branch: str
    tier: int
    node_class: str
    brief: "str | None" = None
    schema: "dict[str, Any] | None" = None

    def to_dict(self) -> dict:
        return {
            "subjectId": self.subject_id, "treeId": self.tree_id, "nodeId": self.node_id,
            "nodeKey": self.node_key, "branch": self.branch, "tier": self.tier,
            "nodeClass": self.node_class,
        }


@dataclass
class RunPlan:
    subjects: "list[Subject]"
    held: "list[tuple[str, str]]"
    already_done: "list[str]"
    #: Subjects whose ledger row is being INTENTIONALLY re-rolled this run (§8's
    #: provenance-supersede pass, J4): they are planned for generation like `subjects`, but their
    #: acceptance goes through `record_superseded` (the prior row preserved), never
    #: `record_accepted`'s raise-on-duplicate. Empty unless the caller asked for supersede.
    superseded: "list[Subject]" = field(default_factory=list)
    #: Subjects superseded because their committed row shares a `nameKey` OR a display `name` with an
    #: EARLIER node of the same tree (`plan_run`'s own duplicate scan, J9-B1(b)). Unlike a staleness
    #: supersede, the re-roll must NOT be free to keep its own prior identity: the prior name/key is
    #: exactly what collides, so `_generate_one`/`_record_outcome` count it as somebody else's claim
    #: and a re-roll that repeats it lands `unresolved` rather than persisting the duplicate again
    #: (measured: without this, a re-roll of `AcientSunNut`'s collided `Solar Flare` produced a THIRD
    #: node named `Solar Flare`).
    duplicate_ids: "frozenset[str]" = frozenset()

    @property
    def complete(self) -> bool:
        """A plan with a held subject is NOT complete — same rule `items/setgen/run.py`'s own
        `RunPlan.complete` states, so a held quota cell (an `UnsatisfiableCell`, upstream) can never
        be silently reported as a finished run."""
        return not self.held

    def summary(self) -> dict:
        by_reason: "dict[str, int]" = {}
        for _, reason in self.held:
            by_reason[reason] = by_reason.get(reason, 0) + 1
        return {"toGenerate": len(self.subjects), "alreadyDone": len(self.already_done),
                "held": len(self.held), "heldByReason": by_reason, "complete": self.complete}


def read_ledger(path: "Path | None" = None) -> "dict[str, dict]":
    ledger_path = path or DEFAULT_LEDGER
    if not ledger_path.exists():
        return {}
    doc = json.loads(ledger_path.read_text(encoding="utf-8"))
    return dict(doc.get("done") or {})


def write_ledger(done: "dict[str, dict]", path: "Path | None" = None) -> Path:
    """Atomic replace — same discipline `items/setgen/run.py:write_ledger` already ships, reused
    here rather than re-derived, so a killed process never leaves a half-written ledger at 1,560
    subjects any more than it does at ~1,800."""
    ledger_path = path or DEFAULT_LEDGER
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"schemaVersion": 1, "done": done}, ensure_ascii=False, indent=2) + "\n"
    handle, tmp_name = tempfile.mkstemp(dir=str(ledger_path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp_name, ledger_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return ledger_path


def plan_run(tree_plan: "plan_read.TreePlan", *, ledger: "dict[str, dict] | None" = None,
             supersede_stale: bool = False,
             prompt_version: str = "",
             only_node_id: str = "") -> RunPlan:
    """Enumerates one `Subject` per node in the plan, skipping any already in the ledger.

    Nothing is `held` at this stage today: a hold this module could name would be a quota cell it
    cannot satisfy, and this module never resolves a quota cell (`quota.py`/H3's job) — so `held` is
    always `[]` here, present in the shape only so H3 has somewhere to put one without changing
    `RunPlan`'s own fields.

    **Ordering (§6.2's sibling-passing shape, closed 2026-09-06):** subjects are stably sorted
    `(tier, 0 if mechanism else 1)` — every mechanism node in a tier generates before that tier's
    magnitude nodes, never reordering ACROSS tiers or within the same `(tier, class)` group (Python's
    `sorted` is stable, so ties keep the plan's own file order). This exists so
    `run_language_stage`'s own tier-sibling tracking (below) has something real to pass a magnitude
    node the first time it renders — a magnitude node is defined as "makes an EXISTING thing larger"
    (`brief.py`'s own class note), and a tree plan is free to list its magnitude nodes before any
    mechanism node in the same tier (confirmed: `might`'s own committed plan does, for its first six
    nodes) — without this reorder, a magnitude node would ALWAYS render with an empty sibling list
    regardless of how well `run_language_stage` tracks acceptance, which is the exact "current tree is
    empty" gap the 2026-09-06 smoke test surfaced. This does not change what the FINAL seed document's
    own node order is — `run_language_stage`'s own `sorted_records = sorted(..., key=... node_id)`
    already re-sorts by `node_id` at emit time, so generation order is a pure scheduling detail.

    **`supersede_stale` (2026-09-11, §8's provenance-supersede pass).** With it, a ledger row whose
    per-record `promptVersion` is ABSENT (pre-provenance, i.e. generated under an older brief) or
    DIFFERENT from `prompt_version` (the caller's current brief vintage, `brief.PROMPT_VERSION`) is
    planned for generation AND listed in `superseded`, so the runner replaces its row through
    `record_superseded` — the prior entry preserved under `supersededRecord`, never silently
    discarded. A row that already carries the current vintage is left alone. This is what makes a
    prompt-version re-roll expressible through the real CLI at all (until now the only caller of
    `record_superseded` was a unit test — a §8-mandated pass with no production path).
    """
    done = ledger if ledger is not None else read_ledger()
    subjects: "list[Subject]" = []
    already: "list[str]" = []
    superseded: "list[Subject]" = []

    def _stale(entry: "dict") -> bool:
        stored = str((entry.get("record") or {}).get("promptVersion") or "")
        return not stored or stored != prompt_version

    # A row-level invariant enforced unconditionally (not only under `supersede_stale`): a committed
    # record whose `nameKey` — or whose display `name` — is already claimed by an EARLIER node of the
    # SAME tree is invalid by definition. `build_seed_document` refuses on duplicate nameKeys, so such
    # a pair used to lose the WHOLE tree at emit time. Measured (J9-B1(b), 2026-09-21, real
    # `AcientSunNut` run): the pre-2026-09-11 same-batch race minted two nodes named `Solar Flare` and
    # two named `Solar Marrow`, with `tree.node.solar-flare-5` twice and `tree.node.solar-marrow-2`
    # twice in the ledger, and every later pass rebuilt the same document and refused again. The race
    # itself is closed in `_record_outcome`; this repairs rows a pre-fix run already committed, by
    # routing the later collidees through the EXISTING §8 supersede path — prior row preserved under
    # `supersededRecord`, never discarded, never renamed out from under the model's answer.
    duplicate_ids: "set[str]" = set()
    claimed_keys: "dict[str, str]" = {}
    claimed_names: "dict[str, str]" = {}
    for node in tree_plan.nodes:
        subject_id = f"{tree_plan.tree_id}:{node.node_id}"
        record = (done.get(subject_id) or {}).get("record") or {}
        key = str(record.get("nameKey") or "")
        name = str(record.get("name") or "")
        if key:
            if key in claimed_keys:
                duplicate_ids.add(subject_id)
            else:
                claimed_keys[key] = subject_id
        if name:
            if name in claimed_names:
                duplicate_ids.add(subject_id)
            else:
                claimed_names[name] = subject_id

    for node in tree_plan.nodes:
        subject_id = f"{tree_plan.tree_id}:{node.node_id}"
        entry = done.get(subject_id)
        if entry is not None and entry.get("record"):
            if subject_id in duplicate_ids or (supersede_stale and _stale(entry)):
                superseded.append(Subject(
                    subject_id=subject_id, tree_id=tree_plan.tree_id, node_id=node.node_id,
                    node_key=node.node_key, branch=node.branch, tier=node.tier,
                    node_class=node.node_class,
                ))
                continue
            already.append(subject_id)
            continue
        # No row, or a row from a prior FAILED attempt (`record: null`, written by `record_attempt`).
        # Either way the node is still owed a real generation, so it is scheduled like a fresh
        # subject — the attempt row is bookkeeping, never "done".
        subjects.append(Subject(
            subject_id=subject_id, tree_id=tree_plan.tree_id, node_id=node.node_id,
            node_key=node.node_key, branch=node.branch, tier=node.tier,
            node_class=node.node_class,
        ))
    subjects.sort(key=lambda s: (s.tier, 0 if s.node_class == "mechanism" else 1))
    superseded.sort(key=lambda s: (s.tier, 0 if s.node_class == "mechanism" else 1))

    # ip-censor T16/IC-4.1: `only_node_id` restricts what this run GENERATES to one node, so
    # `--write --supersede --node <id>` re-rolls exactly that subject. Generation narrows (only the
    # target survives in `subjects`/`superseded`); REPLAY must not. Every other node with a committed
    # row is forced into `already_done`, because `run_language_stage` rebuilds the emitted seed
    # document from `already_done` + this run's accepts — dropping the others is what shrank
    # `command.json` from 40 nodes to 1 on the first real run (a real defect caught by the T16
    # post-check, fixed 2026-09-24). A node id the plan does not carry is refused by name rather than
    # yielding an empty run that reads as "nothing to do".
    if only_node_id:
        plan_node_ids = {node.node_id for node in tree_plan.nodes}
        if only_node_id not in plan_node_ids:
            raise ValueError(
                f"--node {only_node_id!r} is not a node of tree {tree_plan.tree_id!r} "
                f"(the plan carries {len(plan_node_ids)} nodes)")
        target_subject_id = f"{tree_plan.tree_id}:{only_node_id}"
        subjects = [s for s in subjects if s.node_id == only_node_id]
        superseded = [s for s in superseded if s.node_id == only_node_id]
        # Any OTHER node whose row is committed becomes a replay subject, so the document stays whole.
        replayed = set(already)
        for node in tree_plan.nodes:
            sid = f"{tree_plan.tree_id}:{node.node_id}"
            if sid == target_subject_id or sid in replayed:
                continue
            if (done.get(sid) or {}).get("record"):
                already.append(sid)
                replayed.add(sid)

    # A superseded subject is a subject being GENERATED this run (that is the whole re-roll), so it
    # rides the normal `subjects` scheduling path — the generation loop, batch ordering and
    # `outcomes` below all key off `plan.subjects` — while ALSO being listed in `superseded` as the
    # routing tag `_record_outcome` needs to write via `record_superseded`, never `record_accepted`'s
    # raise-on-duplicate.
    return RunPlan(subjects=subjects + superseded, held=[], already_done=already,
                   superseded=superseded, duplicate_ids=frozenset(duplicate_ids))


def record_accepted(done: "dict[str, dict]", subject_id: str, record: NodeSeedRecord) -> "dict[str, dict]":
    """§7 gate 14's own citation, `ProvenanceLedger.record` (`pipeline/provenance.py:109-118`):
    "raises on a duplicate row." This ledger is a plain JSON `{subjectId: entry}` map rather than
    that class (H1's own shape, already round-tripped by `read_ledger`/`write_ledger`), but the
    SAME discipline applies: two runs both believing they generated the same subject is exactly the
    defect idempotence exists to prevent, so recording over an existing row raises rather than
    silently overwriting it. Returns a NEW dict — the caller's own `done` mapping is never mutated
    in place, so a caller mid-loop still holds the pre-record snapshot if it needs to roll back.

    **A row from a prior FAILED attempt is not a duplicate (2026-09-11).** `record_attempt` below
    persists non-accepted outcomes (unresolved/escalated/blocked) with `record: null`, so the ledger
    is an honest record of what happened AND `plan_run` can schedule the subject again. Accepting on
    a later pass is therefore the designed replacement of that attempt row, not idempotence failing:
    the raise fires only when the prior row holds a real accepted `record`.
    """
    prior = done.get(subject_id)
    if prior is not None and prior.get("record"):
        raise ValueError(
            f"subject {subject_id!r} already has a ledger row — a second `record_accepted` call "
            f"means idempotence failed (two runs both believed they generated it)")
    return {**done, subject_id: {"record": record.to_dict()}}


def record_attempt(done: "dict[str, dict]", subject_id: str, outcome: str, detail: str = "",
                   ) -> "dict[str, dict]":
    """Persist a NON-accepted outcome — `unresolved`, `escalated` or `blocked` — so the ledger
    records every real attempt, not only the ones that succeeded (owner request, 2026-09-11).

    **Why this matters, measured.** `run_language_stage` writes the ledger before emitting, so a
    subject that never resolves has historically left NO ledger trace at all. Three real costs
    followed: (1) a corpus could not distinguish "this node was never attempted" from "this node was
    attempted and the model could not resolve it", so a proof of corpus health could not name which
    nodes were still owed; (2) the resume loop had to re-derive the outstanding set purely from
    plan-minus-ledger, with no count of how many times a node had already failed; (3) a failed
    re-roll under `--supersede` looked identical to a node that had never run. An attempt row closes
    all three: `record` stays `null` (so `plan_run` treats it as still-to-generate, never
    "already done"), `outcome`/`detail` say what happened, and `attempts` counts consecutive
    failures so a permanently stuck node is visible rather than silently retried forever.

    Never clobbers an accepted row: a superseded subject whose re-roll fails keeps its prior
    accepted `record` (the D2 contract above), so an attempt is only ever written where no accepted
    record exists.
    """
    prior = done.get(subject_id)
    if prior is not None and prior.get("record"):
        return done
    attempts = int((prior or {}).get("attempts") or 0) + 1
    return {**done, subject_id: {
        "record": None, "outcome": outcome, "detail": detail, "attempts": attempts}}


def record_superseded(done: "dict[str, dict]", subject_id: str, record: NodeSeedRecord) -> "dict[str, dict]":
    """J4 (spec-tree-review.md §8's own two-hazards warning) — the DELIBERATE, EXPLICIT counterpart
    to `record_accepted`'s "raise on duplicate" default, for the ONE case that default exists to
    rule out by accident, not by design: an INTENTIONAL re-review pass regenerating an
    already-accepted node after a prompt-version bump or a plan change (§8's own table). Passive
    tree's own node ids are the STABLE structural slug (`tree-catalog` §3) — the exact property §8
    says "is the single decision that makes a second review pass possible at all" — so a
    regenerated node's `subject_id` is, BY DESIGN, identical to its prior entry's; `record_accepted`
    would refuse it, correctly, for anyone who did not mean to do this.

    **A real, corrected finding, not the spec's own literal citation.** §8 names
    `ProvenanceLedger.record` (`pipeline/provenance.py:109-118`, shared with `items/setgen`) as the
    class that "raises on a re-recorded row" and blocks pass two — but passive-tree's own ledger,
    read directly here, was NEVER an instance of that shared class (H1's own citation two functions
    up already says so: "a plain JSON `{subjectId: entry}` map rather than that class"). The actual
    blocker for THIS program is `record_accepted` above, entirely local to this module — so
    `provenance-supersede` for passive-tree specifically does not require touching shared
    `seedsmith.pipeline.provenance` (a genuinely cross-program change with its own, separate
    `items/setgen` caller to keep safe) at all. Verified by grepping every real caller of
    `ProvenanceLedger` before writing this docstring, not assumed from the spec's own prose.

    Never the default path — a caller must name this function explicitly, the same "loud, not
    silent" discipline `record_accepted` itself already states, applied to the ONE case that
    discipline should not block. The prior entry is PRESERVED under `supersededRecord`, never
    discarded — §8's own "diff card" wants the previous value "struck through in place" alongside
    the new one, which needs the old content to still exist somewhere to render.
    """
    prior = done.get(subject_id)
    entry: "dict[str, Any]" = {"record": record.to_dict()}
    if prior is not None:
        entry["supersededRecord"] = prior["record"]
    return {**done, subject_id: entry}


# ---------------------------------------------------------------------------------------------
# H2 — the real gate runner. Gates 6, 7, 9, 10, 11, 12, 13 fire per node; gates 2, 23, 24 fire once
# per run (description audit before any call, the run verdict after every subject, the offline
# guarantee everywhere — proven by test, never by a runtime check).
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class NodeGenerationInputs:
    """Everything one node's generation needs beyond the `Subject` itself. H3's quota stage is what
    RESOLVES a node's own `permitted_affixes`/`permitted_properties`/`anti_motif_tags` from the
    plan's quota cell (`quota.py`) — this module takes them as already-resolved arguments rather
    than re-deriving them, the same split `Subject.brief`/`Subject.schema` staying `None` in H1
    already draws.

    `quota_cell` is the six-axis cell itself (additive, 2026-09-10): persisted onto the accepted
    `NodeSeedRecord` so `PassiveTree/QuotaDrift` can measure a committed corpus. Optional so every
    pre-persistence construction site keeps working unmodified."""

    tree_display_name: str
    tree_reading: str
    motifs: "Sequence[str]"
    anti_motifs: "Sequence[str]"
    anti_motif_tags: "Sequence[str]"
    permitted_affixes: "Sequence[AffixOption]"
    permitted_properties: "Sequence[str]"
    property_vocabulary: "Mapping[str, tuple[str, ...]] | Sequence[str]"
    affix_vocab: AffixVocabulary
    siblings: "Sequence[brief_mod.SiblingSummary]" = ()
    quota_cell: "Mapping[str, str] | object | None" = None
    #: ip-censor T16/IC-4.1: the rendered IP avoid-list terms the brief prints as its own line. The
    #: CALLER resolves them (the shared `briefkit.avoid_list` helper reading the committed registry);
    #: default empty so every pre-T16 construction site is unchanged and prints no avoid line.
    avoid_terms: "Sequence[str]" = ()


@dataclass(frozen=True)
class NodeOutcome:
    """One node's whole generation result. `outcome` is one of `"accepted" | "blocked" |
    "unresolved" | "escalated"` — the same four-way split `pipeline.model.PipelineResult` and
    `actions.validate_heal.derive.CandidateVerdict` both already use, so a caller reading this
    outcome does not have to learn a fifth vocabulary for the same four ideas."""

    subject_id: str
    outcome: str
    record: "NodeSeedRecord | None" = None
    detail: str = ""


#: 2026-09-06 real-call finding (`might`, tier-4 mechanism node, LM Studio local model): asked to
#: leave `blocked` as the empty string, the model instead wrote a full, valid draft (real `affixIds`,
#: `name`, `flavor`, all schema-legal) with `"blocked": "none"` — read as "I understand this means
#: not-blocked" filtered through a field NAME that shapes like a boolean/nullable rather than the
#: literal empty-string convention `schema.py`'s own description states. The EXACT same finding
#: `general_propose.derive._NULLISH_BLOCKED_TOKENS`'s own docstring already measured and named
#: (2026-09-04, a different real local model, "false"/"none") — this module simply never adopted that
#: fix. Reused verbatim rather than re-derived (`family_propose`/`signature_propose` already keep
#: their own identical copy too, cross-referencing the same evidence).
_NULLISH_BLOCKED_TOKENS = frozenset({"false", "none", "null", "n/a", "na"})


def _normalize_blocked(out: "Mapping[str, Any]") -> dict:
    """See `general_propose.derive._normalize_blocked`'s own docstring for the full real-call
    evidence and reasoning. Any member of `_NULLISH_BLOCKED_TOKENS` (any case/whitespace) is folded
    back to the empty string here. Applied in TWO places, deliberately, not one:
    `call_one_node_sample`'s own return (so the CALLER never misreads "none" as a genuine block) AND
    inside `_node_verify_fn` itself (⛔ corrected 2026-09-06 — see that function's own docstring for
    the real-call evidence a single application at the boundary was not enough: the raw, unfolded
    value inside the self-heal loop could short-circuit `gate()` entirely before it ever ran).
    `"true"` is deliberately NOT normalized: no real-call evidence for that direction exists here
    either, and silently reinterpreting it risks masking an actual decline this module has no way to
    tell apart from the same confusion."""
    if isinstance(out, Mapping) and str(out.get(BLOCKED_FIELD, "")).strip().lower() in _NULLISH_BLOCKED_TOKENS:
        return {**out, BLOCKED_FIELD: ""}
    return dict(out) if isinstance(out, Mapping) else out


def _node_verify_fn(gate: "Callable[[Mapping[str, Any]], list[str]]") -> "Callable":
    """`call_with_self_heal`'s own `verify_fn(items, out) -> (hard, soft)`, closed over one node's
    `gate`. A declared `blocked` response short-circuits (an honest decline is never a defect, the
    same rule every pipeline in this repo already applies) — the caller reads `out[BLOCKED_FIELD]`
    to tell a genuine decline from an accepted draft.

    ⛔ **Corrected 2026-09-06, real-call finding (`fortitude`, 4/40 nodes): `_normalize_blocked`
    MUST run before this short-circuit, not only on the way out.** The original design (this
    function's own prior docstring: "never inside `_node_verify_fn`, which stays a pure hard/soft
    classifier") folded a nullish `blocked` token ("false"/"none"/etc) only in `call_one_node_sample`,
    AFTER the whole self-heal loop already finished — but `verify_fn` runs INSIDE that loop, on the
    RAW, unfolded value, every attempt. A real local model that fills `blocked: "false"` alongside a
    fully-drafted (and, in these four real cases, internally INCONSISTENT — `affixIds` and `affinity`
    different lengths) content payload made this line read `out.get(BLOCKED_FIELD)` as truthy,
    short-circuiting BEFORE `gate()` ever ran — so the length mismatch was never checked at all, and
    the malformed draft was accepted as a clean, unblocked response. Proven live: three vote samples
    for the SAME subject each independently returned the identical malformed
    `(affixIds=["atom.might","atom.ferocity"], affinity=["core"])` shape, all three "succeeding"
    with `soft={}` (never exhausted), which is only possible if `gate()` never ran on any of them.
    Normalizing here, before the check, makes `verify_fn` react to the SAME folded value
    `call_one_node_sample` ultimately returns — a `blocked: "false"` draft is no longer treated as a
    genuine decline, so `gate()` runs against its content fields exactly as it would if the model had
    left `blocked` empty in the first place."""

    def verify_fn(_items: "Mapping[str, Any]", out: "Mapping[str, Any]"):
        if not isinstance(out, dict):
            return {"_draft": "response is not an object"}, {}
        out = _normalize_blocked(out)
        if out.get(BLOCKED_FIELD):
            return {}, {}
        problems = gate(out)
        hard = {f"gate[{i}]": p for i, p in enumerate(problems)}
        return hard, {}

    return verify_fn


def _node_heal_user(brief_text: str, _out: "Mapping[str, Any]", hard: "Mapping[str, str]") -> str:
    """Names the exact defect, then re-sends the ORIGINAL brief — never the model's own prior
    (wrong) draft — mirroring `actions.validate_heal.derive.build_heal_user`'s own shape and its
    own reasoning: a generation stage's "source" is what it was asked to build from.

    ⭐ **"Fix ONLY the named field(s)" — the shared convention, restored 2026-09-11 (real-call
    finding).** This text used to say "Return the COMPLETE corrected JSON object (every required
    key)", which a real local model read as "answer the whole brief again": on a draft whose only
    defect was `affinity`'s length (e.g. one entry for a two-member `affixIds`), it re-chose
    `affixIds` too, producing a genuinely different set on the repair. That made the three §6.1 vote
    samples disagree by construction — a `might` node's three samples returned
    `[plating, carapace]`, `[vitality, fortitude]`, `[shield-capacity, shield-toughness]` — so the
    vote resolved to gate 11's `1-1-1 unresolved` on ~25% of nodes where v1's committed corpus
    recorded ~1‰. The shared `build_heal_user` (this repo's own established wording) already says
    "Fix ONLY the named field(s)", which keeps the model on the defective field and leaves the
    already-valid `affixIds` untouched; the three samples then agree on the affix set, which is the
    whole premise of voting on it. Still returns a complete object (the schema requires every key),
    so the wording names both halves: fix the defect, keep the rest."""
    defects = "\n".join(f"- {reason}" for reason in hard.values())
    return (f"Your previous answer had these problems:\n{defects}\n\n"
            f"Fix ONLY the named field(s). Keep every other field exactly as you had it. Return the "
            f"COMPLETE corrected JSON object (every required key).\n\n"
            f"The brief you are answering:\n{brief_text}")


def call_one_node_sample(*, node_id: str, sample_index: int, brief_text: str,
                         schema: "Mapping[str, Any]", gate: "Callable[[Mapping[str, Any]], list[str]]",
                         config: LlmCallerConfig | None = None) -> "tuple[dict, dict]":
    """One §6.2/§6.3 call at `sample_index`. Gates 7 (contract) and 9 (brief conformance) fire
    inside `gate`, checked on every heal attempt AND once more on the final draft — gate 12
    (bounded repair) is `call_with_self_heal` itself, reused rather than rebuilt. `default_for`
    returns `None` on exhaustion (F9's own rule, `actions.validate_heal.derive.default_for_none`):
    handing back the BRIEF's own value would make an escalated field look like the model answered
    it, which this pipeline refuses to do."""
    out, soft = call_with_self_heal(
        {"nodeId": node_id, "sampleIndex": sample_index}, brief_mod.SYSTEM_PROMPT,
        lambda _items: brief_text, _node_verify_fn(gate),
        config=config, schema=schema, default_for=lambda _key, _original: None,
        build_heal_user=lambda items, out, hard: _node_heal_user(brief_text, out, hard),
    )
    return _normalize_blocked(out), soft


def _exhausted(soft: "Mapping[str, str]") -> bool:
    return any(isinstance(v, str) and v.startswith("FAILED:") for v in soft.values())


_NAME_KEY_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """`name` -> the `<slug>` half of `tree.node.<slug>`, matching `NAME_KEY_PATTERN`
    (`^tree\\.node\\.[a-z0-9-]+$`): lowercase, every run of non-alphanumeric characters becomes one
    hyphen, no leading/trailing hyphen. Never returns an empty string — `"node"` if `name` collapses
    to nothing (e.g. it was pure punctuation), since `NAME_KEY_PATTERN` requires at least one
    character after `tree.node.`."""
    slug = _NAME_KEY_SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "node"


def _derive_unique_name_key(name: str, known_name_keys: "Collection[str]") -> str:
    """2026-09-06 real-call finding (`might`, three separate real collisions across two real runs):
    asked to derive `nameKey` from its own `name` choice (`schema.py`'s own field description, itself
    a fix for this same finding), the real local model kept it as a bare FORMAT instruction and
    repeatedly fell back to a generic templated key (`tree.node.<branch>-<depth>-01`) completely
    decoupled from the name it had just chosen — proven not a one-off: the identical fallback key
    recurred on a FRESH run even after the wording fix landed. No amount of further prompt wording
    can be verified to fix a demonstrated real-model failure to follow an instruction twice in a row;
    the durable fix is to stop trusting the model for this field's UNIQUENESS at all. The model's own
    `nameKey` is still requested and still gates 7/13-validated for FORMAT (a real defect in some
    other field could still make the whole response fail those gates) — only the final persisted
    value is overridden here, deterministically, from the model's own accepted `name` (a slug of
    `name`, exactly what the schema now already asks the model to do by hand), with a numeric suffix
    appended only if that slug collides with an already-known key — collision-free by construction,
    never by hoping the model gets it right."""
    base_key = f"tree.node.{_slugify(name)}"
    if base_key not in known_name_keys:
        return base_key
    suffix = 2
    while f"{base_key}-{suffix}" in known_name_keys:
        suffix += 1
    return f"{base_key}-{suffix}"


def _resolve_affinity_for_members(members: "Sequence[str]",
                                  picks_by_sample: "Mapping[int, tuple[str, ...]]",
                                  affinity_by_sample: "Mapping[int, tuple[str, ...]]",
                                  ) -> "list[str] | None":
    """2026-09-06 real-call finding (`fortitude`, the first real run of a second tree): §6.3's own
    field description pairs `affinity[i]` with `affixIds[i]`, "in the same order" — but the vote
    (§7 gate 11, `resolve_set_vote_field`/`resolve_set_vote`) resolves `affixIds` per-MEMBER, from
    up to 3 independent samples, and returns the resolved set SORTED (`adapters.creatures.anchor.vote
    .resolve_set_vote`'s own `tuple(sorted(...))`) — never any one sample's own order, and not
    necessarily even the same LENGTH as sample 0's own pick. The pre-fix code reused sample 0's raw
    `affinity` array positionally, silently assuming the vote's result always matched sample 0's
    pick exactly. Real data proved this false at scale: `fortitude` failed gate 13 on exactly this
    mismatch on 19/40 nodes (47.5%) — not the rare edge case `might`'s own 2/40 total suggested.

    The correct per-member value is resolved the SAME way `affixIds` itself was: for each member of
    the FINAL voted set, majority-of-the-samples-that-actually-picked-this-member (their own
    `affinity` at that member's position in THEIR OWN `affixIds`), ties broken toward the lowest
    `sample_index` — the same tie-break convention `base_response = dict(out)` (sample 0) already
    embodies elsewhere in this function. Returns `None` if any member has no recorded affinity at
    all — should not happen once `resolve_set_vote`'s own 2-of-3 threshold holds (a member only
    enters the resolved set if at least 2 samples picked it, and a sample that picked it always
    carries a same-length `affinity` array by gate 7's own per-call contract), kept as a named
    defensive case the caller turns into an `escalated` outcome rather than an `IndexError`."""
    result: "list[str]" = []
    for member in members:
        votes: "list[tuple[int, str]]" = []
        for sample_index, ids in picks_by_sample.items():
            if member not in ids:
                continue
            values = affinity_by_sample.get(sample_index, ())
            pos = ids.index(member)
            if pos < len(values):
                votes.append((sample_index, values[pos]))
        if not votes:
            return None
        tally = Counter(v for _, v in votes)
        top_count = max(tally.values())
        winners = {v for v, c in tally.items() if c == top_count}
        votes.sort(key=lambda t: t[0])
        result.append(next(v for _, v in votes if v in winners))
    return result


def generate_node(subject: Subject, inputs: NodeGenerationInputs, *,
                  config: LlmCallerConfig | None = None,
                  known_name_keys: "Collection[str]" = (),
                  taken_names: "Collection[str]" = ()) -> NodeOutcome:
    """One node, start to finish: gate 2 (schema description audit, before any call), the base
    call, the two `affixIds` vote calls (§6.1), gate 11's vote resolution, and gate 13's
    persist-time re-gate over the base response with the VOTED `affixIds` substituted in.

    The persist-time re-gate is not a duplicate of the base call's own gate: the base call only
    ever validated its OWN `affixIds` pick, never the composite the vote may have resolved to
    (majority-per-member, `resolve_set_vote_field` — a member two of three samples picked is not
    necessarily the exact set any ONE of them returned), so that composite is checked here for the
    first time.

    `taken_names` (2026-09-11) is gate 21's generation-time half: every OTHER subject's committed
    name, corpus-wide. The gate checks the base call's draft against it on every heal attempt and
    the persist-time re-gate against the same set — so a draft named identically to any already-
    committed node anywhere in the corpus is re-prompted, never persisted.

    The node's own quota cell (2026-09-11, A2) is the exclusion contract for THIS call, per §4.2
    step 6 ("THIS is what goes into the schema's enum. Not the whole vocabulary"): a `none`-cell
    offers the form enum `("none",)` — "most nodes have none" becomes the schema's own word, not a
    brief exhortation — while a designated cell offers `(form, "none")`, the real rung plus the
    honest default the §6.3 field description already describes. `None` (a legacy record without a
    persisted cell, or a caller that does not resolve cells) keeps the full four-form ladder, never
    a fabricated allocation.
    """
    permitted_affix_ids = [o.affix_id for o in inputs.permitted_affixes]
    if not permitted_affix_ids:
        # P5.1 (passive-tree-repair): no resolvable affix for this branch — the blocker is
        # named (branch + cell), never papered over with the whole vocabulary.
        from .quota import UnsatisfiableCell as _UnsatisfiableCell
        raise _UnsatisfiableCell(
            f"branch={subject.branch!r} in cell {inputs.quota_cell!r}: no binder-resolvable "
            f"affix — held")
    # §4.2 step 6 for the exclusion axis, resolved HERE (where the cell lives) rather than in
    # `schema_for_call`: `cell_forms` is the pair the brief's "Your quota cell:" line and the
    # schema enum both name. A missing cell keeps the full ladder — additive, never widening a
    # cell that exists.
    cell_exclusion_form = getattr(inputs.quota_cell, "exclusion_form", None)
    cell_forms = ((str(cell_exclusion_form), "none")
                  if cell_exclusion_form and cell_exclusion_form != "none" else ("none",))
    schema = schema_for_call(permitted_affix_ids, list(inputs.permitted_properties),
                             exclusion_forms=cell_forms)

    schema_defects = audit_descriptions(schema)
    if schema_defects:
        raise ValueError(
            f"{subject.node_id}: response schema fails the description audit (§7 gate 2), before "
            f"any call: {[str(d) for d in schema_defects]}")

    gate = build_response_gate(
        schema=schema, permitted_affix_ids=permitted_affix_ids,
        permitted_property_keys=list(inputs.permitted_properties),
        anti_motif_tags=inputs.anti_motif_tags, affix_vocab=inputs.affix_vocab,
        property_vocabulary=inputs.property_vocabulary,
        tree_display_name=inputs.tree_display_name, motifs=inputs.motifs,
        taken_names=taken_names, permitted_exclusion_forms=cell_forms)

    picks_by_sample: "dict[int, tuple[str, ...]]" = {}
    affinity_by_sample: "dict[int, tuple[str, ...]]" = {}
    base_response: "dict[str, Any] | None" = None

    for sample_index in range(VOTE_SAMPLE_COUNT):
        sample_brief = brief_mod.render_brief(
            node_id=subject.node_id, sample_index=sample_index,
            tree_display_name=inputs.tree_display_name, tree_reading=inputs.tree_reading,
            branch=subject.branch, tier=subject.tier, node_class=subject.node_class,
            motifs=inputs.motifs, anti_motifs=inputs.anti_motifs,
            permitted_affixes=inputs.permitted_affixes,
            permitted_properties=inputs.permitted_properties, siblings=inputs.siblings,
            exclusion_form=cell_exclusion_form,
            avoid_terms=inputs.avoid_terms)
        out, soft = call_one_node_sample(
            node_id=subject.node_id, sample_index=sample_index, brief_text=sample_brief,
            schema=schema, gate=gate, config=config)

        if sample_index == 0:
            if out.get(BLOCKED_FIELD):
                # §6.3's own field description: the REASON lives in `blocked` itself ("set this
                # INSTEAD of the content fields ... and say why"), never in `rationale`.
                return NodeOutcome(subject.subject_id, "blocked", detail=str(out[BLOCKED_FIELD]))
            if _exhausted(soft) or not out:
                return NodeOutcome(subject.subject_id, "escalated",
                                   detail=f"base call exhausted the repair budget: {soft}")
            base_response = dict(out)

        # A sample that came back blocked or exhausted contributes an empty pick to the vote —
        # never crashes the whole node over one bad vote-only call (the base call already proved
        # this brief is answerable).
        if out.get(BLOCKED_FIELD) or _exhausted(soft):
            picks_by_sample[sample_index] = ()
            affinity_by_sample[sample_index] = ()
        else:
            picks_by_sample[sample_index] = tuple(out.get("affixIds") or ())
            affinity_by_sample[sample_index] = tuple(out.get("affinity") or ())

    assert base_response is not None  # sample 0 always returns above on blocked/escalated

    samples = [
        VoteSample(
            sample_index=i,
            rendered_order=tuple(order_for(subject.node_id, "affixIds", i, permitted_affix_ids)),
            chosen_value=canonical_set_key(picks_by_sample[i]),
        )
        for i in range(VOTE_SAMPLE_COUNT)
    ]
    try:
        for sample in samples:
            verify_permutation(subject.node_id, "affixIds", permitted_affix_ids, sample)
        vote = resolve_set_vote_field(subject.node_id, "affixIds", permitted_affix_ids, samples)
    except ValueError as ex:
        # §7 gate 11: "never silently the first option" — a claimed permutation that did not
        # reproduce, or a malformed vote call, escalates rather than defaulting to sample 0's pick.
        return NodeOutcome(subject.subject_id, "escalated", detail=str(ex))

    if vote.confidence == "unresolved":
        return NodeOutcome(subject.subject_id, "unresolved",
                           detail=f"{subject.node_id}/affixIds: 1-1-1 vote, no majority")

    final_affinity = _resolve_affinity_for_members(vote.values, picks_by_sample, affinity_by_sample)
    if final_affinity is None:
        return NodeOutcome(subject.subject_id, "escalated",
                           detail=f"{subject.node_id}/affinity: the voted affixIds set "
                                  f"{list(vote.values)!r} has a member no sample recorded an "
                                  f"affinity for — cannot resolve §6.3's paired field")

    final_response = dict(base_response)
    final_response["affixIds"] = list(vote.values)
    final_response["affinity"] = final_affinity

    persist_defects = gate(final_response)
    if persist_defects:
        return NodeOutcome(subject.subject_id, "escalated",
                           detail=f"failed the gate at persist time (§7 gate 13): {persist_defects}")

    # See `_derive_unique_name_key`'s own docstring: the model's own `nameKey` already passed gates
    # 7/13's FORMAT validation above (so a real defect elsewhere in the response is still caught) --
    # only the persisted VALUE is replaced here, deterministically derived from the model's own
    # accepted `name`, collision-free by construction against every already-known key.
    final_response["nameKey"] = _derive_unique_name_key(str(final_response["name"]), known_name_keys)

    record = build_node_record(subject.node_id, subject.node_key, subject.branch, subject.tier,
                               subject.node_class, final_response,
                               quota_cell=inputs.quota_cell,
                               prompt_version=brief_mod.PROMPT_VERSION)
    return NodeOutcome(subject.subject_id, "accepted", record=record)


@dataclass(frozen=True)
class LanguageStageResult:
    """One tree's whole run: every node's outcome, the seed document path (only written when at
    least one record exists), and the §7 gate 23 `RunReport`."""

    tree_id: str
    outcomes: "tuple[NodeOutcome, ...]"
    seed_path: "Path | None"
    report: "verdict.RunReport"


def run_language_stage(tree_plan: "plan_read.TreePlan",
                       inputs_for: "Callable[[Subject], NodeGenerationInputs]", *,
                       ledger_path: "Path | None" = None, seed_root: "Path | None" = None,
                       config: LlmCallerConfig | None = None,
                       unresolved_max_share_permille: "int | None" = None,
                       max_workers: int = 1,
                       supersede_stale: bool = False,
                       only_node_id: str = "") -> LanguageStageResult:
    """One tree, start to finish, idempotent. §7 gate 14: a subject already in the ledger is never
    regenerated — its ALREADY-ACCEPTED record is read back from the ledger and reused, so a forced
    rerun over unchanged inputs makes zero model calls and re-emits byte-identical bytes (the
    historical defect this whole task exists to catch: "the commander-effect generator rewrote all
    84 entries every run").

    **`supersede_stale` (2026-09-11, §8's provenance-supersede pass, J4's production path).** With
    it, a ledger row whose per-record `promptVersion` is absent (pre-provenance vintage) or
    different from the current `brief.PROMPT_VERSION` is planned for generation AND listed in
    `RunPlan.superseded`; its acceptance goes through `record_superseded` (prior row preserved
    under `supersededRecord`), never `record_accepted`'s raise-on-duplicate. A row already carrying
    the current vintage is left alone. This is what makes a prompt-version re-roll expressible
    through the real CLI at all — until now `record_superseded`'s only caller was a unit test.

    **Tree-wide sibling tracking (§6.2, closed 2026-09-06, widened same day).** This function, not
    `inputs_for`, owns "already-accepted siblings" — populating it needs `records`/`done`, data only
    this loop holds. Whatever `siblings` the caller's own `inputs_for(subject)` sets is REPLACED with
    the real, freshly-tracked tuple (via `dataclasses.replace`); a caller is never expected to track
    this itself. The pool is seeded from resumed (`plan.already_done`) records too, so a resumed run's
    first newly-generated node still sees whatever an EARLIER run already accepted, not just what this
    call accepts. **Tree-wide, not tier-scoped** — widened from the original per-tier design the same
    day a real run proved tier-scoping insufficient for its own stated "do not repeat" purpose (a
    real, independent three-way name collision across two different tiers) — capped to the most
    recent `_TREE_SIBLING_CAP` (12) accepted nodes, matching §6.2's own "k nearest siblings" language
    rather than passing an ever-growing, unbounded list as the tree fills in. Combined with
    `plan_run`'s own mechanism-before-magnitude ordering, a magnitude node normally has at least one
    real sibling to read by the time it renders, rather than always seeing brief.py's own "(none yet)"
    placeholder.

    **`max_workers` (owner request, 2026-09-06): batched parallelism, not blanket parallelism.**
    `plan.subjects` is already grouped into contiguous `(tier, node_class)` runs by `plan_run`'s own
    ordering — every subject in ONE such run shares the identical siblings snapshot (none of them can
    be a sibling of another in the SAME run; siblings only ever come from an EARLIER run), so they have
    no dependency on each other and are safe to generate concurrently. Runs themselves stay STRICTLY
    SEQUENTIAL — a later run must see everything an earlier one accepted, which is the whole point of
    §6.2's sibling pass. `max_workers=1` (the default) takes the single-subject-at-a-time path
    unconditionally, byte-for-byte the same code as before this parameter existed — every existing
    caller and test keeps its exact prior behavior with zero change. `max_workers>1` fans out within a
    run via a bounded `ThreadPoolExecutor`, mirroring `workflow.runner.MAX_WORKERS=4`'s own stated
    rationale ("one local model serves one request at a time; a small pool keeps it fed without
    stampeding it") — `workflow.runner.run_many` itself cannot be reused here, since it is built around
    a LangGraph `app.invoke()` interface this module never adopted. Outcomes are always reassembled in
    `plan.subjects`' own original order before being returned, regardless of which worker in a run
    finished first, so `result.outcomes` is deterministic either way.
    """
    from . import verdict  # local import — avoids a module-level cycle with `verdict.py`'s own
                            # re-export of A2's `targets` module, which nothing here otherwise needs

    if config is None:
        config = resolve_live_transport()   # the seed document's provenance stamps config.model
    done = read_ledger(ledger_path)
    plan = plan_run(tree_plan, ledger=done, supersede_stale=supersede_stale,
                    prompt_version=brief_mod.PROMPT_VERSION, only_node_id=only_node_id)

    # A superseded subject's PRIOR row still matters: the runner seeds siblings/known keys/taken
    # names from the whole ledger regardless, and its own name stays excluded from its own
    # taken-names gate (a re-roll may keep its own prior name). These ids are NOT replayed as
    # already-done records — they are re-generated through the supersede path below.
    superseded_ids = {s.subject_id for s in plan.superseded}
    # A DUPLICATE supersede (J9-B1(b)) must break the collision, not merely re-roll: see
    # `RunPlan.duplicate_ids`'s own note.
    duplicate_ids = set(plan.duplicate_ids)

    records: "dict[str, NodeSeedRecord]" = {}
    # 2026-09-06 real-call finding: TIER-scoped siblings (the original §6.2 shape) proved insufficient
    # for the "do not repeat" purpose the spec's own text names -- a real run independently generated
    # "Deep Rooting" for three DIFFERENT defensive-branch nodes across TWO different tiers (t2-n0,
    # t2-n1, t3-n1), which tier-scoping cannot see across. Widened to a tree-wide, most-recent-N list
    # (capped, not unbounded, matching §6.2's own "k nearest siblings" language) -- this is sound now
    # that the magnitude class-note fix (brief.py, same date) already decoupled "what a magnitude node
    # amplifies" from siblings entirely ("an EXISTING game stat... never a node this tree has or has
    # not generated"), so widening scope here only affects the dedup purpose, never the amplification
    # one, and cannot reintroduce the tier-1-3-have-no-mechanism-sibling problem the original ordering
    # fix solved.
    _TREE_SIBLING_CAP = 12
    tree_siblings: "list[brief_mod.SiblingSummary]" = []
    # 2026-09-06 real-call finding: even with an explicit "derive nameKey from your own name" schema
    # description (the fix for the SAME finding, wording alone did not hold up against a second real
    # run), the model kept falling back to an identical generic templated key. `known_name_keys`
    # tracks every nameKey already spoken for so `generate_node` can override the model's own choice
    # deterministically -- see `_derive_unique_name_key`'s own docstring for the full reasoning.
    #
    # 2026-09-06, second real-call finding (found the moment a SECOND tree's real generation ran):
    # `nameKey` is spec-mandated "deduplicated corpus-wide" (spec-tree-language.md's own field table,
    # row `name`/`nameKey`), not per-tree -- but this set used to be seeded only from
    # `plan.already_done`, this TREE's own already-accepted subjects (`plan_run` filters `done` down
    # to subject ids prefixed with THIS tree's own id). Two different trees running the same day
    # independently minted the identical key from an identical model-chosen name (e.g.
    # `tree.node.primal-surge` landed in `might`, `vigor` AND `ferocity`'s own committed seed
    # documents, unrelated runs, none aware of the others) -- 46 real cross-tree collisions confirmed
    # across the 12 trees committed so far, none of them EVER checked against each other because
    # `known_name_keys` never left this tree's own scope. Fixed by seeding from the WHOLE ledger
    # (`done`, already read in full above -- every tree's entries, not re-read here), never only this
    # tree's own filtered subset. `tree_siblings` (below) stays correctly TREE-scoped -- that is a
    # separate mechanism serving a separate purpose (giving the model local "don't repeat yourself"
    # context, spec's own §6.2), not the hard corpus-wide uniqueness constraint this set enforces.
    known_name_keys: "set[str]" = set()
    taken_names: "set[str]" = set()
    prior_names: "dict[str, str]" = {}
    for entry in done.values():
        # Attempt rows (`record: null`, written by `record_attempt`) carry no content to seed from.
        record = entry.get("record") or {}
        existing_name_key = record.get("nameKey")
        if existing_name_key:
            known_name_keys.add(existing_name_key)
        existing_name = record.get("name")
        if existing_name:
            # Gate 21's generation-time half (2026-09-11): every subject's committed name, corpus-
            # wide, feeds `generate_node`'s own taken-names gate — the same whole-ledger seeding
            # rule the `known_name_keys` fix above already established (a per-tree set never saw
            # the cross-tree collisions the metric measures). A subject's OWN prior name is kept
            # aside (below), never treated as somebody else's claim: the metric counts a name
            # colliding with a DIFFERENT node, so a superseded subject may keep its old name.
            taken_names.add(str(existing_name))
    def _replay_record(subject_id: str) -> NodeSeedRecord:
        """Rebuild one committed ledger row into a `NodeSeedRecord` — the additive replay path.

        Used for `plan.already_done` (this run's no-op subjects) AND for a superseded subject's
        PRIOR row. The prior row is kept in `records` until a replacement is accepted, so a FAILED
        re-roll leaves the tree complete rather than silently deleting an already-accepted node.

        Prefer the ledger's own persisted `quotaCell` when present (a record accepted after the
        2026-09-10 persistence wiring); absent on every older ledger row — `build_node_record` then
        leaves `quota_cell=None`, matching the additive load path. Same additive contract for
        provenance (2026-09-11): a ledger row that carries its own vintage keeps it; older rows leave
        it empty, and `build_seed_document`'s document-stamp logic reads an all-empty set as the
        legacy shape.
        """
        node = done[subject_id]["record"]
        return build_node_record(
            node["id"], node["nodeKey"], node["branch"], node["tier"], node["nodeClass"], {
                "affixIds": node["affixIds"], "affinity": node["affinity"],
                "exclusion": node["exclusion"], "name": node["name"], "nameKey": node["nameKey"],
                "flavor": node["flavor"], "rationale": node.get("rationale", ""),
                "quotaCell": node.get("quotaCell"),
                "promptVersion": node.get("promptVersion", ""),
            })

    for subject_id in plan.already_done:
        entry = done[subject_id]
        node = entry["record"]
        prior_names[subject_id] = str(node.get("name") or "")
        if subject_id in superseded_ids:
            continue
        record = _replay_record(subject_id)
        records[subject_id] = record
        tree_siblings.append(brief_mod.SiblingSummary(record.node_id, record.name, record.affix_ids))
        known_name_keys.add(record.name_key)
        taken_names.add(record.name)

    # §8's provenance-supersede replay: a superseded subject's PRIOR record is re-read for the
    # cross-cutting sets above (whole-ledger seeding), but its record is NOT reused as-is — it is
    # re-generated below like any other subject, with the prior row preserved on acceptance. The
    # only differences from a fresh subject: its own prior name is excluded from its own
    # taken-names gate (`prior_names`, used in `_generate_one`), and acceptance records via
    # `record_superseded` rather than `record_accepted`.
    #
    # The prior record is ALSO seeded into `records` here, deliberately: a superseded subject rides
    # `plan.subjects`, not `already_done`, so without this a re-roll that fails to resolve (gate 11's
    # "1-1-1 vote, no majority") would leave the subject absent from `records` — silently deleting an
    # already-accepted node from the seed document and shrinking the tree below its plan (a real
    # MechanismRamp shortfall, not a metric artefact). Seeding the prior keeps the tree complete; a
    # successful accept overwrites it in `_record_outcome`. Its name/nameKey are already in the
    # corpus-wide `taken_names`/`known_name_keys` (whole-ledger seeding above), so nothing is
    # re-added to those sets, and `tree_siblings` is intentionally NOT seeded from it — the re-roll's
    # own "don't repeat yourself" context stays exactly what it was before this fix.
    for subject in plan.superseded:
        prior_node = done[subject.subject_id]["record"]
        prior_names.setdefault(subject.subject_id, str(prior_node.get("name") or ""))
        records[subject.subject_id] = _replay_record(subject.subject_id)

    outcomes_by_subject: "dict[str, NodeOutcome]" = {}
    unresolved_count = 0

    def _generate_one(subject: Subject, siblings_here: "tuple[brief_mod.SiblingSummary, ...]",
                      known_keys_here: "frozenset[str]") -> NodeOutcome:
        base_inputs = inputs_for(subject)
        # A superseded subject re-generating against its own prior name: the metric counts a name
        # colliding with a DIFFERENT node, so the subject's own old name is never somebody else's
        # claim. Removing it here keeps the re-roll free to keep (or change) its own prior name.
        others_taken = taken_names - ({prior_names[subject.subject_id]}
                                      if subject.subject_id in prior_names
                                      and subject.subject_id not in duplicate_ids else set())
        return generate_node(subject, replace(base_inputs, siblings=siblings_here), config=config,
                             known_name_keys=known_keys_here, taken_names=others_taken)

    def _record_outcome(subject: Subject, outcome: NodeOutcome) -> None:
        nonlocal done, unresolved_count
        outcomes_by_subject[subject.subject_id] = outcome
        if outcome.outcome == "unresolved":
            unresolved_count += 1
        if outcome.outcome != "accepted":
            if subject.subject_id in duplicate_ids:
                # A DUPLICATE-driven supersede (J9-B1(b)) that fails to resolve must DROP its seeded
                # prior from THIS document: the prior name/key is the very thing colliding, so
                # keeping it would ship the duplicate anyway. The ledger row itself is untouched
                # (`record_attempt` never overwrites an accepted row), so nothing is lost — the node
                # is simply owed on a later pass rather than shipped twice.
                records.pop(subject.subject_id, None)
            # Persist the attempt (owner request, 2026-09-11): an unresolved/escalated/blocked
            # subject leaves a real ledger row (`record: null`) so the corpus can name which nodes
            # are still owed and how many times each has failed. `record_attempt` never overwrites
            # an accepted row, so a superseded subject's failed re-roll keeps its prior record.
            done = record_attempt(done, subject.subject_id, outcome.outcome, outcome.detail or "")
            return
        if outcome.record is not None:
            record = outcome.record
            # Same-batch race closure (2026-09-11 real-call finding, `might` with `--workers 4`).
            # The generation-time gates (`_derive_unique_name_key`, gate 21's `name_collision`) run
            # against a snapshot taken BEFORE a parallel batch starts, so two subjects in the SAME
            # batch can independently pick the identical name/nameKey and only collide here, at
            # record time — where `build_seed_document`'s own `assert_no_duplicate_name_keys` used to
            # refuse the WHOLE tree (a real run lost all 35 accepted nodes to one such pair). These
            # sets are the live, authoritative corpus state at this point (every accept above, plus
            # whole-ledger seeding), so resolving here is collision-free by construction regardless
            # of worker count — the guarantee the sequential path already got by retaking the
            # snapshot per subject.
            #
            # A superseded subject's OWN prior key/name is excluded from the collision check, exactly
            # as `_generate_one` excludes its own prior name from the taken-names gate: re-rolling
            # and KEEPING one's own identity is legal, and must not be treated as somebody else's
            # claim (nor silently suffixed into a different key).
            prior_entry = (done.get(subject.subject_id) or {}).get("record") or {}
            own_prior_key = str(prior_entry.get("nameKey") or "")
            own_prior_name = str(prior_entry.get("name") or "")
            keep_own_identity = subject.subject_id not in duplicate_ids
            other_keys = known_name_keys - (
                {own_prior_key} if keep_own_identity and own_prior_key else set())
            other_names = taken_names - (
                {own_prior_name} if keep_own_identity and own_prior_name else set())
            if record.name_key in other_keys:
                record = replace(record, name_key=_derive_unique_name_key(record.name, other_keys))
                outcome = replace(outcome, record=record)
                outcomes_by_subject[subject.subject_id] = outcome
            # Gate 21's contract is "re-prompted, never persisted": an exact name another node
            # already holds is NOT renamed out from under the model's answer. The sequential path
            # re-prompts via the generation-time gate; here the re-prompt already happened and the
            # race still lost, so the honest, resumable outcome is `unresolved` — the subject stays
            # out of the seed document this run and a later pass re-rolls it (never a persisted
            # collision, never a whole-tree refusal).
            if record.name in other_names:
                unresolved_count += 1
                if subject.subject_id in duplicate_ids:
                    # Same rule as the non-accepted branch above: a collided duplicate leaves the
                    # document rather than riding in on its prior row.
                    records.pop(subject.subject_id, None)
                collision_detail = (
                    f"{subject.node_id}: name {record.name!r} is already taken by a different node "
                    "in this same parallel batch — re-roll on the next pass (gate 21: a colliding "
                    "name is re-prompted, never persisted)")
                outcomes_by_subject[subject.subject_id] = NodeOutcome(
                    subject.subject_id, "unresolved", detail=collision_detail)
                # This branch used to return before ``record_attempt``. The in-memory result was
                # truthful, but a killed process lost the attempt row entirely; BCU2.12's copied
                # ledger consequently had 162 fewer rows than the 352 reached tree plans required.
                # Persist the failed attempt exactly like every earlier non-accepted branch. It stays
                # ``record: null`` and is therefore still scheduled on resume, while its count and
                # named cause remain visible.
                done = record_attempt(done, subject.subject_id, "unresolved", collision_detail)
                return
            tree_siblings.append(brief_mod.SiblingSummary(
                record.node_id, record.name, record.affix_ids))
            known_name_keys.add(record.name_key)
            taken_names.add(record.name)
            if subject.subject_id in superseded_ids:
                # §8's deliberate path: this subject was PLANNED for re-roll this run, so the
                # raise-on-duplicate default must not fire — the prior row is preserved under
                # `supersededRecord`, never silently discarded. Everything else (sibling list,
                # known keys, taken names, the records map) updates exactly as a fresh accept.
                done = record_superseded(done, subject.subject_id, record)
            else:
                done = record_accepted(done, subject.subject_id, record)
            records[subject.subject_id] = record

    for _key, group_iter in itertools.groupby(plan.subjects, key=lambda s: (s.tier, s.node_class)):
        run = list(group_iter)

        if max_workers <= 1 or len(run) <= 1:
            # Sequential: nothing stops a subject from seeing what the PREVIOUS subject in this SAME
            # batch just produced -- there is no real concurrency here, so the snapshot is retaken
            # fresh before every single subject (real-call finding, 2026-09-06: an earlier version of
            # this fix took the snapshot once per BATCH even on the sequential path, which meant two
            # same-batch subjects with max_workers=1 could still both derive the identical nameKey
            # slug and collide -- caught by testing the fix against `might`'s own real 4-per-tier
            # magnitude batches, not assumed correct).
            for subject in run:
                siblings_here = tuple(tree_siblings[-_TREE_SIBLING_CAP:])
                known_keys_here = frozenset(known_name_keys)
                _record_outcome(subject, _generate_one(subject, siblings_here, known_keys_here))
            continue

        # Parallel: every subject in this run shares ONE siblings/known-keys snapshot, taken before
        # any of them starts -- none can see (or collide-check against) another accepted in the SAME
        # run, only what an EARLIER run already contributed. The most recent _TREE_SIBLING_CAP
        # accepted nodes, tree-wide, never just this subject's own tier. Two subjects in the SAME
        # parallel batch independently choosing the identical name is a real, narrower remaining edge
        # case `assert_no_duplicate_name_keys` would still catch at emit time, just not pre-empt --
        # the same trade-off already accepted for siblings under real concurrency.
        siblings_here = tuple(tree_siblings[-_TREE_SIBLING_CAP:])
        known_keys_here = frozenset(known_name_keys)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_by_subject = {
                pool.submit(_generate_one, subject, siblings_here, known_keys_here): subject for subject in run
            }
            results: "dict[str, NodeOutcome]" = {}
            for future in future_by_subject:
                subject = future_by_subject[future]
                results[subject.subject_id] = future.result()
        # Applied in the run's own original order, never completion order, so tier_siblings grows
        # deterministically regardless of which worker finished first.
        for subject in run:
            _record_outcome(subject, results[subject.subject_id])

    outcomes = [outcomes_by_subject[s.subject_id] for s in plan.subjects]

    if plan.subjects:
        write_ledger(done, ledger_path)

    seed_path = None
    if records:
        sorted_records = sorted(records.values(), key=lambda r: r.node_id)
        # `planHash` is the per-tree plan's own content hash — the SAME value the manifest names in
        # `trees[].sha256` (`plan.emit.tree_content_hash`, sha256 over that plan's canonical bytes).
        # The B1 plan document itself carries no `sha256` key (it lives only in the manifest's index
        # row), so the earlier `tree_plan.raw.get("sha256", "")` read stamped EVERY seed document
        # with an empty string — a provenance field that named nothing. Deriving it here from the
        # plan the run actually read is the one value that is both always present and verifiable
        # against the committed manifest.
        doc = build_seed_document(
            tree_plan.tree_id, sorted_records, plan_hash=tree_content_hash(tree_plan.raw),
            prompt_version=brief_mod.PROMPT_VERSION, model=config.model)
        seed_path = write_seed_document(doc, seed_root)

    report = verdict.RunReport()
    total = len(plan.subjects) + len(plan.already_done)
    unresolved_share_permille = (unresolved_count * 1000) // total if total else 0
    if unresolved_max_share_permille is not None:
        report.record(
            verdict.UNRESOLVED_COUNT_METRIC, ran=True,
            cleared=unresolved_share_permille <= unresolved_max_share_permille,
            detail=f"{unresolved_count}/{total} unresolved ({unresolved_share_permille}‰)")

    return LanguageStageResult(tree_id=tree_plan.tree_id, outcomes=tuple(outcomes),
                              seed_path=seed_path, report=report)
