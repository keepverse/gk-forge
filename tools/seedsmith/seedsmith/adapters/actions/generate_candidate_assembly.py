"""seedsmith.adapters.actions.generate_candidate_assembly — the post-validation mechanical
assembly helper. Reads:

    <candidates> (one or more)   A-P1/A-P2/A-P3's own round output for this round -- each an A-C1
                                  envelope, `kind: "action-candidate"`, one file per scope partition
                                  (real shape today: `data/seed/actions/_candidates/general/
                                  round-<n>.json`, `.../family/round-<n>.json`; signature would add
                                  a third once A-P3 has a real round). Every file is read and its
                                  `entries` concatenated -- order across files never matters (this
                                  module's own total order re-sorts everything by scope/briefId/
                                  candidateId before minting a single id).
    <briefs>                     A-S1's own brief envelope for this round (`distribution_planner`'s
                                  output, `kind: "action-brief"`, real shape: `gk-data/packs/fusion/data/seed/actions/
                                  _briefs/round-<n>.json`) -- or A-S2's `p3-briefs.json` for a round
                                  that includes signature-scope candidates. Indexed by `briefId`.
    gk-data/packs/fusion/data/seed/actions/ (excluding `_rounds/`)   the already-committed corpus, via A-C1's own
                                  `load_committed` -- read ONLY to seed each anchor's own next
                                  ordinal (`(scope, scopeKey) -> count of already-minted action-seed
                                  rows in that anchor`), never to gate or dedup (that stays A-S3's).

and writes, through the A-C1 envelope:

    data/seed/actions/_rounds/round-<n>/assembled.json    kind: "action-seed" -- exactly the shape
                                  `generate_dedup_select.py`'s own docstring already calls "A-S4's
                                  accepted output for this round, an A-C1 `action-seed` envelope" --
                                  point `generate_dedup_select.py --candidates` at THIS file.

**Gates by default** (`--no-gate` skips it): every accepted candidate is re-checked against A-S4's
real per-pipeline schema (`validate_heal.schemas`, fixed 2026-09-04) and brief-conformance rules
(`validate_heal.gates`) before it is assembled and minted an id. The canonical round entrypoint
(`generate_validate_heal.py`) invokes this helper only AFTER A-S4 validation. Do not run this
helper on raw proposal partitions as a substitute for A-S4.
A candidate A-S4 rejects is recorded in the summary's own `gateRejects`, never silently dropped nor
silently assembled anyway.

**Zero model calls, permanently** -- purely mechanical merge + id mint (module docstring,
`candidate_assembly/derive.py`); no LLM transport import anywhere in this module or its package.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .candidate_assembly import derive as ca
from .load import load_committed

__all__ = ["run", "regenerate", "ACTIONS_ROOT"]

REPO_ROOT = Path(__file__).resolve().parents[5]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from ...workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

ACTIONS_ROOT = _owned("data/seed/actions")


def _load_candidate_rows(paths: Sequence[Path]) -> "list[dict]":
    rows: "list[dict]" = []
    for path in paths:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("kind") != "action-candidate":
            raise ValueError(
                f"{path}: expected an 'action-candidate' envelope (A-P1/A-P2/A-P3's own round "
                f"output) -- got kind={doc.get('kind')!r}")
        rows.extend(doc.get("entries") or [])
    return rows


def _existing_counts(actions_root: Path) -> "dict[tuple[str, str], int]":
    load_result = load_committed(actions_root)          # excludes `_rounds/` already (A-C1)
    counts: "dict[tuple[str, str], int]" = {}
    for entry in load_result.corpus.by_kind("action-seed"):
        row = entry.data
        anchor = ca.anchor_key(row.get("scope"), row.get("scopeKey"))
        action_id = row.get("id")
        try:
            ordinal = int(str(action_id).rsplit(".", 1)[1])
        except (AttributeError, IndexError, TypeError, ValueError):
            # Hand-authored rows outside the ordinal scheme (e.g. `act.attack`, the
            # hand-authored basic-attack fallback) carry no trailing ordinal to continue from —
            # skip, never crash the whole assembly on one row's shape. Skipping changes nothing
            # downstream: the count is a per-anchor MAX, and a row with no ordinal contributes
            # no information about where the next ordinal starts.
            continue
        counts[anchor] = max(counts.get(anchor, 0), ordinal)
    return counts


def regenerate(*, candidates_paths: Sequence[Path], briefs_path: Path,
              actions_root: Path = ACTIONS_ROOT, round_no: int = 1, gate: bool = True,
              write: bool = True) -> dict:
    """Pure computation + (optionally) one file write. Returns a summary dict for the caller to
    report -- never prints itself, so a test can call this without capturing stdout."""
    candidate_rows = _load_candidate_rows(list(candidates_paths))

    briefs_doc = json.loads(briefs_path.read_text(encoding="utf-8"))
    if briefs_doc.get("kind") != "action-brief":
        raise ValueError(f"{briefs_path}: expected an 'action-brief' envelope (A-S1/A-S2's own "
                         f"brief output) -- got kind={briefs_doc.get('kind')!r}")
    briefs_by_id = {b.get("briefId") or b.get("id"): b for b in (briefs_doc.get("entries") or [])}

    existing_counts = _existing_counts(actions_root)

    result = ca.assemble_round(candidate_rows, briefs_by_id, gate=gate,
                               existing_counts=existing_counts)

    envelope = ca.build_envelope("action-seed", result.assembled_rows, {
        "partition": f"round-{round_no}", "round": round_no,
        "candidatesPaths": [str(p) for p in candidates_paths], "briefsPath": str(briefs_path),
        "gateEnabled": gate,
    })

    if write:
        round_dir = actions_root / "_rounds" / f"round-{round_no}"
        round_dir.mkdir(parents=True, exist_ok=True)
        (round_dir / "assembled.json").write_text(ca.canonical_dump(envelope), encoding="utf-8")

    return {
        "round": round_no,
        "candidateRowCount": len(candidate_rows),
        "skippedUnacceptedCount": len(result.skipped_unaccepted),
        "gateEnabled": gate,
        "gateRejectCount": len(result.gate_rejects),
        "gateRejects": [
            {"candidateId": r.candidate_id, "briefId": r.brief_id, "outcome": r.outcome,
             "gateDefects": r.gate_defects}
            for r in result.gate_rejects
        ],
        "assembledCount": len(result.assembled_rows),
        "assembledIds": [row["id"] for row in result.assembled_rows],
        "written": bool(write),
    }


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Assemble A-S4-accepted candidates into real action-seed rows (post-validation).")
    ap.add_argument("--candidates", required=True, nargs="+",
                    help="one or more paths to a round's own action-candidate envelope(s) "
                        "(A-P1/A-P2/A-P3's output, one file per scope partition)")
    ap.add_argument("--briefs", required=True,
                    help="path to A-S1/A-S2's own action-brief envelope for this round")
    ap.add_argument("--round", type=int, default=1, dest="round_no")
    ap.add_argument("--no-gate", action="store_true", dest="no_gate",
                    help="skip A-S4 re-gating -- assemble every already-accepted candidate as-is")
    ap.add_argument("--dry-run", action="store_true", help="compute and print, write nothing")
    args = ap.parse_args(argv)

    summary = regenerate(
        candidates_paths=[Path(p) for p in args.candidates], briefs_path=Path(args.briefs),
        round_no=args.round_no, gate=not args.no_gate, write=not args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
