"""seedsmith.adapters.actions.generate_coverage_assignment -- A-S7's entrypoint
(spec-coverage-assignment.md). Reads:

    <plan>          A-S1's own `action-brief` envelope for this round (`distribution_planner`'s
                     output, `_briefs/round-<n>.json`) -- every existing field passes through
                     byte-identical; `requiredFamilies` is the only field this stage adds.
    <usage-report>  the latest roster-balance FC1 report (`docs/research/action-corpus/
                     _usage-<date>.json`) by default -- optional override for a specific one.

and writes, in place (or to `--plan-out`):

    the SAME `action-brief` envelope, each entry gaining `requiredFamilies: list[str]`.

**Zero model calls, permanently** -- same class of module as A-S1/A-S2/A-S5, pure arithmetic over
already-committed files (`coverage_assignment.derive`, no transport import anywhere in this module
or its package).

    python -m seedsmith.adapters.actions.generate_coverage_assignment --plan <path> --dry-run
    python -m seedsmith.adapters.actions.generate_coverage_assignment --plan <path>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .coverage_assignment.derive import assign_required_families, load_current_usage
from .vocab import load_family_ids

__all__ = ["run", "regenerate", "ACTIONS_ROOT", "USAGE_REPORTS_DIR"]

REPO_ROOT = Path(__file__).resolve().parents[5]
ACTIONS_ROOT = REPO_ROOT / "data" / "seed" / "actions"
USAGE_REPORTS_DIR = REPO_ROOT / "docs" / "research" / "action-corpus"


def _canonical_dump(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def regenerate(*, plan_path: Path, usage_reports_dir: Path = USAGE_REPORTS_DIR,
              plan_out_path: "Path | None" = None, pairings_path: "Path | None" = None,
              write: bool = True) -> dict:
    """Pure-ish computation (`write=False` writes nothing) plus, on a real run, one file write.
    Returns a summary dict; never prints itself, matching every sibling `regenerate`'s own "a test
    can call this without capturing stdout" convention.

    Reads `pairings.json` to learn which families are **payoff keys**, and passes them to
    `assign_required_families` so the non-pairing round-robin never requires a payoff without its
    enabler (see that function's own 2026-09-12 note: 74 live anchors were otherwise guaranteed
    `enablerPayoffCoverage` gaps). A missing/blank `pairings.json` degrades to an empty payoff set --
    the pre-fix behaviour exactly -- rather than refusing, matching how `coverage_report` treats the
    same absent input."""
    doc = json.loads(plan_path.read_text(encoding="utf-8"))
    if doc.get("kind") != "action-brief":
        raise ValueError(
            f"{plan_path}: expected an 'action-brief' envelope (A-S1's own plan,"
            f" distribution_planner.derive.build_envelope) -- got kind={doc.get('kind')!r}")

    entries = doc.get("entries") or []
    usage_counts = load_current_usage(usage_reports_dir)
    family_ids = load_family_ids()
    pairings_file = pairings_path or (ACTIONS_ROOT / "pairings.json")
    payoff_families: "list[str]" = []
    if pairings_file.is_file():
        table = json.loads(pairings_file.read_text(encoding="utf-8"))
        payoff_families = sorted(table)
    assignments = assign_required_families(entries, usage_counts=usage_counts,
                                           family_ids=family_ids,
                                           payoff_families=payoff_families)

    for entry in entries:
        brief_id = entry.get("briefId") or entry.get("id")
        entry["requiredFamilies"] = assignments.get(brief_id, [])

    out_path = plan_out_path or plan_path
    if write:
        out_path.write_text(_canonical_dump(doc), encoding="utf-8")

    assigned_count = sum(1 for v in assignments.values() if v)
    unassigned_count = sum(1 for v in assignments.values() if not v)
    return {
        "totalBriefs": len(entries),
        "assignedCount": assigned_count,
        "unassignedCount": unassigned_count,
        "usageReportUsed": bool(usage_counts),
        "written": bool(write),
    }


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Assign a required coverage family per brief (A-S7 'coverage-assignment').")
    ap.add_argument("--plan", required=True, type=Path,
                    help="path to A-S1's own action-brief envelope for this round")
    ap.add_argument("--usage-report-dir", type=Path, default=USAGE_REPORTS_DIR,
                    help="directory to read the latest FC1 usage report from")
    ap.add_argument("--plan-out", type=Path, default=None,
                    help="where to write the updated plan (defaults to overwriting --plan)")
    ap.add_argument("--dry-run", action="store_true", help="compute and print, write nothing")
    args = ap.parse_args(argv)

    summary = regenerate(plan_path=args.plan, usage_reports_dir=args.usage_report_dir,
                         plan_out_path=args.plan_out, write=not args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    raise SystemExit(run(argv))


if __name__ == "__main__":
    main()
