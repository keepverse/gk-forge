"""seedsmith.adapters.actions.generate_coverage_report — A-S5's entrypoint
(spec-coverage-report.md). Reads:

    gk-data/packs/fusion/data/seed/actions/ (via A-C1's load_committed)      the committed corpus (today: empty —
                                                          A-S6 has never promoted anything)
    data/seed/actions/_rounds/round-<n>/survivors.json   A-S3's survivors for the round being
                                                          measured, if the round ran (today:
                                                          usually absent — A-S4/A-S3 have not run
                                                          for real; see module docstring below)
    gk-data/packs/fusion/data/seed/actions/type-weights.json                  A-T1 — categoryMilli, for quota recompute
    gk-core/data/tuning/action-corpus-run.v1.json                round counts (generalCount/perFamilyCount/
                                                          perSpeciesCount) and mode
    gk-data/packs/fusion/data/seed/creatures/species/**/*.json                      live species/family membership
    gk-data/packs/fusion/data/seed/items/affix-families/*.json                the 98-family namespace
    gk-data/packs/fusion/data/seed/actions/pairings.json                      read-only; today's 5 out-of-namespace ids

and writes, through the A-C1 envelope:

    data/seed/actions/_reports/coverage-round-<n>.json   kind: "action-coverage"

**Zero model calls.** Every metric here is arithmetic over committed files (spec's own opening
line) — there is no LLM transport import anywhere in this module or its `coverage_report` package.

**The accepted corpus this module measures is genuinely empty in this checkout.** A-S4
(`validate-heal`) does not exist, so A-S3 (`dedup-select`) has never run for real and there is no
`_rounds/round-<n>/survivors.json` anywhere in the tree — this entrypoint degrades to that state
cleanly (an absent survivors file is read as "no candidates this round", never an error) rather
than requiring one to exist. Running this module for real against the real `round-1.json` plan with
zero accepted rows is exactly the "small batch honesty" case spec §1 names as the legitimate thing
to do: it reports zero counts everywhere and an explicit non-`pass` verdict, honestly.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .characteristic_pool.catalog import (
    CATALOG_PATH, derive_live_family_assignments, load_catalog,
)
from .coverage_report import derive as cr
from .coverage_report.ctx import ActionCoverageCtx, RosterCounts
from .distribution_planner import derive as dp
from .distribution_planner.tuning import RUN_TUNING_PATH, load_run_tuning
from .generate_distribution_planner import RUNGS_PATH as RUNG_TABLE_PATH
from .load import load_committed
from .vocab import load_family_ids
from ...metrics import Ctx, MetricRegistry, run_all
from ...metrics.action_coverage import (
    ALL_ACTION_COVERAGE_CLOSED_METRICS, ALL_ACTION_COVERAGE_OPEN_METRICS,
)

__all__ = ["run", "regenerate", "ACTIONS_ROOT", "CREATURES_ROOT"]

REPO_ROOT = Path(__file__).resolve().parents[5]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from ...workspace_roots import owning_base, seed_root  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

ACTIONS_ROOT = _owned("data/seed/actions")
CREATURES_ROOT = seed_root() / "creatures"
TYPE_WEIGHTS_PATH = ACTIONS_ROOT / "type-weights.json"
PAIRINGS_PATH = ACTIONS_ROOT / "pairings.json"


def _family_members(family_assignments: dict) -> "dict[str, list[str]]":
    members: "dict[str, list[str]]" = {}
    for species_id, families in family_assignments.items():
        if isinstance(families, str):
            families = [families]
        for fam in families:
            members.setdefault(fam, []).append(species_id)
    return {fam: sorted(v) for fam, v in members.items()}


def _build_ctx(*, actions_root: Path, creatures_root: Path, catalog_path: Path,
              type_weights_path: Path, run_tuning_path: Path,
              family_assignments_path: "Path | None", pairings_path: Path,
              rung_table_path: Path = RUNG_TABLE_PATH,
              round_no: int) -> ActionCoverageCtx:
    catalog = load_catalog(catalog_path)
    species_ids = [s.species_id for s in catalog]

    using_live_families = family_assignments_path is None
    if using_live_families:
        live_species_root = catalog_path if catalog_path.is_dir() else creatures_root / "species"
        family_assignments = derive_live_family_assignments(live_species_root)
    else:
        family_assignments = json.loads(family_assignments_path.read_text(encoding="utf-8"))
    if using_live_families and set(family_assignments) != set(species_ids):
        raise ValueError("live family assignments do not cover exactly the live species roster")
    family_members = _family_members(family_assignments)

    type_weights_doc = json.loads(type_weights_path.read_text(encoding="utf-8"))
    weights_by_key = dp.parse_type_weights(type_weights_doc)

    run_tuning = load_run_tuning(run_tuning_path)
    family_ids = load_family_ids()
    pairing_table = dp.load_pairing_table(pairings_path)

    subject_counts = cr.recompute_subject_category_counts(
        species_ids=species_ids, family_members=family_members, weights_by_key=weights_by_key,
        general_count=run_tuning.general_count, per_family_count=run_tuning.per_family_count,
        per_species_count=run_tuning.per_species_count,
    )
    quota_by_scope_category = cr.aggregate_scope_category_quota(subject_counts)

    committed = load_committed(actions_root)
    accepted_rows = [e.data for e in committed.corpus.by_kind("action-seed")]

    round_dir = actions_root / "_rounds" / f"round-{round_no}"
    survivors_path = round_dir / "survivors.json"
    if survivors_path.is_file():
        survivors_doc = json.loads(survivors_path.read_text(encoding="utf-8"))
        # A-S6 (`innate_picker.derive.reduce_round_survivors_to_markers`) rewrites an
        # already-promoted round's own survivors.json IN PLACE to bare `{"id": ..., "promoted":
        # true}` markers once its full content has moved into a `committed-round-<n>.json` this
        # same `load_committed(actions_root)` call above already loaded -- "one id exists in
        # exactly one place" (that module's own docstring). Before A-S6 ever ran for real this
        # branch only ever saw FULL, un-promoted rows, so the gap was latent; the first real
        # A-S6-then-A-S5 run over the same round (2026-09-04) surfaced it as a genuine `KeyError`
        # in `partition_accepted` (a marker carries no `rungBand`/`category`/etc.). Skipping a
        # marker here is not a filter of convenience -- re-adding it would silently double-count
        # the row (once from `committed`, once as a content-free stub) on top of crashing.
        accepted_rows.extend(
            e for e in (survivors_doc.get("entries") or []) if not e.get("promoted"))

    # ⛔ ONE ROW PER ID — the 2026-09-12 gate finding (T3.1). The filter above trusts this round's
    # `survivors.json` to have been reduced to `promoted` markers once its content moved into a
    # `committed-round-<n>.json`. That is true only if S6 promoted THIS round. When a LATER round's
    # S6 run promotes a row that also still sits in an EARLIER round's un-marked survivors file, the
    # committed copy and the stale round copy are both admitted, with different payloads: measured,
    # `_rounds/round-1/survivors.json` held 12 rows, 11 of them already committed in
    # `committed-round-2000.json`, so this report measured 191 rows for a 179-row corpus and the two
    # reports disagreed about the same baseline.
    #
    # The invariant the pipeline claims is "one id exists in exactly one place" (`innate_picker`).
    # A producer-side violation is not the consumer's to police, but the consumer is where it does
    # damage, and a duplicate row double-counts every cell, `thinCell` and `speciesCoverage` alike.
    # So: keep the FIRST occurrence per id. `load_committed` is read first and already guarantees
    # committed ids are unique, so the committed (promoted, authoritative) copy wins and a stale
    # round copy is dropped. Deterministic: iteration order is committed-then-survivors, sorted by
    # file and entry order, so "first" is stable.
    deduped: "list[dict]" = []
    seen_ids: "set[str]" = set()
    for row in accepted_rows:
        row_id = row.get("id")
        if row_id is None:
            deduped.append(row)                     # an id-less row is not this guard's business
            continue
        if row_id in seen_ids:
            continue
        seen_ids.add(row_id)
        deduped.append(row)
    accepted_rows = deduped

    review_rows: "tuple[dict, ...]" = ()
    review_path = round_dir / "review-queue.json"
    if review_path.is_file():
        review_doc = json.loads(review_path.read_text(encoding="utf-8"))
        review_rows = tuple(review_doc.get("entries") or ())

    roster = RosterCounts(
        species_count=len(species_ids), family_count=len(family_members),
        family_assigned_count=sum(len(v) for v in family_members.values()))

    # ST3 (`spec-scope-window-tunables.md` contract 3): the windows are loaded HERE, once, and ride
    # the ctx every metric already receives -- this stage never imports a constant.
    scope_windows = dp.load_scope_windows(rung_table_path)

    return ActionCoverageCtx(
        accepted_rows=tuple(accepted_rows), quota_by_scope_category=quota_by_scope_category,
        subject_category_counts=subject_counts, family_ids=family_ids, pairing_table=pairing_table,
        roster=roster, scope_windows=scope_windows,
        review_rows=review_rows, round_no=round_no, mode=run_tuning.mode,
        tuning_version=run_tuning.version, per_species_count=run_tuning.per_species_count,
    )


def regenerate(*, actions_root: Path = ACTIONS_ROOT, creatures_root: Path = CREATURES_ROOT,
              catalog_path: Path = CATALOG_PATH, type_weights_path: "Path | None" = None,
              run_tuning_path: Path = RUN_TUNING_PATH, family_assignments_path: "Path | None" = None,
              pairings_path: "Path | None" = None, rung_table_path: Path = RUNG_TABLE_PATH,
              round_no: int = 1, write: bool = True) -> dict:
    """Pure computation + (optionally) one file write. Returns a summary dict for the caller to
    report — never prints itself, so a test can call this without capturing stdout."""
    type_weights_path = type_weights_path or TYPE_WEIGHTS_PATH
    pairings_path = pairings_path or PAIRINGS_PATH

    cov = _build_ctx(
        actions_root=actions_root, creatures_root=creatures_root, catalog_path=catalog_path,
        type_weights_path=type_weights_path, run_tuning_path=run_tuning_path,
        family_assignments_path=family_assignments_path, pairings_path=pairings_path,
        rung_table_path=rung_table_path,
        round_no=round_no,
    )

    registry = MetricRegistry()
    for metric_cls in ALL_ACTION_COVERAGE_CLOSED_METRICS:
        registry.register(metric_cls())
    ctx = Ctx(corpus=None, adapter=None, action_coverage=cov)
    closed_findings = run_all(registry, ctx)

    open_registry = MetricRegistry()
    for metric_cls in ALL_ACTION_COVERAGE_OPEN_METRICS:
        open_registry.register(metric_cls())
    review_findings = run_all(open_registry, ctx)

    groups = cr.build_cell_groups(cov.accepted_rows, cov.quota_by_scope_category,
                                  cov.scope_windows)
    entries = cr.cell_entries(groups, round_no=round_no)
    targets = cr.next_round_targets(groups=groups, subject_counts=cov.subject_category_counts,
                                    accepted_rows=cov.accepted_rows, round_no=round_no,
                                    windows=cov.scope_windows)
    entries = entries + targets
    entries.sort(key=lambda e: e["id"])

    closed_ids = [m.id for m in ALL_ACTION_COVERAGE_CLOSED_METRICS]
    # The SAME `gates` set `report/cli.py --gate` builds, read from the live registry rather than
    # duplicated: a metric earns the right to gate by flipping `gates` (spec-metrics.md §4), and that
    # one flag decides both this verdict and the general reporter's exit code — so they cannot
    # disagree. T1.2/T1.3 (2026-09-12).
    gating_ids = [m.id for m in registry.all() if m.gates]
    verdict = cr.compute_verdict(closed_findings, closed_ids, cov.mode,
                                 gating_metric_ids=gating_ids)

    doc = cr.build_envelope(entries, meta={
        "partition": f"round-{round_no}",
        "round": round_no,
        "mode": cov.mode,
        "corpusHash": cr.corpus_hash(cov.accepted_rows),
        "tuningVersion": cov.tuning_version,
        "roster": {"species": cov.roster.species_count, "families": cov.roster.family_count,
                  "familyAssigned": cov.roster.family_assigned_count},
        "acceptedCorpusSize": len(cov.accepted_rows),
        "verdict": verdict.to_dict(),
        "reviewQueueCount": len(review_findings),
    })

    dump = cr.canonical_dump(doc)
    if write:
        reports_dir = actions_root / "_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        out_path = reports_dir / f"coverage-round-{round_no}.json"
        out_path.write_text(dump, encoding="utf-8")

    gap_count = sum(1 for f in closed_findings if f.severity.value == "gap")
    return {
        "round": round_no,
        "mode": cov.mode,
        "acceptedCorpusSize": len(cov.accepted_rows),
        "cellCount": len(groups),
        "nextTargetCount": len(targets),
        "closedFindingCount": len(closed_findings),
        "closedGapCount": gap_count,
        "docHash": hashlib.sha256(dump.encode("utf-8")).hexdigest(),
        "reviewQueueCount": len(review_findings),
        "verdict": verdict.verdict,
        "evaluatedMetrics": list(verdict.evaluated_metrics),
        "notMeasuredMetrics": list(verdict.not_measured_metrics),
        "gapMetrics": list(verdict.gap_metrics),
        "written": bool(write),
    }


def run(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Measure the accepted action corpus against A-T1's quota and derive next-round "
                    "targets (A-S5 coverage-report).")
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
