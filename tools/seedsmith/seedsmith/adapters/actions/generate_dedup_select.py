"""seedsmith.adapters.actions.generate_dedup_select — A-S3's entrypoint (spec-dedup-select.md).
Reads:

    <candidates>                                        A-S4's accepted output for this round,
                                                          an A-C1 `action-seed` envelope -- path
                                                          supplied by the caller, see below
    gk-data/packs/fusion/data/seed/actions/ (excluding `_rounds/`)            the already-accepted corpus, via A-C1's
                                                          own `load_committed` (`../load.py`)
    gk-core/data/tuning/action-dedup.v1.json                     this module's OWN tuning file (k,
                                                          similarityThresholdMilli, t2FieldDistance)

and writes, through the A-C1 envelope, under `data/seed/actions/_rounds/round-<n>/`:

    survivors.json      kind: "action-seed"
    rejects.json         kind: "action-reject"
    review-queue.json    kind: "action-review"

**No shipped default for `--candidates`.** A-S4 (`validate-heal`) is not built, so there is no
real accepted-candidate-set file anywhere in this checkout to point a default at, and guessing a
path for an unbuilt sibling's output would invent structure this module has no evidence for --
unlike `gk-core/data/tuning/action-dedup.v1.json`, whose path IS named by this module's own spec. The
caller (a human, or A-S4 once it exists) must always name the file explicitly.

**Zero model calls on the acceptance path** -- tier 3's token-overlap heuristic
(`dedup_select/similarity.py`) is pure local arithmetic, never a transport call; `--no-semantic`
skips it entirely and survivors/rejects are proven byte-identical either way
(`tests/test_dedup_select.py`, acceptance #6).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .dedup_select import derive as ds
from .dedup_select.similarity import SIMILARITY_FUNCTION_ID, SIMILARITY_FUNCTION_VERSION
from .dedup_select.tuning import DEDUP_TUNING_PATH, load_dedup_tuning
from .load import load_committed
from .vocab import load_family_ids

__all__ = ["run", "regenerate", "ACTIONS_ROOT"]

REPO_ROOT = Path(__file__).resolve().parents[5]
ACTIONS_ROOT = REPO_ROOT / "data" / "seed" / "actions"


def regenerate(*, candidates_path: Path, actions_root: Path = ACTIONS_ROOT,
              dedup_tuning_path: Path = DEDUP_TUNING_PATH, round_no: int = 1,
              run_semantic: bool = True, write: bool = True) -> dict:
    """Pure computation + (optionally) three file writes. Returns a summary dict for the caller to
    report -- never prints itself, so a test can call this without capturing stdout."""
    tuning = load_dedup_tuning(dedup_tuning_path)
    family_ids = load_family_ids()

    candidates_doc = json.loads(candidates_path.read_text(encoding="utf-8"))
    if candidates_doc.get("kind") != "action-seed":
        raise ValueError(
            f"{candidates_path}: expected an 'action-seed' envelope (A-S4's accepted output for "
            f"this round) -- got kind={candidates_doc.get('kind')!r}")
    candidate_rows = candidates_doc.get("entries") or []

    load_result = load_committed(actions_root)          # excludes `_rounds/` already (A-C1)
    accepted_rows = [e.data for e in load_result.corpus.by_kind("action-seed")]

    result = ds.select_round(
        candidate_rows=candidate_rows, accepted_rows=accepted_rows, round_no=round_no,
        similarity_threshold_milli=tuning.similarity_threshold_milli, run_semantic=run_semantic,
        family_ids=family_ids,
    )

    base_meta = {"partition": "rounds", "round": round_no, "corpusHash": result.corpus_hash,
                "candidateSetHash": result.candidate_set_hash, "tuningVersion": tuning.version}

    survivors_doc = ds.build_envelope("action-seed", result.survivor_entries, dict(base_meta))
    rejects_doc = ds.build_envelope("action-reject", result.reject_entries, dict(base_meta))
    # Only review-queue.json's own `_meta` carries the semantic-pass fields -- survivors.json and
    # rejects.json must stay byte-identical with `--no-semantic` on or off (acceptance #6), and
    # tier 3 is the only pass that flag would ever change.
    review_meta = dict(base_meta)
    review_meta["semanticEnabled"] = result.semantic_ran
    review_meta["similarityFunctionId"] = SIMILARITY_FUNCTION_ID if result.semantic_ran else None
    review_meta["similarityFunctionVersion"] = (
        SIMILARITY_FUNCTION_VERSION if result.semantic_ran else None)
    review_doc = ds.build_envelope("action-review", result.review_entries, review_meta)

    if write:
        round_dir = actions_root / "_rounds" / f"round-{round_no}"
        round_dir.mkdir(parents=True, exist_ok=True)
        (round_dir / "survivors.json").write_text(ds.canonical_dump(survivors_doc), encoding="utf-8")
        (round_dir / "rejects.json").write_text(ds.canonical_dump(rejects_doc), encoding="utf-8")
        (round_dir / "review-queue.json").write_text(ds.canonical_dump(review_doc), encoding="utf-8")

    return {
        "round": round_no,
        "candidateCount": len(candidate_rows),
        "survivorCount": len(result.survivor_entries),
        "rejectCount": len(result.reject_entries),
        "tier1RejectCount": sum(1 for r in result.reject_entries if r["tier"] == 1),
        "tier2RejectCount": sum(1 for r in result.reject_entries if r["tier"] == 2),
        "reviewQueueCount": len(result.review_entries),
        "semanticEnabled": result.semantic_ran,
        "corpusHash": result.corpus_hash, "candidateSetHash": result.candidate_set_hash,
        "tuningVersion": tuning.version,
        "written": bool(write),
    }


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Select survivors for one action-corpus round via mechanical dedup (A-S3).")
    ap.add_argument("--candidates", required=True,
                    help="path to A-S4's accepted action-seed envelope for this round")
    ap.add_argument("--round", type=int, default=1, dest="round_no")
    ap.add_argument("--no-semantic", action="store_true",
                    help="skip tier 3 entirely -- survivors/rejects are byte-identical either way")
    ap.add_argument("--dry-run", action="store_true", help="compute and print, write nothing")
    args = ap.parse_args(argv)

    summary = regenerate(candidates_path=Path(args.candidates), round_no=args.round_no,
                         run_semantic=not args.no_semantic, write=not args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
