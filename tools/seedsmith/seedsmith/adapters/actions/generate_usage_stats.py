"""seedsmith.adapters.actions.generate_usage_stats --- FC1 `usage-stats`'s own entrypoint
(spec-usage-stats.md, roster-balance program).

    python -m seedsmith.adapters.actions.generate_usage_stats                 # human-readable report
    python -m seedsmith.adapters.actions.generate_usage_stats --json          # machine-readable
    python -m seedsmith.adapters.actions.generate_usage_stats --write         # also write the report file

Model-free: reads committed round files and the affix-family corpus, never calls a model.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .usage_stats.derive import build_report, canonical_dump

__all__ = ["run", "load_policy", "verdict", "REPO_ROOT", "TUNING_PATH", "REPORT_DIR"]

REPO_ROOT = Path(__file__).resolve().parents[5]
TUNING_PATH = REPO_ROOT / "data" / "tuning" / "action-family-usage.v1.json"
REPORT_DIR = REPO_ROOT / "docs" / "research" / "action-corpus"


def load_policy(path: "Path | None" = None) -> "dict[str, Any]":
    """Every threshold lives here, never as a literal in this module — the tuning file's own
    `_meta.owner` names the spec that requires it."""
    doc = json.loads((path or TUNING_PATH).read_text(encoding="utf-8"))
    for key in ("minEvennessMilli", "maxTop10SharePermille", "minFamiliesUsedShare"):
        if not isinstance(doc.get(key), int) or isinstance(doc.get(key), bool):
            raise ValueError(
                f"usage-stats policy: {key!r} must be a per-mille integer, got {doc.get(key)!r} "
                f"({TUNING_PATH}) — per-mille integers only, never floats")
    return doc


def verdict(report: "Mapping[str, Any]", policy: "Mapping[str, Any]") -> "dict[str, Any]":
    """all-time vs the declared floors/ceilings — the honest reading, not a claim. Latest-round is
    reported alongside for visibility but does not itself gate (§"the policy" in the spec: all-time
    is "how are we doing"; a single round is expected to look worse before FC3 weighting exists)."""
    all_time = report["allTime"]
    findings: "list[str]" = []
    if all_time["evennessMilli"] < policy["minEvennessMilli"]:
        findings.append(
            f"evenness {all_time['evennessMilli']} below floor {policy['minEvennessMilli']}")
    if all_time["top10SharePermille"] > policy["maxTop10SharePermille"]:
        findings.append(
            f"top10Share {all_time['top10SharePermille']} above ceiling "
            f"{policy['maxTop10SharePermille']}")
    families_used_share = round((all_time["familiesUsed"] * 1000) / max(1, report["populationSize"]))
    if families_used_share < policy["minFamiliesUsedShare"]:
        findings.append(
            f"familiesUsedShare {families_used_share} below floor {policy['minFamiliesUsedShare']}")
    return {"pass": not findings, "findings": findings, "familiesUsedSharePermille": families_used_share}


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Measure real per-family usage across the action corpus.")
    ap.add_argument("--json", action="store_true", help="print the machine-readable report")
    ap.add_argument("--write", action="store_true",
                    help="also write the report to docs/research/action-corpus/_usage-<date>.json")
    ap.add_argument("--gate", action="store_true", help="exit 1 if the all-time verdict fails")
    args = ap.parse_args(argv)

    report = build_report(REPO_ROOT).to_dict()
    policy = load_policy()
    v = verdict(report, policy)
    report["verdict"] = v

    if args.write:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out_path = REPORT_DIR / f"_usage-{date}.json"
        out_path.write_text(canonical_dump(report), encoding="utf-8")
        print(f"wrote {out_path}")

    if args.json:
        print(canonical_dump(report))
    else:
        at = report["allTime"]
        lr = report["latestRound"]
        print(f"accepted candidates (all-time): {report['acceptedCount']}")
        print(f"population: {report['populationSize']} affix families")
        print(f"all-time   : used {at['familiesUsed']}/{report['populationSize']}  "
             f"evenness={at['evennessMilli']}‰  top10Share={at['top10SharePermille']}‰  "
             f"neverUsed={len(at['neverUsed'])}")
        print(f"latestRound: used {lr['familiesUsed']}/{report['populationSize']}  "
             f"evenness={lr['evennessMilli']}‰  top10Share={lr['top10SharePermille']}‰  "
             f"neverUsed={len(lr['neverUsed'])}  (rounds: {report['latestRoundNumbers']})")
        print(f"verdict: {'PASS' if v['pass'] else 'FAIL'}")
        for f in v["findings"]:
            print(f"  - {f}")
        if at["neverUsed"]:
            print(f"never used ({len(at['neverUsed'])}): {', '.join(at['neverUsed'])}")

    if args.gate and not v["pass"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
