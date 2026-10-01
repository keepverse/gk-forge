"""seedsmith.adapters.actions.generate_brief_assembly — A-S2's entrypoint (spec-brief-assembly.md).
Reads:

    <plan>              A-S1's own brief envelope for this round (`distribution_planner`'s
                          output, `kind: "action-brief"`) -- quotas, rung windows, family-access
                          sets, the anchor. Every non-`familyActions` field of every emitted P3
                          brief comes from here, byte-identical (spec §4: never re-derived).
    <accepted-round>    A-P2's round, AFTER A-S4 validation and A-S3 dedup, id-assigned -- the
                          A-C1 `action-seed` envelope A-S3's own entrypoint already writes
                          (`generate_dedup_select.py`'s `survivors.json`). Never a raw/unaccepted
                          A-P2 proposal set (spec §3.1, §4).

and writes, through the A-C1 envelope:

    data/seed/actions/_rounds/round-<n>/p3-briefs.json    kind: "action-brief" -- one entry per
                                                            species-scope (signature) plan entry,
                                                            each carrying `familyActions`

**No shipped default for either input.** A-P2 (`family-propose`) is not built, so there is no real
accepted-round file anywhere in this checkout to point a default at -- the same "no shipped
default" reasoning `generate_dedup_select.py`'s own docstring already states for its own
`--candidates`. `<plan>` has a real shipped file today (`gk-data/packs/fusion/data/seed/actions/_briefs/round-1.json`)
but this module treats it the same way `generate_validate_heal.py` treats `--briefs`: named
explicitly by the caller every time, never guessed, so this entrypoint works unchanged against any
round's plan, not just round 1.

**Acceptance gating happens at the envelope's own `kind` tag.** `<accepted-round>` must carry
`kind: "action-seed"` -- exactly the tag A-S3's own `survivors.json` and A-S6's own committed-round
files carry, and exactly what `generate_dedup_select.py` (line 56-59) and `generate_innate_picker.py`
already gate their own accepted-corpus reads on. A `kind: "action-review"` / `"action-reject"`
round file -- A-S4's blocked/unresolved/escalated buckets, or A-S3's own rejects.json -- is refused
here rather than silently read as though it were accepted output.

**Zero model calls, permanently** -- there is no LLM transport import anywhere in this module or
its `brief_assembly` package (this module makes no judgement, purely mechanical assembly; spec §4's
first line, "never call a model").
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .brief_assembly import derive as ba
from .vocab import load_family_ids

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


def regenerate(*, plan_path: Path, accepted_round_path: Path, actions_root: Path = ACTIONS_ROOT,
              round_no: int = 1, write: bool = True) -> dict:
    """Pure computation + (optionally) one file write. Returns a summary dict for the caller to
    report -- never prints itself, so a test can call this without capturing stdout."""
    plan_doc = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan_doc.get("kind") != "action-brief":
        raise ValueError(f"{plan_path}: expected an 'action-brief' envelope (A-S1's plan) -- "
                         f"got kind={plan_doc.get('kind')!r}")
    plan_entries = plan_doc.get("entries") or []

    accepted_doc = json.loads(accepted_round_path.read_text(encoding="utf-8"))
    if accepted_doc.get("kind") != "action-seed":
        raise ValueError(
            f"{accepted_round_path}: expected an 'action-seed' envelope (A-P2's round, after "
            f"A-S4 validation and A-S3 dedup, id-assigned) -- got kind={accepted_doc.get('kind')!r} "
            f"-- refused (spec-brief-assembly.md §3.1/§4: never assemble from unaccepted output)")
    accepted_rows = accepted_doc.get("entries") or []

    family_ids = load_family_ids()
    briefs = ba.assemble_briefs(plan_entries, accepted_rows, family_ids)

    for b in briefs:
        ba.require_family_actions(b)              # the absence-vs-empty contract, proven on our own output

    species_count = sum(1 for e in plan_entries if e.get("scope") == "species")
    family_less_count = sum(1 for b in briefs if not b["familyActions"] and
                            not (b.get("anchor") or {}).get("family"))
    envelope = ba.build_envelope(briefs, meta={
        "partition": f"round-{round_no}", "round": round_no,
        "planPath": str(plan_path), "acceptedRoundPath": str(accepted_round_path),
        # Preserve A-S1's round-wide digest so every downstream proposer can prove which
        # complete brief plan its model calls answered. The accepted-round digest below is a
        # different input and must not be substituted for it.
        "planCorpusHash": plan_doc.get("_meta", {}).get("corpusHash"),
        # The accepted P2 round's OWN candidate-set digest (A-S3's `_meta.corpusHash` on its own
        # survivors envelope, `dedup_select.derive.RoundResult.corpus_hash`) -- carried through
        # here so A-P3 (signature-propose) never has to re-open `accepted_round_path` itself just
        # to record "which P2 round did I differ against" in its own `_provenance`
        # (spec-signature-propose.md SS5 acceptance #10). `None` when the accepted round carries
        # no `_meta.corpusHash` of its own (a synthetic/partial fixture, not A-S3's real output).
        "acceptedRoundCorpusHash": accepted_doc.get("_meta", {}).get("corpusHash"),
    })

    if write:
        round_dir = actions_root / "_rounds" / f"round-{round_no}"
        round_dir.mkdir(parents=True, exist_ok=True)
        (round_dir / "p3-briefs.json").write_text(ba.canonical_dump(envelope), encoding="utf-8")

    return {
        "round": round_no,
        "planSpeciesEntryCount": species_count,
        "briefCount": len(briefs),
        "familyLessBriefCount": family_less_count,
        "acceptedRowCount": len(accepted_rows),
        "written": bool(write),
    }


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Assemble A-P3's brief -- A-S1's plan plus A-P2's accepted familyActions (A-S2).")
    ap.add_argument("--plan", required=True, help="path to A-S1's own action-brief envelope for this round")
    ap.add_argument("--accepted-round", required=True, dest="accepted_round",
                    help="path to A-P2's accepted, deduped, id-assigned action-seed envelope")
    ap.add_argument("--round", type=int, default=1, dest="round_no")
    ap.add_argument("--dry-run", action="store_true", help="compute and print, write nothing")
    args = ap.parse_args(argv)

    summary = regenerate(plan_path=Path(args.plan), accepted_round_path=Path(args.accepted_round),
                         round_no=args.round_no, write=not args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
