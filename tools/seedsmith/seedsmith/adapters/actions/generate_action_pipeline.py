"""Run the staged action-corpus pipeline against the live creature seed roster."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Callable

from ...pipeline.llm_caller import LlmCallerConfig, resolve_live_transport
from . import (
    generate_brief_assembly as brief_assembly,
    generate_characteristic_pool as characteristic_pool,
    generate_coverage_assignment as coverage_assignment,
    generate_coverage_report as coverage_report,
    generate_dedup_select as dedup_select,
    generate_distribution_planner as distribution_planner,
    generate_family_actions as family_actions,
    generate_general_actions as general_actions,
    generate_innate_picker as innate_picker,
    generate_signature_actions as signature_actions,
    generate_type_weights as type_weights,
    generate_validate_heal as validate_heal,
)
from .distribution_planner.tuning import RUN_TUNING_PATH, load_run_tuning

__all__ = ["run", "run_pipeline"]

REPO_ROOT = Path(__file__).resolve().parents[5]
ACTIONS_ROOT = REPO_ROOT / "data" / "seed" / "actions"


def _load_plan(path: Path, *, expected_corpus_hash: str | None = None) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("kind") != "action-brief":
        raise ValueError(f"{path}: expected an action-brief envelope")
    actual_hash = doc.get("_meta", {}).get("corpusHash")
    if not isinstance(actual_hash, str):
        raise ValueError(f"{path}: plan is missing its corpusHash")
    if expected_corpus_hash is not None and actual_hash != expected_corpus_hash:
        raise ValueError(
            f"{path}: plan corpusHash {actual_hash!r} is stale relative to the live inputs; "
            f"expected {expected_corpus_hash!r}. Re-run the gated distribution planner."
        )
    return doc


def _run_partition(*, name: str, generate: Callable[..., dict], briefs_path: Path,
                   candidates_dir: Path, round_no: int, batch_size: int, max_passes: int,
                   config: LlmCallerConfig, dry_run: bool, resume: bool) -> dict:
    """Fill one proposal partition in bounded, restartable batches."""
    batches: list[dict] = []
    stalled_passes = 0
    while True:
        summary = generate(
            briefs_path=briefs_path, candidates_dir=candidates_dir, count=batch_size,
            dry_run=dry_run, round_no=round_no, config=config,
            write=not dry_run, resume=resume or bool(batches),
        )
        batches.append(summary)
        if dry_run or summary.get("remaining") == 0:
            break
        if summary.get("selected") == 0:
            raise RuntimeError(f"{name}: no selected briefs but {summary.get('remaining')} remain")
        completed = sum(summary.get("byOutcome", {}).get(outcome, 0)
                        for outcome in ("accepted", "blocked", "escalated"))
        stalled_passes = stalled_passes + 1 if completed == 0 else 0
        if stalled_passes >= max_passes:
            raise RuntimeError(
                f"{name}: stopped after {max_passes} stalled passes with "
                f"{summary.get('remaining')} terminal briefs remaining"
            )
    return {"partition": name, "batches": batches,
            "remaining": batches[-1].get("remaining", 0)}


def _foundation_inputs(actions_root: Path) -> dict:
    """The two model-free foundation stages, computed INTO `actions_root` in dependency order.

    `generate_type_weights` hashes the RAW TEXT of `_generated/role-lean.json`, so it must read the
    role-lean this call just derived -- never whatever happens to be on disk. Computing the pair into
    a throwaway temp root for a dry-run is what makes that true without writing a tracked file:
    before this, a dry-run wrote nothing, so type-weights read the STALE committed role-lean while the
    characteristic-pool hash was fresh, and the expected plan hash became a third value that matched
    neither the committed plan nor a real run (ADG-F3, 2026-09-21).
    """
    pool = characteristic_pool.regenerate(actions_root=actions_root, write=True)
    weights = type_weights.regenerate(
        actions_root=actions_root,
        role_lean_path=actions_root / "_generated" / "role-lean.json", write=True)
    return {"characteristicPool": pool, "typeWeights": weights}


def run_pipeline(*, round_no: int = 1, batch_size: int = 25, max_passes: int = 8,
                 dry_run: bool = False,
                 resume: bool = True, plan_path: Path | None = None,
                 config: LlmCallerConfig | None = None) -> dict:
    """Run all model-free stages and all three proposal stages in dependency order."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if max_passes < 1:
        raise ValueError("max_passes must be positive")
    if config is None:
        config = resolve_live_transport()
    plan_path = plan_path or ACTIONS_ROOT / "_briefs" / f"round-{round_no}.json"

    if dry_run:
        # A temp root keeps the hash honest and the tracked tree untouched; see
        # `_foundation_inputs` for why writing is required even though this is a dry run.
        with tempfile.TemporaryDirectory() as tmp:
            foundation = _foundation_inputs(Path(tmp))
    else:
        foundation = _foundation_inputs(ACTIONS_ROOT)
    tuning = load_run_tuning(RUN_TUNING_PATH)
    if tuning.mode != "full":
        raise ValueError(f"{RUN_TUNING_PATH}: full pipeline requires mode='full'")
    rungs_doc = json.loads(distribution_planner.RUNGS_PATH.read_text(encoding="utf-8"))
    expected_plan_hash = distribution_planner._corpus_hash(
        foundation["characteristicPool"]["corpusHash"],
        foundation["typeWeights"]["leanHash"],
        tuning.version,
        rungs_doc["version"],
    )
    # The planner is a gated upstream stage. The action runner must still prove that the plan
    # it consumes belongs to the freshly regenerated live roster, rather than silently using an
    # older plan after a species seed changes.
    plan = _load_plan(plan_path, expected_corpus_hash=expected_plan_hash)

    # Coverage assignment is model-free and may enrich an existing plan without changing its
    # source digest; proposal stages still prove that digest in their provenance.
    assignment = coverage_assignment.regenerate(plan_path=plan_path, write=not dry_run)
    plan = _load_plan(plan_path, expected_corpus_hash=expected_plan_hash)

    general_path = ACTIONS_ROOT / "_candidates" / "general"
    family_path = ACTIONS_ROOT / "_candidates" / "family"
    signature_path = ACTIONS_ROOT / "_candidates" / "signature"
    general = _run_partition(
        name="general", generate=general_actions.regenerate, briefs_path=plan_path,
        candidates_dir=general_path, round_no=round_no, batch_size=batch_size,
        max_passes=max_passes, config=config, dry_run=dry_run, resume=resume,
    )
    family = _run_partition(
        name="family", generate=family_actions.regenerate, briefs_path=plan_path,
        candidates_dir=family_path, round_no=round_no, batch_size=batch_size,
        max_passes=max_passes, config=config, dry_run=dry_run, resume=resume,
    )

    round_dir = ACTIONS_ROOT / "_rounds" / f"round-{round_no}"
    general_candidate = general_path / f"round-{round_no}.json"
    family_candidate = family_path / f"round-{round_no}.json"
    first_validation = validate_heal.regenerate(
        candidates_path=[general_candidate, family_candidate],
        briefs_path=plan_path, round_no=round_no, dry_run=dry_run, write=not dry_run,
    )
    accepted_path = round_dir / "accepted.json"
    p3_briefs = brief_assembly.regenerate(
        plan_path=plan_path, accepted_round_path=accepted_path, round_no=round_no,
        write=not dry_run,
    )
    p3_path = round_dir / "p3-briefs.json"
    signature = _run_partition(
        name="signature", generate=signature_actions.regenerate, briefs_path=p3_path,
        candidates_dir=signature_path, round_no=round_no, batch_size=batch_size,
        max_passes=max_passes, config=config, dry_run=dry_run, resume=resume,
    )

    candidate_paths = [general_candidate, family_candidate, signature_path / f"round-{round_no}.json"]
    final_validation = validate_heal.regenerate(
        candidates_path=candidate_paths, briefs_path=plan_path, round_no=round_no,
        dry_run=dry_run, write=not dry_run,
    )
    dedup = dedup_select.regenerate(
        candidates_path=accepted_path, round_no=round_no, write=not dry_run,
    )
    innate = innate_picker.regenerate(round_no=round_no, write=not dry_run)
    coverage = coverage_report.regenerate(round_no=round_no, write=not dry_run)

    return {
        "round": round_no, "mode": tuning.mode, "planBriefCount": len(plan["entries"]),
        "planByScope": {
            scope: sum(1 for e in plan["entries"] if e.get("scope") == scope)
            for scope in ("general", "family", "species")
        },
        "foundation": foundation, "coverageAssignment": assignment,
        "general": general, "family": family, "firstValidation": first_validation,
        "briefAssembly": p3_briefs, "signature": signature,
        "finalValidation": final_validation, "dedup": dedup, "innate": innate,
        "coverage": coverage,
    }


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the staged live-seed action corpus pipeline.")
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--batch-size", type=int, default=25,
                    help="model briefs per resumable batch")
    ap.add_argument("--max-passes", type=int, default=8,
                    help="maximum consecutive no-progress batches before refusing to loop")
    ap.add_argument("--dry-run", action="store_true", help="run model-free checks with zero calls")
    ap.add_argument("--fresh", action="store_true",
                    help="replace the first batch instead of resuming existing candidates")
    ap.add_argument("--endpoint", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--plan", type=Path, default=None,
                    help="brief plan to use; defaults to the selected round")
    args = ap.parse_args(argv)
    print(json.dumps(run_pipeline(
        round_no=args.round, batch_size=args.batch_size, max_passes=args.max_passes,
        config=resolve_live_transport(args.endpoint, args.model), dry_run=args.dry_run,
        resume=not args.fresh, plan_path=args.plan,
    ), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
