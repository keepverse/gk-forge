"""species-tree batch driver (task J9 / BCU2.12) — run `run_species_tree` over a roster slice.

This is the harness the 2026-09-07 J9 de-risking pass wrote and the 2026-09-21 bounded proof ran; it
is committed here as a real tool rather than left ad-hoc, because the full run's launcher
(`.claude/cmdc-agents/scripts/bcu212-full-run.ps1`) drives exactly this file. The filename keeps its
historical underscore so that launcher and the runbook's Verify line stay valid.

    python gk-forge/tools/seedsmith/_j9_batch_run.py --check          # plan only, ZERO model calls
    python gk-forge/tools/seedsmith/_j9_batch_run.py --count 2        # run the first 2 roster species
    python gk-forge/tools/seedsmith/_j9_batch_run.py 2                # the same count, positionally (the
                                                             # full-run launcher's own call shape)
    python gk-forge/tools/seedsmith/_j9_batch_run.py                  # the whole roster

Real output goes to the real paths (`gk-data/packs/fusion/data/seed/passive-tree/nodes/<speciesId>.json`,
`gk-data/packs/fusion/data/seed/passive-tree/species/<speciesId>.json`); per-species results go to
`tools/seedsmith/_j9_batch_run_results.json`. `assign_favour_cells` is called ONCE over the FULL
roster (matching what the production pass computes), so a bounded run's committed content stays valid
input to a later, larger continuation — nothing is wasted or redone.

**One invocation converges (task J9-B2, 2026-09-21).** The codex vote is STOCHASTIC — BCU2.12's
bounded re-proof measured roughly one resolve per draw over two species and four draws, and one
invocation therefore did not finish the corpus: a species unlucky on its single draw ended with no
`species/<speciesId>.json` at all, indistinguishable from a species the model refused. This driver now
re-draws the 3-sample vote for ONLY the species whose vote did not resolve, up to
`--codex-attempts` total draws (`generate_codex.DEFAULT_CODEX_VOTE_ATTEMPTS` states the bound and why
that number), and when the bound is reached it still writes the species file — carrying the vote's own
reason and the bound it reached, a NAMED failure. So every species whose tree completed leaves either a
resolved `codexSummary` or a named failure record, never a silent gap, and the per-draw resolve counts
are printed at the end of the run as a reading (recorded in `tasks/reports/`, never asserted).

Resume safety is the SHARED ledger (`run_language_stage` never regenerates a subject already recorded
in `gk-data/packs/fusion/data/seed/passive-tree/_runs/tree-language.ledger.json`), not a flag here.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from seedsmith.adapters.trees.nodegen import plan_read as nodegen_plan_read
from seedsmith.adapters.trees.nodegen import run as nodegen_run
from seedsmith.adapters.trees.nodegen import tuning as nodegen_tuning
from seedsmith.adapters.trees.plan import emit as plan_emit
from seedsmith.adapters.trees.plan import tuning as plan_tuning
from seedsmith.adapters.trees.species.generate_codex import (
    DEFAULT_CODEX_VOTE_ATTEMPTS, resolve_codex_summaries)
from seedsmith.adapters.trees.species.generate_tree import (
    SpeciesTreeGateFailure, run_species_tree, species_metadata_document, write_species_metadata)
from seedsmith.adapters.trees.species.plan import assign_favour_cells
from seedsmith.adapters.trees.species.roster import load_roster
from seedsmith.adapters.trees.targets import load as load_species_targets
from seedsmith.pipeline.llm_caller import DEFAULT_CONFIG

RESULTS_PATH = Path(__file__).resolve().parent / "_j9_batch_run_results.json"

#: One local model serves one request at a time. The captured BCU2.12 log proves that submitting
#: four requests concurrently is not safe for this endpoint: its HTTP burst is four simultaneous
#: failures, followed by repeated 400/500 give-ups. Keep this driver serial; a different endpoint
#: with a measured concurrency contract can own a different value at its own call site.
WORKERS = 1


def _write_results(results: "list[dict]", out_path: Path) -> Path:
    """Atomically checkpoint the completed species prefix after every terminal species row.

    The interrupted BCU2.12 run reached species 361 but the old end-only write left no result file at
    all, so the manager could see only a stale pre-run report. A same-directory temp replace keeps
    the checkpoint parseable even when the next process dies mid-write.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(dir=str(out_path.parent), prefix=f"{out_path.name}.",
                                         suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_name, out_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return out_path


def _species_plan(species_id: str, ordinal: int, cell, *, tuning: dict):
    """The same plan `run_species_tree` builds, for read-only inspection (no model call)."""
    spec = plan_emit.species_tree_spec(
        species_id, ordinal, (cell.aptitude, cell.element, cell.status))
    return nodegen_plan_read.load_from_dict(
        plan_emit.build_plan(spec, tuning), source_label=f"species:{species_id}")


def check(*, count: int) -> dict:
    """Model-free plan: what `--count` would run, and what the ledger already holds."""
    roster = load_roster()
    targets = load_species_targets()
    assignments = assign_favour_cells(roster.species_ids, targets)
    tuning = plan_tuning.load()
    ledger = nodegen_run.read_ledger(nodegen_run.DEFAULT_LEDGER)

    summary: "dict" = {
        "rosterSpecies": len(roster.species_ids),
        "ledgerDoneRows": len(ledger),
        "requested": count,
        "planned": [],
    }
    for ordinal, species_id in enumerate(roster.species_ids[:count]):
        plan = _species_plan(species_id, ordinal, assignments[species_id].cell, tuning=tuning)
        run_plan = nodegen_run.plan_run(plan, ledger=ledger)
        summary["planned"].append({
            "speciesId": species_id,
            "owed": len(run_plan.subjects) - len(run_plan.superseded),
            "alreadyDone": len(run_plan.already_done),
            "superseded": len(run_plan.superseded),
            "duplicateSuperseded": len(run_plan.duplicate_ids),
        })
    return summary


def resolve_codex_with_retry(
    species_id: str, anchor, resolved_cell, *, first_reason: str,
    total_attempts: int = DEFAULT_CODEX_VOTE_ATTEMPTS,
    call=None, config=DEFAULT_CONFIG, workers: int = WORKERS,
) -> "tuple[str | None, str | None, int]":
    """Re-draw ONE species' codex vote until it resolves or the bound is reached.

    `first_reason` is the reason the CALLER's own first draw failed — `run_species_tree` makes draw 1
    as part of its own stage sequence, so this function only makes draws 2..`total_attempts`, and the
    `draws` it returns INCLUDES that first draw. With `total_attempts=1` no model call is made at all
    and `first_reason` is returned unchanged, so the bound is a real total, not an offset.

    Returns `(codex_summary, unresolved_reason, draws)`: `(str, None, n)` when draw `n` resolved,
    `(None, reason, total_attempts)` when the bound was reached and the last draw's own reason stands.
    Only the species passed in is ever re-drawn — the driver calls this once per unresolved species,
    never over the whole roster.

    ⛔ An unbounded loop here would hide a bad brief behind retries: the bound is the caller's stated
    policy (`--codex-attempts`), and reaching it is recorded, never silently continued.
    """
    if total_attempts < 1:
        raise ValueError("total_attempts must be >= 1")
    if not first_reason:
        raise ValueError("first_reason is required: a retry without a reason is an unnamed failure")
    provenance_base = {"pipeline": "species-tree", "model": config.model}
    draws = 1
    reason = first_reason
    while draws < total_attempts:
        draws += 1
        fresh, unresolved, _ = resolve_codex_summaries(
            [(species_id, anchor, resolved_cell)], provenance_base=provenance_base,
            call=call, config=config, workers=workers)
        if species_id in fresh:
            return fresh[species_id]["codexSummary"], None, draws
        reason = unresolved[species_id]["reason"]
    return None, reason, draws


def finalize_codex(result, anchor, *, seed_root: "Path | None" = None,
                   codex_attempts: int = DEFAULT_CODEX_VOTE_ATTEMPTS,
                   call=None, config=DEFAULT_CONFIG, workers: int = WORKERS) -> dict:
    """One `run_species_tree` result -> this species' committed codex outcome.

    `run_species_tree` never writes a summary-less species file (spec-species-tree.md's own `Never`
    rule), so THIS is where a species whose one draw did not resolve either gets its bounded retry
    (and its file, on success) or gets a NAMED failure record at the same path. The returned dict's
    `codexAttempts` counts total draws, 0 when the codex stage was never reached (an unresolved
    favour, or a refused tree -- those name their own reason in the run's results file, and a species
    file is not written for a species whose tree does not exist).
    """
    if codex_attempts < 1:
        raise ValueError("codex_attempts must be >= 1")
    codex_summary = result.codex_summary
    codex_reason = result.codex_unresolved_reason
    metadata_written = result.metadata_path is not None
    failure_record_written = False
    draws = 1 if (codex_summary is not None or codex_reason is not None) else 0
    if codex_reason is not None:
        codex_summary, codex_reason, draws = resolve_codex_with_retry(
            result.species_id, anchor, result.resolved_cell, first_reason=codex_reason,
            total_attempts=codex_attempts, call=call, config=config, workers=workers)
        if codex_summary is not None:
            write_species_metadata(result.species_id, species_metadata_document(
                result.species_id, result.resolved_cell, result.marked_node_ids,
                codex_summary=codex_summary, codex_attempts=draws), seed_root=seed_root)
            metadata_written = True
        else:
            write_species_metadata(result.species_id, species_metadata_document(
                result.species_id, result.resolved_cell, result.marked_node_ids,
                codex_summary=None, codex_unresolved_reason=codex_reason,
                codex_attempts=draws), seed_root=seed_root)
            failure_record_written = True
    return {
        "codexSummary": codex_summary,
        "codexUnresolvedReason": codex_reason,
        "codexAttempts": draws,
        "metadataWritten": metadata_written,
        "failureRecordWritten": failure_record_written,
    }


def run_batch(*, count: int, out_path: Path = RESULTS_PATH,
              codex_attempts: int = DEFAULT_CODEX_VOTE_ATTEMPTS) -> "list[dict]":
    """Run the first `count` roster species. Zero for `count` means the whole roster.

    `codex_attempts` is the TOTAL number of 3-sample codex draws one species may get (draw 1 from
    `run_species_tree`, the rest this driver's bounded retry of the species whose vote did not
    resolve). See `resolve_codex_with_retry` and `DEFAULT_CODEX_VOTE_ATTEMPTS`. A language-stage
    hard-gate failure is checkpointed as a named result and re-raised: the launcher must see a
    non-zero exit rather than silently continuing past the one gate that stops a full run.
    """
    if codex_attempts < 1:
        raise ValueError("codex_attempts must be >= 1")
    roster = load_roster()
    targets = load_species_targets()
    assignments = assign_favour_cells(roster.species_ids, targets)
    tuning = plan_tuning.load()
    node_targets = nodegen_tuning.load()

    batch_ids = list(roster.species_ids[:count] if count else roster.species_ids)
    print(f"batch of {len(batch_ids)} species (of {len(roster.species_ids)} real roster entries)"
          f"; codex draws per species <= {codex_attempts}", flush=True)

    results: "list[dict]" = []
    # Publish an empty current-pass file before the first model call. Otherwise a smoke row (or a
    # prior pass) remains visible if this invocation dies before species 1, which is precisely the
    # stale-artifact ambiguity the launcher is meant to prevent.
    _write_results(results, out_path)
    for i, species_id in enumerate(batch_ids):
        anchor = roster.anchors[species_id]
        assignment = assignments[species_id]
        ordinal = roster.species_ids.index(species_id)
        t0 = time.monotonic()
        try:
            result = run_species_tree(
                species_id, anchor, ordinal, assignment.cell, list(assignment.alternates),
                targets=node_targets, tuning=tuning, config=DEFAULT_CONFIG, workers=WORKERS)
            codex = finalize_codex(result, anchor, codex_attempts=codex_attempts)
        except SpeciesTreeGateFailure as ex:
            elapsed = time.monotonic() - t0
            print(f"[{i+1}/{len(batch_ids)}] {species_id}: HARD GATE FAILED after {elapsed:.1f}s: {ex}",
                  flush=True)
            results.append({"speciesId": species_id, "error": str(ex), "hardGate": "FAIL"})
            _write_results(results, out_path)
            raise
        except Exception as ex:  # a refused/crashed species is reported, never silently drops the batch
            elapsed = time.monotonic() - t0
            print(f"[{i+1}/{len(batch_ids)}] {species_id}: EXCEPTION after {elapsed:.1f}s: {ex}",
                  flush=True)
            results.append({"speciesId": species_id, "error": str(ex)})
            _write_results(results, out_path)
            continue
        elapsed = time.monotonic() - t0
        summary = {
            "speciesId": species_id,
            "elapsedSeconds": round(elapsed, 1),
            "resolvedCell": None if result.resolved_cell is None else {
                "aptitude": result.resolved_cell.aptitude, "element": result.resolved_cell.element,
                "status": result.resolved_cell.status},
            "favourUnresolvedReason": result.favour_unresolved_reason,
            "nodeKeyRefusedReason": result.node_key_refused_reason,
            "outcomeCounts": dict(result.outcome_counts),
            "markedNodeCount": len(result.marked_node_ids),
            "codexSummary": codex["codexSummary"],
            "codexUnresolvedReason": codex["codexUnresolvedReason"],
            "codexAttempts": codex["codexAttempts"],
            "metadataWritten": codex["metadataWritten"],
            "failureRecordWritten": codex["failureRecordWritten"],
        }
        results.append(summary)
        _write_results(results, out_path)
        print(f"[{i+1}/{len(batch_ids)}] {json.dumps(summary)}", flush=True)

    print(f"wrote {out_path}", flush=True)
    _report_codex_rate(results)
    return results


def _report_codex_rate(results: "list[dict]") -> None:
    """Print the run's per-draw resolve reading. A READING, never an assertion: the plan's own
    `unresolved above fifty permille stops the run` gate is the only hard vote gate, and nothing here
    turns a measured rate into a pass/fail."""
    by_draw: "dict[int, int]" = {}
    failures: "list[str]" = []
    for row in results:
        if row.get("codexSummary") is not None:
            draws = row.get("codexAttempts")
            by_draw[draws] = by_draw.get(draws, 0) + 1
        elif row.get("codexUnresolvedReason") is not None:
            failures.append(f"{row['speciesId']}:{row['codexUnresolvedReason']}")
    reached = sum(by_draw.values()) + len(failures)
    if not reached:
        print("codex vote by draw: no species reached the codex stage this run", flush=True)
        return
    by_draw_text = ", ".join(f"draw {k}={v}" for k, v in sorted(by_draw.items())) or "none"
    print(f"codex vote by draw (of {reached} species that reached the codex stage): "
          f"{by_draw_text}; named failures at the bound: {len(failures)}", flush=True)
    if failures:
        print("codex failures named: " + ", ".join(failures), flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--count", type=int, default=None,
                    help="how many roster species to run (in _index.json order); 0 = the whole roster")
    # Compatibility alias, added 2026-09-21 (task J9-B2): the committed full-run launcher
    # (`.claude/cmdc-agents/scripts/bcu212-full-run.ps1`) passes its count POSITIONALLY
    # (`python gk-forge/tools/seedsmith/_j9_batch_run.py $rosterCount`), which argparse refused with exit 2
    # before this alias existed -- the 840-species run would have died in seconds, before any model
    # call. Measured: `_j9_batch_run.py 2 --check` -> "unrecognized arguments: 2", exit 2. `--count`
    # remains the documented form; both may not disagree.
    ap.add_argument("count_positional", nargs="?", type=int, default=None, metavar="count",
                    help="the same count, accepted positionally for the committed launcher")
    ap.add_argument("--codex-attempts", type=int, default=DEFAULT_CODEX_VOTE_ATTEMPTS,
                    help="total codex-vote draws per species (draw 1 is run_species_tree's own; the "
                         f"rest re-draw only unresolved species). Default {DEFAULT_CODEX_VOTE_ATTEMPTS}")
    ap.add_argument("--check", action="store_true",
                    help="plan only: report what --count would run, with zero model calls")
    ap.add_argument("--out", type=Path, default=RESULTS_PATH,
                    help=f"per-species results file (default {RESULTS_PATH.name})")
    args = ap.parse_args(argv)

    if (args.count is not None and args.count_positional is not None
            and args.count != args.count_positional):
        raise SystemExit("--count and the positional count disagree")
    count = args.count if args.count is not None else (args.count_positional or 0)
    if count < 0:
        raise SystemExit("--count must be >= 0")
    if args.codex_attempts < 1:
        raise SystemExit("--codex-attempts must be >= 1")
    if args.check:
        print(json.dumps(check(count=count), indent=2, ensure_ascii=False))
        return 0
    run_batch(count=count, out_path=args.out, codex_attempts=args.codex_attempts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
