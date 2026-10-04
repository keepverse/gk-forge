"""seedsmith.adapters.actions.generate_innate_picker — A-S6's entrypoint (spec-innate-picker.md).
Reads:

    gk-data/packs/fusion/data/seed/actions/ (excluding `_rounds/`)                the already-accepted corpus, via
                                                                A-C1's own `load_committed`
                                                                (`../load.py`)
    data/seed/actions/_rounds/round-<n>/survivors.json        A-S3's survivors for the round, if
                                                                the round ran (today: usually
                                                                absent — A-S4/A-S3 have not run for
                                                                real; see `innate_picker/derive.py`'s
                                                                own module docstring)
    gk-data/packs/fusion/data/seed/actions/_generated/role-lean.json               A-S0 — leanOrder/leanSource/family/
                                                                motifs
    gk-data/packs/fusion/data/seed/creatures/species/**/*.json                      the live roster, seed order + element
                                                                (parsed via `characteristic_pool.catalog`)
    gk-core/data/tuning/action-innate-picker.v1.json                  this module's OWN tuning file (the
                                                                five `w_t`)

and writes, through the A-C1 envelope:

    gk-data/packs/fusion/data/seed/actions/species-innate.json      kind: "action-innate"

and, only when `_rounds/round-<n>/survivors.json` holds real (un-promoted) candidate rows,
performs the promotion MOVE (spec §3.4 step 6b, review F14):

    data/seed/actions/committed-round-<n>.json           kind: "action-seed" — every round row
                                                          this module commits, the picked winner's
                                                          own `kindHint` overwritten to "innate"
    data/seed/actions/_rounds/round-<n>/survivors.json   rewritten IN PLACE — `entries` reduced to
                                                          `{"id": ..., "promoted": true}` markers

**No committed-round file name is spec'd** — §3.4 step 6b says only "written into the committed
corpus at the seed root". `committed-round-<n>.json` is this module's own choice, flagged here
rather than presented as a citation: a plain, non-underscore-prefixed root file, so A-C1's loader
picks it up automatically (zero `_manifest.json` change needed — the same reason `type-weights.json`
needs none: `load.py:_classify_files` only requires a manifest row for an UNDERSCORE-prefixed
directory or a non-envelope file, and this file is a real `kind`+`entries` envelope at the root).

**Zero model calls, permanently** — there is no LLM transport import anywhere in this module or
its `innate_picker` package (spec's own opening line; `OfflineGuaranteeTests` in this module's own
test suite asserts it directly).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .characteristic_pool.catalog import CATALOG_PATH, load_catalog
from .distribution_planner.derive import load_scope_windows
from .generate_distribution_planner import RUNGS_PATH as RUNG_TABLE_PATH
from .innate_picker import derive as ip
from .innate_picker.tuning import INNATE_TUNING_PATH, load_innate_weights
from .load import load_committed

__all__ = ["run", "regenerate", "ACTIONS_ROOT", "ROLE_LEAN_PATH"]

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
ROLE_LEAN_PATH = ACTIONS_ROOT / "_generated" / "role-lean.json"


def regenerate(*, actions_root: Path = ACTIONS_ROOT, catalog_path: Path = CATALOG_PATH,
              role_lean_path: Path = ROLE_LEAN_PATH, tuning_path: Path = INNATE_TUNING_PATH,
              rung_table_path: Path = RUNG_TABLE_PATH,
              round_no: int = 1, write: bool = True) -> dict:
    """Pure computation + (optionally) file writes. Returns a summary dict for the caller to
    report — never prints itself, so a test can call this without capturing stdout."""
    weights = load_innate_weights(tuning_path)
    species_rows = load_catalog(catalog_path)
    # ST3 (`spec-scope-window-tunables.md` contract 3): the `+cap` offset is the species rung
    # window's own ceiling, loaded HERE once from the published table and passed down -- the picker
    # no longer imports a code constant for it.
    cap = load_scope_windows(rung_table_path)["species"][1]

    role_lean_doc = json.loads(role_lean_path.read_text(encoding="utf-8"))
    role_lean_by_key = ip.parse_role_lean_doc(role_lean_doc)
    species_ids = {row.species_id for row in species_rows}
    if set(role_lean_by_key) != species_ids:
        missing = sorted(species_ids - set(role_lean_by_key))
        extra = sorted(set(role_lean_by_key) - species_ids)
        raise ValueError(
            "role-lean.json is stale relative to the live species seed folder: "
            f"missing={missing[:5]!r}, extra={extra[:5]!r}"
        )

    load_result = load_committed(actions_root)          # excludes `_rounds/` already (A-C1)
    committed_rows = [e.data for e in load_result.corpus.by_kind("action-seed")]

    pruned_survivors: "dict[str, int]" = {}
    if write:
        # Phase-4 A4 (2026-09-15) — cross-round sweep BEFORE reading any survivors file: a
        # LATER round's promotion commits ids that may still sit as FULL rows in an EARLIER
        # round's survivors file (measured: round-1 held 11 full rows committed by round-2000's
        # run), and re-reading them below would RE-PROMOTE them into a second committed file.
        # Reducing them to markers first makes re-promotion impossible by construction: markers
        # carry no `scope`, so the scope filter below skips them.
        committed_ids = {r.get("id") for r in committed_rows if r.get("id") is not None}
        pruned_survivors = _prune_stale_survivors(actions_root, committed_ids)

    round_dir = actions_root / "_rounds" / f"round-{round_no}"
    survivors_path = round_dir / "survivors.json"
    round_doc: "dict | None" = None
    round_rows: "list[dict]" = []
    if survivors_path.is_file():
        round_doc = json.loads(survivors_path.read_text(encoding="utf-8"))
        # A row already reduced to a `promoted` marker (an earlier run of this module) carries no
        # `scope` -- never re-processed, matching "one id exists in exactly one place".
        round_rows = [r for r in (round_doc.get("entries") or []) if "scope" in r]

    all_accepted = committed_rows + round_rows

    picks, promotions = ip.pick_all_species(
        species_rows=species_rows, role_lean_by_key=role_lean_by_key,
        candidate_rows=all_accepted, weights=weights, cap=cap,
    )
    entries = ip.build_entries(picks)

    innate_doc = ip.build_envelope(entries, meta={
        "partition": "innate", "corpusHash": ip.corpus_hash(all_accepted),
        "tuningVersion": weights.version,
    })

    if write:
        (actions_root / "species-innate.json").write_text(
            ip.canonical_dump(innate_doc), encoding="utf-8", newline="\n")

    committed_written = False
    if round_rows and write:
        promoted_rows = ip.apply_promotions(round_rows, promotions)
        committed_path = actions_root / f"committed-round-{round_no}.json"
        if committed_path.is_file():
            # Union, never overwrite (see `merge_committed`): survivors hold leftovers, not the
            # round's full output, so a plain write would delete already-committed rows.
            prior_doc = json.loads(committed_path.read_text(encoding="utf-8"))
            promoted_rows = ip.merge_committed(prior_doc.get("entries") or (), promoted_rows)
        committed_doc = ip.build_committed_envelope(promoted_rows, meta={
            "partition": f"round-{round_no}", "round": round_no,
            "corpusHash": ip.corpus_hash(promoted_rows),
        })
        committed_path.write_text(ip.canonical_dump(committed_doc), encoding="utf-8", newline="\n")

        markers = ip.reduce_round_survivors_to_markers(round_rows)
        new_round_doc = dict(round_doc)
        new_round_doc["entries"] = markers
        survivors_path.write_text(ip.canonical_dump(new_round_doc), encoding="utf-8", newline="\n")
        committed_written = True
        # Post-promotion sweep: this run just committed `round_rows` — any OTHER round's
        # survivors file holding the same ids as full rows (measured 2026-09-15: round-1000
        # still held `academic.004`, promoted into committed-round-1.json by this same run)
        # is reduced now, so the invariant holds when this call returns, not just before it.
        newly_committed = {r.get("id") for r in round_rows if r.get("id") is not None}
        for rnd, count in _prune_stale_survivors(actions_root, newly_committed).items():
            pruned_survivors[rnd] = pruned_survivors.get(rnd, 0) + count

    picked_count = sum(1 for p in picks if p.innate_action_id is not None)
    return {
        "round": round_no,
        "speciesCount": len(species_rows),
        "pickedCount": picked_count,
        "nullCount": len(picks) - picked_count,
        "candidateCount": len(all_accepted),
        "committedRoundWritten": committed_written,
        "prunedStaleSurvivors": pruned_survivors,
        "written": bool(write),
    }


def _prune_stale_survivors(actions_root: Path, committed_ids: "set[str]") -> "dict[str, int]":
    """Reduce committed-id FULL rows to markers in every `_rounds/*/survivors.json`.

    Returns `{round_dir_name: pruned_row_count}` for files actually rewritten; untouched files
    (markers only, genuinely-new rows only, missing, or malformed scratch the pipeline itself
    will refuse later) are left byte-identical. Sorted directory order — deterministic."""
    pruned: "dict[str, int]" = {}
    rounds_dir = actions_root / "_rounds"
    if not rounds_dir.is_dir():
        return pruned
    for round_dir in sorted(p for p in rounds_dir.iterdir() if p.is_dir()):
        path = round_dir / "survivors.json"
        if not path.is_file():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries = doc.get("entries") or []
        fixed = ip.drop_committed_full_rows(entries, committed_ids)
        converted = sum(1 for old, new in zip(entries, fixed)
                        if new.get("promoted") and not old.get("promoted"))
        if converted:
            doc = dict(doc)
            doc["entries"] = fixed
            path.write_text(ip.canonical_dump(doc), encoding="utf-8", newline="\n")
            pruned[round_dir.name] = converted
    return pruned


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Pick each species' innate action and commit the accepted corpus (A-S6).")
    ap.add_argument("--round", type=int, default=1, dest="round_no")
    ap.add_argument("--dry-run", action="store_true", help="compute and print, write nothing")
    args = ap.parse_args(argv)

    summary = regenerate(round_no=args.round_no, write=not args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
