"""seedsmith.adapters.trees.species.generate_tree — the per-species orchestration caller (task J8's
own stated remainder / task J9's real prerequisite, spec-species-tree.md whole-module). Sequences
every REAL, tested, independently-provable piece this program built for species trees into ONE
species' own committed output:

    favour-fit (§3.1 step 3) -> species_tree_spec/build_plan (§1/§4) -> quota_for_plan ->
    run_language_stage (the shared, resumable H1-H8 node-generation loop) ->
    mark_species_unique_nodes (§5.3 rule 3) -> codex-summary (§6)

**A real, stated design decision, not an invented one**: the 40 generated NODES are written to the
SAME shared `gk-data/packs/fusion/data/seed/passive-tree/nodes/<speciesId>.json` every other tree category already uses
(`nodegen.emit.write_seed_document`, unchanged, category-agnostic) — species trees reuse the node
RECORD verbatim (§1's own table), and reusing its STORAGE location too needs no new code at all.
`gk-data/packs/fusion/data/seed/passive-tree/species/<speciesId>.json` (spec's own Project structure table) is this
module's own NEW, small, species-SPECIFIC supplement — `codexSummary`, the resolved favour lock, and
the marked namespace-affix node ids — never a second copy of the 40 nodes already committed above.

**What this module does NOT do, by design, matching this program's own "a run is not authoring"
split (already used for J7's affix corpus and J9 itself)**: it never decides how many species to
run, never loops over a roster, and never schedules the real 105,840-call production pass — it is
the unit of work J9's own real run would call once per species, proven correct for ONE call here
rather than assumed correct at 840x scale.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ....pipeline.llm_caller import LlmCallerConfig, resolve_live_transport
from ....workflow.runner import MAX_WORKERS
from ...trees.plan.emit import REPO_ROOT as PLAN_REPO_ROOT
from .generate_codex import resolve_codex_summaries
from .generate_favour_fit import resolve_favour_fit
from .plan import FavourCell, mark_species_unique_nodes
from .roster import SpeciesAnchor

REPO_ROOT = PLAN_REPO_ROOT


def species_metadata_path(species_id: str, seed_root: "Path | None" = None) -> Path:
    root = seed_root or (REPO_ROOT / "data" / "seed")
    return root / "passive-tree" / "species" / f"{species_id}.json"


def species_metadata_document(species_id: str, resolved_cell: FavourCell,
                              marked_node_ids: "Sequence[str]", *,
                              codex_summary: "str | None",
                              codex_unresolved_reason: "str | None" = None,
                              codex_attempts: int = 1) -> dict:
    """The species-metadata document `gk-data/packs/fusion/data/seed/passive-tree/species/<speciesId>.json` holds.

    Defined ONCE, here, because two callers write it: `run_species_tree` (the resolved sentence it
    just voted) and the J9 batch driver's bounded retry (`_j9_batch_run.py`, which re-draws the
    vote for a species whose first draw did not resolve -- task J9-B2). A second hand-built copy of
    this shape in the driver would be free to drift from this one, which is exactly the defect this
    helper exists to prevent.

    `codex_summary=None` is a RECORDED FAILURE, never a silent gap: `codexUnresolvedReason` then
    names why (the vote's own reason, verbatim) and `codexAttempts` carries the bound that was
    reached. A caller may not write a failure record that names nothing -- refused, because an
    unnamed gap is the state this field exists to make impossible.
    """
    if codex_summary is None and not codex_unresolved_reason:
        raise SpeciesTreeRunError(
            f"{species_id}: a species metadata document with no codexSummary must name its failure "
            "(codexUnresolvedReason); refused rather than written as a silent gap")
    document = {
        "schemaVersion": 1,
        "speciesId": species_id,
        "mechanicalFavour": {"aptitude": resolved_cell.aptitude,
                             "element": resolved_cell.element,
                             "status": resolved_cell.status},
        "codexSummary": codex_summary,
        "codexAttempts": codex_attempts,
        "speciesUniqueNodeIds": sorted(marked_node_ids),
    }
    if codex_summary is None:
        document["codexUnresolvedReason"] = codex_unresolved_reason
    return document


def write_species_metadata(species_id: str, document: dict,
                           seed_root: "Path | None" = None) -> Path:
    """Write one species-metadata document to its real seed path, creating the directory if needed.
    Returns the path written. The ONE writer, shared by `run_species_tree` and the batch driver."""
    path = species_metadata_path(species_id, seed_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class SpeciesTreeRunError(ValueError):
    """A species tree run could not proceed to the next stage — refused, never silently skipped."""


class SpeciesTreeGateFailure(SpeciesTreeRunError):
    """A language-stage hard gate failed; the species must not spend later stages."""


def read_species_metadata(species_id: str, seed_root: "Path | None" = None) -> "dict | None":
    """Read one previously persisted species document for resume, or ``None`` when absent.

    A resolved codex sentence and its mechanical favour are completed model work. Re-running either
    stage on every resumed species spends calls and can replace a committed answer with a different
    stochastic one. A named failure record is also reusable for its mechanical favour, but its codex
    stage remains owed. Corrupt/ambiguous persisted state is refused by name, never treated as a
    fresh species.
    """
    path = species_metadata_path(species_id, seed_root)
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as ex:
        raise SpeciesTreeRunError(f"{path}: cannot read persisted species metadata: {ex}") from ex
    if not isinstance(document, dict) or document.get("schemaVersion") != 1:
        raise SpeciesTreeRunError(f"{path}: persisted species metadata has no schemaVersion=1 object")
    if document.get("speciesId") != species_id:
        raise SpeciesTreeRunError(
            f"{path}: persisted speciesId {document.get('speciesId')!r} does not match {species_id!r}")
    favour = document.get("mechanicalFavour")
    if not isinstance(favour, dict) or any(
            not isinstance(favour.get(field), str) or not favour[field].strip()
            for field in ("aptitude", "element", "status")):
        raise SpeciesTreeRunError(f"{path}: persisted mechanicalFavour is missing or malformed")
    summary = document.get("codexSummary")
    reason = document.get("codexUnresolvedReason")
    if summary is not None and (not isinstance(summary, str) or not summary.strip()):
        raise SpeciesTreeRunError(f"{path}: persisted codexSummary must be a non-empty string or null")
    if summary is None and (not isinstance(reason, str) or not reason.strip()):
        raise SpeciesTreeRunError(
            f"{path}: a persisted null codexSummary must name codexUnresolvedReason")
    marked = document.get("speciesUniqueNodeIds")
    if not isinstance(marked, list) or any(not isinstance(node_id, str) or not node_id for node_id in marked):
        raise SpeciesTreeRunError(f"{path}: speciesUniqueNodeIds must be a list of node ids")
    attempts = document.get("codexAttempts")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        raise SpeciesTreeRunError(f"{path}: codexAttempts must be a positive integer")
    return document


@dataclass(frozen=True)
class SpeciesTreeRunResult:
    species_id: str
    resolved_cell: "FavourCell | None"
    favour_unresolved_reason: "str | None"
    node_key_refused_reason: "str | None"
    nodes_seed_path: "Path | None"
    outcome_counts: "Mapping[str, int]"
    marked_node_ids: "frozenset[str]"
    codex_summary: "str | None"
    codex_unresolved_reason: "str | None"
    metadata_path: "Path | None"


def run_species_tree(
    species_id: str, anchor: SpeciesAnchor, ordinal: int,
    offered_cell: FavourCell, alternates: "Sequence[FavourCell]", *,
    targets: object, tuning: dict, speciesUniqueAffixMin: "int | None" = None,
    ledger_path: "Path | None" = None, seed_root: "Path | None" = None,
    call: "Callable[..., str] | None" = None, config: LlmCallerConfig | None = None,
    workers: int = MAX_WORKERS,
) -> SpeciesTreeRunResult:
    """One species, start to finish. `offered_cell`/`alternates` are `assign_favour_cells`'s own
    per-species output (task J5) — this function does not run the corpus-wide quota itself, since
    that is a one-time, whole-roster computation a caller runs ONCE and passes every species' own
    slice of, never re-derived per species.

    Refuses to proceed past an unresolved favour (never generates a tree for a lock nothing
    confirmed). An unresolved codex summary writes NO species metadata file either -- a species file
    with no Codex sentence would violate spec-species-tree.md's own `Never` rule ("ship a species
    without a Codex sentence"), so this function reports the reason and leaves the file absent. The
    J9 batch driver is what turns that reported reason into a NAMED, BOUNDED failure record after its
    own bounded retry (`_j9_batch_run.py`, task J9-B2): this function never ships a summary-less
    species, and the driver never leaves one unnamed. Normal stage outcomes are reported as
    `SpeciesTreeRunResult` fields. A language-stage hard-gate failure is the one deliberate exception:
    it must stop the batch before codex spends more calls, while the language stage's durable ledger
    keeps the failed species resumable.

    **Fail-closed on the IP avoid-list (ip-censor IC-3/IC-4).** Read ONCE, at the top, before the
    favour fit and long before the plan, quota and vocabulary builds: a missing or unreadable
    registry raises `SpeciesTreeRunError` rather than degrading to an empty list. Two reasons for the
    direction, and the second is the one that matters. (1) It is a precondition failure, not an
    answer-side IP check -- nothing is re-asked and no answer is rejected, so IC-3's "the scan never
    blocks generation" is untouched; the generic tree caller already refuses the same way
    (`report/cli.py:2318-2327`). (2) The alternative is the exact failure this program exists to
    prevent: 40 node briefs per species, each carrying NO avoid line, reading to the model and to a
    reviewer as "there is nothing to avoid". Reading it first also means a refused run has built no
    plan and written nothing.
    """
    from ...trees.nodegen import emit as emit_mod
    from ...trees.nodegen import quota as quota_mod
    from ...trees.nodegen import run as run_mod
    from ...trees.nodegen import vocab as vocab_mod
    from ...trees.nodegen import plan_read
    from ...trees.plan import emit as plan_emit
    from ....briefkit.avoid_list import load_avoid_terms

    try:
        avoid_terms = load_avoid_terms()
    except (OSError, ValueError) as ex:
        raise SpeciesTreeRunError(
            f"{species_id}: the IP avoid-list registry could not be read, so every node brief this "
            f"run would send would carry no avoid line and read as 'nothing to avoid' — refused "
            f"instead: {ex}") from ex

    if config is None:
        config = resolve_live_transport()   # the seed document's provenance stamps config.model
    provenance_base = {"pipeline": "species-tree", "model": config.model}

    persisted_metadata = read_species_metadata(species_id, seed_root)
    if persisted_metadata is not None:
        favour = persisted_metadata["mechanicalFavour"]
        resolved_cell = FavourCell(favour["aptitude"], favour["element"], favour["status"])
    else:
        fresh_favour, unresolved_favour, _ = resolve_favour_fit(
            [(species_id, anchor, offered_cell, alternates)], provenance_base=provenance_base,
            call=call, config=config, workers=workers)
        if species_id in unresolved_favour:
            return SpeciesTreeRunResult(
                species_id=species_id, resolved_cell=None,
                favour_unresolved_reason=unresolved_favour[species_id]["reason"],
                node_key_refused_reason=None,
                nodes_seed_path=None, outcome_counts={}, marked_node_ids=frozenset(),
                codex_summary=None, codex_unresolved_reason=None, metadata_path=None)
        resolved_cell = fresh_favour[species_id]["cell"]

    spec = plan_emit.species_tree_spec(
        species_id, ordinal,
        (resolved_cell.aptitude, resolved_cell.element, resolved_cell.status), seed_root)
    plan_dict = plan_emit.build_plan(spec, tuning)
    tree_plan = plan_read.load_from_dict(plan_dict, source_label=f"species:{species_id}")

    cells = quota_mod.quota_for_plan(
        tree_plan, targets, category="species",
        forced_element=resolved_cell.element, forced_status=resolved_cell.status)
    affix_vocab = vocab_mod.build()

    def inputs_for(subject: "run_mod.Subject") -> "run_mod.NodeGenerationInputs":
        cell = cells[subject.node_id]
        permitted_affixes = affix_vocab.permitted_for_branch(subject.branch)
        return run_mod.NodeGenerationInputs(
            tree_display_name=species_id, tree_reading=species_id,
            motifs=(), anti_motifs=(), anti_motif_tags=(),
            permitted_affixes=permitted_affixes,
            permitted_properties=sorted(tree_plan.property_vocabulary),
            property_vocabulary=tree_plan.property_vocabulary, affix_vocab=affix_vocab,
            # 2026-09-11 (A2): a species node's own quota cell travels with it, same as the
            # generic CLI's inputs_for — `generate_node` narrows the exclusion enum to this cell.
            quota_cell=cell,
            # ip-censor IC-3/IC-4: the SAME shared `briefkit.avoid_list` reading the generic tree
            # path already used (T16), resolved once above. Without it every species node brief —
            # 40 per species — was generated with no IP protection at all, because this caller
            # builds its own `NodeGenerationInputs` and the species file carried no avoid wiring
            # whatsoever. `NodeGenerationInputs.avoid_terms` defaults empty, so the generic path is
            # unchanged by this line; `render_brief` already renders it as its own line.
            avoid_terms=avoid_terms)

    # Real-call finding (2026-09-07, `AbyssSwordStar`'s own first live proof-of-concept run): the
    # model independently generated two DIFFERENT nodes both named "Abyssal Shell", and
    # `build_seed_document`'s own `assert_no_duplicate_name_keys` correctly refused rather than
    # silently renaming one out from under the model's answer -- the exact same defect class
    # `_cmd_trees_generate`'s own docstring already names for `might`'s real run ("two DIFFERENT
    # accepted nodes collided on nameKey"), caught there by the identical try/except this mirrors.
    # The ledger itself is not at risk either way: `run_language_stage` writes it before ever
    # building the seed document, so every already-accepted node from this attempt stays safely
    # recorded regardless of this refusal. This function's own first draft had no such guard and
    # crashed the caller outright -- fixed to report it as a structured outcome instead, matching
    # every other "needs another pass, never a crash" result this function already returns.
    try:
        language_result = run_mod.run_language_stage(
            tree_plan, inputs_for, ledger_path=ledger_path, seed_root=seed_root, config=config,
            unresolved_max_share_permille=getattr(targets, "unresolved_count_max_share_permille", None),
            max_workers=workers)
    except emit_mod.NodeKeyRefused as ex:
        return SpeciesTreeRunResult(
            species_id=species_id, resolved_cell=resolved_cell, favour_unresolved_reason=None,
            node_key_refused_reason=str(ex),
            nodes_seed_path=None, outcome_counts={}, marked_node_ids=frozenset(),
            codex_summary=None, codex_unresolved_reason=None, metadata_path=None)

    # `run_language_stage` records the hard-gate result but the species orchestration caller used to
    # ignore it. That let a run with an unresolved-rate FAIL proceed into codex and the next species,
    # despite the spec's explicit "above 50‰ it stops the run" rule. The ledger and node document are
    # already durable at this point; refusing here keeps the owed work resumable without spending a
    # codex vote on a species that has failed its one hard gate.
    if language_result.report.verdict.value != "pass":
        gate_detail = "; ".join(
            f"{outcome.metric}={outcome.verdict.value}: {outcome.detail}"
            for outcome in language_result.report.outcomes
            if outcome.verdict.value != "pass"
        ) or "no passing gate outcome was recorded"
        raise SpeciesTreeGateFailure(
            f"{species_id}: language-stage hard gate {language_result.report.verdict.value} "
            f"({gate_detail})")

    # The species mark set is a property of the WHOLE emitted tree, not only the subjects this pass
    # happened to generate. Read the document `run_language_stage` just emitted: it already merges
    # replayed ledger records with new accepts and is therefore the only complete, already-persisted
    # view. The captured BCU2.12 run proved the old outcomes-only calculation was wrong on every
    # resumed species (for example AbyssSwordStar resumed with zero new outcomes and zero marks).
    if language_result.seed_path is None:
        accepted_records: "list[dict]" = []
    else:
        try:
            emitted = json.loads(language_result.seed_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as ex:
            raise SpeciesTreeRunError(
                f"{language_result.seed_path}: cannot read the emitted species tree: {ex}") from ex
        accepted_records = emitted.get("nodes") or []
        if not isinstance(accepted_records, list) or any(
                not isinstance(record, dict) for record in accepted_records):
            raise SpeciesTreeRunError(
                f"{language_result.seed_path}: emitted species tree has no valid nodes list")
    k = speciesUniqueAffixMin if speciesUniqueAffixMin is not None else getattr(
        targets, "species_unique_affix_min", 8)
    marked = mark_species_unique_nodes(accepted_records, k)

    outcome_counts: "dict[str, int]" = {}
    for o in language_result.outcomes:
        outcome_counts[o.outcome] = outcome_counts.get(o.outcome, 0) + 1

    persisted_summary = (persisted_metadata or {}).get("codexSummary")
    metadata_path = None
    codex_unresolved_reason = None
    if isinstance(persisted_summary, str) and persisted_summary.strip():
        if not accepted_records:
            raise SpeciesTreeRunError(
                f"{species_id}: resolved codex metadata exists but the ledger produced no accepted "
                "node to accompany it; refusing to replay the supplement over an empty tree")
        codex_summary = persisted_summary
        persisted_marked = frozenset(persisted_metadata["speciesUniqueNodeIds"])
        metadata_path = species_metadata_path(species_id, seed_root)
        if marked != persisted_marked:
            metadata_path = write_species_metadata(species_id, species_metadata_document(
                species_id, resolved_cell, sorted(marked), codex_summary=codex_summary,
                codex_attempts=int(persisted_metadata["codexAttempts"])), seed_root=seed_root)
    else:
        fresh_codex, unresolved_codex, _ = resolve_codex_summaries(
            [(species_id, anchor, resolved_cell)], provenance_base=provenance_base,
            call=call, config=config, workers=workers)
        codex_summary = (fresh_codex[species_id]["codexSummary"]
                         if species_id in fresh_codex else None)
        codex_unresolved_reason = unresolved_codex.get(species_id, {}).get("reason")
        if codex_summary is not None:
            metadata_path = write_species_metadata(species_id, species_metadata_document(
                species_id, resolved_cell, sorted(marked), codex_summary=codex_summary,
                codex_attempts=1), seed_root=seed_root)

    return SpeciesTreeRunResult(
        species_id=species_id, resolved_cell=resolved_cell, favour_unresolved_reason=None,
        node_key_refused_reason=None,
        nodes_seed_path=language_result.seed_path, outcome_counts=outcome_counts,
        marked_node_ids=marked, codex_summary=codex_summary,
        codex_unresolved_reason=codex_unresolved_reason, metadata_path=metadata_path)
