#!/usr/bin/env python3
"""Model-free preflight for the action-corpus round run (task T4.5, `action-distribution-gaps`).

Why this exists: T4.5's first pass checked the PLANNER's dry-run and called the run ready, while
`generate_action_pipeline --dry-run` still refused the same plan as stale (ADG-F1, 2026-09-21). The
planner reads the ON-DISK foundation and only compares species **ID SETS**, so a catalog-content drift
leaves the plan stale and the planner green. This script runs the checks that actually decide whether a
round can start, and it fails at the FIRST red, naming it.

Every check is model-free. It never writes a tracked file: steps 5-7 compute in memory.

    python gk-forge/tools/seedsmith/action_run_preflight.py                 # full preflight
    python gk-forge/tools/seedsmith/action_run_preflight.py --skip-endpoint # no LM Studio reachable

Exit codes: 0 all green; 1 a named check failed; 2 could not run the check itself.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from seedsmith.adapters.actions import generate_action_pipeline as pipeline  # noqa: E402
from seedsmith.adapters.actions import generate_distribution_planner as planner  # noqa: E402
from seedsmith.adapters.actions import vocab  # noqa: E402
from seedsmith.adapters.actions.distribution_planner.tuning import (  # noqa: E402
    RUN_TUNING_PATH, load_run_tuning,
)
from seedsmith.pipeline.llm_caller import LlmCallerConfig, resolve_live_transport  # noqa: E402

ACTIONS_ROOT = planner.ACTIONS_ROOT
PLAN_PATH = ACTIONS_ROOT / "_briefs" / "round-1.json"
GATE_PATH = planner.SMOKE_GATE_EVIDENCE_PATH
EXPECTED_TAGS = frozenset({
    "offensive", "defensive", "heal", "buff", "debuff", "movement", "summon", "utility", "construct",
})


def models_url(endpoint: str) -> str:
    """`/v1/chat/completions` -> `/v1/models`, so the reachability probe reuses the caller's own
    configured host instead of a second hardcoded one."""
    base = endpoint.rstrip("/")
    for suffix in ("/chat/completions", "/completions"):
        if base.endswith(suffix):
            return base[: -len(suffix)] + "/models"
    return base + "/models"


def endpoint_has_model(endpoint: str, model: str, *, timeout: float = 10.0) -> bool:
    try:
        with urllib.request.urlopen(models_url(endpoint), timeout=timeout) as response:
            doc = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return any(row.get("id") == model for row in doc.get("data", ()))


def fresh_plan_hash(*, round_no: int = 1) -> str:
    """The hash a REAL run would demand -- the same derivation `generate_action_pipeline` uses, i.e.
    the characteristic-pool/type-weights hashes plus the tuning/rungs versions."""
    summary = planner.regenerate(write=False, full_flag=True, round_no=round_no,
                                 top_up_report_path=None)
    return summary["corpusHash"]


def committed_plan_hash(plan_path: Path = PLAN_PATH) -> str:
    doc = json.loads(plan_path.read_text(encoding="utf-8"))
    return doc["_meta"]["corpusHash"]


def run_checks(*, config: LlmCallerConfig, skip_endpoint: bool) -> "list[tuple[str, bool, str]]":
    results: "list[tuple[str, bool, str]]" = []

    results.append(("endpoint+model", skip_endpoint or endpoint_has_model(config.endpoint, config.model),
                    "skipped" if skip_endpoint else f"{models_url(config.endpoint)} lists {config.model}"))

    tags = frozenset(vocab.TAGS)
    results.append(("vocab.TAGS", tags == EXPECTED_TAGS, f"{len(tags)} tags, missing "
                    f"{sorted(EXPECTED_TAGS - tags)} / extra {sorted(tags - EXPECTED_TAGS)}"))

    tuning = load_run_tuning(RUN_TUNING_PATH)
    results.append(("tuning mode", tuning.mode == "full", f"mode={tuning.mode!r} version={tuning.version}"))

    gate_ok = planner.is_passing_quality_gate(GATE_PATH)
    results.append(("quality gate", gate_ok, f"{GATE_PATH.name} passing={gate_ok}"))

    if not gate_ok:
        return results  # the planner's own gate would refuse before the hash is worth computing

    try:
        fresh = fresh_plan_hash()
    except Exception as exc:  # noqa: BLE001 - the preflight reports any refusal verbatim
        results.append(("planner fresh hash", False, f"{type(exc).__name__}: {exc}"))
        return results
    committed = committed_plan_hash()
    results.append(("plan freshness", fresh == committed,
                    f"committed={committed[:12]}… fresh={fresh[:12]}…"))

    if fresh != committed:
        return results  # the pipeline would refuse here; no point reporting the terminal reason

    try:
        pipeline._load_plan(PLAN_PATH, expected_corpus_hash=fresh)
        results.append(("pipeline accepts the plan", True, "no stale-hash refusal"))
    except ValueError as exc:
        results.append(("pipeline accepts the plan", False, str(exc)))

    # The terminal reason a dry-run stops at must be the scratch the run itself creates, never a
    # hash/tuning refusal -- that is precisely the distinction ADG-F1 got wrong.
    try:
        pipeline.run_pipeline(round_no=1, batch_size=25, max_passes=8, config=config,
                              dry_run=True, resume=True)
        results.append(("pipeline dry-run", False, "completed -- expected it to stop on absent scratch"))
    except ValueError as exc:
        scratch = "_candidates" in str(exc)
        results.append(("pipeline dry-run", scratch,
                        "stops only on absent candidate scratch" if scratch else str(exc)))
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--endpoint", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--skip-endpoint", action="store_true",
                    help="skip the LM Studio reachability probe (offline preflight)")
    args = ap.parse_args(argv)

    results = run_checks(config=resolve_live_transport(args.endpoint, args.model),
                         skip_endpoint=args.skip_endpoint)
    for name, ok, detail in results:
        print(f"[{'OK ' if ok else 'RED'}] {name}: {detail}")
    failed = [name for name, ok, _ in results if not ok]
    if failed:
        print(f"\npreflight RED: {', '.join(failed)} -- do not start the run", file=sys.stderr)
        return 1
    print("\npreflight GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
