"""seedsmith.adapters.actions.generate_distribution_planner — A-S1 "Engine 1"'s entrypoint
(spec-distribution-planner.md). Reads:

    gk-data/packs/fusion/data/seed/actions/_generated/role-lean.json       (A-S0 — species anchor + family membership)
    gk-data/packs/fusion/data/seed/creatures/species/**/*.json                      (live species and family fields)
    gk-data/packs/fusion/data/seed/actions/type-weights.json                (A-T1 — categoryMilli/targetModeMilli/...)
    gk-core/data/tuning/action-rungs.v4.json                   (the 10-row rung table)
    gk-core/data/tuning/action-corpus-run.v1.json              (this module's OWN new tuning file)
    gk-core/data/tuning/action-dedup.v1.json                   (A-S3's -- read, never written; MISSING in
                                                          this checkout, see distribution_planner/
                                                          tuning.py's own docstring for the default)
    gk-data/packs/fusion/data/seed/items/affix-families/*.json              (the 98-family namespace)
    gk-data/packs/fusion/data/seed/actions/pairings.json                    (read-only; 0 real hits today, see §2)

and writes, through the A-C1 envelope:

    gk-data/packs/fusion/data/seed/actions/_briefs/round-1.json             kind: "action-brief"

**Zero model calls** — every value here is read from a shipped table or derived from one; the
`--dry-run` flag previews the summary without writing, and `--full` alone never authorizes a full
run (see `distribution_planner.derive.refuse_full_run_if_ungated`). `--round N --top-up-from
_reports/coverage-round-<N-1>.json` plans round n+1's shortfall-only briefs from round n's report
(the `S5 → S1` edge); without `--top-up-from` the plan is the full base quota (round 1).

**The `pairings.json` rewrite named in spec §3 step 6 is explicitly OUT OF SCOPE for this module's
build** — a deliberate, owner-made scoping decision, not a shortfall. The rewrite authors NEW
payoff atom families (identity-authoring, LLM-layer work per this repo's Law 2); this module only
ever READS the pairing table, verbatim, and builds the full role-ASSIGNMENT mechanism against it
(`distribution_planner.derive.assign_pairing_roles`), proven correct in
`tests/test_distribution_planner.py` against a synthetic fixture. Against the REAL, unmodified
`pairings.json` today, every brief this module emits correctly carries `pairing.role: "none"` —
the spec's own measured, expected state (§2: neither shipped payoff key exists in the 98-family
namespace), not a partial or broken result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .characteristic_pool.catalog import (
    CATALOG_PATH, derive_live_family_assignments, load_catalog,
)
from .distribution_planner import derive as dp
from .distribution_planner.tuning import (
    DEDUP_TUNING_PATH, RUN_TUNING_PATH, load_dedup_k, load_run_tuning,
)
from .dedup_select.derive import parse_candidate
from .characteristic_pool.derive import CATEGORIES
from .vocab import SCOPES, load_family_ids

__all__ = ["run", "regenerate", "is_passing_quality_gate", "ACTIONS_ROOT", "CREATURES_ROOT"]

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
CREATURES_ROOT = _owned("data/seed/creatures")
RUNGS_PATH = _owned("data/tuning/action-rungs.v4.json")
ROLE_LEAN_PATH = ACTIONS_ROOT / "_generated" / "role-lean.json"
TYPE_WEIGHTS_PATH = ACTIONS_ROOT / "type-weights.json"
PAIRINGS_PATH = ACTIONS_ROOT / "pairings.json"
BRIEFS_DIR = ACTIONS_ROOT / "_briefs"

#: Bump ONLY when a change alters the briefs this module emits for unchanged inputs. Folded into
#: `_corpus_hash` so a plan produced by an older algorithm fails the freshness check rather than
#: silently resuming candidates generated against a different ordinal order. History:
#:   1 — 2026-09-11: initial explicit version; the ordinal-spreading fix in `expand_counts` (marginals
#:       unchanged, emitted order changed) is the change that motivated making the algorithm
#:       versioned at all.
#:   2 — 2026-09-12: generalized scope-level allocation. `apportion_axis` (deficit-greedy) now also
#:       drives `targetMode`, and `apportion_area_shapes` drives `areaShape`. `area` and its four
#:       shapes were unreachable at family/species scope before this (0 of 6,655 briefs); now ~750
#:       species / ~188 family briefs carry them. Marginals change, so the version must move.
#:   3 — 2026-09-15: top-up ordinal continuation. A top-up round's brief ordinals continue past
#:       each subject's already-planned briefs (read from prior `_briefs/round-<n>.json`) instead
#:       of restarting at 1, so round n+1 mints no id round ≤ n already used. Round-1 output for
#:       unchanged inputs is byte-identical (starts default to 1), but any top-up plan's briefs
#:       differ from what version 2 emitted under the same hash — the exact staleness class this
#:       version exists to catch — so the version moves and prior top-up plans replan.
ALGORITHM_VERSION = 3

# A-S5 writes the round-scoped quality-gate report at this path. The full-run gate below checks the
# report's measured verdict, not mere file presence.
SMOKE_GATE_EVIDENCE_PATH = ACTIONS_ROOT / "_reports" / "coverage-round-1.json"


def _canonical_dump(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def is_passing_quality_gate(path: Path, *, round_no: int = 1) -> bool:
    """Return whether an A-S5 report can authorize a full A-S1 plan.

    A report is evidence only when it is the expected envelope for this round and its closed
    metrics explicitly passed.  This deliberately fails closed for stale smoke output, malformed
    JSON, a review/reject envelope, an unevaluated metric, or any remaining gap.
    """
    if not path.is_file():
        return False
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(doc, dict) or doc.get("kind") != "action-coverage":
        return False
    meta = doc.get("_meta")
    verdict = meta.get("verdict") if isinstance(meta, dict) else None
    if not isinstance(meta, dict) or meta.get("round") != round_no or not isinstance(verdict, dict):
        return False
    # A clean smoke report is also a passing quality gate. A full report uses `pass`; a smoke
    # report uses `smoke-clean` because A-S5 deliberately never labels a partial run `pass`.
    #
    # ⛔ CORRECTED 2026-09-12 (T1.3). This gate must DEFER to A-S5's own verdict, not re-derive a
    # second rule. It used to also require `gapMetrics == []`, which is exactly the definition A-S5
    # had to abandon: `gates=False` metrics report GAPs without gating (spec-metrics.md §4), so
    # A-S5 emits `pass` with a non-empty `gapMetrics`, and the two disagreed — A-S5 said pass, the
    # gate said no. The verdict string is now the single source of truth. `NOT_MEASURED` stays
    # blocking as belt-and-braces: A-S5 never emits `pass` with an unevaluated metric, and a
    # hand-written report claiming `pass` while listing one is refused here.
    return (verdict.get("verdict") in {"pass", "smoke-clean"} and
            verdict.get("notMeasuredMetrics") == [])


def _family_members(family_assignments: dict) -> "dict[str, list[str]]":
    members: "dict[str, list[str]]" = {}
    for species_id, families in family_assignments.items():
        if isinstance(families, str):
            families = [families]
        for fam in families:
            members.setdefault(fam, []).append(species_id)
    return {fam: sorted(v) for fam, v in members.items()}


def _accepted_neighbours_by_group(
        actions_root: Path, *, before_round: int) -> "dict[tuple[str, str | None], list[tuple[str, dp.FingerprintComponents]]]":
    """§3 step 8's accepted-corpus input, grouped by `(scope, scopeKey)`.

    Reads only rounds **strictly earlier** than the round being planned
    (`committed-round-<n>.json`, `n < before_round`). This is the spec's own round-1 rule made
    precise: "round 1 reading no report" (`spec-distribution-planner.md` §7) exists so the plan is
    not circular, and the same discipline applies to the accepted corpus — a round must never be
    planned against its own already-committed output. On the live tree that means round 1 reads
    nothing (the shipped `committed-round-1/2/909.json` are not earlier than round 1), which is
    exactly what `test_round_1_has_no_accepted_corpus_avoid_neighbours_empty` pins; planning round
    910 would read all three.

    Each row is rendered with **A-S3's own `parse_candidate`**, so the neighbour fingerprint and the
    one A-S3 will judge against are one definition, never a second one shaped like it. A malformed
    committed row is skipped rather than aborting the plan: the accepted corpus is produced by an
    earlier round, and one unparseable row must not make the whole plan unbuildable. The same rows
    are separately reported by `load.load_committed`.
    """
    if before_round <= 1:
        return {}
    family_ids = load_family_ids()
    grouped: "dict[tuple[str, str | None], list[tuple[str, dp.FingerprintComponents]]]" = {}
    pattern = re.compile(r"^committed-round-(\d+)\.json$")
    for path in sorted(actions_root.glob("committed-round-*.json")):
        match = pattern.match(path.name)
        if match is None or int(match.group(1)) >= before_round:
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in doc.get("entries") or ():
            if not isinstance(row, dict):
                continue
            try:
                candidate = parse_candidate(row, family_ids)
            except ValueError:
                continue
            grouped.setdefault((candidate.scope, candidate.scope_key), []).append(
                (candidate.id, candidate.fp))
    return grouped


def _prior_brief_counts(
        actions_root: Path, *, before_round: int) -> "dict[tuple[str, str | None], int]":
    """Per-subject brief counts from already-planned rounds, for top-up ordinal continuation.

    Reads `_briefs/round-<n>.json` for `n < before_round` and counts briefs per
    `(scope, scopeKey-or-None)` — the same round discipline as `_accepted_neighbours_by_group`
    (a round must never be planned against its own output). The caller starts each top-up
    subject's ordinals past its prior count, so round n+1's
    `brief.<scope>.<key>.<ordinal>` ids never collide with round ≤ n's (`Corpus.load` refuses
    duplicate ids). Missing files or rounds contribute zero — a subject with no prior briefs
    starts at 1. Counts are content-derived (one row, one count), never a tunable.
    """
    if before_round <= 1:
        return {}
    counts: "dict[tuple[str, str | None], int]" = {}
    pattern = re.compile(r"^round-(\d+)\.json$")
    briefs_dir = actions_root / "_briefs"
    if not briefs_dir.is_dir():
        return {}
    for path in sorted(briefs_dir.glob("round-*.json")):
        match = pattern.match(path.name)
        if match is None or int(match.group(1)) >= before_round:
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in doc.get("entries") or ():
            if not isinstance(row, dict):
                continue
            scope = row.get("scope")
            if scope not in ("general", "family", "species"):
                continue
            counts[(scope, row.get("scopeKey"))] = counts.get((scope, row.get("scopeKey")), 0) + 1
    return counts


def _corpus_hash(role_lean_corpus_hash: str, type_weights_lean_hash: str, run_tuning_version: int,
                 rungs_version: int) -> str:
    """A stable digest over every real input this module's OWN algorithm consumes -- never a
    wall-clock stamp. Deliberately does NOT re-hash the whole role-lean/type-weights files (their
    own `_meta` hashes already cover their content); this is a hash of THOSE hashes plus the two
    version numbers this module additionally depends on.

    **⛔ ALGORITHM_VERSION is folded in — the 2026-09-11 freshness hole.** The payload originally
    covered only INPUTS (role-lean/type-weights hashes, tuning/rungs versions). A change to a pure
    function the planner owns -- e.g. the 2026-09-11 ordinal-spreading fix in `expand_counts`, whose
    marginals are identical but whose emitted order is not -- therefore produced different briefs
    under the SAME hash. The stale plan would still pass `_load_plan`'s freshness check, and
    `load_resume_entries` would accept candidates generated against the old ordinal order. Bumping
    this integer whenever `distribution_planner.derive`'s OUTPUT for unchanged inputs changes makes
    the freshness check cover the algorithm, not just its inputs. It is not a tuning value and must
    never be moved by a balance pass -- only by a change that alters emitted briefs."""
    payload = {
        "roleLeanCorpusHash": role_lean_corpus_hash, "typeWeightsLeanHash": type_weights_lean_hash,
        "runTuningVersion": run_tuning_version, "rungsVersion": rungs_version,
        "algorithmVersion": ALGORITHM_VERSION,
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def read_top_up_targets(report: "Mapping[str, Any]") -> "dict[tuple[str, str | None], dict[str, int]]":
    """**T2.1 — A-S1 reads round n's report to build round n+1's briefs.** Returns
    `{(scope, scopeKeyOrNone): {category: want}}` from the report's `next-target` rows
    (`coverage_report.derive.next_round_targets`, spec-coverage-report.md §3 step 5).

    This is the `S5 → S1` edge the design specifies (`action-corpus-ideal.md` §15
    `S5 -->|"round n+1 targets"| S1`; `spec-coverage-report.md` §7 *"Depended on by: A-S1, which
    reads the report to build round n+1's briefs"*) and which was never wired — so `thinCell` could
    never clear and the full-run gate was unreachable by construction.

    Rules, each chosen so a caller error cannot masquerade as a healthy empty shortfall:
    - A wrong `kind` raises, naming the kind. Reading zero from an `action-brief` (say) would plan a
      duplicate round 1 and look like success.
    - A `want` of 0 is dropped: zero is not a deficiency, and carrying it would emit a zero-count
      subject for no reason.
    - Duplicate rows for one `(scope, scopeKey, category)` SUM. A-S5 never writes duplicates, but a
      concatenated or hand-merged report must not silently lose one.
    - Rows whose `scope` is not a known scope are refused, not skipped: an unrecognised scope means
      the report is not the shape this planner consumes.
    """
    kind = report.get("kind")
    if kind != "action-coverage":
        raise ValueError(
            f"top-up report must be an 'action-coverage' envelope (A-S5's own output) — got "
            f"kind={kind!r}")
    out: "dict[tuple[str, str | None], dict[str, int]]" = {}
    for row in report.get("entries") or ():
        if not isinstance(row, dict) or row.get("kindOfEntry") != "next-target":
            continue
        scope = row.get("scope")
        if scope not in SCOPES:
            raise ValueError(f"top-up target names an unknown scope {scope!r}")
        want = row.get("want")
        if not isinstance(want, int) or isinstance(want, bool) or want < 0:
            raise ValueError(f"top-up target {row.get('id')!r} has a non-positive-integer want "
                             f"{want!r}")
        if want == 0:
            continue
        category = row.get("category")
        if category not in CATEGORIES:
            raise ValueError(f"top-up target names an unknown category {category!r}")
        by_cat = out.setdefault((scope, row.get("scopeKey")), {})
        by_cat[category] = by_cat.get(category, 0) + want
    return out


def load_top_up_targets(path: Path) -> "dict[tuple[str, str | None], dict[str, int]]":
    """T2.1's file reader. Refuses a missing file by name (`FileNotFoundError`) rather than treating
    it as zero shortfall — the acceptance criterion the plan states explicitly, because silently
    planning a duplicate round 1 is the failure mode a lenient default would hide."""
    if not path.is_file():
        raise FileNotFoundError(f"top-up report not found: {path}")
    return read_top_up_targets(json.loads(path.read_text(encoding="utf-8")))


def convergence_decision(*, thin_cell_count: int, rounds_done: int, max_rounds: int) -> dict:
    """**T2.4 — the bounded convergence criterion.** A round loop stops when no cell is thin OR the
    declared cap is reached, and it REPORTS which, so `"converge over rounds"` is never an unbounded
    promise (the plan's open question Q2). Returning the reason rather than a bare bool is the point:
    a cap stop means the corpus is still incomplete and that must be visible, not indistinguishable
    from convergence."""
    if max_rounds <= 0:
        raise ValueError("max_rounds must be positive — an unbounded round loop is not a criterion")
    if thin_cell_count < 0:
        raise ValueError("thin_cell_count must be non-negative")
    if thin_cell_count == 0:
        return {"stop": True, "reason": "converged", "roundsDone": rounds_done}
    if rounds_done >= max_rounds:
        return {"stop": True, "reason": "round-cap", "roundsDone": rounds_done,
                "thinCellsRemaining": thin_cell_count}
    return {"stop": False, "reason": "thin-cells-remain", "roundsDone": rounds_done,
            "thinCellsRemaining": thin_cell_count}


def regenerate(*, actions_root: Path = ACTIONS_ROOT, creatures_root: Path = CREATURES_ROOT,
              catalog_path: Path = CATALOG_PATH, role_lean_path: Path = ROLE_LEAN_PATH,
              family_assignments_path: "Path | None" = None, type_weights_path: "Path | None" = None,
              rungs_path: Path = RUNGS_PATH, run_tuning_path: Path = RUN_TUNING_PATH,
              dedup_tuning_path: Path = DEDUP_TUNING_PATH, pairings_path: "Path | None" = None,
              top_up_report_path: "Path | None" = None,
              full_flag: bool = False, write: bool = True, round_no: int = 1) -> dict:
    """Pure computation + (optionally) one file write. Returns a summary dict for the caller to
    report -- never prints itself, so a test can call this without capturing stdout."""
    # `type_weights_path`/`pairings_path` deliberately do NOT derive from the `actions_root` parameter -- that
    # parameter names only where THIS run WRITES its own round file (`_briefs/round-1.json`
    # below), so a test can redirect the write target without also redirecting every real read.
    type_weights_path = type_weights_path or (ACTIONS_ROOT / "type-weights.json")
    pairings_path = pairings_path or (ACTIONS_ROOT / "pairings.json")

    run_tuning = load_run_tuning(run_tuning_path)
    dedup_k, dedup_k_source = load_dedup_k(dedup_tuning_path)

    gate_passed = is_passing_quality_gate(SMOKE_GATE_EVIDENCE_PATH)
    dp.refuse_full_run_if_ungated(run_tuning.mode, full_flag, gate_passed)

    catalog = load_catalog(catalog_path)
    species_ids = [s.species_id for s in catalog]

    role_lean_text = role_lean_path.read_text(encoding="utf-8")
    role_lean_doc = json.loads(role_lean_text)
    species_anchor = dp.parse_species_anchor(role_lean_doc)
    role_lean_corpus_hash = role_lean_doc["_meta"]["corpusHash"]

    using_live_families = family_assignments_path is None
    if using_live_families:
        live_species_root = catalog_path if catalog_path.is_dir() else creatures_root / "species"
        family_assignments = derive_live_family_assignments(live_species_root)
    else:
        family_assignments = json.loads(family_assignments_path.read_text(encoding="utf-8"))
    family_members = _family_members(family_assignments)
    if using_live_families and set(family_assignments) != set(species_ids):
        raise ValueError("live family assignments do not cover exactly the live species roster")

    if set(species_anchor) != set(species_ids):
        missing = sorted(set(species_ids) - set(species_anchor))
        extra = sorted(set(species_anchor) - set(species_ids))
        raise ValueError(
            "role-lean.json is stale relative to the live species seed folder: "
            f"missing={missing[:5]!r}, extra={extra[:5]!r}"
        )

    type_weights_text = type_weights_path.read_text(encoding="utf-8")
    type_weights_doc = json.loads(type_weights_text)
    weights_by_key = dp.parse_type_weights(type_weights_doc)
    type_weights_lean_hash = type_weights_doc["_meta"]["leanHash"]

    rung_table = dp.load_rung_table(rungs_path)
    # ST3 (`spec-scope-window-tunables.md` contract 3): the windows are loaded HERE, once, from the
    # same file the structures come from, and passed down -- no stage re-reads or re-imports a
    # literal. This is also why the planner now reads v3: one file for both.
    windows = dp.load_scope_windows(rungs_path)
    family_ids = load_family_ids()
    pairing_table = dp.load_pairing_table(pairings_path)

    rungs_doc = json.loads(rungs_path.read_text(encoding="utf-8"))
    corpus_hash = _corpus_hash(role_lean_corpus_hash, type_weights_lean_hash, run_tuning.version,
                              rungs_doc["version"])

    accepted_neighbours = _accepted_neighbours_by_group(actions_root, before_round=round_no)

    # T2.1/T2.3 — round n+1 reads round n's report; round 1 passes no path and therefore plans the
    # full quota exactly as before (the cycle stays broken by construction, spec §7). Absent path ->
    # no top-up; a path that is given but missing/malformed is refused by the loader, never treated
    # as zero shortfall.
    top_up = load_top_up_targets(top_up_report_path) if top_up_report_path is not None else None
    # Phase-4 2026-09-15 — ordinal continuation for top-up rounds: each subject's new briefs start
    # past its already-planned count (read from prior `_briefs/round-<n>.json`, same round
    # discipline as the neighbours above), so round n+1 mints no id round ≤ n already used.
    # `None` (round 1 / no report) keeps every ordinal starting at 1 — byte-identical to before.
    ordinal_starts = None
    if top_up is not None:
        prior_counts = _prior_brief_counts(actions_root, before_round=round_no)
        ordinal_starts = {key: count + 1 for key, count in prior_counts.items()}

    briefs = dp.plan_round(
        species_ids=species_ids, family_members=family_members, species_anchor=species_anchor,
        weights_by_key=weights_by_key, rung_table=rung_table, family_ids=family_ids,
        windows=windows,
        pairing_table=pairing_table, general_count=run_tuning.general_count,
        per_species_count=run_tuning.per_species_count, per_family_count=run_tuning.per_family_count,
        multiplicative_pairs=run_tuning.multiplicative_pairs,
        family_motif_max=run_tuning.family_motif_max, corpus_hash=corpus_hash,
        tuning_version=run_tuning.version, round_no=round_no, prompt_version=1,
        accepted_neighbours_by_group=accepted_neighbours, avoid_neighbour_k=dedup_k,
        top_up=top_up, ordinal_starts=ordinal_starts,
    )
    briefs.sort(key=lambda b: b["briefId"])
    for b in briefs:
        dp.audit_no_magnitude_smuggling(b)

    out_doc = {
        "schemaVersion": 1,
        "kind": "action-brief",
        "_meta": {"partition": "briefs", "corpusHash": corpus_hash, "tuningVersion": run_tuning.version,
                 "round": round_no},
        "entries": briefs,
    }

    if write:
        briefs_dir = actions_root / "_briefs"
        briefs_dir.mkdir(parents=True, exist_ok=True)
        (briefs_dir / f"round-{round_no}.json").write_text(_canonical_dump(out_doc), encoding="utf-8")

    by_scope: "dict[str, int]" = {}
    by_role: "dict[str, int]" = {}
    restriction_count = 0
    for b in briefs:
        by_scope[b["scope"]] = by_scope.get(b["scope"], 0) + 1
        by_role[b["pairing"]["role"]] = by_role.get(b["pairing"]["role"], 0) + 1
        if not b["slot"]["structureEnforced"]:
            restriction_count += 1

    return {
        "totalBriefs": len(briefs),
        "byScope": by_scope,
        "byPairingRole": by_role,
        "restrictionUnenforcedCount": restriction_count,
        "speciesSubjects": len(species_ids),
        "familySubjects": len(family_members),
        "familyAssignedSpeciesCount": sum(len(v) for v in family_members.values()),
        "dedupK": dedup_k, "dedupKSource": dedup_k_source,
        "topUpSubjects": len(top_up) if top_up else 0,
        "corpusHash": corpus_hash, "tuningVersion": run_tuning.version, "mode": run_tuning.mode,
        "written": bool(write),
    }


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Plan action-corpus briefs by quota, not by sampling (A-S1 'Engine 1').")
    ap.add_argument("--dry-run", action="store_true", help="compute and print, write nothing")
    ap.add_argument("--full", action="store_true",
                    help="required (but not sufficient) to plan a full run -- see refuse_full_run_if_ungated")
    ap.add_argument("--round", type=int, default=1, dest="round_no",
                    help="the round number this plan writes (round-<N>.json)")
    ap.add_argument("--top-up-from", type=Path, default=None, dest="top_up_from",
                    help="round n's action-coverage report: plan only its next-target shortfall "
                         "(the S5 -> S1 edge). Absent: plan the full base quota (round 1). "
                         "A missing/malformed report is refused by name, never read as zero.")
    args = ap.parse_args(argv)

    summary = regenerate(write=not args.dry_run, full_flag=args.full,
                         round_no=args.round_no, top_up_report_path=args.top_up_from)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
