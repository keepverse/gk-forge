"""seedsmith.adapters.actions.generate_validate_heal --- A-S4's entrypoint (spec-validate-heal.md).
Reads:

    <candidates>     one or more JSON envelopes {"entries": [...]} of candidate rows -- each
                      carrying at least candidateId/briefId/pipelineId/scope/draft, matching
                      `validate_heal.derive.validate_round`'s own row shape. The default discovers
                      all proposal partitions that already exist for the round; A-S4 must see the
                      complete available candidate set so round-level checks are not partitioned.
    <briefs>          A-S1's own brief envelope for this round (`distribution_planner`'s output) --
                      used to build each candidate's `BriefContext` (allowed/forbidden atom
                      families, motifs, structure-axis ceiling budget).
    gk-core/data/tuning/action-rungs.v4.json   the rung table g2 reads the ceiling row's own structureBudget
                                        from (via `distribution_planner.derive`, reused, never
                                        re-derived here).

and writes, under `data/seed/actions/_rounds/round-<n>/`:

    accepted.json     kind: "action-seed"   -- validated candidates assembled into real action rows
    blocked.json      kind: "action-review" -- candidates the model genuinely declined
    unresolved.json   kind: "action-review" -- 1-1-1 votes and heal-exhausted candidates
    escalated.json    kind: "action-review" -- anything this module's own contract has no named
                                                path for (see `derive.py`'s own docstring)

**Pipeline order is binding:** proposal candidates -> A-S4 validation -> deterministic ID assembly
-> A-S3 dedup. `generate_candidate_assembly.py` is a pure assembly helper, not a pre-validation
stage.

**Zero model calls under `--dry-run`** (acceptance #9): gates a recorded candidate set, `--preflight`
is skipped, `preflight: "skipped"` is written into the round report's own provenance either way
unless `--preflight` was also passed and a real call ran. The live heal path (no `--dry-run`) is
wired here and consumes the resumable proposal envelopes produced by A-P1/A-P2/A-P3.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .candidate_assembly import derive as candidate_assembly
from .generate_candidate_assembly import _existing_counts
from .distribution_planner.derive import load_rung_table, load_scope_windows, structure_axes_for
from .validate_heal.derive import (build_envelope, candidate_set_hash, canonical_dump,
                                   validate_round)
from .validate_heal.gates import BriefContext
from .validate_heal.preflight import run_preflight

__all__ = ["run", "regenerate", "ACTIONS_ROOT", "RUNG_TABLE_PATH", "BRIEFS_PATH",
           "CANDIDATE_PATHS", "candidate_paths_for_round", "available_candidate_paths_for_round",
           "briefs_path_for_round", "build_contexts"]

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
RUNG_TABLE_PATH = _owned("data/tuning/action-rungs.v4.json")
BRIEFS_PATH = ACTIONS_ROOT / "_briefs" / "round-1.json"
CANDIDATE_PATHS = (
    ACTIONS_ROOT / "_candidates" / "general" / "round-1.json",
    ACTIONS_ROOT / "_candidates" / "family" / "round-1.json",
    ACTIONS_ROOT / "_candidates" / "signature" / "round-1.json",
)


def candidate_paths_for_round(round_no: int) -> "tuple[Path, Path, Path]":
    return tuple(
        ACTIONS_ROOT / "_candidates" / partition / f"round-{round_no}.json"
        for partition in ("general", "family", "signature")
    )


def available_candidate_paths_for_round(round_no: int) -> "list[Path]":
    """Return existing proposal partitions in the canonical pipeline order."""
    return [path for path in candidate_paths_for_round(round_no) if path.is_file()]


def briefs_path_for_round(round_no: int) -> Path:
    return ACTIONS_ROOT / "_briefs" / f"round-{round_no}.json"


def _candidate_paths(value: "Path | Sequence[Path]") -> "list[Path]":
    return [value] if isinstance(value, Path) else list(value)


def _load_candidate_rows(paths: "Sequence[Path]") -> "list[dict]":
    rows: "list[dict]" = []
    for path in paths:
        if not path.is_file():
            raise ValueError(
                f"{path}: no candidate file — run the propose stages first "
                f"(A-P1/A-P2 general+family before first validation, A-P3 after brief assembly); "
                f"a dry-run renders briefs without writing, so it cannot validate a scratch-empty tree.")
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("kind") != "action-candidate":
            raise ValueError(
                f"{path}: expected an 'action-candidate' envelope from A-P1/A-P2/A-P3, "
                f"got kind={doc.get('kind')!r}")
        rows.extend(doc.get("entries") or [])
    return rows


def build_contexts(brief_rows: "list[dict]", *, rung_table_path: Path = RUNG_TABLE_PATH,
                   family_action_atom_sets: "tuple[frozenset, ...]" = (),
                   forbidden_anchor_tokens: "tuple[str, ...]" = ()) -> "dict[str, BriefContext]":
    """One `BriefContext` per brief, keyed by `briefId` -- g2's own ceiling-row budget comes from
    `distribution_planner.derive.structure_axes_for` (A-S1's stated collapse rule), never
    re-derived (spec SS3: "never invent a rung-band resolution").

    ST3 (`spec-scope-window-tunables.md` contract 3): the windows come from the SAME rung table the
    structures do, loaded here and passed down -- `structure_axes_for` no longer reads a code
    literal. The v3 path is the planner's own (H7: one file for windows and budgets); the rows are
    identical to v1's except the budget column this stage does not read."""
    rung_table = load_rung_table(rung_table_path)
    windows = load_scope_windows(rung_table_path)
    out: "dict[str, BriefContext]" = {}
    for b in brief_rows:
        scope = b["scope"]
        pipeline_id = {"general": "A-P1", "family": "A-P2", "species": "A-P3"}[scope]
        anchor = b.get("anchor") or {}
        motifs = frozenset(anchor.get("motifs") or anchor.get("familyMotifs") or ())
        anti_motifs = frozenset(anchor.get("antiMotifs") or anchor.get("familyAntiMotifs") or ())
        pool = b.get("pool") or {}
        out[b["briefId"]] = BriefContext(
            brief_id=b["briefId"], pipeline_id=pipeline_id,
            allowed_atom_families=frozenset(pool.get("allowedAtomFamilies") or ()),
            forbidden_atom_families=frozenset(pool.get("forbiddenAtomFamilies") or ()),
            motifs=motifs, anti_motifs=anti_motifs,
            structure_budget_ceiling=structure_axes_for(scope, rung_table, windows),
            family_action_atom_sets=family_action_atom_sets if pipeline_id == "A-P3" else (),
            forbidden_anchor_tokens=forbidden_anchor_tokens if pipeline_id == "A-P1" else (),
        )
    return out


def regenerate(*, candidates_path: "Path | Sequence[Path]", briefs_path: Path, round_no: int = 1,
               dry_run: bool = True, do_preflight: bool = False, write: bool = True) -> dict:
    candidate_paths = _candidate_paths(candidates_path)
    candidate_rows = _load_candidate_rows(candidate_paths)
    briefs_doc = json.loads(briefs_path.read_text(encoding="utf-8"))
    brief_rows = briefs_doc.get("entries") or []

    contexts = build_contexts(brief_rows)

    # Proposer rows contain an envelope around the model answer. A-S4's strict schemas must see
    # only the answer fields; rows already resolved as blocked/unresolved have no answer to gate
    # and are carried to the matching review output without being misreported as exceptions.
    validation_rows: "list[dict]" = []
    preclassified: "dict[str, list[dict]]" = {
        "accepted": [], "blocked": [], "unresolved": [], "escalated": [],
    }
    for row in candidate_rows:
        draft = row.get("draft")
        if not isinstance(draft, dict):
            outcome = row.get("outcome")
            if outcome == "accepted":
                raise ValueError(
                    f"{row.get('candidateId') or row.get('briefId')}: accepted candidate has no draft")
            if outcome not in preclassified:
                raise ValueError(
                    f"{row.get('candidateId') or row.get('briefId')}: candidate has no draft and "
                    f"unknown outcome {outcome!r}")
            preclassified[outcome].append(dict(row))
            continue
        normalized = dict(row)
        normalized["draft"] = candidate_assembly.answer_only(draft, row["pipelineId"])
        validation_rows.append(normalized)

    if do_preflight and not dry_run:
        from ...pipeline.llm_caller import call_model, load_config
        config = load_config()
        preflight = run_preflight(
            skip=False,
            call_model_fn=lambda system, user, schema: call_model(system, user, config=config, schema=schema),
            endpoint=config.endpoint, model_id=config.model,
        )
        if preflight.blocks_run:
            raise RuntimeError(f"--preflight failed: {preflight.detail} (endpoint={preflight.endpoint})")
    else:
        preflight = run_preflight(skip=True)

    report = validate_round(validation_rows, contexts=contexts)

    by_outcome: "dict[str, list[dict]]" = {"accepted": [], "blocked": [], "unresolved": [], "escalated": []}
    for outcome, rows in preclassified.items():
        by_outcome[outcome].extend(rows)
    for v in report.verdicts:
        row = v.entry if v.entry is not None else {"candidateId": v.candidate_id, "briefId": v.brief_id}
        row = dict(row)
        row["candidateId"] = v.candidate_id
        row["_provenance"] = {**v.provenance, "gateDefects": v.gate_defects,
                              "structureAxesUnchecked": v.structure_axes_unchecked}
        by_outcome[v.outcome].append(row)

    # A-S4 owns acceptance. Only its accepted rows may reach the mechanical ID assembler; raw
    # proposer output must never be minted as an action-seed before validation.
    candidate_by_id = {
        row.get("candidateId"): row for row in candidate_rows if row.get("candidateId")
    }
    accepted_candidates: "list[dict]" = []
    for verdict in report.verdicts:
        if verdict.outcome != "accepted" or verdict.entry is None:
            continue
        source = candidate_by_id.get(verdict.candidate_id)
        if source is None:
            raise ValueError(
                f"A-S4 accepted {verdict.candidate_id!r}, but its source candidate row is missing")
        accepted = dict(source)
        accepted["outcome"] = "accepted"
        accepted["draft"] = dict(verdict.entry)
        accepted_candidates.append(accepted)

    briefs_by_id = {b.get("briefId") or b.get("id"): b for b in brief_rows}
    assembly = candidate_assembly.assemble_round(
        accepted_candidates, briefs_by_id, gate=True,
        existing_counts=_existing_counts(ACTIONS_ROOT),
    )

    base_meta = {
        "partition": "rounds", "round": round_no, "candidateSetHash": candidate_set_hash(candidate_rows),
        "disagreementRate": report.disagreement_rate,
        "differentiatorNoneRate": report.differentiator_none_rate,
        "restrictionUncheckedCount": report.restriction_unchecked_count,
        "preflight": preflight.status,
        "assemblyGateRejectCount": len(assembly.gate_rejects),
    }

    docs = {
        "accepted": build_envelope("action-seed", assembly.assembled_rows, dict(base_meta)),
        "blocked": build_envelope("action-review", by_outcome["blocked"], dict(base_meta)),
        "unresolved": build_envelope("action-review", by_outcome["unresolved"], dict(base_meta)),
        "escalated": build_envelope("action-review", by_outcome["escalated"], dict(base_meta)),
    }

    if write:
        round_dir = ACTIONS_ROOT / "_rounds" / f"round-{round_no}"
        round_dir.mkdir(parents=True, exist_ok=True)
        for name, doc in docs.items():
            (round_dir / f"{name}.json").write_text(canonical_dump(doc), encoding="utf-8")

    return {
        "round": round_no, "candidateCount": len(candidate_rows),
        "acceptedCount": len(assembly.assembled_rows),
        "validatedAcceptedCount": len(by_outcome["accepted"]),
        "assemblyGateRejectCount": len(assembly.gate_rejects),
        "blockedCount": len(by_outcome["blocked"]),
        "unresolvedCount": len(by_outcome["unresolved"]), "escalatedCount": len(by_outcome["escalated"]),
        "candidateSetHash": candidate_set_hash(candidate_rows), "disagreementRate": report.disagreement_rate,
        "differentiatorNoneRate": report.differentiator_none_rate,
        "restrictionUncheckedCount": report.restriction_unchecked_count,
        "preflight": preflight.status, "written": bool(write),
    }


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Validate + bounded-self-heal one round of action-corpus candidates (A-S4).")
    ap.add_argument("--candidates", nargs="+", default=None,
                    help="one or more A-P1/A-P2/A-P3 action-candidate envelopes; defaults to all "
                         "present round-1 partitions")
    ap.add_argument("--briefs", default=None,
                    help="path to A-S1's own brief JSON envelope for this round; defaults to the "
                         "selected round")
    ap.add_argument("--round", type=int, default=1, dest="round_no")
    ap.add_argument("--dry-run", action="store_true",
                    help="gate the recorded candidate set with zero model calls -- preflight is skipped")
    ap.add_argument("--preflight", action="store_true", dest="do_preflight",
                    help="prove constrained decoding with one real call before running (ignored under --dry-run)")
    args = ap.parse_args(argv)

    paths = ([Path(p) for p in args.candidates] if args.candidates
             else available_candidate_paths_for_round(args.round_no))
    if not paths:
        raise ValueError(f"round-{args.round_no}: no action-candidate partitions found")
    briefs_path = Path(args.briefs) if args.briefs else briefs_path_for_round(args.round_no)
    summary = regenerate(candidates_path=paths, briefs_path=briefs_path,
                         round_no=args.round_no, dry_run=args.dry_run,
                         do_preflight=args.do_preflight, write=not args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
