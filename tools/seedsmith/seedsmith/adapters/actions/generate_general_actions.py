"""seedsmith.adapters.actions.generate_general_actions --- A-P1 "general-propose"'s own entrypoint
(spec-general-propose.md, action-corpus program). Mirrors
`adapters/effects/affix/generate_affixes.py`'s own `--dry-run`/`--count` shape (SS1's own named
precedent), adapted for a pipeline that reads a PLANNED brief (A-S1's `_briefs/round-<n>.json`)
rather than computing its own eligible pool, and that votes three permuted samples per brief
instead of calling once.

    python -m seedsmith.adapters.actions.generate_general_actions --dry-run          # briefs only
    python -m seedsmith.adapters.actions.generate_general_actions --count 5          # real calls

**Where candidates land, decided here because no prior module decided it.** Spec SS3 forbids
writing into `gk-data/packs/fusion/data/seed/actions/` in the sense that matters -- an ACCEPTED `kind: "action-seed"`
entry at the corpus root ("Acceptance is A-S3's; persistence is A-S6's"). It does not forbid the
whole subtree: A-S1 already writes `_briefs/` and A-S4 already writes `_rounds/` there, both
underscore-prefixed scratch directories a fellow module in this exact domain owns. Neither A-S1
nor A-S4's own entrypoint (`generate_validate_heal.py`'s `--candidates` flag has no committed
default) named where a GENERATION stage's own pre-acceptance candidates should land, so this build
follows the same convention: `data/seed/actions/_candidates/general/round-<n>.json`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ...pipeline.llm_caller import LlmCallerConfig, resolve_live_transport
from .distribution_planner.derive import load_pairing_table
from .generation_batches import load_resume_entries, merge_entries, select_brief_batch
from .general_propose.derive import candidate_row, candidate_set_hash, canonical_dump, propose_general_action
from .general_propose.prompts import build_brief, build_context, render_worked_example
from .vocab import load_family_glossary

__all__ = ["run", "regenerate", "load_general_briefs", "ACTIONS_ROOT", "BRIEFS_PATH"]

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
BRIEFS_PATH = ACTIONS_ROOT / "_briefs" / "round-1.json"
PAIRINGS_PATH = ACTIONS_ROOT / "pairings.json"
CANDIDATES_DIR = ACTIONS_ROOT / "_candidates" / "general"

PROMPT_VERSION = "general-propose/1"


def _brief_hash(brief: dict) -> str:
    """Acceptance #8: "`_provenance` records ... brief hash" -- per CANDIDATE, over the exact
    brief it answers, so a rerun over one unchanged brief is verifiably unchanged even when a
    sibling brief in the same round moved. Never `briefsCorpusHash` (a round-wide digest A-S1
    already stamps in `_meta`) -- that is carried alongside it for the round-level check, not in
    its place."""
    blob = json.dumps(brief, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _general_briefs_of(doc: dict) -> "list[dict]":
    """Every `scope: "general"` entry of A-S1's round envelope, sorted by `briefId` -- never
    dict/filesystem iteration order."""
    general = [e for e in doc.get("entries", []) if e.get("scope") == "general"]
    general.sort(key=lambda b: b.get("briefId") or "")
    return general


def load_general_briefs(briefs_path: Path = BRIEFS_PATH) -> "list[dict]":
    return _general_briefs_of(json.loads(briefs_path.read_text(encoding="utf-8")))


def regenerate(*, briefs_path: Path = BRIEFS_PATH, pairings_path: Path = PAIRINGS_PATH,
              candidates_dir: Path = CANDIDATES_DIR, count: int = 1, dry_run: bool = True,
              round_no: int = 1, write: bool = True,
              resume: bool = False, config: LlmCallerConfig | None = None) -> dict:
    """Pure-ish computation (`dry_run=True` makes zero model calls and writes nothing regardless
    of `write`) plus, on a real run, up to `count * 3 * (MAX_HEAL + 1)` model calls and one file
    write. Returns a summary dict; never prints itself, matching `generate_distribution_planner
    .regenerate`'s own "a test can call this without capturing stdout" convention."""
    briefs_doc = json.loads(briefs_path.read_text(encoding="utf-8"))
    general_briefs = _general_briefs_of(briefs_doc)
    output_path = candidates_dir / f"round-{round_no}.json"
    plan_hash = briefs_doc.get("_meta", {}).get("corpusHash")
    existing_entries = (load_resume_entries(
        output_path, partition="general", round_no=round_no, briefs_corpus_hash=plan_hash)
        if resume else [])
    selected = (select_brief_batch(general_briefs, count=count, existing_entries=existing_entries)
                if resume else general_briefs[:max(0, count)])
    brief_index = {brief["briefId"]: i for i, brief in enumerate(general_briefs)}

    pairing_table = load_pairing_table(pairings_path) if pairings_path.is_file() else {}
    #: SMOKE BATCH criterion-2 fix, 2026-09-05: read fresh every call, never cached (matches
    #: `load_family_ids`'s own discipline) -- see `vocab.load_family_glossary`'s own docstring.
    family_glossary = load_family_glossary()
    #: SMOKE BATCH criterion-2 PROBE, 2026-09-05: rendered once per run (not once per brief, and
    #: never per sample -- it is one fixed illustration, the same text everywhere it is used) --
    #: see `general_propose.prompts.render_worked_example`'s own docstring. `""` when the pinned
    #: pair cannot be found, which `build_context` already treats as "no worked example".
    worked_example = render_worked_example(family_glossary)

    if dry_run:
        sample_brief_text = ""
        if selected:
            context = build_context(selected[0], sample_index=0, pairing_table=pairing_table,
                                    family_glossary=family_glossary, worked_example=worked_example)
            sample_brief_text = build_brief(context)
        return {
            "dryRun": True,
            "totalGeneralBriefs": len(general_briefs),
            "selected": len(selected),
            "modelCalls": 0,
            "sampleBrief": sample_brief_text,
        }

    if config is None:
        config = resolve_live_transport()
    base_provenance = {
        "pipeline": "general-propose", "model": config.model, "promptVersion": PROMPT_VERSION,
        "briefsCorpusHash": briefs_doc.get("_meta", {}).get("corpusHash"),
    }

    rows: "list[dict]" = []
    by_outcome: "dict[str, int]" = {}
    for i, brief in enumerate(selected):
        candidate_id = f"candidate.general.{brief_index[brief['briefId']]:03d}"
        prov = dict(base_provenance)
        prov["briefHash"] = _brief_hash(brief)
        candidate = propose_general_action(
            brief, candidate_id=candidate_id, pairing_table=pairing_table,
            family_glossary=family_glossary, worked_example=worked_example,
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
            "partition": "general", "round": round_no, "promptVersion": PROMPT_VERSION,
            "model": config.model, "candidateSetHash": set_hash,
            "briefsCorpusHash": base_provenance["briefsCorpusHash"],
        },
        "entries": rows,
    }

    if write:
        candidates_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_text(canonical_dump(out_doc), encoding="utf-8")

    return {
        "dryRun": False,
        "totalGeneralBriefs": len(general_briefs),
        "selected": len(selected),
        "resumed": len(existing_entries),
        "remaining": sum(1 for brief in general_briefs
                         if not any(e.get("briefId") == brief["briefId"] and
                                    e.get("outcome") in {"accepted", "blocked", "escalated"}
                                    for e in rows)),
        "byOutcome": by_outcome,
        "candidateSetHash": set_hash,
        "written": bool(write),
    }


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Propose general-scope actions from A-S1's planned briefs (A-P1 'general-propose').")
    ap.add_argument("--dry-run", action="store_true", help="render briefs, make no model calls")
    ap.add_argument("--count", type=int, default=1, help="how many briefs to draw a candidate for")
    ap.add_argument("--round", type=int, default=1, help="the round number this run writes")
    ap.add_argument("--resume", action="store_true",
                    help="merge this batch into the existing partition and skip terminal rows")
    ap.add_argument("--endpoint", default="")
    ap.add_argument("--model", default="")
    args = ap.parse_args(argv)

    summary = regenerate(count=args.count, dry_run=args.dry_run, round_no=args.round,
                         config=resolve_live_transport(args.endpoint, args.model),
                         resume=args.resume)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
