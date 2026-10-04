"""seedsmith.adapters.actions.generate_signature_actions --- A-P3 "signature-propose"'s own
entrypoint (spec-signature-propose.md, action-corpus program). Mirrors
`generate_family_actions.py`'s own `--dry-run`/`--count` shape (itself modelled on
`adapters/effects/affix/generate_affixes.py`), adapted for a pipeline that reads A-S2's own
ASSEMBLED brief (`brief_assembly`, carrying `familyActions` -- never A-S1's raw plan directly, spec
SS0/SS6) and votes three permuted samples per brief over BOTH `atomFamilies` and `differentiator`.

    python -m seedsmith.adapters.actions.generate_signature_actions --briefs <path> --dry-run
    python -m seedsmith.adapters.actions.generate_signature_actions --briefs <path> --count 5

**No shipped default for `--briefs`.** A-S2 (`brief_assembly`) has never run for real in this
checkout -- there is no `data/seed/actions/_rounds/round-<n>/p3-briefs.json` anywhere on disk yet,
since A-P2's own round has never run for real either. Same "no shipped default" reasoning
`generate_brief_assembly.py`'s own docstring already states for ITS OWN `--plan`/`--accepted-round`:
`--briefs` is named explicitly by the caller every time, never guessed at a path that may not
exist -- this entrypoint works unchanged against any round's assembled briefs, not just a round-1
file that happens to exist today.

**Where candidates land, following `generate_family_actions.py`'s own precedent exactly** (spec SS3
forbids writing an ACCEPTED `kind: "action-seed"` entry at the corpus root -- "Acceptance is A-S3's;
persistence is A-S6's" -- never the whole `_`-prefixed scratch subtree A-S1/A-S2/A-S4 already
share): `data/seed/actions/_candidates/signature/round-<n>.json`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ...pipeline.llm_caller import LlmCallerConfig, resolve_live_transport
from .distribution_planner.derive import load_pairing_table
from .signature_propose.derive import (
    candidate_row,
    candidate_set_hash,
    canonical_dump,
    propose_signature_action,
)
from .signature_propose.prompts import build_brief, build_context
from .generation_batches import load_resume_entries, merge_entries, select_brief_batch
from .usage_direction.weights import latest_usage_report_path, weights_from_usage_report
from .vocab import load_family_glossary

__all__ = ["run", "regenerate", "load_signature_briefs", "ACTIONS_ROOT", "PAIRINGS_PATH", "CANDIDATES_DIR"]

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
PAIRINGS_PATH = ACTIONS_ROOT / "pairings.json"
CANDIDATES_DIR = ACTIONS_ROOT / "_candidates" / "signature"
USAGE_REPORTS_DIR = _owned("docs/research/action-corpus")

PROMPT_VERSION = "signature-propose/1"


def _brief_hash(brief: dict) -> str:
    """Acceptance #10: "`_provenance` records ... brief hash" -- per CANDIDATE, over the exact
    brief it answers, so a rerun over one unchanged brief is verifiably unchanged even when a
    sibling brief in the same round moved. Never `briefsCorpusHash` (a round-wide digest carried
    alongside it for the round-level check, not in its place). Identical to
    `generate_family_actions._brief_hash`, kept local for the same self-containment reason the
    sibling module's own functions state."""
    blob = json.dumps(brief, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _signature_briefs_of(doc: dict) -> "list[dict]":
    """Every `scope: "species"` entry of A-S2's assembled brief envelope, sorted by `briefId` --
    never dict/filesystem iteration order. A-S2's own output is species-scope only by construction
    (`brief_assembly.derive.assemble_briefs` never emits a general/family-scope entry), but this
    stays a defensive filter rather than an assumption, matching every sibling entrypoint's own
    `_family_briefs_of`/`_general_briefs_of` discipline."""
    species = [e for e in doc.get("entries", []) if e.get("scope") == "species"]
    species.sort(key=lambda b: b.get("briefId") or "")
    return species


def load_signature_briefs(briefs_path: Path) -> "list[dict]":
    return _signature_briefs_of(json.loads(briefs_path.read_text(encoding="utf-8")))


def regenerate(*, briefs_path: Path, pairings_path: Path = PAIRINGS_PATH,
              candidates_dir: Path = CANDIDATES_DIR, count: int = 1, dry_run: bool = True,
              round_no: int = 1, write: bool = True,
              usage_reports_dir: "Path | None" = USAGE_REPORTS_DIR,
              resume: bool = False, config: LlmCallerConfig | None = None) -> dict:
    """Pure-ish computation (`dry_run=True` makes zero model calls and writes nothing regardless
    of `write`) plus, on a real run, up to `count * 3 * (MAX_HEAL + 1)` model calls and one file
    write. Returns a summary dict; never prints itself, matching
    `generate_distribution_planner.regenerate`'s own "a test can call this without capturing
    stdout" convention.

    `briefs_path` must resolve to an `action-brief` envelope A-S2 (`brief_assembly`) assembled --
    refused otherwise, the same `kind`-tag gating `generate_brief_assembly.py` and
    `generate_dedup_select.py` already apply to their own upstream reads, rather than silently
    reading a wrong-shaped file as though it were this stage's real input."""
    briefs_doc = json.loads(briefs_path.read_text(encoding="utf-8"))
    if briefs_doc.get("kind") != "action-brief":
        raise ValueError(
            f"{briefs_path}: expected an 'action-brief' envelope (A-S2's own assembled P3 "
            f"briefs, brief_assembly.derive.build_envelope) -- got kind={briefs_doc.get('kind')!r}"
        )
    signature_briefs = _signature_briefs_of(briefs_doc)
    output_path = candidates_dir / f"round-{round_no}.json"
    plan_hash = (briefs_doc.get("_meta", {}).get("planCorpusHash") or
                 briefs_doc.get("_meta", {}).get("corpusHash"))
    existing_entries = (load_resume_entries(
        output_path, partition="signature", round_no=round_no, briefs_corpus_hash=plan_hash)
        if resume else [])
    selected = (select_brief_batch(signature_briefs, count=count, existing_entries=existing_entries)
                if resume else signature_briefs[:max(0, count)])
    brief_index = {brief["briefId"]: i for i, brief in enumerate(signature_briefs)}

    pairing_table = load_pairing_table(pairings_path) if pairings_path.is_file() else {}
    #: SMOKE BATCH criterion-2 fix, 2026-09-05: read fresh every call, never cached -- see
    #: `vocab.load_family_glossary`'s own docstring.
    family_glossary = load_family_glossary()

    # ⛔ Real gap closed 2026-09-06: this entrypoint never threaded roster-balance's own FC3
    # `usage_weights` fix through to real calls -- proven correct against FC1's report, but
    # inert here since nothing ever passed it in. Read the latest FC1 report (never required --
    # `weights_from_usage_report` degrades to `None`/`{}` exactly like an omitted
    # `family_glossary`, so a checkout with no report yet renders byte-identical to today).
    usage_weights: "dict[str, int] | None" = None
    if usage_reports_dir is not None:
        report_path = latest_usage_report_path(usage_reports_dir)
        if report_path is not None:
            usage_weights = weights_from_usage_report(json.loads(report_path.read_text(encoding="utf-8")))

    if dry_run:
        sample_brief_text = ""
        if selected:
            context = build_context(selected[0], sample_index=0, pairing_table=pairing_table,
                                    family_glossary=family_glossary, usage_weights=usage_weights)
            sample_brief_text = build_brief(context)
        return {
            "dryRun": True,
            "totalSignatureBriefs": len(signature_briefs),
            "selected": len(selected),
            "modelCalls": 0,
            "sampleBrief": sample_brief_text,
        }

    meta = briefs_doc.get("_meta") or {}
    if config is None:
        config = resolve_live_transport()
    base_provenance = {
        "pipeline": "signature-propose", "model": config.model, "promptVersion": PROMPT_VERSION,
        # A-S2 carries A-S1's plan digest under its own explicit key. Keep the old generic key as
        # a read-only fallback for hand-built/legacy fixtures.
        "briefsCorpusHash": meta.get("planCorpusHash", meta.get("corpusHash")),
        # Acceptance #10's own EXTRA field relative to A-P1/A-P2: "the P2 candidate-set hash this
        # round differed against". A-S2's own envelope meta (`generate_brief_assembly.regenerate`)
        # carries the accepted P2 round's own `_meta.corpusHash` forward under this key, so this
        # stage never has to re-open the accepted-round file itself just to record which P2 round
        # it read `familyActions` from.
        "p2CandidateSetHash": meta.get("acceptedRoundCorpusHash"),
    }

    rows: "list[dict]" = []
    by_outcome: "dict[str, int]" = {}
    for i, brief in enumerate(selected):
        candidate_id = f"candidate.signature.{brief_index[brief['briefId']]:03d}"
        prov = dict(base_provenance)
        prov["briefHash"] = _brief_hash(brief)
        candidate = propose_signature_action(
            brief, candidate_id=candidate_id, pairing_table=pairing_table,
            family_glossary=family_glossary, usage_weights=usage_weights,
            config=config, provenance=prov,
        )
        row = candidate_row(candidate)
        rows.append(row)
        by_outcome[candidate.outcome] = by_outcome.get(candidate.outcome, 0) + 1

    rows.sort(key=lambda r: r["briefId"])
    rows = merge_entries(existing_entries, rows) if resume else rows
    set_hash = candidate_set_hash(rows)

    out_doc = {
        "schemaVersion": 1,
        "kind": "action-candidate",
        "_meta": {
            "partition": "signature", "round": round_no, "promptVersion": PROMPT_VERSION,
            "model": config.model, "candidateSetHash": set_hash,
            "briefsCorpusHash": base_provenance["briefsCorpusHash"],
            "p2CandidateSetHash": base_provenance["p2CandidateSetHash"],
        },
        "entries": rows,
    }

    if write:
        candidates_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_text(canonical_dump(out_doc), encoding="utf-8", newline="\n")

    return {
        "dryRun": False,
        "totalSignatureBriefs": len(signature_briefs),
        "selected": len(selected),
        "resumed": len(existing_entries),
        "remaining": sum(1 for brief in signature_briefs
                         if not any(e.get("briefId") == brief["briefId"] and
                                    e.get("outcome") in {"accepted", "blocked", "escalated"}
                                    for e in rows)),
        "byOutcome": by_outcome,
        "candidateSetHash": set_hash,
        "written": bool(write),
    }


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Propose signature-scope actions from A-S2's assembled briefs (A-P3 'signature-propose').")
    ap.add_argument("--briefs", required=True,
                    help="path to A-S2's own assembled action-brief envelope for this round (p3-briefs.json)")
    ap.add_argument("--dry-run", action="store_true", help="render briefs, make no model calls")
    ap.add_argument("--count", type=int, default=1, help="how many briefs to draw a candidate for")
    ap.add_argument("--round", type=int, default=1, dest="round_no", help="the round number this run writes")
    ap.add_argument("--resume", action="store_true",
                    help="merge this batch into the existing partition and skip terminal rows")
    ap.add_argument("--endpoint", default="")
    ap.add_argument("--model", default="")
    args = ap.parse_args(argv)

    summary = regenerate(briefs_path=Path(args.briefs), count=args.count, dry_run=args.dry_run,
                         round_no=args.round_no,
                         config=resolve_live_transport(args.endpoint, args.model),
                         resume=args.resume)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
