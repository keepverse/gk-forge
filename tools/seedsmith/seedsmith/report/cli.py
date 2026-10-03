"""seedsmith.report.cli — `seedsmith check`, exit codes (spec-foundation §7.3).

Exit codes are a stable contract CI depends on: 0 clean, 1 findings at GAP, 2 could not run
(corpus unreadable, unknown adapter), 3 refused (planner refuses an unsatisfiable work order —
not reachable from `check`; W2).

Two review modes over the same run, not two contradictory truths:
- plain `check`: exit 1 if ANY GAP-severity finding exists, from any metric — "tell me everything
  currently wrong," for local dev. This is exactly what tasks/seedsmith-todo.md's S1/S2
  acceptance tests exercise.
- `--gate`: exit 1 only if a GAP comes from a metric with `gates=True` — the CI-safe mode, usable
  once a metric family has been calibrated and promoted (spec-metrics.md §4). Every metric ships
  `gates=False` for the whole of W1 (by design — new metrics are measure-only until calibrated),
  so `--gate` always exits clean for now. That is correct, not a bug: nothing has been promoted.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
import re
import sys
from pathlib import Path

from ..adapters.registry import known_adapter_names, resolve_adapter
from ..corpus import Corpus, CorpusLoadError
from ..metrics import Ctx, MetricRegistry, Severity, run_all
from ..metrics.coverage import EmptyPartitionMetric, HostRoleDiversityMetric
from ..metrics.linkage import ALL_LINKAGE_METRICS
from ..metrics.pairwise import PairwiseHole
from ..metrics.balance import LadderInversion, OutOfEnvelope
from ..metrics.cell_occupancy import CellOccupancy
from ..metrics.distribution import CellDeviation, Evenness, Inequality
from ..metrics.constraint import Constraint
from ..metrics.exemplar import ExemplarConformance
from ..metrics.dedup import SemanticDedup
from ..metrics.quality import FLAVOR_EXPECTED_KINDS, FlavourGeneric, FlavourMissing
from ..metrics.content_completeness import (
    CompletenessSpec, ContentFieldMissing, ContentFieldStale, ContentLanguageContamination,
    register_completeness,
)
from ..adapters.actions.description_backfill import ACTIONS_COMPLETENESS_SPEC
from ..metrics.corpus_coverage import BasisHistogramMetric, DumpCompletenessMetric
from ..metrics.creature_coverage import CreatureUncoveredMetric
from ..metrics.creature_roster import ALL_CREATURE_ROSTER_METRICS
from ..metrics.pipeline_health import ALL_PIPELINE_HEALTH_METRICS
from ..metrics.motif_sharing import MotifSharingMetric
from ..metrics.passive_tree import TreeEqualValueMetric, ALL_PASSIVE_TREE_METRICS
from ..numerics import BattleRulesetProgression, NumericsContext, TierBands
from ..budget import derive_all

EXIT_CLEAN = 0
EXIT_GAP = 1
EXIT_CANNOT_RUN = 2
EXIT_REFUSED = 3
EXIT_ESCALATED = 4

_SEVERITY_ORDER = {Severity.GAP: 0, Severity.NOTE: 1, Severity.NOT_MEASURED: 2}


def _exit_for_graph_batch(result) -> int:
    """EXIT_CLEAN when the batch finished without escalate — persisted and/or blocked (or empty).

    Affix already returns 0 on a coherent `blocked`. Set/charm/combination used to require at least
    one persist this batch, so fill `--limit 1` turned a legitimate decline into `gap` and stalled
    resume. Escalate has its own result so the fill walker can record it and keep walking without
    treating a genuine corpus gap as recoverable.
    """
    if any(getattr(o, "outcome", None) == "escalated" for o in getattr(result, "outcomes", ())):
        return EXIT_ESCALATED
    return EXIT_CLEAN


def build_registry() -> MetricRegistry:
    """Every metric that exists so far. S2-S8 each add their own metrics here — one line per
    metric, never a rewrite of this function."""
    registry = MetricRegistry()
    registry.register(EmptyPartitionMetric())
    # Coverage/HostRoleDiversity (strain-splice-host SSH2.7, combination-regen "The helm joins the
    # host set" step 2): the R11 reading — does the model actually choose the helm once
    # `sockets.v2.json` offers it? Report-only (`gates = False`), and every finding is NOTE
    # severity, so it prints through a plain `check` without failing it.
    registry.register(HostRoleDiversityMetric())
    for metric_cls in ALL_LINKAGE_METRICS:
        registry.register(metric_cls())
    registry.register(PairwiseHole())
    registry.register(LadderInversion())
    registry.register(OutOfEnvelope())
    registry.register(CellDeviation())
    registry.register(Evenness())
    registry.register(Inequality())
    registry.register(CellOccupancy())
    registry.register(Constraint())
    registry.register(ExemplarConformance())
    registry.register(SemanticDedup())
    registry.register(FlavourMissing())
    registry.register(FlavourGeneric())
    # Content/FieldMissing + Content/FieldStale (seedsmith-content-standard, content-completeness-
    # core, Task 3): a generalized registry a domain adopts via `register_completeness`, rather
    # than editing FLAVOR_EXPECTED_KINDS's own hardcoded frozenset for every new domain. Registered
    # unconditionally here (same as every other metric in this function) — reporting zero findings
    # when no domain has registered a spec yet is correct, not a bug (matches `gates=False`'s own
    # measure-only-until-adopted posture).
    #
    # `content-completeness-items` (Task 6): items is the FIRST real domain adoption — a real gap
    # found building this task: nothing outside `tests/test_content_completeness.py` ever called
    # `register_completeness`, so `Content/FieldMissing` reported nothing at all on a real `check`
    # run even though the registry/metric machinery was fully built in Phase 0. Registering here
    # (not inside `metrics/quality.py` at import time) means every real invocation of `check` gets
    # the items spec regardless of module import order, and `register_completeness`'s own
    # idempotency (content_completeness.py) makes it safe that this function runs more than once in
    # one process. `FlavourMissing` itself is left registered too, unchanged (Task 3's own
    # byte-identical guarantee) — this is an ADDITIVE second reporting path onto the same real data,
    # not a replacement.
    register_completeness(CompletenessSpec(
        domain="items", kinds=FLAVOR_EXPECTED_KINDS, field="flavor"))
    # `content-completeness-actions` (Task 8): actions had NOTHING before this task (no ledger, no
    # `_provenance`, no missing-field metric — `seedsmith-content-standard-ideal.md`'s own "Real
    # gap" finding). `ACTIONS_COMPLETENESS_SPEC` (`adapters/actions/description_backfill/
    # __init__.py`) names `description` — the AUTHORED flavour-text field this task added to
    # `action-seed` (`adapters/actions/kinds.py`'s own `ACTION_SEED_OPTIONAL`), distinct from the
    # already-existing `descriptionKey` (a minted, empty i18n key with nothing behind it yet).
    register_completeness(ACTIONS_COMPLETENESS_SPEC)
    registry.register(ContentFieldMissing())
    registry.register(ContentFieldStale())
    registry.register(ContentLanguageContamination())
    registry.register(CreatureUncoveredMetric())
    registry.register(MotifSharingMetric())
    registry.register(DumpCompletenessMetric())
    registry.register(BasisHistogramMetric())
    for metric_cls in ALL_CREATURE_ROSTER_METRICS:
        registry.register(metric_cls())
    for metric_cls in ALL_PIPELINE_HEALTH_METRICS:
        registry.register(metric_cls())
    registry.register(TreeEqualValueMetric())
    # H4 (spec-tree-language.md §7 gates 15-22): the eight PassiveTree/* corpus metrics, registered
    # exactly once, matching the ALL_LINKAGE_METRICS/ALL_CREATURE_ROSTER_METRICS/ALL_PIPELINE_HEALTH_METRICS
    # loop pattern above. This is the wiring H4's own evidence named as deliberately left for a later
    # task: the metric classes existed with the correct `gates` attribute, but `--write`'s own registry
    # never carried them, so `assert_exactly_one_hard_gate` always found zero and refused every write.
    # DeepMechanismValueMetric/HiddenFileCountMetric (H5) are correctly NOT included here -- both need
    # externally-supplied data (CombatSim samples / seed roots) build_registry()'s generic construction
    # has no parameter for, matching H5's own stated precedent for keeping them standalone-registrable.
    for metric_cls in ALL_PASSIVE_TREE_METRICS:
        registry.register(metric_cls())
    return registry


def _build_numerics_context(adapter_name: str, adapter) -> NumericsContext | None:
    """Only the `items` adapter has a `tier-bands.v{n}.json` to load (spec-numerics.md §3.1's
    path is item-corpus-specific); any other adapter runs without a numerics context, and
    numerics-dependent metrics correctly report NOT_MEASURED via their declared `needs`."""
    if adapter_name != "items":
        return None
    try:
        tuning = TierBands.load("latest")
    except FileNotFoundError:
        return None
    return NumericsContext(tuning=tuning, progression=BattleRulesetProgression.from_adapter(adapter))


def _print_human(findings, *, stream=None) -> None:
    # `stream` used to default to `sys.stdout` directly -- an early-binding bug (the same class
    # already fixed once this session in `generate_affixes.py`'s own `output_dir`/`id_prefix`
    # defaults): a default evaluated at function-DEFINITION time captures whatever `sys.stdout` WAS
    # when this module first imported, not whatever it is at call time, so
    # `contextlib.redirect_stdout` in a test (or any caller that temporarily swaps `sys.stdout`)
    # silently failed to capture anything printed here -- found 2026-09-07 the moment a real test
    # first asserted on this function's own captured output instead of only an exit code.
    if stream is None:
        stream = sys.stdout
    if not findings:
        print("no findings", file=stream)
        return
    for f in sorted(findings, key=lambda f: (_SEVERITY_ORDER[f.severity], f.metric, f.subject)):
        print(f"[{f.severity.value.upper()}] {f.metric} — {f.subject}: {f.message}", file=stream)
    counts: dict[Severity, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    summary = ", ".join(f"{v} {k.value}" for k, v in counts.items())
    print(f"\n{summary}", file=stream)


def _cmd_check_family(args: argparse.Namespace) -> int:
    """`seedsmith check --family <X> --gate` (spec-tree-language.md §Commands) — a family-scoped
    check that needs no `corpus_root`/`--adapter` at all, the same shape `_cmd_creatures_metrics`
    already uses for `CreatureRoster`. Only `PassiveTree` exists today (task H2); a later family adds
    its own branch here rather than a second command.

    Exit codes, reusing the shipped four (`cli.py`'s own docstring) rather than inventing new
    semantics: `EXIT_CANNOT_RUN` (2) when there is nothing to check at all (no committed plan);
    `EXIT_REFUSED` (3) when `--gate` is asked to trust a hard-gate contract that is not wired yet —
    §7.1's own rule is "exactly one gate is promoted to hard-fail first," and today's real registry
    has ZERO `PassiveTree/*` metrics at `gates=True` (`PassiveTree/UnresolvedCount` is task H4's,
    not yet built) — reporting a clean pass here would be exactly the lie H9 §6.4 rule 1 names:
    "an absent check is never a pass." Without `--gate`, every registered finding is reported and
    `EXIT_GAP` (1) fires on a real one, `EXIT_CLEAN` (0) otherwise — the same two codes `check`
    already uses for a corpus.
    """
    if args.family != "PassiveTree":
        print(f"seedsmith: check --family only supports 'PassiveTree' today; got {args.family!r}",
              file=sys.stderr)
        return EXIT_CANNOT_RUN

    from ..adapters.trees.nodegen import emit as nodegen_emit
    from ..adapters.trees.nodegen import plan_read as nodegen_plan_read
    from ..adapters.trees.nodegen import quota as nodegen_quota
    from ..adapters.trees.nodegen import run as nodegen_run
    from ..adapters.trees.nodegen import verdict as tree_verdict
    from ..adapters.trees.plan import emit as plan_emit
    from ..adapters.trees.plan import tuning as plan_tuning
    from ..adapters.trees.plan.archetypes import SHIPPED_ARCHETYPES, TIER_COUNT
    from ..adapters.trees.targets import PassiveTreeTargetsError
    from ..adapters.trees.targets import load as load_tree_targets
    from ..workspace_roots import seed_root
    from ..metrics.passive_tree import (
        HiddenFileCountMetric, PassiveTreePlanCtx, SpeciesUniquenessMetric,
    )

    # `data/seed` is gk-data's pack, not gk-forge's, so it cannot be joined onto a repository root.
    # The local is RENAMED because a variable called `seed_root` would shadow the resolver function
    # of the same name for the rest of this function's scope.
    resolved_seed = (Path(args.plan_root) if getattr(args, "plan_root", None)
                     else seed_root(plan_emit.REPO_ROOT))
    plan_dir = resolved_seed / "passive-tree" / "plan"
    plan_paths = sorted(plan_dir.glob("*.v1.json")) if plan_dir.exists() else []
    if not plan_paths:
        print(f"seedsmith: check --family PassiveTree: no committed plan under {plan_dir} — "
              f"nothing to check (run `trees plan --emit` first)", file=sys.stderr)
        return EXIT_CANNOT_RUN

    try:
        tuning_doc = plan_tuning.load()
    except plan_tuning.PassiveTreePlanTuningError as ex:
        print(f"seedsmith: {ex}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    plans = [json.loads(p.read_text(encoding="utf-8")) for p in plan_paths]

    # Real corpus-side wiring (closes the gap a same-day J1 investigation found: this ctx never
    # carried `targets`/`tree_plans`/`nodes_by_tree`/`outcomes_by_tree`, so `PassiveTree/
    # UnresolvedCount` — the ONE hard gate this family promotes — always reported NOT_MEASURED
    # here, never a real pass or fail, regardless of what the real committed corpus looked like).
    # Every input below is real, already-committed, local data — no model call, no corpus fixture:
    # `tree-language.ledger.json` (what was actually accepted) and `nodegen.plan_run` (the SAME
    # function `run_language_stage` itself uses to tell "already done" from "still needed" on a
    # resume) applied to each committed plan tells us, per tree, exactly which node ids never got
    # an accepted record. `plan_run` cannot distinguish "genuinely stuck after retries" from "never
    # attempted yet" — no run history survives past a live run (named, not fixed, in J9/J1's own
    # notes) — so every ledger-absent node is reported as `"unresolved"`, matching this gate's own
    # purpose: a node with no accepted record is a hole `tree-binder` has nothing to price, for
    # either reason, and `check --family` is a completion check, not a mid-run progress probe.
    try:
        tree_targets = load_tree_targets()
    except (PassiveTreeTargetsError, OSError):
        tree_targets = None
    ledger = nodegen_run.read_ledger(resolved_seed / "passive-tree" / "_runs" / "tree-language.ledger.json")
    tree_plans: list[object] = []
    nodes_by_tree: dict[str, list] = {}
    outcomes_by_tree: dict[str, list] = {}
    quota_cells_by_tree: dict[str, dict] = {}
    for plan_doc in plans:
        tree_id = plan_doc.get("treeId")
        if not tree_id:
            continue
        tree_plan = nodegen_plan_read.load_from_dict(plan_doc, source_label=f"plan:{tree_id}")
        tree_plans.append(tree_plan)
        run_plan = nodegen_run.plan_run(tree_plan, ledger=ledger)
        seed_doc = nodegen_emit.read_seed_document(tree_id, seed_root=resolved_seed)
        nodes_by_tree[tree_id] = list(seed_doc["nodes"]) if seed_doc else []
        outcomes = [{"nodeId": subject_id.split(":", 1)[1], "outcome": "accepted"}
                   for subject_id in run_plan.already_done]
        # A scheduled subject either has no ledger row (never attempted) or a prior FAILED attempt
        # row (`record: null` from `record_attempt`, 2026-09-11). Prefer the recorded outcome so the
        # metric reflects what actually happened (escalated/blocked/unresolved), falling back to
        # `unresolved` for a never-attempted node — the same "not accepted" bucket the metric gates.
        for subject in run_plan.subjects:
            entry = ledger.get(subject.subject_id) or {}
            outcomes.append({"nodeId": subject.node_id,
                             "outcome": entry.get("outcome") or "unresolved"})
        outcomes_by_tree[tree_id] = outcomes
        # Distribution-audit wiring (2026-09-10): re-derive each tree's six-axis cells from the
        # committed plan via the SAME `quota_for_plan` the generation CLI calls — so
        # `PassiveTree/QuotaDrift` and `PassiveTree/CellOccupancy` measure for real instead of
        # reporting NOT_MEASURED forever (the cells were never persisted on pre-2026-09-10 seed
        # records; re-derivation is the designed stand-in until a regeneration writes `quotaCell`).
        # Prefer a node's own persisted `quotaCell` when present (post-persistence generation), so
        # a future regenerated corpus is measured against what was actually assigned, not a fresh
        # re-draw that could drift from the generation-time assignment if the quota walk ever
        # changes. A tree with neither targets nor a resolvable category contributes nothing, never
        # a crash — QuotaDrift already reports NOT_MEASURED per tree in that case.
        if tree_targets is not None:
            try:
                cells = nodegen_quota.quota_for_plan(
                    tree_plan, tree_targets, category=str(plan_doc.get("category")),
                    forced_element=plan_doc.get("forcedElement"),
                    forced_status=plan_doc.get("forcedStatus"))
            except (ValueError, KeyError):
                cells = {}
            # Overlay any persisted cells from the seed document (additive; absent on old records).
            for node in nodes_by_tree[tree_id]:
                raw_cell = node.get("quotaCell")
                if not raw_cell:
                    continue
                try:
                    from ..adapters.trees.nodegen.emit import quota_cell_from_dict
                    parsed = quota_cell_from_dict(raw_cell)
                except (KeyError, TypeError):
                    continue
                if parsed is None:
                    continue
                cells[node["id"]] = nodegen_quota.QuotaCell(
                    node_class=parsed["nodeClass"], trigger=parsed["trigger"],
                    element=parsed["element"], status=parsed["status"],
                    channel_family=parsed["channelFamily"],
                    exclusion_form=parsed["exclusionForm"])
            if cells:
                quota_cells_by_tree[tree_id] = cells

    registry = build_registry()
    # H5's own reason `build_registry()` never carries `HiddenFileCountMetric`/`DeepMechanismValueMetric`
    # (see that function's own comment) is real: BOTH need externally-supplied data no generic caller
    # has. `_cmd_check_family` is different -- it just computed a real `seed_root` above, exactly what
    # `HiddenFileCountMetric` needs and nothing `DeepMechanismValueMetric` (CombatSim samples) can use
    # here either way -- so THIS caller registers it locally, closing H5's own remaining acceptance gap
    # ("populated somewhere a real run reaches") without touching the shared registry's own documented
    # exclusion for every other caller.
    registry.register(HiddenFileCountMetric())
    # SpeciesUniqueness (J6) is gates=False and deliberately NOT in ALL_PASSIVE_TREE_METRICS (that
    # tuple is H4's own eight, frozen by a length assertion). Register it here the same way
    # HiddenFileCount is — a check-family-only registration that never breaks generation's
    # assert_exactly_one_hard_gate. ExclusionPresentation stays out (gates=True; would break that
    # invariant), per metrics/passive_tree.py's own tracked note.
    registry.register(SpeciesUniquenessMetric())
    passive_tree_ctx = PassiveTreePlanCtx(
        plans=plans, archetypes=SHIPPED_ARCHETYPES, tier_count=TIER_COUNT,
        unlock_first_points=tuning_doc["unlockCost"]["firstPoints"],
        unlock_step_points=tuning_doc["unlockCost"]["stepPoints"],
        reward_spread_max_ratio_milli=tuning_doc["archetype"]["rewardSpreadMaxRatioMilli"],
        min_terminal_width=tuning_doc["potency"]["minTerminalWidth"],
        targets=tree_targets, tree_plans=tuple(tree_plans),
        nodes_by_tree=nodes_by_tree, outcomes_by_tree=outcomes_by_tree,
        quota_cells_by_tree=quota_cells_by_tree,
        # H5's own real acceptance gap (spec-tree-review.md §7): `HiddenFileCountMetric` was fully
        # built and tested but had ZERO real call site, `tree_seed_roots` always defaulting to `()`
        # everywhere outside its own test. A single root here already covers every category's own
        # seed tree via `rglob` (species's `gk-data/packs/fusion/data/seed/passive-tree/species/`,
        # spec-species-tree.md §2.1 rule 2's own requirement, included for free the moment anything
        # is committed under it — no second root needed).
        tree_seed_roots=(resolved_seed / "passive-tree",))
    ctx = Ctx(corpus=Corpus(), adapter=resolve_adapter("stub"), passive_tree_plan=passive_tree_ctx)
    family_ids = [m.id for m in registry.all() if m.family == "PassiveTree"]
    findings = run_all(registry, ctx, metric_ids=family_ids)

    if args.gate:
        try:
            tree_verdict.assert_exactly_one_hard_gate(registry, "PassiveTree")
        except ValueError as ex:
            print(f"seedsmith: check --family PassiveTree --gate: refused — {ex}", file=sys.stderr)
            return EXIT_REFUSED
        gating_ids = {m.id for m in registry.all() if m.family == "PassiveTree" and m.gates}
        relevant = [f for f in findings if f.metric in gating_ids]
    else:
        relevant = findings

    _print_human(findings)
    return EXIT_GAP if any(f.severity is Severity.GAP for f in relevant) else EXIT_CLEAN


def cmd_check(args: argparse.Namespace) -> int:
    if getattr(args, "family", None):
        return _cmd_check_family(args)

    if not args.corpus_root:
        print("seedsmith: check needs either corpus_root or --family <name>", file=sys.stderr)
        return EXIT_CANNOT_RUN

    try:
        adapter = resolve_adapter(args.adapter)
    except KeyError:
        print(f"seedsmith: unknown adapter {args.adapter!r} "
              f"(known: {', '.join(known_adapter_names())})", file=sys.stderr)
        return EXIT_CANNOT_RUN

    loader_findings = []
    if args.adapter == "actions":
        # Actions has a domain loader because `_rounds/` is scratch output and must not be
        # loaded beside the committed root corpus. Raw `Corpus.load` would see both copies of
        # the same action id and fail before any metric can run.
        from ..adapters.actions import load_committed
        try:
            load_result = load_committed(Path(args.corpus_root))
        except CorpusLoadError as e:
            print(f"seedsmith: could not load corpus: {e}", file=sys.stderr)
            return EXIT_CANNOT_RUN
        corpus = load_result.corpus
        loader_findings = load_result.findings
    elif args.adapter == "dungeon":
        # `Corpus.load()` requires a top-level `kind`/`entries` wrapper (`corpus/model.py:183-186`)
        # -- dungeon's own real content is one bare object per file (`emit.py`'s own docstring), so
        # the generic loader silently sees zero entries for this adapter. `load_dungeon_corpus`
        # (`adapters/dungeon/completeness.py`) bridges that gap; `ensure_completeness_registered`
        # wires the `Content/FieldMissing`/`Content/LanguageContamination` check for dungeon events
        # into `content_completeness`'s own registry (`seedsmith-content-standard` Task 12).
        from ..adapters.dungeon.completeness import ensure_completeness_registered, load_dungeon_corpus
        ensure_completeness_registered()
        corpus = load_dungeon_corpus(Path(args.corpus_root))
    elif args.adapter == "creatures":
        # `creature`/`commander-effect` kind files under this root already are real `{kind, entries}`
        # documents and load correctly via the generic path below -- but `species/**/*.json` is a
        # bare JSON ARRAY per file (`anchor/emit.py`'s own `render_family_file`), the same shape gap
        # dungeon has for ALL its kinds. `load_species_corpus` (`adapters/creatures/completeness.py`)
        # ADDS the one kind the generic loader cannot see on top of what it already loads correctly,
        # rather than replacing the whole load the way dungeon's own bridge does (`seedsmith-
        # content-standard` Task 10).
        from ..adapters.creatures.completeness import ensure_completeness_registered, load_species_corpus
        ensure_completeness_registered()
        try:
            corpus = Corpus.load(Path(args.corpus_root))
        except CorpusLoadError as e:
            print(f"seedsmith: could not load corpus: {e}", file=sys.stderr)
            return EXIT_CANNOT_RUN
        load_species_corpus(Path(args.corpus_root), into=corpus)
    else:
        try:
            corpus = Corpus.load(Path(args.corpus_root))
        except CorpusLoadError as e:
            print(f"seedsmith: could not load corpus: {e}", file=sys.stderr)
            return EXIT_CANNOT_RUN

    numerics_ctx = _build_numerics_context(args.adapter, adapter)
    budget_rows = derive_all(corpus, adapter) if args.adapter == "items" else None
    ctx = Ctx(corpus=corpus, adapter=adapter, numerics=numerics_ctx, budget=budget_rows)
    registry = build_registry()
    findings = run_all(registry, ctx, metric_ids=args.metric or None)
    if loader_findings and (not args.metric or "Actions/Loader" in args.metric):
        from ..metrics import Finding
        findings.extend(
            Finding(
                metric="Actions/Loader", severity=Severity.GAP,
                subject=f.entry_id or f.path,
                message=f.message,
                evidence={"code": f.code, "path": f.path, "entryId": f.entry_id},
            )
            for f in loader_findings
        )

    if args.json:
        Path(args.json).write_text(
            json.dumps([f.to_dict() for f in findings], indent=2), encoding="utf-8")

    _print_human(findings)

    relevant = findings
    if args.gate:
        gating_ids = {m.id for m in registry.all() if m.gates}
        relevant = [f for f in findings if f.metric in gating_ids]
    return EXIT_GAP if any(f.severity is Severity.GAP for f in relevant) else EXIT_CLEAN


def _load_creature_anchors(anchors_root: Path) -> list[dict] | None:
    """Reads the `_index.json` an `anchor-emit` tree publishes and loads every family file it
    names, deduplicated by file — the same O(1)-lookup structure `run-control` resumes from."""
    index_path = anchors_root / "_index.json"
    if not index_path.exists():
        return None
    index = json.loads(index_path.read_text(encoding="utf-8"))
    anchors: list[dict] = []
    for rel_path in sorted(set(index.values())):
        path = anchors_root / rel_path
        if path.exists():
            anchors.extend(json.loads(path.read_text(encoding="utf-8")))
    return anchors


def cmd_report(args: argparse.Namespace) -> int:
    """`seedsmith report [--gate] [--corpus DIR --adapter NAME] [--creature-dump DIR]` — runs the
    FULL registry (every metric family, item-corpus and creature-dump alike) in one pass. Each
    metric's own `needs` decides whether it runs against what was actually supplied; a metric
    whose need is absent reports NOT_MEASURED rather than being silently skipped (`run_all`'s own
    contract) — this is the single command T1.10/T2.12/T3.8's own metrics are meant to appear in,
    so a later phase adding a metric family never has to invent a second report command.

    At least one of `--corpus`/`--creature-dump` should normally be given; running with neither is
    legal (every metric reports NOT_MEASURED) but produces no real signal.
    """
    corpus = Corpus() if args.corpus is None else None
    if args.corpus is not None:
        try:
            corpus = Corpus.load(Path(args.corpus))
        except CorpusLoadError as e:
            print(f"seedsmith: could not load corpus: {e}", file=sys.stderr)
            return EXIT_CANNOT_RUN

    try:
        adapter = resolve_adapter(args.adapter)
    except KeyError:
        print(f"seedsmith: unknown adapter {args.adapter!r} "
              f"(known: {', '.join(known_adapter_names())})", file=sys.stderr)
        return EXIT_CANNOT_RUN

    creature_dump = None
    if args.creature_dump is not None:
        from ..adapters.creatures.dump_ctx import load_creature_dump_ctx
        creature_dump = load_creature_dump_ctx(Path(args.creature_dump))
        if creature_dump is None:
            print(f"seedsmith: no readable corpus-dump tree at {args.creature_dump}", file=sys.stderr)
            return EXIT_CANNOT_RUN

    creature_anchors = None
    if getattr(args, "creature_anchors", None) is not None:
        creature_anchors = _load_creature_anchors(Path(args.creature_anchors))
        if creature_anchors is None:
            print(f"seedsmith: no readable anchor tree at {args.creature_anchors} "
                  f"(expected an _index.json)", file=sys.stderr)
            return EXIT_CANNOT_RUN

    numerics_ctx = _build_numerics_context(args.adapter, adapter) if args.corpus is not None else None
    budget_rows = derive_all(corpus, adapter) if args.corpus is not None and args.adapter == "items" else None
    ctx = Ctx(corpus=corpus, adapter=adapter, numerics=numerics_ctx, budget=budget_rows,
             creature_dump=creature_dump, creature_anchors=creature_anchors)

    registry = build_registry()
    findings = run_all(registry, ctx, metric_ids=args.metric or None)

    if args.json:
        Path(args.json).write_text(json.dumps([f.to_dict() for f in findings], indent=2), encoding="utf-8")
    _print_human(findings)

    relevant = findings
    if args.gate:
        gating_ids = {m.id for m in registry.all() if m.gates}
        relevant = [f for f in findings if f.metric in gating_ids]
    return EXIT_GAP if any(f.severity is Severity.GAP for f in relevant) else EXIT_CLEAN


def cmd_metrics(args: argparse.Namespace) -> int:
    registry = build_registry()
    if args.coverage:
        from ..metrics.appendix_a import coverage_report
        report = coverage_report(registry.all())
        for row, metric_ids in sorted(report["claimed"], key=lambda pair: pair[0].number):
            print(f"[CLAIMED]    #{row.number} {row.family}: {row.description} — "
                  f"{', '.join(metric_ids)}")
        for row in sorted(report["known_gap"], key=lambda r: r.number):
            print(f"[KNOWN GAP]  #{row.number} {row.family}: {row.description} "
                  f"(out of W1 scope)")
        for row in sorted(report["unclaimed"], key=lambda r: r.number):
            print(f"[UNCLAIMED]  #{row.number} {row.family}: {row.description}")
        unclaimed_count = len(report["unclaimed"])
        print(f"\n{len(report['claimed'])} claimed, {len(report['known_gap'])} known gap, "
              f"{unclaimed_count} unclaimed")
        return EXIT_GAP if unclaimed_count else EXIT_CLEAN

    for metric in sorted(registry.all(), key=lambda m: m.id):
        print(f"{metric.id} ({metric.family}, {metric.loop.value}, "
              f"gates={metric.gates})")
    return EXIT_CLEAN



def cmd_effects(args: argparse.Namespace) -> int:
    """`seedsmith effects generate --kind affix` (T7.1, `affix-authoring`, effect-pipeline module 9).

    Same defect class `cmd_creatures`'s own docstring already names (D1.4): a real entrypoint reachable
    only as `python -m seedsmith.adapters.effects.affix.generate_affixes` is a documented interface
    that only works if you know the private module path — not an interface. Import deferred for the
    same reason `cmd_creatures` defers its own: `effects generate` pulls in the workflow package, and
    `langgraph` is an optional extra a base `seedsmith check` install must not require.
    """
    if args.effects_command == "generate":
        if args.kind != "affix":
            print(f"unknown kind {args.kind!r}; only 'affix' has a generator today")
            return EXIT_CANNOT_RUN
        from ..adapters.effects.affix.generate_affixes import main as run
        passthrough: list[str] = []
        if args.only:
            passthrough += ["--only", args.only]
        if args.theme:
            passthrough += ["--theme", args.theme]
        if args.endpoint:
            passthrough += ["--endpoint", args.endpoint]
        if args.model:
            passthrough += ["--model", args.model]
        if args.count:
            passthrough += ["--count", str(args.count)]
        if args.dry_run:
            passthrough.append("--dry-run")
        if args.workers:
            passthrough += ["--workers", str(args.workers)]
        if args.species_id:
            passthrough += ["--species-id", args.species_id]
        return run(passthrough)

    print(f"unknown effects command {args.effects_command!r}")
    return EXIT_CANNOT_RUN


def _apply_items_write_defaults(args: argparse.Namespace) -> None:
    """Fill empty `--out-dir` / `--allow-production-tree` from `.env` before plan or write.

    Mutates `args` in place so planning and writing share the same out-dir (ledger resume).
    """
    from ..adapters.items import defaults as items_defaults

    allow = items_defaults.allow_production_tree(cli_allow=bool(args.allow_production_tree))
    args.allow_production_tree = allow
    args.out_dir = items_defaults.resolve_out_dir_arg(
        args.kind, getattr(args, "out_dir", "") or "", allow_production=allow)


def _retry_blocked_ledger(ledger: dict[str, dict]) -> tuple[dict[str, dict], set[str]]:
    """Return a resume ledger with terminal subjects removed and duplicate-name feedback.

    Authored rows stay in the ledger.  Only rows explicitly terminal (blocked/escalated) are
    retried; duplicate-name defects are surfaced to the next model brief so repair is a new
    answer rather than an accidental replay of the rejected name.
    """
    feedback = {
        subject_id for subject_id, row in ledger.items()
        if isinstance(row, dict) and any(
            "duplicate name" in str(defect).casefold()
            for defect in (row.get("defects") or ())
        )
    }
    resumable = {
        subject_id: row for subject_id, row in ledger.items()
        if isinstance(row, dict) and row.get("outcome") not in {"blocked", "escalated"}
    }
    return resumable, feedback


def cmd_items(args: argparse.Namespace) -> int:
    """`seedsmith items generate|validate|combogen-migrate|fill` (item modules 13 + 21 + fill UX).

    ⛔ **`--dry-run` is the default on `generate`.** A real run is ~1,800 model calls; `--write`
    is the explicit opt-in. `items fill` is the intentional “just finish it” verb (write/resume
    across kinds). Empty `--endpoint` / `--out-dir` fall through to `tools/seedsmith/.env`.
    """
    if args.items_command == "validate":
        return _cmd_items_validate(args)
    if args.items_command == "combogen-migrate":
        return _cmd_items_combogen_migrate(args)
    if args.items_command == "combogen-reemit":
        return _cmd_items_combogen_reemit(args)
    if args.items_command == "fill":
        return _cmd_items_fill(args)
    if args.items_command == "repair-sets":
        return _cmd_items_repair_sets(args)
    if args.items_command == "repair-species":
        return _cmd_items_repair_species(args)
    if args.items_command == "repair-set-class":
        return _cmd_items_repair_set_class(args)
    if args.items_command == "repair-set-roles":
        return _cmd_items_repair_set_roles(args)
    if args.items_command == "repair-ledger":
        return _cmd_items_repair_ledger(args)
    if args.items_command == "repair-names":
        return _cmd_items_repair_names(args)
    if args.items_command == "repair-materials":
        return _cmd_items_repair_materials(args)

    if args.items_command == "repair-name-grammar":
        return _cmd_items_repair_name_grammar(args)
    if args.items_command == "repair-charms":
        return _cmd_items_repair_charms(args)
    if args.items_command == "combo-budget":
        return _cmd_items_combo_budget(args)
    if args.items_command != "generate":
        print(f"unknown items command {args.items_command!r}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    if args.kind in ("set", "charm", "combination"):
        if args.write or args.out_dir:
            _apply_items_write_defaults(args)
        elif args.dry_run:
            # A read-only plan must inspect the same production ledger that a write would use.
            # Do not turn on the production-write permission; only resolve its configured path.
            from ..adapters.items import defaults as items_defaults
            args.out_dir = items_defaults.default_out_dir(args.kind)

    if args.kind == "combination":
        return _cmd_items_combination(args)

    if args.kind in ("set", "charm"):
        # ⛔ Real defect, measured 2026-09-28: `--overwrite` was ACCEPTED and SILENTLY IGNORED here.
        # `items generate --kind set --overwrite set.abyssswordstar-001` reported `toGenerate: 60` and
        # `plannedBeforeLimit: 60` - naming ONE id planned 60 subjects, with nothing to say the id had
        # been dropped. The cause is structural, not a slip: `setgen.run.plan_run` takes no `overwrite`
        # argument and setgen has no `plan_overwrite` (unlike `materialgen`, which has one at
        # `materialgen/run.py:104`), so this branch cannot narrow its plan and never did.
        #
        # The flag's own `--help` documents it for `base-type` / `enhancement-milestone` / `recipe` /
        # `drop-table` and for `combination` - never for `set` or `charm` - so this is not a broken
        # promise but an accepted-and-ignored argument, and the two call for different fixes: a broken
        # promise needs the feature, an unkept one needs a refusal. Nothing needs the feature here,
        # because the NATURAL plan for these two kinds is already the closure plan: measured against the
        # 61 empty `sets/*` partitions, `--population species` plans 60 subjects covering 60 of them and
        # `--population build` plans the 61st, with NOT ONE subject failing to close a gap. So the
        # actionable advice is the population, not an id list - which is why the refusal says so.
        #
        # `material` and `trophy` are deliberately NOT caught here: they route through
        # `_cmd_items_generate_passthrough`, which DOES forward `--overwrite` to the child module. A
        # refusal placed in a shared layer would have broken them.
        overwrite_arg = (getattr(args, "overwrite", "") or "").strip()
        if overwrite_arg:
            supported = ("base-type, enhancement-milestone, recipe, drop-table, gem, material, "
                         "consumable, affix-family, trophy, combination")
            print(
                f"seedsmith: --kind {args.kind} does not support --overwrite ({overwrite_arg!r} would "
                f"have been ignored, and this branch plans the WHOLE remaining population instead, so "
                f"the run would spend on subjects you did not name). Supported kinds: {supported}.\n"
                f"  For set/charm the natural plan is already the closure plan - scope it with "
                f"--population and --limit instead:\n"
                f"    seedsmith items generate --kind {args.kind} "
                f"[--population species|build] [--limit N]",
                file=sys.stderr,
            )
            return EXIT_CANNOT_RUN

    if args.kind in ("base-type", "enhancement-milestone", "recipe", "drop-table", "gem",
                    "material", "consumable", "affix-family", "trophy"):
        return _cmd_items_generate_passthrough(args)

    from ..adapters.items.setgen import run as run_mod
    from ..adapters.items.setgen import themes as themes_mod
    from ..adapters.items.setgen import tuning as tuning_mod
    from ..adapters.items.setgen import vocab as vocab_mod
    from ..adapters.items.setgen.verdict import GATING_METRICS, missing_thresholds

    tuning = tuning_mod.load()
    vocabulary = vocab_mod.build(tuning)
    # ⛔ Real bug, found 2026-09-08 on a live run: `ledger=None` here fell through to
    # `plan_run`'s own `read_ledger()` with NO PATH, which reads a hardcoded default
    # (`data/seed/items/_runs/set-charm-gen.ledger.json`) — a COMPLETELY DIFFERENT file from the
    # one `_cmd_items_write` actually reads/writes (`<out-dir>/set-charm-gen.ledger.json`, computed
    # further down at write time). Every `--write` run against a real `--out-dir` therefore always
    # planned the FULL, un-resumed population — "alreadyDone": 0 on every single invocation, no
    # matter how many prior runs had already persisted real content — while still correctly
    # persisting fresh answers under the RIGHT ledger path, silently re-attempting (and, when a
    # subject succeeded twice, re-writing) subjects a resumed run should have skipped outright.
    # Read from the SAME path `--write` will use: `--ledger` if given, else `<out-dir>/
    # set-charm-gen.ledger.json` — matching `_cmd_items_write`'s own resolution below exactly, so
    # planning and writing can never disagree about which subjects are already done again.
    if args.ignore_ledger:
        ledger = {}
    elif args.ledger:
        ledger = run_mod.read_ledger(Path(args.ledger))
    elif args.out_dir:
        ledger = run_mod.read_ledger(Path(args.out_dir) / "set-charm-gen.ledger.json")
    else:
        ledger = None
    # Explicit recovery mode: retry only terminal blocked/escalated subjects while preserving
    # authored rows and their sequence numbers. This is deliberately separate from
    # --ignore-ledger, which would re-plan every subject and can mint duplicates.
    retry_feedback: set[str] = set()
    if getattr(args, "retry_blocked", False) and ledger:
        ledger, retry_feedback = _retry_blocked_ledger(ledger)
    # `sets_dir` is deliberately NOT threaded here, though `plan_run` accepts it. Measured, and the reason is
    # NOT subject selection: `_existing_charm_axis_counts` / `_existing_charm_class_counts` take a default
    # argument and are called with none (run.py:293-294), so `sets_dir` has exactly ONE reader -
    # `_set_entry_on_disk` at run.py:120/328/338, the CORPUS-PRESENCE check.
    #
    # So passing `out_dir` does not mislead the planner about the population; it makes the corpus-presence
    # check look at the temp dir. Run 1 writes its row there, run 2's ledger skips it AND the corpus check
    # skips it, so the plan advances to the next theme and a resumed run re-asks. Reproduced exactly:
    # toGenerate 1 -> 1 -> 1 while requests went 1 -> 5 -> 9.
    #
    # That is CORRECT behaviour, not a defect: `--ignore-ledger` is documented as "plan every generatable
    # subject, even ones a previous run recorded" - it is scoped to LEDGER rows, not to on-disk content.
    # An earlier version of this comment claimed subject selection and was wrong; do not re-litigate it
    # without re-measuring. The ledger resolution above IS the whole of the 2026-09-08 incident.
    try:
        plan = run_mod.plan_run(kind=args.kind, population=args.population,
                                tuning=tuning, vocabulary=vocabulary, ledger=ledger)
    except ValueError as exc:
        print(f"seedsmith: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    planned_total = len(plan.subjects)
    if retry_feedback:
        plan.subjects = [
            replace(subject, brief=(subject.brief + "\nPrevious attempt was rejected because its "
                                    "name duplicated an existing item. Choose a completely new "
                                    "surface name; do not reuse that name or a close variant."))
            if subject.subject_id in retry_feedback else subject
            for subject in plan.subjects
        ]
    if args.limit and args.limit > 0:
        plan.subjects = plan.subjects[:args.limit]

    coverage = themes_mod.coverage_report(themes_mod.load_species_themes())
    summary = {
        **plan.summary(),
        "kind": args.kind,
        "population": args.population,
        "plannedBeforeLimit": planned_total,
        "capabilityPicks": vocabulary.capability_count,
        "statPicks": vocabulary.stat_count,
        "themeCoverage": {"species": coverage.species, "themes": coverage.themes,
                          "uncovered": len(coverage.uncovered),
                          "orphaned": len(coverage.orphaned)},
        "gatingMetrics": sorted(GATING_METRICS),
        "gatesMissingAThreshold": missing_thresholds(tuning),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    # A stale creature theme registry is an upstream registration defect, not a smaller valid item
    # population. Without this guard, a newly shipped species absent from themes.v1.json simply
    # disappeared from the set/charm plan while the command still returned success. Refresh the
    # registry first (`seedsmith creatures themes`); never spend model calls on a partial walk.
    if args.population == "species" and (coverage.uncovered or coverage.orphaned):
        print(
            "seedsmith: species plan refused — creature theme registry is stale "
            f"(uncovered={len(coverage.uncovered)}, orphaned={len(coverage.orphaned)}); "
            "run `seedsmith creatures themes` and retry",
            file=sys.stderr,
        )
        return EXIT_CANNOT_RUN

    if args.sample_brief and plan.subjects:
        print("\n--- sample brief ---")
        print(plan.subjects[0].brief)

    if args.briefs_out:
        target = Path(args.briefs_out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({
            "schemaVersion": 1, "kind": args.kind, "population": args.population,
            "promptVersion": _prompt_version(),
            "subjects": [{**s.to_dict(), "brief": s.brief} for s in plan.subjects],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {len(plan.subjects)} brief(s) to {target}", file=sys.stderr)

    if args.write:
        return _cmd_items_write(args, plan=plan, tuning=tuning, vocabulary=vocabulary)
    return EXIT_CLEAN


def _prompt_version() -> str:
    from ..adapters.items.setgen.brief import PROMPT_VERSION
    return PROMPT_VERSION


def _cmd_items_write(args: argparse.Namespace, *, plan, tuning, vocabulary) -> int:
    """The `--write` half. Refuses loudly and specifically rather than writing an empty run.

    Empty `--out-dir` / `--endpoint` fall through to `.env` defaults (`SEEDSMITH_ALLOW_PRODUCTION_TREE`,
    production kind dirs, `SEEDSMITH_LLM_*`) via `_apply_items_write_defaults` /
    `resolve_live_transport`. A path inside `gk-data/packs/fusion/data/seed/items/` still needs allow-production.
    """
    from ..adapters.items.setgen import authored as authored_mod
    from ..adapters.items.setgen import answers as answers_mod
    from ..adapters.items.setgen import run as run_mod
    from ..adapters.items.setgen import seedfile as seedfile_mod
    from ..pipeline.llm_caller import resolve_live_transport

    _apply_items_write_defaults(args)

    if not args.out_dir:
        print("seedsmith: --write is refused — no --out-dir given and production defaults are "
              "off. Pass --out-dir, or set SEEDSMITH_ALLOW_PRODUCTION_TREE=1 in "
              "tools/seedsmith/.env (with optional SEEDSMITH_ITEMS_OUT_DIR).",
              file=sys.stderr)
        return EXIT_REFUSED

    transport = resolve_live_transport(args.endpoint, args.model, cli_mode=getattr(args, "mode", ""))
    if not args.answers and not transport.endpoint:
        print("seedsmith: --write is refused — no transport. Pass --answers <file>, "
              "--endpoint <url>, or set SEEDSMITH_LLM_ENDPOINT in tools/seedsmith/.env.",
              file=sys.stderr)
        return EXIT_REFUSED

    try:
        out_dir = seedfile_mod.resolve_out_dir(
            args.out_dir, allow_production_tree=args.allow_production_tree)
    except seedfile_mod.OutDirRefused as exc:
        print(f"seedsmith: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    call = None
    if args.answers:
        try:
            answers = answers_mod.load_answers(Path(args.answers))
        except answers_mod.AnswerFileError as exc:
            print(f"seedsmith: {exc}", file=sys.stderr)
            return EXIT_REFUSED
        if answers.kind != args.kind or answers.population != args.population:
            print(f"seedsmith: the answer file is for --kind {answers.kind} --population "
                  f"{answers.population}; this run is {args.kind}/{args.population}",
                  file=sys.stderr)
            return EXIT_REFUSED
        effective_model = args.model
    else:
        answers = answers_mod.AnswerFile(kind=args.kind, population=args.population,
                                         prompt_version=_prompt_version(), by_subject={})
        effective_model = transport.model
        call = run_mod.live_caller(transport)

    ledger_path = Path(args.ledger) if args.ledger else out_dir / "set-charm-gen.ledger.json"
    result = authored_mod.run_batch(
        plan=plan, answers=answers, tuning=tuning, vocabulary=vocabulary, out_dir=out_dir,
        kind=args.kind, population=args.population, authored_utc=args.authored_utc,
        model=effective_model, ledger_path=ledger_path, call=call)
    print("\n--- write report ---")
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return _exit_for_graph_batch(result)


def _cmd_items_repair_sets(args: argparse.Namespace) -> int:
    """Bind legacy role/frame-only set members to real base types.

    This is deliberately separate from ``items fill``: it changes existing authored rows, while
    fill only appends new subjects. The default is a read-only plan; ``--write`` is an explicit
    production-tree migration.
    """
    from ..adapters.items.setgen import repair as repair_mod
    from ..adapters.items.setgen import seedfile as seedfile_mod

    sets_dir = Path(args.sets_dir) if args.sets_dir else seedfile_mod.ITEM_SEED_ROOT / "sets"
    base_types_dir = Path(args.base_types_dir) if args.base_types_dir else None
    if args.write:
        try:
            sets_dir.resolve().relative_to(seedfile_mod.ITEM_SEED_ROOT.resolve())
        except ValueError:
            pass
        else:
            if not args.allow_production_tree:
                print("seedsmith: repair-sets refused — production data/seed/items is read-only "
                      "unless --allow-production-tree is passed", file=sys.stderr)
                return EXIT_REFUSED
    try:
        files = repair_mod.repair_set_corpus(sets_dir=sets_dir, base_types_dir=base_types_dir,
                                             write=bool(args.write))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"seedsmith: repair-sets failed — {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN
    print(json.dumps(repair_mod.repair_report(files, write=bool(args.write)),
                     ensure_ascii=False, indent=2))
    return EXIT_CLEAN


def _cmd_items_repair_species(args: argparse.Namespace) -> int:
    """species-gear-chain T28 (`set-species-binding` b): join `speciesId` onto every shipped `set`
    entry from the creature theme registry. Deterministic, no model call — a `creature.*` themeKey
    that fails to resolve refuses the WHOLE run by name rather than writing a partial repair.
    """
    from ..adapters.items.setgen import seedfile as seedfile_mod
    from ..adapters.items.setgen import species_repair as repair_mod

    sets_dir = Path(args.sets_dir) if args.sets_dir else seedfile_mod.ITEM_SEED_ROOT / "sets"
    if args.write:
        try:
            sets_dir.resolve().relative_to(seedfile_mod.ITEM_SEED_ROOT.resolve())
        except ValueError:
            pass
        else:
            if not args.allow_production_tree:
                print("seedsmith: repair-species refused — production data/seed/items is "
                      "read-only unless --allow-production-tree is passed", file=sys.stderr)
                return EXIT_REFUSED
    try:
        files = repair_mod.repair_species_ids(sets_dir=sets_dir, write=bool(args.write))
    except (OSError, ValueError, json.JSONDecodeError, repair_mod.SpeciesRepairError) as exc:
        print(f"seedsmith: repair-species failed — {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN
    print(json.dumps(repair_mod.repair_report(files, write=bool(args.write)),
                     ensure_ascii=False, indent=2))
    return EXIT_CLEAN


def _cmd_items_repair_set_class(args: argparse.Namespace) -> int:
    """species-gear-chain T27 (`set-species-binding` a, `setClass` half): resolve every shipped `set`
    entry's topology class from its OWN declared topology (distinct member roles + thresholds) through
    `setgen/topology.py`, the same resolver the emitter uses. Deterministic, no model call — and a
    shape no class admits refuses the WHOLE run by name rather than being written as `general` or
    parked in a fourth `legacy` bucket, which is what the owner's 2026-09-21 ruling refused.
    """
    from ..adapters.items.setgen import seedfile as seedfile_mod
    from ..adapters.items.setgen import topology as topology_mod
    from ..adapters.items.setgen import topology_repair as repair_mod

    sets_dir = Path(args.sets_dir) if args.sets_dir else seedfile_mod.ITEM_SEED_ROOT / "sets"
    if args.write:
        try:
            sets_dir.resolve().relative_to(seedfile_mod.ITEM_SEED_ROOT.resolve())
        except ValueError:
            pass
        else:
            if not args.allow_production_tree:
                print("seedsmith: repair-set-class refused — production data/seed/items is "
                      "read-only unless --allow-production-tree is passed", file=sys.stderr)
                return EXIT_REFUSED
    try:
        result = repair_mod.repair_set_classes(sets_dir=sets_dir, write=bool(args.write))
    except (OSError, ValueError, json.JSONDecodeError, topology_mod.SetTopologyError) as exc:
        print(f"seedsmith: repair-set-class failed — {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN
    print(json.dumps(repair_mod.repair_report(result, write=bool(args.write)),
                     ensure_ascii=False, indent=2))
    return EXIT_CLEAN

def _cmd_items_repair_set_roles(args: argparse.Namespace) -> int:
    """D30 hybrid-role backward pass (ISG-gap-1): re-place every shipped `set` member row still on a
    role core.v1.json dropped (`ward-array`/`head-guard`/`sense`) onto the host the registry's own
    `hybridDropReason` names, re-binding each member's baseType through the ONE resolver.
    Deterministic, no model call — and an entry whose role list cannot be re-placed at equal
    cardinality refuses the WHOLE run by name rather than being written with a shorter list.

    **Why a repair and not a re-run.** The five partitions that carry the defect are the legacy
    `theme.*` ones, authored 2026-08-22 against `registryVersions.core: 1` -- thirteen days before D30
    froze v2. `themes.py` treats those partitions as an id-collision list, never as generatable
    subjects, so the forward run cannot repair them: no `theme.verdant-graft` subject is planned
    again, and hand-editing the emitted rows would fork the corpus from its generator.
    """
    from ..adapters.items.setgen import role_repair as repair_mod
    from ..adapters.items.setgen import seedfile as seedfile_mod

    sets_dir = Path(args.sets_dir) if args.sets_dir else seedfile_mod.ITEM_SEED_ROOT / "sets"
    if args.write:
        try:
            sets_dir.resolve().relative_to(seedfile_mod.ITEM_SEED_ROOT.resolve())
        except ValueError:
            pass
        else:
            if not args.allow_production_tree:
                print("seedsmith: repair-set-roles refused — production data/seed/items is "
                      "read-only unless --allow-production-tree is passed", file=sys.stderr)
                return EXIT_REFUSED
    try:
        result = repair_mod.repair_set_roles(sets_dir=sets_dir, write=bool(args.write))
    except (OSError, ValueError, json.JSONDecodeError, repair_mod.SetRoleRepairError) as exc:
        print(f"seedsmith: repair-set-roles failed — {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN
    print(json.dumps(repair_mod.repair_report(result, write=bool(args.write)),
                     ensure_ascii=False, indent=2))
    return EXIT_CLEAN


def _cmd_items_repair_ledger(args: argparse.Namespace) -> int:
    """`seedsmith items repair-ledger` — drop run-ledger rows whose emitted set row is not on disk.

    **Why a repair and not a re-run.** A run ledger is a resume contract: it says a subject was emitted so
    a later run does not pay for it again, which only works while the ledger is true. Measured 2026-09-28:
    all **60** `species-no-set-entry` subjects are claimed in the sets ledger as
    `set-species-creature.<slug>` while **0** of their 60 entry ids appear in any of the 885 shipped sets
    files. `setgen/run.py:247` skipped every one of them as already-done — before the corpus check at
    `:258` could run — so `items fill --kind set --full --dry-run` reported `toGenerate 0 | complete true`
    while `ISG-gap-2-per-partition.json` counted the same partitions empty. Two views, contradictory, and
    neither pointing at the ledger. A re-run cannot fix that: the re-run reads the same ledger.

    Deterministic, no model call. Dry-run by default, and the write is refused against the production tree
    without `--allow-production-tree`, exactly as `repair-set-roles` does — a ledger rewrite cannot be
    undone from the ledger's own contents, so the safe direction has to be the default one.
    """
    from ..adapters.items.setgen import ledger_reconcile as reconcile_mod
    from ..adapters.items.setgen import seedfile as seedfile_mod

    sets_dir = Path(args.sets_dir) if args.sets_dir else seedfile_mod.ITEM_SEED_ROOT / "sets"
    # Beside the corpus, not `run_mod.DEFAULT_LEDGER`. That constant resolves to
    # `data/seed/items/_runs/set-charm-gen.ledger.json`, which does not exist; the real ledgers are
    # `gk-data/packs/fusion/data/seed/items/sets/set-charm-gen.ledger.json` and `.../charms/...`. The first run of this command
    # inherited the constant and the module's own missing-ledger refusal caught it — which is the refusal
    # earning its place, since reporting "the ledger is clean" for a file that never existed is the worst
    # answer this command could give. Deriving from `sets_dir` also means `--sets-dir` moves the ledger
    # with it, rather than reconciling one tree against another's ledger.
    ledger_path = Path(args.ledger) if args.ledger else sets_dir / "set-charm-gen.ledger.json"
    if args.write:
        try:
            sets_dir.resolve().relative_to(seedfile_mod.ITEM_SEED_ROOT.resolve())
        except ValueError:
            pass
        else:
            if not args.allow_production_tree:
                print("seedsmith: repair-ledger refused — production data/seed/items is "
                      "read-only unless --allow-production-tree is passed", file=sys.stderr)
                return EXIT_REFUSED
    try:
        result = reconcile_mod.reconcile_ledger(ledger_path=ledger_path, sets_dir=sets_dir,
                                                write=bool(args.write))
    except (OSError, ValueError, json.JSONDecodeError, reconcile_mod.LedgerReconcileError) as exc:
        print(f"seedsmith: repair-ledger failed — {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN
    print(json.dumps(reconcile_mod.reconcile_report(result, write=bool(args.write)),
                     ensure_ascii=False, indent=2))
    return EXIT_CLEAN


def _cmd_items_combo_budget(args: argparse.Namespace) -> int:
    """`seedsmith items combo-budget --report` — strain-splice-host SSH6.4 (spec-combo-budget §3).

    The readable form of the C# pricing computation: per frame both geometry readings, the per-role
    circuit count and the enabled words per admitted role; per cell power, the floor and every leg,
    the ratio, the reference and pass/fail; and, whenever anything is red, the DERIVED coefficients and
    the cells no permitted leg can fix. It asserts no reading's size. A red run is a result, not a
    crash: the ids it names are the publish `socket-pricing` owes."""
    from ..adapters.items.combogen import tuning as tuning_mod

    if not args.report:
        print("seedsmith: `items combo-budget` needs --report today — no other mode is wired.",
              file=sys.stderr)
        return EXIT_CANNOT_RUN

    from ..workspace_roots import seed_root
    root = Path(args.items_dir) if args.items_dir else (seed_root(tuning_mod.REPO_ROOT) / "items")
    try:
        dump = tuning_mod.combo_budget_dump(root)
    except RuntimeError as exc:
        print(f"seedsmith: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    return _print_combo_budget_report(dump, root)


def _print_combo_budget_report(dump: dict, items_root: Path) -> int:
    from ..adapters.items.combogen import tuning as tuning_mod

    tuning = tuning_mod.load()
    geometry = dump["geometry"]
    cells = dump["cells"]
    refused = dump["refused"]
    failing = [c for c in cells if not c["passes"]]

    # The frames come from the CORPUS's own base-type ENTRIES, never a list written here: the shipped
    # corpus puts most roles in flat `humanoid-<role>-<band>.json` files and a few in nested
    # `<role>/<frame>/<band>.json` directories, so the entry's own `frame` is the only reading that
    # sees both shapes.
    by_frame: "dict[str, set[str]]" = {}
    base_types = items_root / "base-types"
    if base_types.exists():
        for path in sorted(base_types.rglob("*.json")):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if document.get("kind") != "base-type":
                continue
            for entry in document.get("entries") or ():
                role, frame = entry.get("role"), entry.get("frame")
                if role and frame:
                    by_frame.setdefault(frame, set()).add(role)

    # Enabled words per role, from the corpus itself: a recipe with no hostRole admits every role.
    words_per_role: "dict[str, int]" = {}
    unpinned = 0
    for path in sorted((items_root / "combinations").glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if document.get("kind") != "combination":
            continue
        for entry in document.get("entries") or ():
            role = entry.get("hostRole") or ""
            if role:
                words_per_role[role] = words_per_role.get(role, 0) + 1
            else:
                unpinned += 1

    print("combo-budget report")
    print(f"  sockets revision     {tuning_mod.SOCKETS_PATH.name}")
    print(f"  materials revision   {tuning_mod.latest_materials_path().name}")
    print(f"  maxRatioToRarityRouteMilli {dump['maxRatioToRarityRouteMilli']} "
          "(D23 as arithmetic: a word may equal, never undercut, the rarity route)")
    # SSH6.8: the `measuredAgainst` object a PASSING report prints, so the publisher COPIES it into
    # `comboPricing` (spec-combo-budget §4) — never typed. It is printed even on a red run (it is the
    # measurement's own reading), but must only be PUBLISHED when the run passes.
    measured = dump.get("measuredAgainst")
    if measured is not None:
        print("  measuredAgainst      " + json.dumps(measured, separators=(",", ":")))
    print(f"  geometric ceiling    {geometry['allRoles']} over every role; "
          f"{geometry['reachable']} reachable from the shipped recipes")

    print("\nframes")
    for frame, roles in sorted(by_frame.items()):
        admitted = []
        for role in sorted(roles):
            ceiling = next((r["ceiling"] for r in geometry["byRole"] if r["role"] == role), 0)
            if ceiling <= 0:
                continue
            admitted.append(role)
        circuits = sum(next((r["circuits"] for r in geometry["byRole"] if r["role"] == role), 0)
                       for role in admitted)
        reachable = sum(
            1 for role in admitted
            if words_per_role.get(role, 0) + unpinned > 0)
        print(f"  {frame}: geometricCeiling {circuits} over {len(admitted)} role(s); "
              f"reachableCeiling {reachable} role(s) with at least one enabled word")
        for role in admitted:
            ceiling = next(r["ceiling"] for r in geometry["byRole"] if r["role"] == role)
            print(f"    {role:<20} ceiling {ceiling}  circuits {ceiling // tuning_mod.CIRCUIT_SIZE}"
                  f"  words {words_per_role.get(role, 0)}"
                  + (" (+ every unpinned word)" if unpinned else ""))
    if not by_frame:
        print("  (no base-type partitions found)")

    reference = dump["reference"]
    print(f"\nreference step       '{reference['fromRung']}' -> '{reference['toRung']}': "
          f"{reference['deltaPower']} power per {reference['elevateSouls']} souls of elevate")
    for step in dump["excludedSteps"]:
        print(f"  EXCLUDED step      '{step['fromRung']}' -> '{step['toRung']}': {step['reason']}")

    print(f"\ncells                {len(cells)} (power, floor and every leg, ratio, reference, verdict)")
    for cell in cells:
        legs = ", ".join(f"{l['name']}x{l['quantity']}={l['souls']}@r{l['rungIndex']}" for l in cell["legs"])
        verdict = "pass" if cell["passes"] else "FAIL"
        variant = "attuned" if cell["attuned"] else "plain"
        print(f"  {cell['comboId']:<44} t{cell['tier']:<2} {variant:<7} "
              f"power {cell['power']:<9} floor {cell['priceFloorSouls']:<7} "
              f"ratio {cell['ratioMilli']:<10} ref {cell['referenceMilli']:<9} {verdict}")
        print(f"      floor rung {cell['floorRungIndex']}  legs: {legs}")

    if dump["recipeRefusals"]:
        print(f"\nrecipe refusals      {len(dump['recipeRefusals'])}")
        for refusal in dump["recipeRefusals"]:
            print(f"  {refusal['reason']}: {refusal['detail']}")

    if refused:
        families = sorted({re.findall(r"grants family '([^']+)'", r["reason"])[0]
                           for r in refused if re.findall(r"grants family '([^']+)'", r["reason"])})
        other = [r for r in refused if not re.findall(r"grants family '([^']+)'", r["reason"])]
        print(f"\nunpriced cells       {len(refused)} — a container that cannot build is a content gap, "
              "named by the cell that names it")
        print(f"  distinct grant families with no atom at the requested tier: {len(families)}")
        for family in families:
            ids = sorted({r["comboId"] for r in refused if f"grants family '{family}'" in r["reason"]})
            print(f"    {family:<26} {len(ids)} cell(s), e.g. {ids[0]}")
        for row in other:
            print(f"    {row['comboId']}: {row['reason']}")

    derivation = dump["derivation"]
    if failing or refused:
        print("\nderived coefficients (only where a cell is red)")
        for lever in derivation["levers"]:
            moved = "" if lever["derivedCoefficient"] == lever["currentCoefficient"] else "  <-- moves"
            print(f"  {lever['lever']:<10} {lever['currentCoefficient']} -> "
                  f"{lever['derivedCoefficient']}{moved}")
        for fix in derivation["cells"]:
            lever = fix["smallestLever"] or "(no lever can fix this cell)"
            print(f"  {fix['comboId']:<44} levers {','.join(fix['levers']) or '-':<18} "
                  f"smallest {lever:<10} needs {fix['requiredCoefficient']}")
        for combo_id in derivation["unfixable"]:
            print(f"  UNFIXABLE {combo_id} — no permitted leg moves its floor route")

    print()
    if not failing and not refused:
        print(f"PASS — every cell is at or under the rarity route "
              f"({len(cells)} priced, 0 refused).")
        return EXIT_CLEAN
    print(f"RED — {len(failing)} cell(s) cheaper than the rarity route, {len(refused)} cell(s) "
          "unpriced; the derived coefficients above are what a materials publish owes "
          "(never a count cap).")
    return EXIT_GAP


def _cmd_items_repair_name_grammar(args: argparse.Namespace) -> int:
    """Plan or apply model-authored repairs for names the C# validator reports as failing the
    naming grammar, across every item family kind.

    Unlike `repair-names`, which is driven by duplicate-name COLLISIONS, this repair is driven by
    `ItemSeedValidator --findings-json --codes=...`: the defect is a grammar violation on an
    ALREADY-UNIQUE name. `NamingCheck` / `NameNormalizer` stay the sole authority on what fails and
    what a replacement must satisfy - nothing here re-implements `naming.v1.json`'s grammar in
    Python - so when the tool cannot run this refuses rather than guessing which names look wrong.

    NOTE the reversed argument order against the sibling: this module's `apply` takes ANSWERS FIRST
    (`apply(answers, repairs, write=True)`) where `name_repair.apply` takes repairs first. That is
    the shipped signature and it is left alone deliberately, but it is a genuine footgun.
    """
    from ..adapters.items import naming_grammar_repair as grammar_mod
    from ..pipeline.llm_caller import live_answer_caller, resolve_live_transport

    label = getattr(args, "items_command", "") or "repair-name-grammar"
    root = Path(args.items_dir) if args.items_dir else grammar_mod.ITEM_SEED_ROOT
    try:
        repairs = grammar_mod.plan(root)
    except grammar_mod.RepairRefused as exc:
        print(f"seedsmith: {label} refused - {exc}", file=sys.stderr)
        return EXIT_REFUSED
    if args.limit > 0:
        repairs = repairs[:args.limit]
    payload = {"write": bool(args.write), "repairs": [
        {"entryId": repair.entry_id, "kind": repair.kind, "oldName": repair.old_name,
         "codes": list(repair.codes), "brief": grammar_mod.brief(repair)}
        for repair in repairs]}
    if not args.write:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return EXIT_CLEAN
    if not repairs:
        # Nothing to rename is a CLEAN result, not a failed run: a corpus with no grammar finding
        # reaches this far legitimately, and reporting "no usable answers (0 failed)" would blame
        # the model for a plan that never asked it anything.
        print(json.dumps({**payload, "changed": [], "failed": []}, ensure_ascii=False, indent=2))
        return EXIT_CLEAN
    try:
        root.resolve().relative_to(grammar_mod.ITEM_SEED_ROOT.resolve())
    except ValueError:
        pass
    else:
        if not args.allow_production_tree:
            print(f"seedsmith: {label} refused - production data/seed/items is read-only "
                  "unless --allow-production-tree is passed", file=sys.stderr)
            return EXIT_REFUSED
    failed: "list[dict[str, str]]"
    if args.answers:
        document = json.loads(Path(args.answers).read_text(encoding="utf-8"))
        supplied = document.get("answers", document) if isinstance(document, dict) else None
        if not isinstance(supplied, dict):
            print(f"seedsmith: {label} answers must be a JSON object keyed by entry id",
                  file=sys.stderr)
            return EXIT_REFUSED
        # An authored answer is validated exactly as a model's is: `validate_answer` is the single
        # gate on unchanged / already-shipped / empty, so `--answers` cannot smuggle a bad name past
        # the rule the live path enforces.
        answers: "dict[str, str]" = {}
        failed = []
        taken: "set[str]" = set()
        for repair in repairs:
            raw = supplied.get(repair.entry_id)
            if raw is None:
                continue
            try:
                name = grammar_mod.validate_answer(
                    repair, raw if isinstance(raw, dict) else {"name": raw},
                    items_root=root, extra_taken=taken)
            except ValueError as exc:
                failed.append({"entryId": repair.entry_id, "reason": str(exc)})
                continue
            answers[repair.entry_id] = name
            taken.add(name.casefold())
    else:
        transport = resolve_live_transport(args.endpoint, args.model, cli_mode=getattr(args, "mode", ""))
        if not transport.endpoint:
            print(f"seedsmith: {label} --write needs --answers or a live endpoint", file=sys.stderr)
            return EXIT_REFUSED
        # `run_batch` already owns the bounded per-row retry loop (5 attempts, each refused candidate
        # named back to the model), so the resilience `repair-names` hand-rolls is not duplicated.
        answers, failed = grammar_mod.run_batch(
            repairs, caller=live_answer_caller(transport), items_root=root)
    if not answers:
        print(f"seedsmith: {label} produced no usable answers ({len(failed)} failed)",
              file=sys.stderr)
        return EXIT_CANNOT_RUN
    # Only answered rows are applied; the rest stay for the next run.
    repairs = tuple(repair for repair in repairs if repair.entry_id in answers)
    try:
        changed = grammar_mod.apply(answers, repairs, write=True)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"seedsmith: {label} failed - {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN
    print(json.dumps({**payload, "changed": [str(path) for path in changed],
                      "failed": failed}, ensure_ascii=False, indent=2))
    return EXIT_CLEAN


def _cmd_items_repair_names_derived(args: argparse.Namespace, root: Path,
                                    kind: str, label: str) -> int:
    """Apply the DETERMINISTIC repair: each losing row is renamed from its own fields.

    This is the path that needs no model. A duplicate display name is a fact about two rows, not a
    writing task, so the replacement is derived from the row's own identity - its slot ordinal and the
    concept its `scopeKey` / `speciesId` carries - and validated against the C# authority
    (`--normalize-names` for uniqueness, `--check-names` for grammar) rather than against a Python
    re-implementation of `naming.v1.json`.

    The production tree is refused exactly as the model branch refuses it, and for the same reason: a
    corpus write is not something a flag should make incidental.
    """
    from ..adapters.items.setgen import name_repair  # noqa: PLC0415 - mirrors the sibling's local import
    if not args.write:
        print(json.dumps({"write": False, "derive": True,
                          **({"kind": kind} if kind else {}),
                          "note": "dry run - pass --write to apply"},
                         ensure_ascii=False, indent=2))
        return EXIT_CLEAN
    try:
        root.resolve().relative_to(name_repair.ITEM_SEED_ROOT.resolve())
    except ValueError:
        pass
    else:
        if not args.allow_production_tree:
            print(f"seedsmith: {label} refused - production data/seed/items is read-only "
                  "unless --allow-production-tree is passed", file=sys.stderr)
            return EXIT_REFUSED
    try:
        outcome = name_repair.repair_names_deterministically(
            items_root=root, kind=kind, write=True)
    except (OSError, ValueError) as exc:
        # It raises no refusal of its own - a fully-taken row ladder is reported, not thrown - so this
        # is an I/O or bad-input failure, not a policy gate. Keep it named and loud rather than letting
        # a traceback be the interface.
        print(f"seedsmith: {label} failed - {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN
    print(json.dumps({"write": True, "derive": True, **({"kind": kind} if kind else {}),
                      "derived_count": len(outcome.get("derived", [])),
                      "derived": outcome.get("derived", []),
                      "changed_files": len(outcome.get("changed", [])),
                      "changed": [str(path) for path in outcome.get("changed", [])]},
                     ensure_ascii=False, indent=2))
    return EXIT_CLEAN


def _cmd_items_repair_names(args: argparse.Namespace, *, kind: str = "") -> int:
    """Plan or apply model-authored surface-name repairs for persisted duplicate display names.

    `kind` narrows the plan to one kind and is what `repair-materials` / `repair-charms` pass. The
    collision RULE is never re-decided here: a group's members may span kinds (measured 2026-10-01
    on the real corpus — `material.140` "The Verdant Seedling" loses to `charm.surv-util-008`
    "Verdant Seedling"), so narrowing selects which LOSING rows this run renames, never which row
    wins. A keeper is never renamed by a narrowed run, which is the point: `repair-charms` against a
    corpus where every charm is its group's keeper legitimately plans zero rows, because there is
    nothing on that side to repair.
    """
    from ..adapters.items.setgen import name_repair
    from ..pipeline.llm_caller import live_answer_caller, resolve_live_transport

    # The refusal/reporting text names the command the user actually typed, exactly as
    # `repair-sets` / `repair-species` / `repair-set-class` name their own.
    label = getattr(args, "items_command", "") or "repair-names"
    root = Path(args.items_dir) if args.items_dir else name_repair.ITEM_SEED_ROOT
    repairs = name_repair.plan(root)
    if kind:
        repairs = tuple(repair for repair in repairs if repair.kind == kind)
    if args.limit > 0:
        repairs = repairs[:args.limit]
    if getattr(args, "derive", False):
        return _cmd_items_repair_names_derived(args, root, kind, label)
    payload = {"write": bool(args.write), **({"kind": kind} if kind else {}), "repairs": [
        {"entryId": repair.entry_id, "kind": repair.kind, "oldName": repair.old_name,
         "keeperId": repair.keeper_id,
         "brief": name_repair.brief(repair, cluster_size=repair.cluster_size)}
        for repair in repairs]}
    if not args.write:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return EXIT_CLEAN
    if not repairs:
        # Nothing to rename is a CLEAN result, not a failed run: a narrowed command reaches this far
        # on a corpus with no collisions in its kind, and reporting "no usable answers (0 failed)"
        # would blame the model for a plan that never asked it anything.
        print(json.dumps({**payload, "changed": [], "failed": []}, ensure_ascii=False, indent=2))
        return EXIT_CLEAN
    try:
        root.resolve().relative_to(name_repair.ITEM_SEED_ROOT.resolve())
    except ValueError:
        pass
    else:
        if not args.allow_production_tree:
            print(f"seedsmith: {label} refused — production data/seed/items is read-only "
                  "unless --allow-production-tree is passed", file=sys.stderr)
            return EXIT_REFUSED
    # The validator's own normalizer is the authority for whether a replacement REUSES an idea
    # (`Ferocity Bulwark` vs the shipped `Bulwark of Ferocity`), not the casefold comparison —
    # without it a repair clears one collision by minting another. Bound once, for both branches.
    key_of = lambda names: name_repair.validator_keys(names, items_root=root)  # noqa: E731
    if args.answers:
        document = json.loads(Path(args.answers).read_text(encoding="utf-8"))
        answers = document.get("answers", document) if isinstance(document, dict) else None
        if not isinstance(answers, dict):
            print(f"seedsmith: {label} answers must be a JSON object keyed by entry id", file=sys.stderr)
            return EXIT_REFUSED
        failed: list[dict] = []
    else:
        transport = resolve_live_transport(args.endpoint, args.model, cli_mode=getattr(args, "mode", ""))
        if not transport.endpoint:
            print(f"seedsmith: {label} --write needs --answers or a live endpoint", file=sys.stderr)
            return EXIT_REFUSED
        caller = live_answer_caller(transport)
        # Per-row resilience with a bounded retry. A single out-of-vocabulary answer ("Evasion"
        # when "Evasion" already ships) used to abort the WHOLE batch, discarding every good answer
        # generated before it — and a local model needs a second try far more often than a whole
        # batch needs discarding. A row that still fails after the retries is reported with its
        # reason and skipped, never silently written.
        answers: dict = {}
        failed: list[dict] = []
        taken: set[str] = set()
        for repair in repairs:
            prompt = name_repair.brief(repair, cluster_size=repair.cluster_size)
            attempted: list[str] = []
            for attempt in (1, 2, 3, 4, 5):
                try:
                    answer = caller(prompt, name_repair.schema())
                    name_repair.validate_answers((repair,), {repair.entry_id: answer},
                                                 items_root=root, extra_taken=taken, key_of=key_of)
                    answers[repair.entry_id] = answer
                    taken.add(str(answer.get("name", "")).strip())
                    break
                except (ValueError, json.JSONDecodeError) as exc:
                    last = str(exc)
                    attempted.append(str(answer.get("name", "")) if isinstance(answer, dict) else "?")
                    # Name the rejected candidates explicitly. A local model repeats "Verdant
                    # Reliquary" or a CJK name indefinitely when only told "already exists"; the
                    # concrete refusal list is what breaks the loop. The CJK rows additionally need
                    # to be told the name must be ASCII (the key is derived from it).
                    prompt = (
                        name_repair.brief(repair, cluster_size=repair.cluster_size)
                        + f"\n\nYour previous answers were refused: {', '.join(attempted)}.\n"
                        + "Return a DIFFERENT name that is NOT any of those and is not already in the "
                        + "game. Use ONLY English words from the game's own vocabulary — no CJK "
                        + "characters, because the id key is derived from the name.\n")
                    if attempt == 5:
                        failed.append({"entryId": repair.entry_id, "reason": last})
                except RuntimeError as exc:
                    # A transport failure is not the row's fault; report and continue.
                    failed.append({"entryId": repair.entry_id, "reason": f"model call failed: {exc}"})
                    break
        if not answers:
            print(f"seedsmith: {label} produced no usable answers ({len(failed)} failed)",
                  file=sys.stderr)
            return EXIT_CANNOT_RUN
        # Only the rows with a valid answer are applied; the rest stay for the next run.
        repairs = tuple(r for r in repairs if r.entry_id in answers)
    try:
        changed = name_repair.apply(repairs, answers, write=True, items_root=root, key_of=key_of)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"seedsmith: {label} failed — {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN
    print(json.dumps({**payload, "changed": [str(path) for path in changed],
                      "failed": failed}, ensure_ascii=False, indent=2))
    return EXIT_CLEAN


def _cmd_items_repair_materials(args: argparse.Namespace) -> int:
    """`seedsmith items repair-materials` — the `name_repair` plan narrowed to `kind == "material"`.

    Materials are the largest colliding population (measured 2026-10-01 on the real corpus: 72 of the
    84 losing rows across 66 groups), and they collide ACROSS kinds with charms and sets, so a run
    that cannot be narrowed would either mix three populations into one model batch or slice the
    wrong subset with `--limit`.
    """
    return _cmd_items_repair_names(args, kind="material")


def _cmd_items_repair_charms(args: argparse.Namespace) -> int:
    """`seedsmith items repair-charms` — the `name_repair` plan narrowed to `kind == "charm"`.

    The narrow kind because `plan()` keeps the lexically first id of each group, and `charm.` sorts
    before `material.` and `set.`: every charm in a cross-kind group is therefore the keeper, so a
    charm is only ever renamed when it collides with another charm. Measured 2026-10-01 on the real
    corpus that is 0 losing rows — charms are 5 group members and 5 keepers — which is the correct
    answer, not a missing detection.
    """
    return _cmd_items_repair_names(args, kind="charm")


_PASSTHROUGH_MODULE_BY_KIND = {
    "base-type": "..adapters.items.basetypegen.run",
    "enhancement-milestone": "..adapters.items.milestonegen.run",
    "recipe": "..adapters.items.recipegen.run",
    "drop-table": "..adapters.items.droptablegen.run",
    "gem": "..adapters.items.gemgen.run",
    "material": "..adapters.items.materialgen.run",
    "consumable": "..adapters.items.consumablegen.run",
    "affix-family": "..adapters.items.affixfamgen.run",
    "trophy": "..adapters.items.trophyplan.run",
}


def _cmd_items_generate_passthrough(args: argparse.Namespace) -> int:
    """`seedsmith items generate --kind base-type|enhancement-milestone|recipe|drop-table`.

    Each of these four kinds has real, tested generation machinery of its own
    (`basetypegen`/`milestonegen`/`recipegen`/`droptablegen`, each `run.py`'s own `main(argv)`) but
    was never reachable through `items generate --kind <x>` — the shape every one of their own specs
    (`docs/architecture/item-seedgen/spec-*.md`) already documents as the real invocation. Fixed by
    passthrough, mirroring `cmd_effects`'s own `--kind affix` dispatch: this function builds an argv
    list from whichever of the shared flags the operator actually set, and hands it to that module's
    own argparse — so each module's own flag semantics (including a default `--count` that differs
    per module, deliberately never forced to one shared value here) apply exactly as if its script
    had been invoked directly.
    """
    import importlib

    mod = importlib.import_module(_PASSTHROUGH_MODULE_BY_KIND[args.kind], package=__package__)

    passthrough: list[str] = []
    if args.kind == "base-type":
        if not args.role:
            print("seedsmith: --kind base-type needs --role", file=sys.stderr)
            return EXIT_CANNOT_RUN
        if not args.frame:
            print("seedsmith: --kind base-type needs --frame", file=sys.stderr)
            return EXIT_CANNOT_RUN
        if not args.band:
            print("seedsmith: --kind base-type needs --band", file=sys.stderr)
            return EXIT_CANNOT_RUN
        passthrough += ["--role", args.role, "--frame", args.frame, "--band", args.band]
    if args.kind in ("drop-table", "gem"):
        if not args.slot:
            print(f"seedsmith: --kind {args.kind} needs --slot", file=sys.stderr)
            return EXIT_CANNOT_RUN
        passthrough += ["--slot", str(args.slot)]
    if args.kind == "consumable" and args.slot:
        # Optional here (unlike drop-table/gem): consumablegen's own main() only requires --slot
        # for a brand-new entry, never for --overwrite <existing-id>.
        passthrough += ["--slot", str(args.slot)]
    if args.kind == "affix-family":
        if not args.group:
            print("seedsmith: --kind affix-family needs --group", file=sys.stderr)
            return EXIT_CANNOT_RUN
        if not args.affix_kind:
            print("seedsmith: --kind affix-family needs --affix-kind", file=sys.stderr)
            return EXIT_CANNOT_RUN
        passthrough += ["--group", args.group, "--affix-kind", args.affix_kind]
    if args.kind in ("base-type", "enhancement-milestone", "drop-table", "consumable",
                    "affix-family"):
        passthrough += ["--theme", args.theme] if args.theme else []
    if args.kind == "recipe" and args.theme:
        # recipegen's own flag reads a FILE path, not an inline hint — write the hint to a temp
        # file so the same shared `--theme` string works uniformly across all four kinds.
        import os
        import tempfile
        fd, brief_path = tempfile.mkstemp(suffix=".txt", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(args.theme)
        passthrough += ["--brief", brief_path]
    if args.count is not None and args.kind not in ("consumable", "affix-family"):
        # gemgen's own flag is named `--batch-size`, not `--count` (it draws a whole gems/N
        # partition batch at once, not N independent open-ended draws like the other three) —
        # the shared `--count` flag still selects it, so an operator does not need to learn a
        # second flag name per kind. consumablegen/affix-family have no `--count` at all — each
        # mints exactly one entry per invocation (neither ever had a batch-planning mechanism).
        passthrough += ["--batch-size" if args.kind == "gem" else "--count", str(args.count)]
    if args.overwrite and args.kind != "affix-family":
        # affix-family has no --overwrite: the module's own `force_requests` mechanism needs a
        # previously-recorded ledger row to reconcile against (a real request's own `word`, which
        # only becomes known AFTER a model answers) — there is no id string an operator could name
        # upfront the way every sibling module's own --overwrite <id> takes.
        passthrough += ["--overwrite", args.overwrite]
    if args.kind == "recipe" and args.backfill:
        passthrough.append("--backfill")
    if args.dry_run:
        passthrough.append("--dry-run")
    if args.write:
        passthrough.append("--write")
    if args.endpoint:
        passthrough += ["--endpoint", args.endpoint]
    if args.model and args.model != "unrecorded":
        passthrough += ["--model", args.model]
    if getattr(args, "max_name_attempts", None) is not None:
        # ⛔ Unreachable knob, fixed 2026-09-28. `materialgen.run` has had `--max-name-attempts` and
        # `--max-consecutive-call-failures` on its OWN parser since they were written, and neither was
        # forwarded here — so `seedsmith items generate --kind material` could not reach them at all. A
        # live re-emit found it the hard way: the child exited 2 (argparse rejecting an unknown flag) with
        # 0 ids written. The runner had to add the flag to its own argv too, which makes this the THIRD
        # instance in this programme of a named knob that exists and is silently dropped before the work
        # — after `--overwrite` on `--kind set`/`charm`, and after `basetypegen`'s partition-name guard
        # reading a registry `check` never consults. A knob is only a control if the whole path carries it.
        #
        # `is not None` rather than truthiness on both counts: an explicit `0` is a real request
        # (disable the re-ask, or never stop on call failures), and `if args.x:` would drop it.
        if args.kind == "material":
            passthrough += ["--max-name-attempts", str(args.max_name_attempts)]
    if getattr(args, "max_consecutive_call_failures", None) is not None:
        if args.kind == "material":
            passthrough += ["--max-consecutive-call-failures", str(args.max_consecutive_call_failures)]

    return mod.main(passthrough)


def _combination_needing_work(plan, ledger, *, retry_blocked: bool):
    """`authored.plan_needing_work` plus, under `--retry-blocked`, every subject the ledger
    currently marks `blocked`/`escalated` — drawn from the ledger's own real rows, never a
    caller-supplied id list, so a widened vocabulary (SSH2.1's grant fix) or a widened host-role set
    (R11) is retried automatically without hand-copying ids. An authored (persisted) subject is
    never in this set either way — `plan_needing_work` already excludes it via `_ledger_is_valid`,
    and this function only ADDS blocked/escalated ids on top, so `--retry-blocked` can never
    resurrect a persisted row (`retry_blocked_never_reruns_an_authored_cell`, SSH2.2)."""
    from ..adapters.items.combogen import authored as authored_mod

    needing = authored_mod.plan_needing_work(plan, ledger)
    if not retry_blocked:
        return needing
    done = ledger.read_done()
    already = {s.subject_id for s in needing}
    extra = [
        s for s in plan.subjects
        if s.subject_id not in already
        and isinstance(done.get(s.subject_id), dict)
        and done[s.subject_id].get("outcome") in {"blocked", "escalated"}
    ]
    return needing + extra


def _combination_overwrite_subjects(plan, token: str):
    """`--overwrite <ids>` for `--kind combination`. Accepts an entry id (`combo.splice-x-y`, the
    validator's own spelling) or a subject id (`combination-splice-x-y`, the ledger's), comma
    separated, or the literal `all`. Returns the matching subjects in grid order, or `None` when a
    name matches nothing — a typo must refuse loudly rather than silently re-running nothing, the
    same boundary `plan_overwrite`'s bare-string guard enforces one layer down (SSH2.5 needed this
    and had to run the full `--retry-blocked` walk because `--limit` does not partition it)."""
    token = (token or "").strip()
    if token == "all":
        return list(plan.subjects)
    wanted = [part.strip() for part in token.split(",") if part.strip()]
    by_entry = {s.entry_id: s for s in plan.subjects}
    by_subject = {s.subject_id: s for s in plan.subjects}
    missing = [w for w in wanted if w not in by_entry and w not in by_subject]
    if missing:
        return None
    chosen = [by_entry.get(w) or by_subject[w] for w in wanted]
    order = {s.subject_id: i for i, s in enumerate(plan.subjects)}
    return sorted(chosen, key=lambda s: order[s.subject_id])


def _combination_still_blocked_rows(shape_subjects, ledger, *, shape: str,
                                    retry_label: str = "",
                                    prior_rows: list[dict] | None = None) -> list[dict]:
    """R13's still-blocked report, for ONE shape. `shape_subjects` must be the FULL, un-narrowed
    grid for `shape` (every cell `run.cells_for(shape)` mints), never an already-narrowed
    `needing`/`overwrite` list — a cell this run did not even attempt (because it was already
    ledgered `blocked` and `--retry-blocked` was not passed) must still appear here, or the report
    would silently drop every cell nobody is currently re-running.

    One row per still-`blocked` cell: `gridId` (the subject's own grid-cell key, recovered from
    `Subject.subject_id`'s own `combination-{shape}-{cell.key}` shape — never re-derived from
    `StrainSpliceGrid.AllIds` directly, since this module has no C# access; the id space is the
    SAME one by construction, per `grid.py`'s own "keeps a Strain's grid and a build set's grid the
    SAME grid" discipline), `shape`, `aptitudes`, `archetype`, `blockedReason` (the model's own
    words), `outcome`, and `survivedReruns` — the ordered list of `--retry-label`s this cell has
    answered `blocked` again under, carried forward from `prior_rows` (the JSON artefact's own last
    write) and never invented from ledger state that does not exist. A cell that resolves (persists
    or is ruled) simply stops appearing — it is not "withdrawn" from the grid (the grid is a closed
    product of the aptitude/archetype axes, untouched by this function), only from THIS report.

    ⛔ `escalated` is the OTHER terminal non-entry state and is reported here too. It is not a
    `blocked` answer — the graph's validators refused every draft the model produced — but a report
    that filtered on `blocked` alone would drop it from R13's own gate ("every cell is `entry` or
    listed by id") while every retry path already treats it as work remaining
    (`_combination_needing_work`). Measured 2026-09-21: the R11 re-run's
    `combo.strain-ferocity-balance` escalated against the shipped-name guard and vanished from the
    artefact. Its `blockedReason` carries the validator defects instead of a model decline.
    """
    prior_by_id = {
        r["gridId"]: r for r in (prior_rows or ()) if isinstance(r, dict) and r.get("shape") == shape
    }
    done = ledger.read_done()
    prefix = f"combination-{shape}-"
    rows: list[dict] = []
    for subject in shape_subjects:
        row = done.get(subject.subject_id)
        outcome = row.get("outcome") if isinstance(row, dict) else None
        if outcome not in ("blocked", "escalated"):
            continue
        grid_id = (subject.subject_id[len(prefix):] if subject.subject_id.startswith(prefix)
                  else subject.subject_id)
        survived = list(prior_by_id.get(grid_id, {}).get("survivedReruns", ()))
        if retry_label and (not survived or survived[-1] != retry_label):
            survived.append(retry_label)
        reason = (str(row.get("blockedReason", "")) if outcome == "blocked"
                  else "; ".join(str(d) for d in (row.get("defects") or ())) or "escalated")
        rows.append({
            "gridId": grid_id,
            "shape": shape,
            "aptitudes": list(subject.aptitudes),
            "archetype": subject.archetype,
            "blockedReason": reason,
            "outcome": outcome,
            "survivedReruns": survived,
        })
    return sorted(rows, key=lambda r: r["gridId"])


def _read_combination_still_blocked_prior(ledger_root: Path) -> list[dict]:
    """Read-only: the JSON artefact's own last write, if one exists yet. Safe to call on every
    invocation, `--dry-run` included — reading never mutates the production tree."""
    report_path = ledger_root / "combination-still-blocked.json"
    if not report_path.exists():
        return []
    try:
        return json.loads(report_path.read_text(encoding="utf-8")).get("rows", [])
    except (json.JSONDecodeError, OSError):
        return []


def _persist_combination_still_blocked_report(shape_rows: list[dict], *, shape: str,
                                              ledger_root: Path,
                                              prior_rows: list[dict]) -> None:
    """Merge-write beside the ledger (`combination-still-blocked.json`, one file shared by both
    shapes — a strain run must never wipe a splice run's own still-blocked rows, and vice versa).

    Called ONLY after a real `--write` run: `--dry-run` reads the report (via
    `_read_combination_still_blocked_prior` + `_combination_still_blocked_rows`) but never writes
    it, matching every other path in `items generate --dry-run` — nothing in this command persists
    to the production tree without `--write` except the explicitly opt-in `--briefs-out`, and this
    artefact does not get a second, implicit exception."""
    other_rows = [r for r in prior_rows if isinstance(r, dict) and r.get("shape") != shape]
    merged = sorted(other_rows + shape_rows, key=lambda r: (r.get("shape", ""), r.get("gridId", "")))
    report_path = ledger_root / "combination-still-blocked.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps({"schemaVersion": 1, "rows": merged}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def _cmd_items_combination(args: argparse.Namespace) -> int:
    """`seedsmith items generate --kind combination --shape strain|splice` (item module 21).

    ⛔ **`--dry-run` is the default here too.** A real run is 102 model calls; the plan, the ids, the
    gem-supply precheck and the learnability report all run without one, which is what makes the run
    inspectable before a token is spent.

    ⚠ **`--population` is meaningless for a combination and is refused rather than ignored.** The
    grid is closed — 12 aptitudes x 3 archetypes and C(12,2) — so there is no species/build split to
    make, and silently accepting the flag would let a caller believe they had selected something.
    """
    from ..adapters.items.combogen import deps as deps_mod
    from ..adapters.items.combogen import migrate as migrate_mod
    from ..adapters.items.combogen import run as run_mod
    from ..adapters.items.combogen import supply as supply_mod
    from ..adapters.items.combogen import tuning as tuning_mod

    if getattr(args, "population", None) not in (None, "species"):
        # "species" is the parser default, i.e. "not passed"; anything else was passed on purpose.
        print("seedsmith: --population does not apply to --kind combination — the grid is closed "
              "(12 aptitudes x 3 archetypes, and C(12,2)); use --shape strain|splice",
              file=sys.stderr)
        return EXIT_CANNOT_RUN

    tuning = tuning_mod.load()
    retry_blocked = getattr(args, "retry_blocked", False)
    # item-seed-gen ISG3: `--overwrite <ids>` names cells to re-author, alongside ssh27's own R11
    # pre-flight below. A caller passing BOTH has made a USAGE error, and it must be reported before
    # the tuning-state refusal below can fire: otherwise the exit code depends on corpus state rather
    # than on the flags the caller passed. Found when the two lanes' guards were merged (merge of
    # 4e94fd92): the pre-flight returned EXIT_REFUSED 3 where CliTests expects EXIT_CANNOT_RUN 2.
    overwrite_arg = (getattr(args, "overwrite", "") or "").strip()
    explicit_overwrite = bool(overwrite_arg)
    if explicit_overwrite and retry_blocked:
        print("seedsmith: --overwrite and --retry-blocked select different subject sets — pass "
              "one, not both", file=sys.stderr)
        return EXIT_CANNOT_RUN
    if retry_blocked:
        # R11 pre-flight (strain-splice-host SSH2.7), BEFORE any model call: the host set is
        # derived from the TUNING ceilings, not from the base-type corpus, so between
        # `sockets.v2.json` (head-guard 4) and SSH5.12's `resocket --write` re-stamp the model
        # would be offered the helm while no helm chassis yet holds four sockets. Refuse by role
        # name and stop — a plan built here would author words the game cannot equip.
        stranded = deps_mod.roles_without_a_base(tuning)
        if stranded:
            print("seedsmith: the --retry-blocked re-run is refused before any model call — the "
                  f"tuning offers host role(s) {', '.join(stranded)} but no shipped base type's "
                  f"socketMax reaches the ingredient count ({tuning.ingredient_count}); re-stamp "
                  "the base-type corpus (circuit-topology SSH5.12 `resocket --write`) first.",
                  file=sys.stderr)
            return EXIT_REFUSED
    try:
        supply = supply_mod.build()
        plan = run_mod.plan_run(shape=args.shape, tuning=tuning, supply=supply)
    except (ValueError, supply_mod.SupplyRefused) as exc:
        print(f"seedsmith: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    planned_total = len(plan.subjects)
    full_subjects = plan.subjects  # captured before narrowing -- the still-blocked report (R13)
    # needs the WHOLE grid for this shape, including cells nobody is attempting this run.
    # Resume before limit: slicing the full grid first made --limit 1 hit an already-ledgered
    # sample cell and report planned=0 while dozens of subjects still needed work.
    from ..adapters.items.combogen import authored as authored_mod
    from ..pipeline.run_ledger import RunLedger
    import dataclasses

    ledger_root = Path(args.out_dir) if args.out_dir else authored_mod.COMBINATIONS_DIR
    ledger = RunLedger(ledger_root / authored_mod.DEFAULT_LEDGER_NAME)
    # (the `--overwrite` + `--retry-blocked` usage refusal is made above, before the R11 pre-flight,
    # so a combined-flags call is refused for the flags it passed and not for corpus state)
    if explicit_overwrite:
        chosen = _combination_overwrite_subjects(plan, overwrite_arg)
        if chosen is None:
            print(f"seedsmith: --overwrite names an id that is not a grid subject of shape "
                  f"{args.shape!r}: {overwrite_arg!r} — ids are entry ids "
                  f"('combo.splice-x-y') or subject ids ('combination-splice-x-y'), or 'all'",
                  file=sys.stderr)
            return EXIT_CANNOT_RUN
        needing = chosen
    else:
        needing = _combination_needing_work(plan, ledger, retry_blocked=retry_blocked)
    if args.limit and args.limit > 0:
        needing = needing[: args.limit]
    plan = dataclasses.replace(plan, subjects=needing)

    legality = migrate_mod.legality_report(tuning, host_roles=plan.host_roles)
    summary = {
        **plan.summary(),
        "kind": "combination",
        "plannedBeforeLimit": planned_total,
        "ingredientCount": tuning.ingredient_count,
        "attunedTierBonus": tuning.attuned_tier_bonus,
        "legacyRetirement": legality.to_dict(),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.sample_brief and plan.subjects:
        print("\n--- sample brief ---")
        print(plan.subjects[0].brief)

    if args.briefs_out:
        from ..adapters.items.combogen.brief import PROMPT_VERSION as combo_prompt_version

        target = Path(args.briefs_out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({
            "schemaVersion": 1, "kind": "combination", "shape": args.shape,
            "promptVersion": combo_prompt_version,
            "subjects": [{**s.to_dict(), "brief": s.brief} for s in plan.subjects],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {len(plan.subjects)} brief(s) to {target}", file=sys.stderr)

    if args.write:
        exit_code = _cmd_items_combination_write(args, plan=plan, tuning=tuning)
    else:
        exit_code = EXIT_CLEAN

    # R13: report every still-blocked cell of THIS shape, read fresh from the SAME ledger the run
    # itself used -- never a second reader that could disagree with what was actually persisted.
    # After a real `--write` run this also PERSISTS the merged JSON artefact beside the ledger; a
    # `--dry-run` only reads and prints it -- `--dry-run` writes nothing to the production tree
    # anywhere else in this command (except the explicitly opt-in `--briefs-out`), and this report
    # does not get an implicit exception. Printed to STDERR, never stdout: `items generate
    # --dry-run`'s stdout is a single parseable JSON object (`CliTests.test_items_generate_kind_
    # combination_plans_both_shapes` reads it with a bare `json.loads`), and this report is a
    # separate artefact, not a field of that summary -- an additional stdout block would silently
    # break that parse.
    prior_rows = _read_combination_still_blocked_prior(ledger_root)
    still_blocked = _combination_still_blocked_rows(
        full_subjects, ledger, shape=args.shape, retry_label=getattr(args, "retry_label", ""),
        prior_rows=prior_rows)
    # `args.out_dir` (not just `args.write`) gates the persist: when `--write` is refused before
    # any out-dir was resolved (`_cmd_items_combination_write`'s own "no --out-dir given and
    # production defaults are off" refusal), `ledger_root` fell back to
    # `authored_mod.COMBINATIONS_DIR` a few lines up -- persisting there would write to the REAL
    # production tree as a side effect of a REFUSED run that touched nothing else. Real bug, found
    # by `CliTests.test_write_is_refused_rather_than_writing_nothing`: without this check that test
    # left an untracked `combination-still-blocked.json` in `gk-data/packs/fusion/data/seed/items/combinations/` on
    # every pytest run.
    if args.write and args.out_dir:
        _persist_combination_still_blocked_report(
            still_blocked, shape=args.shape, ledger_root=ledger_root, prior_rows=prior_rows)
    print("\n--- still-blocked report (R13) ---", file=sys.stderr)
    print(json.dumps({"shape": args.shape, "blocked": len(still_blocked), "rows": still_blocked},
                     ensure_ascii=False, indent=2), file=sys.stderr)
    return exit_code


def _cmd_items_combination_write(args: argparse.Namespace, *, plan, tuning) -> int:
    """The `--write` half for `--kind combination` (`combination-write-unblock`, item module 21).

    ⛔ **Investigation finding, not an assumption.** The refusal this replaces used to read *"the
    generation graph... is not wired, and the kind rename touches a FROZEN registry"* as one
    blocker. They are two SEPARATE facts and only the first was real:

    1. **The graph really was unwired** — `combogen/grid.py`, `catalogue.py`, `schema.py`,
       `supply.py`, `emit.py`, `brief.py` and `run.py` were already complete (`run.plan_run`
       produced real subjects and briefs before this module touched anything); what did not exist
       anywhere was `workflow/graphs/item_combination.py` — the file that connects a subject's
       brief to an LLM caller — or a batch driver to run subjects through it
       (`combogen/authored.py`, mirroring `setgen.authored.run_batch`). Both now exist. This
       mirrors module 13's own history almost exactly (`workflow/graphs/item_set.py`'s docstring
       names the identical defect it fixed).
    2. **The frozen-registry claim does not hold up.** `naming.v1.json`'s `idNamespaces.socketWords`
       (then `registryVersion 4`, `frozen: true`) allocated the WAVE-1 AUTHORING FLEET's tracking-id
       template (`sockword.{seq:03}`) — a collision-avoidance scheme for ~125 PARALLEL human/LLM
       partitions. The `combination` generator is a single deterministic pipeline (one grid,
       zero parallel partitions, `run.plan_run` already asserts its 102 ids are unique by
       construction) that mints `combo.strain-*`/`combo.splice-*` directly from the grid cell —
       it never draws from `sockword.{seq:03}` at all. The same precedent already exists,
       unregistered, for other deterministic post-wave-1 batches: `build-themes.v1.json`'s 36
       Strain themes and module 16's C# `ResonanceGenerator` output both have NO `naming.v1.json`
       idNamespaces entry either, because that registry exists to coordinate parallel AUTHORING
       AGENTS, and neither of those is one. **That allocation is now RETIRED rather than worked
       around** (item-seed-gen ISG7, 2026-09-20): `sockwords.json` is gone, `socket-word` is gone
       from both kind tables, and `idNamespaces.socketWords` became `idNamespaces._socketWords`
       (the registry's own `_`-prefix "not a live namespace" convention) at registryVersion 10 —
       an allocated namespace with no kind is a stop-the-fleet gap the validator must keep
       reporting (`MissingNamespaces`/`NamespaceUncovered`), and this one had no content left to
       validate. **The workaround this module originally took:** the
       frozen registry is not bumped, and no `decisions.md` entry is added for a change that is
       not made** — per the spec's own instruction, the pre-approval to bump was conditional on no
       workaround existing, and one does.

    **A real, separate, and NOT worked around gap:** `gk-forge/tools/ItemSeedValidator/Registries/
    KindCatalog.cs` has no `combination` entry (only the legacy `socket-word`), so
    `NamespaceAllocation` cannot allocate a prefix for it and the C# validator will not recognize a
    `combination`-kind seed file today. Closing that needs a C# change, and this module's own
    boundary is read-only C# — so it is reported here, not silently patched around and not hidden.
    Content this command writes is verified against the checks this program's OWN Python tooling
    owns (`items validate --deps`, schema/`audit_schema` conformance, `dependency_validator`), not
    against `gk-forge/tools/ItemSeedValidator`.
    """
    from ..adapters.items.combogen import authored as authored_mod
    from ..adapters.items.setgen import answers as answers_mod
    from ..adapters.items.setgen import run as set_run_mod
    from ..adapters.items.setgen import seedfile as seedfile_mod
    from ..pipeline.llm_caller import resolve_live_transport

    _apply_items_write_defaults(args)

    if not args.out_dir:
        print("seedsmith: --write is refused — no --out-dir given and production defaults are "
              "off. Pass --out-dir, or set SEEDSMITH_ALLOW_PRODUCTION_TREE=1 in "
              "tools/seedsmith/.env.", file=sys.stderr)
        return EXIT_REFUSED
    transport = resolve_live_transport(args.endpoint, args.model, cli_mode=getattr(args, "mode", ""))
    if not args.answers and not transport.endpoint:
        print("seedsmith: --write is refused — no transport. Pass --answers <file>, "
              "--endpoint <url>, or set SEEDSMITH_LLM_ENDPOINT in tools/seedsmith/.env.",
              file=sys.stderr)
        return EXIT_REFUSED
    try:
        out_dir = seedfile_mod.resolve_out_dir(
            args.out_dir, allow_production_tree=args.allow_production_tree)
    except seedfile_mod.OutDirRefused as exc:
        print(f"seedsmith: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    call = None
    if args.answers:
        try:
            answers = answers_mod.load_answers(Path(args.answers))
        except answers_mod.AnswerFileError as exc:
            print(f"seedsmith: {exc}", file=sys.stderr)
            return EXIT_REFUSED
        if answers.kind != "combination":
            print(f"seedsmith: the answer file is for --kind {answers.kind!r}; this run is "
                  f"'combination'", file=sys.stderr)
            return EXIT_REFUSED
        effective_model = args.model
    else:
        answers = answers_mod.AnswerFile(
            kind="combination", population="n/a", prompt_version="live", by_subject={})
        effective_model = transport.model
        call = set_run_mod.live_caller(transport)

    ledger_path = Path(args.ledger) if args.ledger else None
    # `plan.subjects` here is already `_combination_needing_work`'s own narrowed set (computed by
    # `_cmd_items_combination` before this function was called) -- under `--retry-blocked` that set
    # includes cells `run_batch`'s OWN internal `plan_needing_work` call would otherwise re-exclude
    # (a `blocked` ledger row reads as "already valid, skip" to `_ledger_is_valid`). Passing these
    # ids through `overwrite` makes `run_batch` use `plan_overwrite` instead, which bypasses that
    # re-check for exactly the ids this caller already decided need work -- never a wider "all".
    # The same path carries an explicit `--overwrite <ids>` request, which is how a cell that is
    # `persisted` but wrong (SSH2.5's grants) is re-authored.
    overwrite_ids = ([s.subject_id for s in plan.subjects]
                     if (getattr(args, "retry_blocked", False)
                         or (getattr(args, "overwrite", "") or "").strip()) else None)
    # The name-collision guard (2026-09-21): the shipped corpus's own normalized keys come from the
    # validator, never a Python re-implementation, so an authored row can neither duplicate a
    # shipped name nor a sibling minted in this same run. Refused rather than skipped when the
    # authoritative check cannot run — a run that cannot check names must not author them.
    from ..adapters.items.setgen import name_repair as name_repair_mod
    try:
        taken_keys = name_repair_mod.shipped_name_keys()
        key_of = lambda names: name_repair_mod.validator_keys(names)  # noqa: E731
        # SSH5.13-P1: the same authority, for the naming GRAMMAR. A single-word fusion that does not
        # decompose into two pool words is refused by name here, with the defect as heal feedback,
        # instead of being written and caught by the C# gate afterwards.
        name_defects = lambda names: name_repair_mod.name_defects(names)  # noqa: E731
    except RuntimeError as exc:
        print(f"seedsmith: combination name guard unavailable — {exc}", file=sys.stderr)
        return EXIT_REFUSED
    result = authored_mod.run_batch(
        plan=plan, answers=answers, tuning=tuning, out_dir=out_dir,
        authored_utc=args.authored_utc, model=effective_model, ledger_path=ledger_path, call=call,
        overwrite=overwrite_ids, taken_keys=taken_keys, key_of=key_of, name_defects=name_defects)
    print("\n--- write report ---")
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return _exit_for_graph_batch(result)


def _cmd_items_validate(args: argparse.Namespace) -> int:
    """`seedsmith items validate --deps` (acceptance 3a, `combination-write-unblock`).

    Scoped to `combination` for now — the module this command was built for. Runs the pre-flight
    `dependency_validator` report over the REAL corpus, BEFORE any subject is planned: every
    `hostRole` a run could request must have >=1 real base type whose socket ceiling reaches the
    ingredient count, and every `ingredients` family must have >=1 real gem. This is the REPORTED
    form of a guarantee `combogen.schema.combination_schema` already enforces structurally (it
    refuses to build a schema for an empty universe); reported so "resolves, but only barely" stays
    visible (`dependency_validator.py`'s own reason for a count, never a bare bool).
    """
    if not args.deps:
        print("seedsmith: `items validate` needs --deps today — no other check is wired to this "
              "command yet.", file=sys.stderr)
        return EXIT_CANNOT_RUN

    from ..adapters.items.combogen import deps as deps_mod
    from ..adapters.items.combogen import tuning as tuning_mod

    tuning = tuning_mod.load()
    report = deps_mod.preflight(tuning)
    print(json.dumps({"kind": "combination", **report.to_dict()}, ensure_ascii=False, indent=2))
    return EXIT_REFUSED if report.refused else EXIT_CLEAN


def _cmd_items_fill(args: argparse.Namespace) -> int:
    """`seedsmith items fill` — resume/fill missing subjects across item kinds.

    Implies write (unless `--dry-run`). Uses `.env` for endpoint / production out-dirs. Walks
    kinds in item-seedgen-map dependency order; partition kinds use discovered corpus files only.

    Unbounded set/charm/combination require `--limit N` or `--full`. Allow-production is required
    only when the plan includes those kinds.
    """
    from ..adapters.items import defaults as items_defaults
    from ..adapters.items import fill as fill_mod

    kinds = None
    if getattr(args, "kinds", ""):
        kinds = tuple(k.strip() for k in args.kinds.split(",") if k.strip())
        unknown = [k for k in kinds if k not in items_defaults.FILL_KIND_ORDER]
        if unknown:
            print(f"seedsmith: unknown --kinds {unknown!r}; legal: "
                  f"{', '.join(items_defaults.FILL_KIND_ORDER)}", file=sys.stderr)
            return EXIT_CANNOT_RUN

    selected = set(kinds) if kinds is not None else set(items_defaults.FILL_KIND_ORDER)
    needs_production = bool(selected & fill_mod.PRODUCTION_KINDS)
    allow = items_defaults.allow_production_tree(
        cli_allow=bool(getattr(args, "allow_production_tree", False)))
    if not args.dry_run and needs_production and not allow:
        print("seedsmith: items fill refused — set/charm/combination need "
              "SEEDSMITH_ALLOW_PRODUCTION_TREE=1 in tools/seedsmith/.env or "
              "--allow-production-tree.",
              file=sys.stderr)
        return EXIT_REFUSED

    count_raw = getattr(args, "count", None)
    batch_raw = getattr(args, "batch_size", None)
    # argparse defaults are None so --full can drain; smoke still gets 1 when omitted.
    count_explicit = count_raw is not None
    batch_explicit = batch_raw is not None
    limits = fill_mod.FillLimits(
        limit=int(getattr(args, "limit", 0) or 0),
        count=int(count_raw) if count_explicit else 1,
        batch_size=int(batch_raw) if batch_explicit else 1,
        max_partitions=int(getattr(args, "max_partitions", 1) or 0),
        full=bool(getattr(args, "full", False)),
        count_explicit=count_explicit,
        batch_size_explicit=batch_explicit,
    )
    # When not --full, default max_partitions stays 1 (smoke). --full means all partitions
    # (max_partitions 0 = uncapped in plan_fill_steps).
    if limits.full:
        limits.max_partitions = 0

    if not args.dry_run and getattr(args, "validate_deps", True) and "combination" in selected:
        vargs = argparse.Namespace(deps=True)
        deps_code = _cmd_items_validate(vargs)
        if deps_code == EXIT_REFUSED:
            print("seedsmith: items fill refused — combination deps preflight failed "
                  "(fix with items validate --deps, or pass --no-validate-deps).",
                  file=sys.stderr)
            return EXIT_REFUSED

    report = fill_mod.run_fill(
        kinds=kinds, dry_run=bool(args.dry_run), allow_production=allow or not needs_production,
        limits=limits,
        stop_on_error=not bool(getattr(args, "continue_on_error", False)))
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    if report.refused_reason:
        print(f"seedsmith: {report.refused_reason}", file=sys.stderr)
        return EXIT_REFUSED
    code = report.worst_exit_code
    # A clean dispatch only means every scheduled batch returned clean.  Reconcile the finite
    # populations separately so held set/charm subjects (or an unconsumed gem pool) cannot be
    # mistaken for a complete fill.  This is model-free and reads the same ledgers as generation.
    completion = fill_mod.generation_completion(kinds=kinds)
    print("\n--- generation completion ---")
    print(json.dumps(completion, ensure_ascii=False, indent=2))
    if code == EXIT_CLEAN and getattr(args, "verify", False):
        completion_gap = not completion["complete"]
        if completion_gap:
            print("seedsmith: items fill left finite populations pending or held; the run is not "
                  "complete", file=sys.stderr)
        print("\n--- post-fill corpus gate ---")
        verify_args = argparse.Namespace(
            family="", corpus_root=str(fill_mod.ITEM_SEED_ROOT), adapter="items",
            gate=True, json=None, metric=None, plan_root="")
        verify_code = cmd_check(verify_args)
        if verify_code != EXIT_CLEAN:
            print("seedsmith: items fill completed its generation steps, but the corpus gate "
                  "still reports unresolved gaps; the run is not complete", file=sys.stderr)
            return verify_code
        if completion_gap:
            return EXIT_GAP
    return code


def _cmd_items_combogen_reemit(args: argparse.Namespace) -> int:
    """`seedsmith items combogen-reemit --dry-run|--write` — SSH7.4 (spec-tier-ladder §3).

    Re-emits the shipped combination corpus from the RUN LEDGER: the model's recorded answers (families,
    grants, pins, names) are carried across and only the emitted SHAPE moves, so a shape change needs no
    model call and no hand edit. Idempotent — re-emitting the re-emission plans nothing.
    """
    from ..adapters.items.combogen import authored as authored_mod
    from ..adapters.items.combogen import emit as emit_mod
    from ..adapters.items.combogen import tuning as tuning_mod

    tuning = tuning_mod.load()
    ledger_path = Path(args.ledger) if args.ledger else None
    shapes = ["strain", "splice"] if args.shape == "both" else [args.shape]

    plan: "dict[str, list[dict]]" = {}
    changed: "dict[str, list[str]]" = {}
    for shape in shapes:
        current = authored_mod.entries_from_ledger(shape, ledger_path=ledger_path)
        reemitted = authored_mod.reemit(shape, tuning=tuning, ledger_path=ledger_path)
        unchanged = {entry["id"]: entry for entry in current}
        plan[shape] = reemitted
        changed[shape] = [entry["id"] for entry in reemitted
                          if unchanged.get(entry["id"]) != entry]

    report = {"shapes": {shape: {"entries": len(plan[shape]), "changed": len(changed[shape])}
                         for shape in shapes},
              "changedIds": changed}
    if not args.write:
        print(json.dumps({**report, "write": False}, ensure_ascii=False, indent=2))
        return EXIT_CLEAN

    root = Path(args.out_dir) if args.out_dir else authored_mod.COMBINATIONS_DIR
    written: "dict[str, list[str]]" = {}
    for shape in shapes:
        if not changed[shape]:
            written[shape] = []
            continue
        # `none` is the closed sentinel for a deterministic generator: this re-emits a shape from
        # the ledger's recorded answers and makes no model call, so there is no model to choose.
        authored_mod.write_seed_file(shape, plan[shape], out_dir=root, model="none",
                                     authored_utc=args.authored_utc)
        written[shape] = changed[shape]
        _record_combogen_reemit_amendment(shape, changed[shape], root, args.authored_utc)
    print(json.dumps({**report, "write": True, "written": written}, ensure_ascii=False, indent=2))
    return EXIT_CLEAN


def _record_combogen_reemit_amendment(shape: str, ids: "list[str]", root: Path,
                                      authored_utc: str) -> None:
    """Append the re-emit's `_meta.amendments` record — the generated tree must say how it was made,
    and `write_seed_file` rewrites `_meta` from scratch, so the record is appended here."""
    path = root / ("strains.json" if shape == "strain" else "splices.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    amendment = {
        "batch": f"combogen-reemit/{shape}-1",
        "note": ("Re-emitted from the run ledger by seedsmith.adapters.items.combogen.authored.reemit "
                 "(strain-splice-host SSH7.4/SSH7.6): the model's recorded answers are unchanged and "
                 "only the emitted SHAPE moves — ingredient rows drop their tier, `grantedTier` is gone "
                 "(SSH7.3), and identical families fold. No model call."),
        "promptVersion": "n/a-deterministic-reemit",
        "model": "none",   # the closed sentinel: no model call made this row
        "authoredUtc": authored_utc,
        "sourceRef": "docs/architecture/strain-splice-host/spec-tier-ladder.md",
        "entries": sorted(ids),
    }
    meta = {**document["_meta"], "amendments": [*document["_meta"].get("amendments", []), amendment]}
    path.write_text(json.dumps({**document, "_meta": meta}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def _cmd_items_combogen_migrate(args: argparse.Namespace) -> int:
    """`seedsmith items combogen-migrate --dry-run|--write` (acceptance 4,
    `combination-write-unblock`; the `--write` half is strain-splice-host SSH2.3).

    ⛔ **`--write` is a VERB, never a hand deletion** — `combogen.migrate.retire_legacy_partition`
    is deterministic (no model call) and idempotent (a second `--write` reproduces the identical
    ledger record and no-ops the delete). This command does NOT itself decide whether it is SAFE to
    retire yet: `combogen.migrate`'s own ✅ ruling ("regenerate, do not retain", 2026-09-04) retires
    `sockwords.json` only once the real 102-entry combination corpus exists to replace it, which is
    SSH2.6's own precondition to check before calling `--write` for real, not this function's.
    """
    if args.write:
        from ..adapters.items.combogen import migrate as migrate_mod

        record, deleted_this_run = migrate_mod.retire_legacy_partition()
        summary = {"write": True, "fileDeletedThisRun": deleted_this_run,
                  "record": record.to_dict(), "ledger": str(migrate_mod.DEFAULT_MIGRATE_LEDGER)}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return EXIT_CLEAN

    if not args.dry_run:
        print("seedsmith: `items combogen-migrate` needs --dry-run (report only) or --write "
              "(retire for real — deterministic and idempotent, but a real filesystem delete).",
              file=sys.stderr)
        return EXIT_REFUSED

    from ..adapters.items.combogen import migrate as migrate_mod
    from ..adapters.items.combogen import tuning as tuning_mod

    tuning = tuning_mod.load()
    from ..adapters.items.combogen import supply as supply_mod
    from ..adapters.items.combogen import run as run_mod

    supply = supply_mod.build()
    plan = run_mod.plan_run(shape="strain", tuning=tuning, supply=supply)
    legality = migrate_mod.legality_report(tuning, host_roles=plan.host_roles)
    missing = migrate_mod.missing_sites()
    summary = {
        "dryRun": True,
        "legacyRetirement": legality.to_dict(),
        "migrationSitesMissing": missing,
        "planStillHolds": not missing,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return EXIT_CLEAN if not missing else EXIT_GAP


def cmd_creatures(args: argparse.Namespace) -> int:
    """`seedsmith creatures <motifs|themes|theme-enrich|generate>` — the creature generation entrypoints.

    ⛔ Why this exists. Two of the audit's own `Verify` lines named commands that did not exist:
    `python -m seedsmith creatures motifs` (G1.3) and
    `python -m seedsmith creatures generate --kind commander-effect` (G4.3). The real entrypoints were
    reachable only as `python -m seedsmith.adapters.creatures.<module>`, so both Verify lines failed
    when actually executed during the 2026-09-01 final-proof pass.

    This is the same defect D1.4 already caught once ("the real CLI — `report` from the spec's own
    example doesn't exist"). There it was fixed by correcting the command; here the claim is made
    true instead, matching P6's own precedent of "making the claim true rather than softening it" —
    a documented interface that only works if you know the private module path is not an interface.

    Imports are deferred: `creatures generate` pulls in the workflow package, and `langgraph` is an
    optional extra. A top-level import would make `seedsmith check` fail on a base install.
    """
    if args.creature_command == "families":
        from ..adapters.creatures.generate_families import run as run_families
        passthrough: list[str] = []
        for flag in ("dry_run", "write", "ack"):
            if getattr(args, flag, False):
                passthrough.append(
                    {"dry_run": "--dry-run", "write": "--write",
                     "ack": "--i-have-read-the-append-only-note"}[flag])
        return run_families(passthrough)

    if args.creature_command == "motifs":
        import json as _json

        from ..adapters.creatures.generate_motifs import regenerate
        print(_json.dumps(regenerate(), ensure_ascii=False, indent=2))
        return EXIT_CLEAN

    if args.creature_command in ("themes", "theme-refresh"):
        # Keep the documented theme-refresh stage on the public CLI. Calling the private module
        # path was the only way to register a newly observed species, so an item fill could read a
        # stale theme snapshot and quietly plan a partial population. This is deterministic and
        # model-free; --dry-run exercises the complete-roster read without replacing the registry.
        import json as _json

        from ..adapters.creatures.generate_themes import regenerate
        summary = regenerate(rebuild=bool(args.rebuild), write=not bool(args.dry_run))
        print(_json.dumps({**summary, "dryRun": bool(args.dry_run)},
                          ensure_ascii=False, indent=2))
        return EXIT_CLEAN

    if args.creature_command == "theme-enrich":
        from ..adapters.creatures import theme_enrich
        passthrough: list[str] = []
        if args.dry_run:
            passthrough.append("--dry-run")
        if args.write:
            passthrough.append("--write")
        for flag in ("endpoint", "model"):
            value = getattr(args, flag, "")
            if value:
                passthrough.extend([f"--{flag}", value])
        return theme_enrich.main(passthrough)

    if args.creature_command == "power-parse":
        return _cmd_creatures_power_parse(args)

    if args.creature_command == "threat-band":
        return _cmd_creatures_threat_band(args)

    if args.creature_command == "contract":
        return _cmd_creatures_contract(args)

    if args.creature_command == "build-favour":
        return _cmd_creatures_build_favour(args)

    if args.creature_command == "preflight":
        return _cmd_creatures_preflight(args)

    if args.creature_command == "permute":
        return _cmd_creatures_permute(args)

    if args.creature_command == "metrics":
        return _cmd_creatures_metrics(args)

    if args.creature_command == "run":
        return _cmd_creatures_run(args)

    if args.creature_command == "diff-legacy":
        return _cmd_creatures_diff_legacy(args)

    if args.kind == "anchor":
        return _cmd_creatures_generate_anchor(args)

    from ..adapters.creatures.generate_commander_effects import main as run

    if args.kind != "commander-effect":
        print(f"unknown kind {args.kind!r}; only 'commander-effect' has a generator today")
        return EXIT_CANNOT_RUN
    passthrough: list[str] = []
    for flag in ("only", "endpoint", "model"):
        value = getattr(args, flag, None)
        if value:
            passthrough += [f"--{flag}", str(value)]
    for flag in ("dry_run", "stale", "force"):
        if getattr(args, flag, False):
            passthrough.append("--" + flag.replace("_", "-"))
    if args.workers:
        passthrough += ["--workers", str(args.workers)]
    return run(passthrough)


def _cmd_creatures_power_parse(args: argparse.Namespace) -> int:
    """`seedsmith creatures power-parse --dump <dir> [--report]` (creature-seed module 3,
    spec-power-parse.md). Zero model calls: reads the committed `corpus-dump` tree
    (`almanac/plant.json` + `almanac/zombie.json`) and runs the deterministic parse over it.
    """
    from ..adapters.creatures.power.parse import basis_histogram, disagreements, parse_power_seed

    dump_dir = Path(args.dump)
    plant_path = dump_dir / "almanac" / "plant.json"
    zombie_path = dump_dir / "almanac" / "zombie.json"
    if not plant_path.exists() or not zombie_path.exists():
        print(f"seedsmith: no corpus-dump tree at {dump_dir} "
              f"(expected almanac/plant.json and almanac/zombie.json)", file=sys.stderr)
        return EXIT_CANNOT_RUN

    rows = json.loads(plant_path.read_text(encoding="utf-8")) + json.loads(zombie_path.read_text(encoding="utf-8"))
    seeds = [
        parse_power_seed(
            side=r["side"], type_id=r["typeId"], stats_observed=r["statsObserved"],
            hp=r["hp"], attack=r["attack"], flavor_text=r["flavorInfo"])
        for r in rows
    ]

    hist = basis_histogram(seeds)
    total = len(seeds)
    print(f"power-parse: {total} species — "
          f"observed={hist['observed']} stated={hist['stated']} "
          f"inferred={hist['inferred']} blocked={hist['blocked']}")

    if args.report:
        for basis, count in hist.items():
            pct = 100 * count / total if total else 0.0
            print(f"  {basis}: {count} ({pct:.1f}%)")
        dis = disagreements(seeds)
        tempo_stated = sum(1 for s in seeds if s.interval_ms is not None)
        print(f"  attackTempo stated (interval on the damage line): {tempo_stated} "
              f"({100 * tempo_stated / total:.1f}%)" if total else "  attackTempo stated: 0")
        print(f"  disagreements: {len(dis)}")
        for d in dis:
            print(f"    {d.side}:{d.type_id} toughness={d.toughness} (text={d.text_toughness}) "
                  f"damage={d.damage} (text={d.text_damage})")

    return EXIT_CLEAN


def _cmd_creatures_threat_band(args: argparse.Namespace) -> int:
    """`seedsmith creatures threat-band --dump <dir> [--histogram]` (creature-seed module 4,
    spec-threat-band.md). Zero model calls: power-parse's score, looked up in the tuning table.
    """
    from ..adapters.creatures.power.bands import ThreatTuning, classify, histogram
    from ..adapters.creatures.power.parse import parse_power_seed

    dump_dir = Path(args.dump)
    plant_path = dump_dir / "almanac" / "plant.json"
    zombie_path = dump_dir / "almanac" / "zombie.json"
    if not plant_path.exists() or not zombie_path.exists():
        print(f"seedsmith: no corpus-dump tree at {dump_dir} "
              f"(expected almanac/plant.json and almanac/zombie.json)", file=sys.stderr)
        return EXIT_CANNOT_RUN

    rows = json.loads(plant_path.read_text(encoding="utf-8")) + json.loads(zombie_path.read_text(encoding="utf-8"))
    seeds = [
        parse_power_seed(
            side=r["side"], type_id=r["typeId"], stats_observed=r["statsObserved"],
            hp=r["hp"], attack=r["attack"], flavor_text=r["flavorInfo"])
        for r in rows
    ]

    tuning = ThreatTuning.load(1)
    rungs: list[int] = []
    unscored = 0
    for s in seeds:
        result = classify(s, tuning)
        if result is None:
            unscored += 1
            continue
        rungs.append(result.rung)

    print(f"threat-band: {len(seeds)} species — {len(rungs)} scored (observed/stated), "
          f"{unscored} inferred/blocked (no score at this layer)")

    if args.histogram:
        h = histogram(rungs, tuning)
        for t in tuning.thresholds:
            marker = " ⚠️ EMPTY" if h[t.id] == 0 else ""
            print(f"  rung {t.rung:2d} {t.id:<10s}: {h[t.id]:4d}{marker}")

    return EXIT_CLEAN


def _cmd_creatures_contract(args: argparse.Namespace) -> int:
    """`seedsmith creatures contract --print|--audit` (creature-seed module 2, spec-anchor-contract.md).
    No model calls: prints or numerically audits the resolved anchor schema.
    """
    from ..adapters.creatures.anchor.audit import numeric_audit
    from ..adapters.creatures.anchor.schema import build_anchor_schema

    schema = build_anchor_schema()

    if args.print_schema:
        print(json.dumps(schema, indent=2, ensure_ascii=False))
        return EXIT_CLEAN

    # --audit (also the default when neither flag is passed)
    defects = numeric_audit(schema)
    if not defects:
        print(f"contract --audit: clean — {len(schema['properties'])} fields, "
              f"0 numeric-smuggling findings")
        return EXIT_CLEAN
    for d in defects:
        print(f"[FINDING] {d}")
    print(f"\n{len(defects)} numeric-smuggling finding(s)")
    return EXIT_GAP


def cmd_trees(args: argparse.Namespace) -> int:
    """`seedsmith trees <plan|generate>` — passive-tree entrypoints (task B1 plan, task H2
    generate, spec-tree-plan.md / spec-tree-language.md)."""
    if args.trees_command == "plan":
        return _cmd_trees_plan(args)
    if args.trees_command == "generate":
        return _cmd_trees_generate(args)
    if args.trees_command == "review":
        return _cmd_trees_review(args)
    if args.trees_command == "census":
        return _cmd_trees_census(args)

    print(f"unknown trees command {args.trees_command!r}")
    return EXIT_CANNOT_RUN


def _every_planned_tree_id(seed_root: Path | None = None) -> list[str]:
    """Every tree id with a committed plan under `<seed_root>/passive-tree/plan/*.v1.json` —
    `seed_root` is the SAME parameter `plan_read.load`'s own `seed_root` takes (defaults to
    `gk-data/packs/fusion/data/seed`), so a caller passes one root to both this function and `plan_read.load`."""
    from ..adapters.trees.plan import emit as plan_emit
    from ..workspace_roots import seed_root as resolve_seed_root

    # `data/seed` is gk-data's pack, not gk-forge's. The import is ALIASED because this function's
    # own PARAMETER is called `seed_root`, and an unaliased import would be shadowed by it.
    root = seed_root or resolve_seed_root(plan_emit.REPO_ROOT)
    plan_dir = root / "passive-tree" / "plan"
    if not plan_dir.exists():
        return []
    return sorted(p.name[: -len(".v1.json")] for p in plan_dir.glob("*.v1.json"))


def _all_roster_specs() -> list:
    """Every tree spec the roster names — 12 aptitudes, 6 elements, 24 statuses — built through the
    SAME named spec functions `--tree <id>` already uses (`primary_tree_spec`/`elemental_tree_spec`/
    `status_tree_spec`), so the manifest and a single-tree emit can never disagree about one tree's
    plan. Creature families are deliberately absent: they have no committed plan under
    `plan/*.v1.json` and ride the manifest's `_pending` list (spec-tree-plan.md's own `roster`
    block), never `trees[]`."""
    from ..adapters.trees.plan import emit as plan_emit
    from ..adapters.trees.plan.vocabulary import load_roster

    roster = load_roster()
    specs: list = []
    for aptitude in roster.aptitudes:
        specs.append(plan_emit.primary_tree_spec(aptitude))
    for element in roster.elements:
        specs.append(plan_emit.elemental_tree_spec(element))
    for status in roster.statuses:
        specs.append(plan_emit.status_tree_spec(status))
    return specs


def _cmd_trees_generate(args: argparse.Namespace) -> int:
    """`seedsmith trees generate --tree <id>|--all [--dry-run|--write] [--sample-brief]`
    (task H2/H3, spec-tree-language.md §Commands).

    ⛔ **`--dry-run` is the default, and that is deliberate** — the SAME rule `items generate` and
    `items generate --kind combination` already state for their own real-call costs: a real run is
    thousands of model calls, so a flag you must remember to pass to AVOID spending them is a flag
    someone eventually forgets. The dry run prints `gatingMetrics`/`gatesMissingAThreshold`
    (§7 gate 5) and the call-count arithmetic BEFORE a single call is made — `--sample-brief` prints
    one rendered brief on top, still zero calls.

    **H3 closes the gap this docstring used to name.** Every planned tree's own `QuotaCell`s are
    now resolved for real (`quota.quota_for_plan`), and every node's `permittedIds`
    (`quota.permitted_ids_for_cell`) plus its branch-tagged affix subset
    (`vocab.AffixVocabulary.permitted_for_branch`) are real, non-empty subsets — `resolvedSubjects`
    in the summary below proves it, and `--sample-brief` renders an ACTUAL brief against a real
    node's real permitted subset rather than the placeholder string this command used to print.

    `--write` is STILL refused, but for a different, still-true reason today: §7.1's own rule is
    "exactly one gate is promoted to hard-fail first," and the real metric registry has ZERO
    `PassiveTree/*` metrics at `gates=True` (`PassiveTree/UnresolvedCount` is task H4's, not built
    yet) — the exact same contract `check --family PassiveTree --gate` already refuses on
    (`_cmd_check_family`'s own docstring). Spending thousands of real calls with nowhere for a
    systematic failure to land would be the defect §7.1 exists to prevent.
    """
    from ..adapters.trees.nodegen import brief as brief_mod
    from ..adapters.trees.nodegen import emit as emit_mod
    from ..adapters.trees.nodegen import plan_read
    from ..adapters.trees.nodegen import quota as quota_mod
    from ..adapters.trees.nodegen import run as run_mod
    from ..adapters.trees.nodegen import tuning as tuning_mod
    from ..adapters.trees.nodegen import vocab as vocab_mod
    from ..adapters.trees.nodegen import verdict as tree_verdict
    from ..adapters.trees.nodegen.verdict import GATING_METRICS, missing_thresholds

    if not args.tree and not args.all:
        print("seedsmith: --tree <id> or --all is required", file=sys.stderr)
        return EXIT_CANNOT_RUN

    seed_root = Path(args.plan_root) if args.plan_root else None
    tree_ids = [args.tree] if args.tree else _every_planned_tree_id(seed_root)
    if not tree_ids:
        print(f"seedsmith: no committed plan found — run `trees plan --emit` first", file=sys.stderr)
        return EXIT_CANNOT_RUN

    try:
        targets = tuning_mod.load()
    except tuning_mod.PassiveTreeTargetsError as ex:
        print(f"seedsmith: {ex}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    try:
        affix_vocab = vocab_mod.build()
    except vocab_mod.AffixVocabularyError as ex:
        print(f"seedsmith: {ex}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    total_subjects = 0
    resolved_subjects = 0
    sample_brief_text = None
    plans_and_cells: dict[str, tuple[Any, Any]] = {}
    # ip-censor T16/IC-4.1: the IP avoid-list the brief prints, read once from the committed registry
    # through the shared `briefkit.avoid_list` helper (the same reader T15's uniques brief uses). A
    # missing registry is a hard error, never silently an empty list — an absent avoid line must not
    # read as "nothing to avoid".
    from ..briefkit.avoid_list import load_avoid_terms
    try:
        avoid_terms = load_avoid_terms()
    except (OSError, ValueError) as ex:
        print(f"seedsmith: the IP avoid-list registry could not be read — {ex}", file=sys.stderr)
        return EXIT_CANNOT_RUN
    for tree_id in tree_ids:
        try:
            plan = plan_read.load(tree_id, seed_root)
        except plan_read.TreePlanReadError as ex:
            print(f"seedsmith: {ex}", file=sys.stderr)
            return EXIT_CANNOT_RUN
        # The dry-run previews the SAME plan the write will run: `--supersede` (which rows are stale)
        # and `--node` (which single node) both narrow it, so the summary's subject count is what
        # `--write` will actually generate — never a wider plan that reads as "all stale rows" when
        # the selector means one (ip-censor T16/IC-4.1).
        try:
            run_plan = run_mod.plan_run(
                plan, supersede_stale=bool(getattr(args, "supersede", False)),
                prompt_version=brief_mod.PROMPT_VERSION,
                only_node_id=str(getattr(args, "node", "") or ""))
        except ValueError as ex:
            # `--node <id>` names a node this tree's plan does not carry. Refuse cleanly in the
            # dry run too, so the preview fails the same way the write does (ip-censor T16/IC-4.1).
            print(f"seedsmith: {tree_id}: {ex}", file=sys.stderr)
            return EXIT_CANNOT_RUN
        total_subjects += len(run_plan.subjects) + len(run_plan.already_done)
        category = plan.raw.get("category")
        try:
            cells = quota_mod.quota_for_plan(
                plan, targets, category=str(category),
                forced_element=plan.raw.get("forcedElement"),
                forced_status=plan.raw.get("forcedStatus"))
        except (ValueError, KeyError) as ex:
            print(f"seedsmith: {tree_id}: quota resolution refused — {ex}", file=sys.stderr)
            return EXIT_CANNOT_RUN
        plans_and_cells[tree_id] = (plan, cells)

        for node in plan.nodes:
            cell = cells[node.node_id]
            permitted_ids = quota_mod.permitted_ids_for_cell(cell, plan.property_vocabulary)
            permitted_affixes = affix_vocab.permitted_for_branch(node.branch)
            if permitted_affixes and any(permitted_ids.values()):
                resolved_subjects += 1
            if args.sample_brief and sample_brief_text is None:
                sample_brief_text = brief_mod.render_brief(
                    node_id=node.node_id, sample_index=0, tree_display_name=tree_id,
                    tree_reading=tree_id, branch=node.branch, tier=node.tier,
                    node_class=node.node_class, motifs=(), anti_motifs=(),
                    permitted_affixes=permitted_affixes,
                    permitted_properties=sorted(plan.property_vocabulary),
                    exclusion_form=cell.exclusion_form, avoid_terms=avoid_terms)

    # §6.1's own cost arithmetic (D29's corpus table), COMPUTED from `total_subjects` — never a
    # hardcoded literal. At the generic corpus's real size (1,560 subjects: 39 trees x 40 nodes)
    # `run.calls_for` returns exactly the spec's own 4,680; `test_nodegen_generate.py` proves that
    # arithmetic directly at 1,560 without depending on the real corpus being fully committed yet.
    summary = {
        "trees": tree_ids,
        "totalSubjects": total_subjects,
        "resolvedSubjects": resolved_subjects,
        **run_mod.calls_for(total_subjects),
        "gatingMetrics": sorted(GATING_METRICS),
        "gatesMissingAThreshold": missing_thresholds(targets),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.sample_brief and sample_brief_text:
        print("\n--- sample brief ---")
        print(sample_brief_text)

    if args.write:
        registry = build_registry()
        try:
            tree_verdict.assert_exactly_one_hard_gate(registry, "PassiveTree")
        except ValueError as ex:
            print(f"seedsmith: --write is refused — {ex}. The plan, the resolved quota cells and "
                  f"the call count above are real; the model call is not, because a systematic "
                  f"failure would have nowhere to land (§7.1).", file=sys.stderr)
            return EXIT_REFUSED

        # Real generation, one tree at a time — `run_language_stage` (task H2) is already the
        # complete, idempotent runner (ledger read, per-node gates 2/6/7/9/10/11/12/13, ledger
        # write, seed-document emit, gate-23 RunReport); this is that function's first real
        # production caller. `inputs_for` supplies exactly the fields `--sample-brief` above
        # already resolves per node (`permitted_affixes`/`permitted_properties`, via the SAME
        # `cells`/`affix_vocab` this function already computed during the dry-run pass, never
        # re-derived) plus the two fields a single rendered brief did not need: `tree_display_name`/
        # `tree_reading` default to the tree's own id (matching the dry-run's own
        # `--sample-brief` call above) since a shared/mechanical tree like `might` carries no
        # authored display name yet (tree-language's own naming pass, I10, has not run); `motifs`/
        # `anti_motifs`/`anti_motif_tags` are empty for the same reason a primary/mechanical tree's
        # own `--sample-brief` output already showed "(none named)" — this corpus category has no
        # motif system, unlike the creature corpus's themed content.
        overall_outcomes: dict[str, int] = {}
        per_tree_reports: list[dict] = []
        for tree_id in tree_ids:
            plan, cells = plans_and_cells[tree_id]

            def inputs_for(subject, _plan=plan, _cells=cells):
                # Matches the dry-run's own --sample-brief call above exactly: permitted_properties
                # is the sorted set of property AXIS NAMES (e.g. "aptitude", "element") a node's
                # exclusion may reference, never a per-cell-narrowed id list — `permitted_ids_for_cell`
                # (used above only for the dry run's own resolved_subjects boolean check) is not an
                # input `NodeGenerationInputs`/`render_brief` takes. `quota_cell` is the SAME cell
                # this dry-run already resolved into `_cells` — persisted onto the accepted record
                # so `PassiveTree/QuotaDrift` can measure without a generation-time snapshot.
                permitted_affixes = affix_vocab.permitted_for_branch(subject.branch)
                return run_mod.NodeGenerationInputs(
                    tree_display_name=tree_id, tree_reading=tree_id,
                    motifs=(), anti_motifs=(), anti_motif_tags=(),
                    permitted_affixes=permitted_affixes,
                    permitted_properties=sorted(_plan.property_vocabulary),
                    property_vocabulary=_plan.property_vocabulary,
                    affix_vocab=affix_vocab,
                    quota_cell=_cells.get(subject.node_id),
                    avoid_terms=avoid_terms,
                )

            # 2026-09-06 real-call finding (`might`, a real generation run): two DIFFERENT accepted
            # nodes collided on `nameKey` ("Deep Rooting" generated twice, independently, for two
            # different tiers) -- `build_seed_document`'s own `assert_no_duplicate_name_keys` refused
            # exactly as designed ("refused, never renamed out from under the model's answer" --
            # NodeKeyRefused's own message), but nothing here caught it, so a real, well-defined,
            # already-reported-elsewhere content defect crashed the whole CLI with a raw traceback
            # instead of a clean report. The ledger itself is NOT at risk: `run_language_stage` writes
            # it before ever building the seed document, so every already-accepted node from this run
            # (and prior runs) stays safely recorded regardless of this refusal -- confirmed by reading
            # the function's own body, not assumed. Caught here, once, at the one place that already
            # aggregates per-tree reports, so `--all` still reports every OTHER tree that succeeded.
            try:
                result = run_mod.run_language_stage(
                    plan, inputs_for,
                    ledger_path=Path(args.ledger_path) if getattr(args, "ledger_path", "") else None,
                    seed_root=seed_root,
                    unresolved_max_share_permille=targets.unresolved_count_max_share_permille,
                    max_workers=max(1, getattr(args, "workers", 1)),
                    supersede_stale=bool(getattr(args, "supersede", False)),
                    only_node_id=str(getattr(args, "node", "") or ""))
            except emit_mod.NodeKeyRefused as ex:
                per_tree_reports.append({
                    "tree": tree_id, "seedPath": None,
                    "nameKeyRefused": str(ex),
                })
                overall_outcomes["nameKeyRefused"] = overall_outcomes.get("nameKeyRefused", 0) + 1
                continue
            except ValueError as ex:
                # ip-censor T16/IC-4.1: `--node <id>` names a node the plan does not carry. A clean
                # refusal with the message, never a raw traceback — the same discipline the
                # NameKeyRefused handler above applies.
                print(f"seedsmith: {tree_id}: {ex}", file=sys.stderr)
                return EXIT_CANNOT_RUN
            for outcome in result.outcomes:
                overall_outcomes[outcome.outcome] = overall_outcomes.get(outcome.outcome, 0) + 1
            # `detail` is a real, model-authored reason (§H9's own diagnostic history: "current tree
            # is empty", "'might' is a property/stat, not an effect id" were both only ever found by
            # reading this field) — printed here, per non-accepted subject, so a future run's real
            # blocks/escalations are diagnosable from the CLI's own output rather than requiring a
            # second real-call reproduction just to see why.
            per_tree_reports.append({
                "tree": tree_id,
                "seedPath": str(result.seed_path) if result.seed_path else None,
                "outcomeCounts": {
                    o: sum(1 for x in result.outcomes if x.outcome == o)
                    for o in ("accepted", "blocked", "unresolved", "escalated")
                },
                "nonAcceptedDetail": [
                    {"subject": o.subject_id, "outcome": o.outcome, "detail": o.detail}
                    for o in result.outcomes if o.outcome != "accepted"
                ],
                "runReport": result.report.to_dict(),
            })

        print(json.dumps({"perTree": per_tree_reports, "outcomeTotals": overall_outcomes},
                          ensure_ascii=False, indent=2))
        any_refused = any("nameKeyRefused" in r for r in per_tree_reports)
        any_fail = any(r.get("runReport", {}).get("verdict") == "FAIL" for r in per_tree_reports)
        return EXIT_GAP if (any_fail or any_refused) else EXIT_CLEAN
    return EXIT_CLEAN


def _cmd_trees_review(args: argparse.Namespace) -> int:
    """`seedsmith trees review --census --lot <lot>` (task H7, spec-tree-review.md §5.5).

    **Scope, stated honestly.** This lands exactly the gate the todo's H7 acceptance names — the
    `sheetRead` refusal in front of a census — and nothing past it. The sheet itself, the three
    sampling tiers (§3.2) and the acceptance ladder (§6.2/§6.3) are `adapters.trees.review.sample`
    / `.fingerprint` / `.verdict`, none of which exist yet (H8 and later, per the spec's own
    "Project structure" list) — `--census` here proves the gate holds and stops; it does not run
    a census, because there is no census machinery to hand off to yet. That is a wiring gap this
    task names rather than a scope this task quietly narrowed.
    """
    from ..adapters.trees.review import census_gate

    if not args.census:
        print("seedsmith: trees review currently only implements --census (§5.5's gate) — the "
              "sampling tiers (§3.2) and the acceptance ladder (§6.2/§6.3) are unbuilt (H8+)",
              file=sys.stderr)
        return EXIT_CANNOT_RUN

    lot = args.lot
    sheet_dir = Path(args.sheet_dir) if args.sheet_dir else census_gate.DEFAULT_SHEET_DIR
    review_dir = Path(args.review_dir) if args.review_dir else census_gate.DEFAULT_REVIEW_DIR

    try:
        row = census_gate.assert_may_start_census(sheet_dir, review_dir, lot)
    except census_gate.SheetNotRendered as ex:
        print(f"seedsmith: {ex}", file=sys.stderr)
        return EXIT_CANNOT_RUN
    except census_gate.CensusRefused as ex:
        print(f"EXIT_REFUSED: {ex}", file=sys.stderr)
        return EXIT_REFUSED

    print(json.dumps({
        "lot": lot,
        "sheetRead": {"sheetRevision": row.sheet_revision, "by": row.by, "utc": row.utc},
        "note": "gate cleared — the census tiers themselves are not wired yet (H8+)",
    }, ensure_ascii=False, indent=2))
    return EXIT_CLEAN


def _run_tree_equal_value(plans: list[dict], tuning_doc: dict) -> str | None:
    """`PassiveTree/TreeEqualValue` (spec-tree-plan.md §3.2, task C1) — runs at BOTH `--emit` and
    `--check`, before anything else that could spend a model call, over the emitted plan(s) alone.
    Returns `None` on a clean pass, or the refusal message naming the tree/branch/tier/archetype
    it found. Never clamps — the caller turns a message into `EXIT_REFUSED`."""
    from ..adapters.trees.plan import invariants as plan_invariants
    from ..adapters.trees.plan.archetypes import TIER_COUNT, SHIPPED_ARCHETYPES

    try:
        plan_invariants.check_tree_equal_value(
            plans, SHIPPED_ARCHETYPES, TIER_COUNT,
            tuning_doc["unlockCost"]["firstPoints"], tuning_doc["unlockCost"]["stepPoints"],
            tuning_doc["archetype"]["rewardSpreadMaxRatioMilli"],
            tuning_doc["potency"]["minTerminalWidth"],
        )
    except plan_invariants.PlanInvariantError as ex:
        return str(ex)
    return None


def _cmd_trees_census(args: argparse.Namespace) -> int:
    """`seedsmith trees census [--json]` (task P0.1, tasks/passive-tree-repair-plan.md §1).

    Prints the passive-tree DISTRIBUTION, not an aggregate: bind rate by node class, by tier (for
    mechanism), by category and by tree, plus the refusal buckets, the inert-bound count, the unspent
    budget and any orphaned generated node. The 2026-09-11 aggregate (`266/1680 bound`) hid the
    defect that actually matters — mechanism binds at 2.1% while magnitude binds at 29.5%, so tiers
    8-10, which the plan authors as 100% mechanism, produce nothing. This command is what makes that
    visible in one run, so every later repair phase reports a delta against a fixed baseline.

    It measure-only: exit 0 unless the corpus could not be read at all (`EXIT_CANNOT_RUN`). It never
    gates and never writes a corpus file — a later phase's gate diffs two runs of it.
    """
    from ..adapters.trees import census as census_mod

    seed_root = Path(args.seed_root) if args.seed_root else None
    out_root = Path(args.out_root) if args.out_root else None
    tree_ids = [args.tree] if args.tree else None
    try:
        result = census_mod.census(seed_root, out_root, tree_ids)
    except (OSError, json.JSONDecodeError) as ex:
        print(f"seedsmith: passive-tree census could not read the corpus: {ex}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    if not result.trees:
        print("seedsmith: no committed tree plans found — run `trees plan --emit` first",
              file=sys.stderr)
        return EXIT_CANNOT_RUN

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.format_text())
    return EXIT_CLEAN


def _cmd_trees_plan(args: argparse.Namespace) -> int:
    """`seedsmith trees plan --emit|--check [--tree <id>] [--manifest] [--generate] [--diff a b]`
    (spec-tree-plan.md Commands). No model calls, no RNG — every value is a pure function of
    tuning + roster mirrors + (for --check) the already-committed plan."""
    from ..adapters.trees.plan import emit as plan_emit
    from ..adapters.trees.plan import invariants as plan_invariants
    from ..adapters.trees.plan import tuning as plan_tuning

    if args.diff:
        path_a, path_b = Path(args.diff[0]), Path(args.diff[1])
        try:
            report = plan_emit.diff_manifests(path_a, path_b)
        except plan_emit.EmitError as ex:
            print(f"EXIT_CANNOT_RUN: {ex}")
            return EXIT_CANNOT_RUN
        any_diff = any(report.values())
        for label, entries in report.items():
            if entries:
                print(f"{label}: {len(entries)}")
                for entry in entries:
                    print("  " + entry)
        if not any_diff:
            print(f"{path_a} and {path_b} are equivalent — no budget deltas, archetype "
                 f"reassignments, quota-cell moves, or id changes.")
            return EXIT_CLEAN
        return EXIT_GAP

    try:
        tuning_doc = plan_tuning.load()
    except plan_tuning.PassiveTreePlanTuningError as ex:
        print(f"EXIT_CANNOT_RUN: {ex}")
        return EXIT_CANNOT_RUN

    # H9 (2026-09-06): generalized past "might" alone — `primary_tree_spec` is a mechanical
    # extension of `might_tree_spec`'s own logic (proven byte-identical for "might" itself, see its
    # own docstring), reading each of the 12 primary trees' `ordinal`/`gate_quantity` from the SAME
    # roster/gate-evidence files `might_tree_spec` always read, never a new content decision. "might"
    # keeps calling the original named function verbatim — zero behavior change for the one tree
    # every existing test already exercises.
    #
    # `--tree` omitted (`None`): a single-tree emit still needs a spec, and "might" is B1's own named
    # default. `--manifest` without `--tree` ignores `spec` entirely and builds the full roster.
    tree_id = args.tree if args.tree is not None else "might"
    if tree_id == "might":
        try:
            spec = plan_emit.might_tree_spec()
        except Exception as ex:  # gates.GateEvidenceError, etc. — never resolved silently
            print(f"EXIT_CANNOT_RUN: {ex}")
            return EXIT_CANNOT_RUN
    else:
        from ..adapters.trees.plan.vocabulary import load_roster
        roster = load_roster()
        aptitude_by_lower = {a.lower(): a for a in roster.aptitudes}
        aptitude_id = aptitude_by_lower.get(tree_id)
        # J1 (spec-tree-plan.md §7 table): elemental_tree_spec/status_tree_spec, the two remaining
        # mechanical extensions of primary_tree_spec's own generalization pattern. Checked after
        # aptitudes (the pre-existing, most-exercised path stays first and unchanged) — roster.elements
        # and roster.statuses are already lowercase (generated from ElementTypeId/
        # StatusCategoryRegistry), so no case-folding lookup is needed the way aptitudes' PascalCase
        # roster required.
        if aptitude_id is not None:
            try:
                spec = plan_emit.primary_tree_spec(aptitude_id)
            except Exception as ex:  # ValueError, gates.GateEvidenceError, etc. — never resolved silently
                print(f"EXIT_CANNOT_RUN: {ex}")
                return EXIT_CANNOT_RUN
        elif tree_id in roster.elements:
            try:
                spec = plan_emit.elemental_tree_spec(tree_id)
            except Exception as ex:
                print(f"EXIT_CANNOT_RUN: {ex}")
                return EXIT_CANNOT_RUN
        elif tree_id in roster.statuses:
            try:
                spec = plan_emit.status_tree_spec(tree_id)
            except Exception as ex:
                print(f"EXIT_CANNOT_RUN: {ex}")
                return EXIT_CANNOT_RUN
        else:
            print(f"seedsmith: {tree_id!r} is not one of the {len(roster.aptitudes)} primary trees "
                 f"{sorted(aptitude_by_lower)!r}, the {len(roster.elements)} elemental trees "
                 f"{sorted(roster.elements)!r}, or the {len(roster.statuses)} status trees "
                 f"{sorted(roster.statuses)!r}", file=sys.stderr)
            return EXIT_CANNOT_RUN

    if args.generate:
        try:
            plan_invariants.check_r_g1_generation_allowed(spec.tree_id, spec.gate_state, spec.gate_quantity)
        except plan_invariants.PlanInvariantError as ex:
            print(f"EXIT_REFUSED: {ex}")
            return EXIT_REFUSED
        print(f"{spec.tree_id}: gateState='carrier' — R-G1 allows stage-2 generation. "
             f"tree-language (H1) is not built yet, so nothing is generated here beyond the gate check.")
        return EXIT_CLEAN

    if args.manifest:
        # `--manifest` operates on the TOP-LEVEL manifest and the full `trees[]` index it carries
        # (spec-tree-plan.md Commands: `trees plan --emit` writes the whole manifest). Before this
        # fix the branch built a one-element `[spec]` list from `--tree`'s default ("might"), so a
        # bare `--emit` rewrote `plan.v1.json` indexing ONE tree while 41 committed per-tree plans
        # sat unindexed — the roster block claimed 21 statuses against the roster's real 24, and the
        # manifest's own `planHash` described a 1-tree corpus. A manifest is a corpus-level object;
        # only an explicit `--tree` narrows it (the single-tree case the old tests exercised).
        if args.tree is not None:
            specs = [spec]
        else:
            try:
                specs = _all_roster_specs()
            except Exception as ex:  # GateEvidenceError, EmitError, a missing roster mirror, ...
                print(f"EXIT_CANNOT_RUN: {ex}")
                return EXIT_CANNOT_RUN
        if args.check:
            try:
                diffs = plan_emit.check_manifest(specs, tuning_doc)
            except plan_emit.EmitError as ex:
                print(f"EXIT_CANNOT_RUN: {ex}")
                return EXIT_CANNOT_RUN
            if not diffs:
                print(f"{plan_emit.manifest_path()} is byte-identical to a fresh regeneration.")
                return EXIT_CLEAN
            print(f"{len(diffs)} difference(s):")
            for d in diffs:
                print("  " + d)
            return EXIT_GAP

        try:
            path = plan_emit.emit_manifest(specs, tuning_doc)
        except (plan_emit.EmitError, plan_invariants.PlanInvariantError) as ex:
            print(f"EXIT_REFUSED: {ex}")
            return EXIT_REFUSED
        print(f"wrote {path} ({len(specs)} tree(s) indexed)")
        return EXIT_CLEAN

    if args.check:
        try:
            diffs = plan_emit.check(spec, tuning_doc)
        except plan_emit.EmitError as ex:
            print(f"EXIT_CANNOT_RUN: {ex}")
            return EXIT_CANNOT_RUN
        refusal = _run_tree_equal_value([plan_emit.build_plan(spec, tuning_doc)], tuning_doc)
        if refusal is not None:
            print(f"EXIT_REFUSED: PassiveTree/TreeEqualValue: {refusal}")
            return EXIT_REFUSED
        if not diffs:
            print(f"{plan_emit.plan_path(spec.tree_id)} is byte-identical to a fresh regeneration.")
            return EXIT_CLEAN
        print(f"{len(diffs)} difference(s):")
        for d in diffs:
            print("  " + d)
        return EXIT_GAP

    try:
        built = plan_emit.build_plan(spec, tuning_doc)
    except (plan_emit.EmitError, plan_invariants.PlanInvariantError) as ex:
        print(f"EXIT_REFUSED: {ex}")
        return EXIT_REFUSED

    refusal = _run_tree_equal_value([built], tuning_doc)
    if refusal is not None:
        print(f"EXIT_REFUSED: PassiveTree/TreeEqualValue: {refusal}")
        return EXIT_REFUSED

    try:
        path = plan_emit.emit(spec, tuning_doc)
    except (plan_emit.EmitError, plan_invariants.PlanInvariantError) as ex:
        print(f"EXIT_REFUSED: {ex}")
        return EXIT_REFUSED
    print(f"wrote {path}")
    return EXIT_CLEAN


def _parse_set_pairs(pairs: list[str]) -> dict[str, float]:
    """`channelWeight.<id>=<value>` / `baseShare=<value>` -> the override map `TierBands.adjust`
    already consumes (spec-numerics.md §3.2's own worked example). Values are plain ratio
    multipliers (`1.0` == 1000‰), never per-mille integers — the same grammar the shipped
    `tier-bands.v1.json` `_meta` line names."""
    overrides: dict[str, float] = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep:
            raise ValueError(f"--set expects KEY=VALUE, got {pair!r}")
        key = key.strip()
        if key != "baseShare" and not key.startswith("channelWeight."):
            raise ValueError(
                f"--set key must be 'baseShare' or 'channelWeight.<id>', got {key!r}")
        overrides[key] = float(raw)
    return overrides


def _cmd_numerics_rebalance(args: argparse.Namespace) -> int:
    """`seedsmith numerics rebalance --set channelWeight.<id>=<value> [--publish]` — the command
    `gk-data/packs/fusion/data/seed/items/_tuning/tier-bands.v1.json`'s own `_meta.rebalance` line has named since the
    file shipped, and which did not exist until now (the `numerics` package was library-only).

    Dry by default: it prints what would move and exits without touching disk, matching
    spec-numerics.md §3.2's "nothing until publish". `--publish` writes `tier-bands.v{n+1}.json`
    and leaves the old version in place for revert, exactly as that `_meta` line promises.
    """
    from ..numerics import TierBands, tier_bands_io

    pairs = list(args.set_pairs or [])
    if args.set_file:
        for line in Path(args.set_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                pairs.append(line)

    try:
        overrides = _parse_set_pairs(pairs)
    except ValueError as ex:
        print(f"EXIT_CANNOT_RUN: {ex}")
        return EXIT_CANNOT_RUN

    if not overrides:
        print("EXIT_CANNOT_RUN: no --set/--set-file overrides given — refusing a no-op publish")
        return EXIT_CANNOT_RUN

    before = TierBands.load("latest")
    after = before.adjust(overrides)

    added = sorted(set(after.channel_weight_permille) - set(before.channel_weight_permille))
    changed = sorted(
        k for k in before.channel_weight_permille
        if after.channel_weight_permille[k] != before.channel_weight_permille[k])

    print(f"tier-bands v{before.version}: {len(before.channel_weight_permille)} channel weights, "
          f"baseShare {before.base_share_permille}‰")
    print(f"  + {len(added)} added, ~{len(changed)} changed, "
          f"= {len(before.channel_weight_permille) - len(changed)} unchanged")
    if after.base_share_permille != before.base_share_permille:
        print(f"  baseShare {before.base_share_permille}‰ -> {after.base_share_permille}‰")
    for key in changed:
        print(f"  ~ {key}: {before.channel_weight_permille[key]}‰ -> "
              f"{after.channel_weight_permille[key]}‰")
    for key in added:
        print(f"  + {key}: {after.channel_weight_permille[key]}‰")
    print(f"total after: {len(after.channel_weight_permille)} channel weights")

    if not args.publish:
        print("dry run — nothing written (pass --publish to write the next version)")
        return EXIT_CLEAN

    published = TierBands(version=before.version + 1,
                          base_share_permille=after.base_share_permille,
                          channel_weight_permille=after.channel_weight_permille,
                          op_weight_permille=after.op_weight_permille)
    path = tier_bands_io.save(published, meta=tier_bands_io.read_meta("latest"))
    print(f"wrote {path}")
    return EXIT_CLEAN


def cmd_numerics(args: argparse.Namespace) -> int:
    if args.numerics_command == "rebalance":
        return _cmd_numerics_rebalance(args)
    print(f"unknown numerics command {args.numerics_command!r}")
    return EXIT_CANNOT_RUN


def cmd_structures(args: argparse.Namespace) -> int:
    """`seedsmith structures <contract>` — base-defense structure corpus entrypoints. Mirrors
    `cmd_creatures`'s own dispatch shape exactly (module 23+, spec-structure-schema.md)."""
    if args.structures_command == "contract":
        return _cmd_structures_contract(args)

    print(f"unknown structures command {args.structures_command!r}")
    return EXIT_CANNOT_RUN


def _cmd_structures_contract(args: argparse.Namespace) -> int:
    """`seedsmith structures contract --print|--audit` (base-defense module 23,
    spec-structure-schema.md). No model calls: prints or numerically audits the resolved structure
    anchor schema — a line-for-line copy of `_cmd_creatures_contract` pointed at
    `adapters.structures.anchor.{schema,audit}` instead of `adapters.creatures.anchor.{schema,audit}`.
    """
    from ..adapters.structures.anchor.audit import numeric_audit
    from ..adapters.structures.anchor.schema import build_structure_anchor_schema

    schema = build_structure_anchor_schema()

    if args.print_schema:
        print(json.dumps(schema, indent=2, ensure_ascii=False))
        return EXIT_CLEAN

    # --audit (also the default when neither flag is passed)
    defects = numeric_audit(schema)
    if not defects:
        print(f"contract --audit: clean — {len(schema['properties'])} fields, "
              f"0 numeric-smuggling findings")
        return EXIT_CLEAN
    for d in defects:
        print(f"[FINDING] {d}")
    print(f"\n{len(defects)} numeric-smuggling finding(s)")
    return EXIT_GAP


def _cmd_creatures_preflight(args: argparse.Namespace) -> int:
    """`seedsmith creatures preflight [--json] [--skip-model]` (creature-seed module 5,
    spec-dump-preflight.md). Refuses to start a run unless every prerequisite is present.
    """
    from ..adapters.creatures.preflight import run_preflight, write_preflight_record

    report = run_preflight(skip_model=args.skip_model)

    if args.json:
        print(json.dumps({
            "fullPass": report.full_pass,
            "dumpHash": report.dump_hash,
            "checks": [
                {"id": c.id, "name": c.name, "ok": c.ok, "observed": c.observed,
                 "expected": c.expected, "action": c.action, "fixCommand": c.fix_command}
                for c in report.checks
            ],
        }, indent=2))
    else:
        for c in report.checks:
            status = "OK" if c.ok else c.action.upper()
            print(f"[{status:6s}] check {c.id} {c.name}: observed={c.observed!r} expected={c.expected!r}")
            if not c.ok:
                print(f"           fix: {c.fix_command}")
        print(f"\n{'PASS' if report.full_pass else 'NOT READY'} — "
              f"{len(report.refusals)} refusal(s), {len(report.asks)} thing(s) to ask about")

    if report.full_pass:
        write_preflight_record(report, skip_model=args.skip_model)

    return EXIT_CLEAN if report.full_pass else EXIT_GAP


def _cmd_creatures_build_favour(args: argparse.Namespace) -> int:
    """`seedsmith creatures build-favour [--dry-run] [--write] [--limit N]` — pass 2 of
    `lead-relabel-pass` (`empire-progression` EP2.12, spec-lead-relabel-pass.md).

    **Dry run by default**, like `families`/`theme-enrich`: the plan (which aptitudes are over the cap,
    which species are therefore asked, and who was requeued by staleness) is printed and NOTHING is
    called or written. `--write` is the real pass: three samples per asked species, stage A's quota,
    and the accepted re-labels written into the anchors through the emit with their provenance.

    The candidate list comes from `favour-detector`'s measure artifact, never a Python recount, so the
    cap is judged on the same population the measure counted. `--limit` asks the first N in ordinal
    speciesId order — the staged way to spend a few calls before committing to the pass.
    """
    import json as _json

    from ..adapters.creatures.build_favour import run as build_favour

    root = Path(args.root) if args.root else Path(__file__).resolve().parents[4]
    limit = args.limit if args.limit and args.limit > 0 else None
    plan = build_favour.load_plan(
        root,
        measure_path=Path(args.measure) if args.measure else None,
        tuning_path=Path(args.tuning) if args.tuning else None,
        limit=limit,
    )

    if not args.write:
        print(_json.dumps(build_favour.execute(plan), ensure_ascii=False, indent=2))
        return EXIT_CLEAN

    from ..pipeline.llm_caller import resolve_live_transport

    # An empty flag falls through to `.env` / `seedsmith.toml` / the built-in default — the one
    # config layer (spec-model-config-resolve.md §3.3).
    config = resolve_live_transport(args.endpoint, args.model, cli_mode=getattr(args, "mode", ""))
    print(_json.dumps(
        build_favour.execute(
            plan, ask=build_favour.graph_ask(config=config), write=True,
            lore_by_id=build_favour.load_lore(root)),
        ensure_ascii=False, indent=2))
    return EXIT_CLEAN


def _cmd_creatures_permute(args: argparse.Namespace) -> int:
    """`seedsmith creatures permute --species <id> --field <name>` (creature-seed module 6,
    spec-option-permutation.md) — shows the three deterministic orders a species/field pair would
    see, so a reviewer can see the shuffle without instrumenting a real pipeline call."""
    from ..adapters.creatures.anchor.permute import order_for
    from ..adapters.creatures.anchor.schema import build_anchor_schema

    schema = build_anchor_schema()
    prop = schema["properties"].get(args.field)
    if prop is None or "enum" not in prop:
        print(f"seedsmith: {args.field!r} is not an enum field in the anchor schema "
              f"(known enum fields: {sorted(k for k, v in schema['properties'].items() if 'enum' in v)})",
              file=sys.stderr)
        return EXIT_CANNOT_RUN

    options = [v for v in prop["enum"] if v != "none"]
    print(f"permute: species={args.species!r} field={args.field!r} ({len(options)} options)")
    for i in range(3):
        print(f"  sample {i}: {order_for(args.species, args.field, i, options)}")
    return EXIT_CLEAN


def _cmd_creatures_generate_anchor(args: argparse.Namespace) -> int:
    """`seedsmith creatures generate --kind anchor --pipeline <id> --species <id> [--dry-run]`
    (creature-seed module 7, spec-classify-pipelines.md). `--dry-run` renders every prompt without
    calling — the cheapest way to review a description change across the roster before spending
    hours on a real run. `--all` here is refused on purpose: a real multi-hour run needs the
    pause/resume/cancel state machine, which is `creatures run start --all` (module 9, run-control),
    not this single-shot command.
    """
    from ..adapters.creatures.anchor.prompts import PIPELINES, SpeciesLore, threat_audit_spec_for_basis
    from ..adapters.creatures.dump_ctx import load_creature_dump_ctx

    if args.all:
        print("seedsmith: this command has no run-control (pause/resume/checkpoint) — "
              "use `seedsmith creatures run start --all` instead, or --species with --dry-run "
              "to review one species at a time here", file=sys.stderr)
        return EXIT_CANNOT_RUN

    dump_dir = Path(args.dump) if args.dump else Path("../../data/seed/creatures/_dump")
    creature_dump = load_creature_dump_ctx(dump_dir)
    if creature_dump is None:
        print(f"seedsmith: no readable corpus-dump tree at {dump_dir}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    manifest_rows = json.loads((dump_dir / "almanac" / "plant.json").read_text(encoding="utf-8")) + \
                    json.loads((dump_dir / "almanac" / "zombie.json").read_text(encoding="utf-8"))
    by_species = {r["typeName"] or f"{r['side']}-{r['typeId']}": r for r in manifest_rows}

    def lore_for(row: dict) -> SpeciesLore:
        return SpeciesLore(
            species_id=row["typeName"] or f"{row['side']}-{row['typeId']}", side=row["side"],
            display_name=row["displayName"], flavor_info=row["flavorInfo"],
            flavor_introduce=row["flavorIntroduce"], enrichment=row.get("enrichment"))

    seed_by_species = {s.side + ":" + str(s.type_id): s for s in creature_dump.seeds}

    def basis_for(row: dict) -> str:
        s = seed_by_species.get(row["side"] + ":" + str(row["typeId"]))
        return s.basis if s else "blocked"

    if args.dry_run:
        rows = [by_species[args.species]] if args.species else manifest_rows
        rendered = 0
        for row in rows:
            lore = lore_for(row)
            basis = basis_for(row)
            for pid, spec in PIPELINES.items():
                if pid == "threat-audit":
                    spec = threat_audit_spec_for_basis(basis)
                spec.build_brief(lore, {"order": [], "elementPrimary": "fire",
                                        "aptitudePrimary": "Might", "rungId": "nuisance", "rungOrdinal": 1})
                rendered += 1
        print(f"generate --dry-run: rendered {rendered} prompts across {len(rows)} species x "
              f"{len(PIPELINES)} pipelines — zero model calls made")
        return EXIT_CLEAN

    if not args.pipeline or not args.species:
        print("seedsmith: --pipeline and --species are both required for a real (non-dry-run) call",
              file=sys.stderr)
        return EXIT_CANNOT_RUN
    if args.species not in by_species:
        print(f"seedsmith: species {args.species!r} not found in {dump_dir}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    from ..workflow.graphs.creature_anchor import build_pipeline_graph, state_for_pipeline

    row = by_species[args.species]
    lore = lore_for(row)
    basis = basis_for(row)
    graph = build_pipeline_graph(args.pipeline, basis=basis)
    state = state_for_pipeline(args.pipeline, lore, basis=basis)
    result = graph.invoke(state)
    print(json.dumps({"species": args.species, "pipeline": args.pipeline,
                      "outcome": result.get("outcome"), "draft": result.get("draft")},
                     indent=2, ensure_ascii=False))
    return EXIT_CLEAN if result.get("outcome") == "persisted" else EXIT_GAP


def _selector_from_args(args: argparse.Namespace) -> dict:
    """One of the eight `run-control` selector shapes (spec-run-control.md §4), chosen by which
    flag the caller actually passed. `--all` and the `start`/`rerun` defaults both resolve to
    `{"kind": "all"}` when nothing more specific is given — `start` already skips
    already-emitted species on its own, so "all" is the right default rather than a refusal.

    `--pipeline` is two DIFFERENT things depending on what else is set (creature-corpus-self-heal B1,
    2026-09-04, found live: `rerun --pipeline kit-shape --species Peashooter,...` silently did a
    FULL 8-pipeline reclassification instead of the intended kit-shape-only smoke test, because
    `--species` won the if-elif chain and `--pipeline`'s own value was discarded entirely). When no
    OTHER selecting flag is given, `--pipeline` picks WHICH species (every classified one). When a
    species-selecting flag IS also given, `--pipeline` instead narrows EXECUTION scope for those
    selected species — attached as an extra `pipeline` key `_run_loop` reads regardless of `kind`,
    never silently dropped.
    """
    if args.species:
        selector = {"kind": "species", "species": [s.strip() for s in args.species.split(",") if s.strip()]}
    elif args.side:
        selector = {"kind": "side", "side": args.side}
    elif args.family:
        selector = {"kind": "family", "family": args.family}
    elif args.pipeline:
        return {"kind": "pipeline", "pipeline": args.pipeline}  # --pipeline alone: selects AND scopes
    elif args.basis:
        selector = {"kind": "basis", "basis": args.basis}
    elif args.unresolved:
        selector = {"kind": "unresolved"}
    elif args.stale:
        selector = {"kind": "stale"}
    else:
        selector = {"kind": "all"}

    if args.pipeline:
        selector["pipeline"] = args.pipeline
    return selector


def _cmd_creatures_run(args: argparse.Namespace) -> int:
    """`seedsmith creatures run <start|pause|resume|cancel|rerun|status|overwrite-all> [selector]`
    (creature-seed module 9, spec-run-control.md). Ties the pure `machine`/`record`/`selectors`
    modules to the real classification loop via `adapters.creatures.run.runner` — every refusal
    (`RunRefused`) is printed and turned into a non-zero exit, never a silent no-op.
    """
    from ..adapters.creatures.run import runner as run_module

    paths = run_module.RunPaths(
        dump_dir=Path(args.dump) if args.dump else run_module.DEFAULT_DUMP_DIR,
        anchors_dir=Path(args.anchors) if args.anchors else run_module.DEFAULT_ANCHORS_DIR)

    def progress(species_id: str, done: int, total: int) -> None:
        print(f"  [{done}/{total}] {species_id}")

    workers = max(1, args.workers)

    try:
        if args.run_verb == "start":
            record = run_module.start(_selector_from_args(args), paths=paths, progress=progress,
                                      workers=workers)
        elif args.run_verb == "resume":
            record = run_module.resume(paths=paths, progress=progress, workers=workers)
        elif args.run_verb == "pause":
            run_module.request_pause(paths=paths)
            print("pause requested — the in-flight species finishes, then the run stops")
            return EXIT_CLEAN
        elif args.run_verb == "cancel":
            record = run_module.cancel(paths=paths)
        elif args.run_verb == "rerun":
            record = run_module.rerun(_selector_from_args(args), paths=paths, progress=progress,
                                      workers=workers)
        elif args.run_verb == "overwrite-all":
            if not args.confirm:
                dump_hash = run_module._compute_dump_hash(paths.dump_dir)
                from ..adapters.creatures.run.record import overwrite_all_token
                print(f"seedsmith: overwrite-all needs --confirm <token>; "
                      f"the token for the current dump is {overwrite_all_token(dump_hash)}", file=sys.stderr)
                return EXIT_CANNOT_RUN
            record = run_module.overwrite_all(args.confirm, paths=paths, progress=progress,
                                              workers=workers)
        elif args.run_verb == "fix-unresolved":
            fixed = run_module.fix_unresolved(paths=paths, dry_run=args.dry_run)
            verb = "would fix" if args.dry_run else "fixed"
            if args.json:
                print(json.dumps({"dryRun": args.dry_run, "fixed": fixed}, indent=2))
            else:
                print(f"{len(fixed)} field-fixes {verb} (threatBand, rarity, aptitudePrimary — "
                      f"each has a deterministic fallback now; element has none and stays "
                      f"unresolved)")
                for f in fixed:
                    before = f['before'] if f['before'] is not None else "(absent)"
                    print(f"  {f['speciesId']:24} {before:12} -> {f['after']}")
            return EXIT_CLEAN
        elif args.run_verb == "rederive-measured":
            rederived = run_module.rederive_from_measured_capture(paths=paths, dry_run=args.dry_run)
            verb = "would change" if args.dry_run else "changed"
            if args.json:
                print(json.dumps({"dryRun": args.dry_run, "changed": rederived}, indent=2))
            else:
                by_field: dict[str, int] = {}
                for c in rederived:
                    by_field[c["field"]] = by_field.get(c["field"], 0) + 1
                print(f"{len(rederived)} field(s) {verb} from the committed type-base-stats capture "
                      f"(basis, speciesKind — threatBand is deliberately not re-scored; see "
                      f"rederive_from_measured_capture's own docstring for the measurement)")
                for field, n in sorted(by_field.items()):
                    print(f"  {field:14} {n}")
                for c in rederived:
                    before = c["before"] if c["before"] is not None else "(absent)"
                    print(f"  {c['speciesId']:24} {c['field']:12} {before:12} -> {c['after']}")
            return EXIT_CLEAN
        elif args.run_verb == "refresh-rank":
            refreshed = run_module.refresh_rank(paths=paths, dry_run=args.dry_run)
            verb = "would refresh" if args.dry_run else "refreshed"
            if args.json:
                print(json.dumps({"dryRun": args.dry_run, "refreshed": refreshed}, indent=2))
            else:
                print(f"{len(refreshed)} rank value(s) {verb} from the entry's own committed "
                      f"(threatBand, rarity) pair (spec-species-rank.md §1; rank is DERIVED, so no "
                      f"model call and no dump read — a second run over an unchanged tree is a "
                      f"byte-for-byte no-op)")
                for c in refreshed:
                    before = c["before"] if c["before"] is not None else "(absent)"
                    print(f"  {c['speciesId']:24} {before:12} -> {c['after']}")
            return EXIT_CLEAN
        elif args.run_verb == "fix-secondary-from-fusion":
            recipes_path = Path(args.fusion_recipes) if args.fusion_recipes else run_module.DEFAULT_FUSION_RECIPES_PATH
            fixed = run_module.fix_secondary_from_fusion_lineage(
                paths=paths, recipes_path=recipes_path, dry_run=args.dry_run)
            verb = "would fix" if args.dry_run else "fixed"
            if args.json:
                print(json.dumps({"dryRun": args.dry_run, "fixed": fixed}, indent=2))
            else:
                print(f"{len(fixed)} elementSecondary fix(es) {verb} from fusion-recipe lineage "
                      f"(one fusion parent's own real element supplied the signal; species with "
                      f"no clean single-candidate signal are left unchanged)")
                for f in fixed:
                    print(f"  {f['speciesId']:24} {f['before']:6} -> {f['after']}")
            return EXIT_CLEAN
        elif args.run_verb == "status":
            s = run_module.status(paths=paths)
            print(json.dumps(s, indent=2) if args.json else
                  " ".join(f"{k}={v}" for k, v in s.items()))
            return EXIT_CLEAN
        else:  # unreachable — argparse `choices` already guards this
            print(f"seedsmith: unknown run verb {args.run_verb!r}", file=sys.stderr)
            return EXIT_CANNOT_RUN
    except run_module.RunRefused as e:
        print(f"seedsmith: run {args.run_verb} refused: {e}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    print(f"run {record.run_id}: state={record.state} completed={len(record.completed)} "
          f"failed={len(record.failed)} callsMade={record.calls_made}")
    return EXIT_CLEAN if record.state in ("completed", "paused", "cancelled") and not record.failed else EXIT_GAP


def _cmd_creatures_metrics(args: argparse.Namespace) -> int:
    """`seedsmith creatures metrics [--gate] [--grid] [--queue] [--anchors DIR]` (creature-seed module
    14, spec-roster-metrics.md). A thin wrapper over `CreatureRoster/*`'s own registry entries so the
    spec's literal command line works, without a second metrics engine beside `report`.
    """
    from ..adapters.creatures.anchor.review_queue import read_review_queue
    from ..metrics.creature_roster import ALL_ELEMENT_PAIRS, GridFillMetric

    anchors_root = Path(args.anchors) if args.anchors else Path("../../data/seed/creatures/species")
    anchors = _load_creature_anchors(anchors_root)
    if anchors is None:
        print(f"seedsmith: no readable anchor tree at {anchors_root} (expected an _index.json) — "
              f"run `creatures run start --all` first (the full corpus run is a real, hours-long "
              f"commitment; run a small --species selector first to prove the mechanism)", file=sys.stderr)
        return EXIT_CANNOT_RUN

    if args.queue:
        queue_path = anchors_root.parent / "_runs" / "threat-audit-queue.json"
        entries = read_review_queue(queue_path)
        if not entries:
            print(f"metrics --queue: no review queue at {queue_path} (or it is empty)")
            return EXIT_CLEAN
        for e in entries:
            print(f"  {e.side}:{e.species_id} computed={e.computed_rung_id} verdict={e.verdict} — {e.reason}")
        return EXIT_CLEAN

    ctx = Ctx(corpus=Corpus(), adapter=resolve_adapter("stub"), creature_anchors=anchors)
    registry = build_registry()
    creature_ids = [m.id for m in registry.all() if m.family == "CreatureRoster"]
    findings = run_all(registry, ctx, metric_ids=creature_ids)

    if args.grid:
        grid_findings = [f for f in findings if f.metric == GridFillMetric.id]
        empty = set()
        for f in grid_findings:
            empty.update(f.evidence.get("emptyCells", []))
        print(f"grid: {len(ALL_ELEMENT_PAIRS)} pairs x 12 aptitudes = {len(ALL_ELEMENT_PAIRS) * 12} cells; "
              f"{len(empty)} empty (showing up to 20)")
        for cell in sorted(empty):
            print(f"  EMPTY: {cell}")
        return EXIT_CLEAN

    _print_human(findings)
    if args.gate:
        gating_ids = {m.id for m in registry.all() if m.gates}
        relevant = [f for f in findings if f.metric in gating_ids]
        return EXIT_GAP if any(f.severity is Severity.GAP for f in relevant) else EXIT_CLEAN
    return EXIT_GAP if any(f.severity is Severity.GAP for f in findings) else EXIT_CLEAN


def _cmd_creatures_diff_legacy(args: argparse.Namespace) -> int:
    """`seedsmith creatures diff-legacy --legacy PATH [--anchors DIR]` (T2.7, spec-anchor-emit.md §6).

    Closes the "no committed entrypoint" gap `legacy_diff.py`'s own function had — the same class of
    defect `families`/`generate --kind commander-effect` each hit once before this
    (`cmd_creatures`'s own docstring). `--legacy` points at the plain-JSON export
    `dotnet run --project gk-forge/tools/CreatureSpeciesGen -- --export-legacy PATH` produces from the real,
    compiled, shipped catalog; this module never reads C# source, matching `legacy_diff.py`'s own
    stated boundary.
    """
    from ..adapters.creatures.anchor.legacy_diff import diff_legacy, format_report

    if not args.legacy:
        print("seedsmith: diff-legacy needs --legacy <path> — produce it with "
              "`dotnet run --project tools/CreatureSpeciesGen -- --export-legacy <path>`", file=sys.stderr)
        return EXIT_CANNOT_RUN

    legacy_path = Path(args.legacy)
    if not legacy_path.exists():
        print(f"seedsmith: no file at {legacy_path}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    anchors_root = Path(args.anchors) if args.anchors else Path("../../data/seed/creatures/species")
    anchors = _load_creature_anchors(anchors_root)
    if anchors is None:
        print(f"seedsmith: no readable anchor tree at {anchors_root} (expected an _index.json)", file=sys.stderr)
        return EXIT_CANNOT_RUN

    import json as _json
    legacy_raw = _json.loads(legacy_path.read_text(encoding="utf-8"))
    # Case-sensitivity: the compiled catalog's own ids are lowercase (CreatureSpeciesCatalog.Validate's
    # own rule), the real anchor's speciesId is the captured TitleCase typeName -- the same mismatch
    # class `_load_families` already found and fixed once this session (runner.py).
    legacy = [{**e, "id": e["id"].lower()} for e in legacy_raw]
    new_anchors = [{**a, "speciesId": a["speciesId"].lower()} for a in anchors]

    report = diff_legacy(new_anchors, legacy, legacy_id_key="id", new_id_key="speciesId")
    overlap = len({a["speciesId"] for a in new_anchors} & {e["id"] for e in legacy})
    print(format_report(report))
    print(f"\nlegacy species: {len(legacy)}, new anchors: {len(new_anchors)}, "
          f"species present in both sets: {overlap}")
    return EXIT_CLEAN


def _regen_review_sample_size() -> int:
    """`event.regenReviewSample` from the published dungeon budget (v2 is v1 plus the event block). A
    bound no file owns is the code-owned tunable this project forbids, so the size is READ, never a
    constant in this module."""
    from ..workspace_roots import content_root

    path = content_root() / "data/seed/dungeon/_plan/budget.v2.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    value = (document.get("event") or {}).get("regenReviewSample")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{path}: event.regenReviewSample must be a positive integer, got {value!r}")
    return value


def cmd_dungeon(args: argparse.Namespace) -> int:
    """`seedsmith dungeon events regen` — the production host for the legacy Delve event driver (NS13).

    ⛔ Why this exists. `adapters/dungeon/regen.py` landed with its plan, draw, review and commit halves
    tested, but nothing in the pipeline could reach them: the shared CLI had no `dungeon` subcommand
    tree at all, so no real run could be planned, drawn, reviewed or committed. That is the same defect
    D1.4 and G1.3 caught for `creatures` and `items`, fixed the same way — by making the claim true
    rather than softening it.

    The stages are the order a run goes through them: `--dry-run` (the default; prints the base and
    worst call bounds and spends nothing), `--write` (draws every planned event with the RESOLVED
    config into a scratch run file; the corpus is never touched here), `--review` (the seeded,
    stratified sample) and `--commit` (only the run's ACCEPTED events, through the committer).

    `--accept` / `--reject` record verdicts, and they are part of this verb even though the row's own
    flag list does not name them: `--commit` reads only verdicts, so without a way to record one the
    commit stage could never write anything and the driver would still have no production caller.
    """
    if (getattr(args, "dungeon_command", "") != "events"
            or getattr(args, "dungeon_events_command", "") != "regen"):
        print(f"unknown dungeon command: {args.dungeon_command} "
              f"{getattr(args, 'dungeon_events_command', '')}")
        return EXIT_CANNOT_RUN

    from ..adapters.dungeon.regen import (
        commit_reviewed, latest_run_id, load_run, plan_legacy_regen, record_verdict, render_plan,
        review_sample, run_legacy_regen, write_run,
    )
    from ..pipeline.llm_caller import resolve_live_transport

    events_dir = args.events_dir or None
    runs_dir = args.runs_dir or None
    ids = [part.strip() for part in (args.ids or "").split(",") if part.strip()] or None

    run = None
    try:
        if args.accept or args.reject:
            run_id = args.run_id or latest_run_id(runs_dir)
            if not run_id:
                print("refused: no scratch run to record a verdict against — run "
                      "`dungeon events regen --write` first")
                return EXIT_REFUSED
            run = load_run(run_id, runs_dir)
            for event_id in args.accept or []:
                run = record_verdict(run, event_id.strip(), verdict="accept", runs_dir=runs_dir)
            for pair in args.reject or []:
                event_id, _separator, reason = pair.partition("=")
                run = record_verdict(run, event_id.strip(), verdict="reject", reason=reason.strip(),
                                     runs_dir=runs_dir)

        if args.write:
            run = run_legacy_regen(events_dir, ids=ids, runs_dir=runs_dir, dry_run=False)
            print(f"drew {len(run.events)} event(s), {len(run.unresolved)} unresolved -> "
                  f"{write_run(run, runs_dir)}")
        elif (args.review or args.commit) and run is None:
            run_id = args.run_id or latest_run_id(runs_dir)
            if not run_id:
                print("refused: no scratch run to review or commit — run "
                      "`dungeon events regen --write` first")
                return EXIT_REFUSED
            run = load_run(run_id, runs_dir)
    except ValueError as refusal:
        # A named refusal from the driver (a missing or mismatched run file, an unknown event id, a
        # rejection without a reason) is the CLI's refusal exit code, not a traceback.
        print(f"refused: {refusal}")
        return EXIT_REFUSED

    if args.commit:
        if not run.accepted_ids():
            # `commit_event_draws` rewrites the index even for an empty batch, so a commit with no
            # accepted event would look like it did something. It must not: only accepted events are
            # written, and there are none.
            print("refused: this run has no accepted event — record one with --accept first")
            return EXIT_REFUSED
        committed = commit_reviewed(run, events_dir, config=resolve_live_transport())
        print(json.dumps({"runId": run.run_id, "accepted": list(run.accepted_ids()),
                          "committed": sorted(path.name for path in committed)}, ensure_ascii=False))
        return EXIT_CLEAN
    if args.review:
        print(json.dumps({"runId": run.run_id,
                          "sample": review_sample(run, sample_size=_regen_review_sample_size())},
                         ensure_ascii=False, indent=2))
        return EXIT_CLEAN
    if run is not None:
        print(json.dumps({"runId": run.run_id, "drawn": len(run.events),
                          "unresolved": sorted(run.unresolved),
                          "accepted": list(run.accepted_ids()),
                          "rejected": list(run.rejected_ids())}, ensure_ascii=False))
        return EXIT_CLEAN

    print(render_plan(plan_legacy_regen(events_dir, ids=ids)))
    return EXIT_CLEAN


def _narrative_gloss_inputs() -> "tuple[list[str], list[dict], dict]":
    """The three things a gloss fill reads from the corpus: the source motifs, the authored exemplar
    pairs and the budget's gloss block. Read fresh, never transcribed; a bound no file owns is the
    code-owned tunable this project forbids."""
    from ..workspace_roots import content_root

    root = content_root()
    motifs_path = root / "data/seed/creatures/_registry/motifs.v1.json"
    motifs = [m for m in (json.loads(motifs_path.read_text(encoding="utf-8")).get("motifs") or [])
              if isinstance(m, str)]
    if not motifs:
        raise ValueError(f"{motifs_path}: declares no motif")
    exemplars_path = root / "data/seed/narrative/_exemplars/gloss.en.v1.json"
    exemplars = [dict(pair)
                 for pair in (json.loads(exemplars_path.read_text(encoding="utf-8")).get("pairs") or [])]
    if not exemplars:
        raise ValueError(f"{exemplars_path}: declares no exemplar pair")
    budget_path = root / "data/seed/narrative/_plan/budget.v1.json"
    block = json.loads(budget_path.read_text(encoding="utf-8")).get("gloss") or {}
    chunk_size = block.get("chunkSize")
    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or chunk_size < 1:
        raise ValueError(f"{budget_path}: gloss.chunkSize must be a positive integer, got {chunk_size!r}")
    return motifs, exemplars, block


def _narrative_gloss_fill(args: argparse.Namespace) -> int:
    from ..adapters.narrative.gloss.fill import fill_glosses, gloss_run_id, write_gloss_run
    from ..adapters.narrative.gloss.prompt import GLOSS_PROMPT_VERSION
    from ..briefkit.gloss import load_glosses
    from ..pipeline.llm_caller import resolve_live_transport

    try:
        motifs, exemplars, block = _narrative_gloss_inputs()
        already = list(load_glosses().rows)
        regenerate = [motif.strip() for motif in (args.regenerate or []) if motif.strip()]
        already = [motif for motif in already if motif not in set(regenerate)]
        todo = [motif for motif in motifs if motif not in set(already)]
        run_id = gloss_run_id(todo)
        result = fill_glosses(motifs, config=resolve_live_transport(), exemplars=exemplars,
                              chunk_size=block["chunkSize"], already_glossed=already,
                              limit=args.limit or None, dry_run=not args.write)
    except ValueError as refusal:
        print(f"refused: {refusal}")
        return EXIT_REFUSED

    if not args.write:
        print(json.dumps({"runId": run_id, "dryRun": True, "chunks": result["chunks"],
                          "calls": result["calls"], "toGloss": len(todo),
                          "alreadyGlossed": len(already), "chunkSize": block["chunkSize"]},
                         ensure_ascii=False))
        return EXIT_CLEAN

    document = {"runId": run_id, "model": resolve_live_transport().model,
                "promptVersion": GLOSS_PROMPT_VERSION, "chunkSize": block["chunkSize"],
                "regenerated": regenerate, "glosses": result["glosses"],
                "unresolved": result["unresolved"], "calls": result["calls"],
                "chunks": result["chunks"], "verdicts": {}}
    print(json.dumps({"runId": run_id, "glossed": len(result["glosses"]),
                      "unresolved": sorted(result["unresolved"]), "calls": result["calls"],
                      "run": str(write_gloss_run(document, runs_dir=args.runs_dir or None))},
                     ensure_ascii=False))
    return EXIT_CLEAN


def _narrative_gloss_commit(args: argparse.Namespace) -> int:
    from ..adapters.narrative.gloss.commit import commit_glosses
    from ..adapters.narrative.gloss.fill import latest_gloss_run_id, load_gloss_run, write_gloss_run

    runs_dir = args.runs_dir or None
    try:
        run_id = args.run_id or latest_gloss_run_id(runs_dir=runs_dir)
        if not run_id:
            print("refused: no fill run to commit — run `narrative gloss fill --write` first")
            return EXIT_REFUSED
        run = load_gloss_run(run_id, runs_dir=runs_dir)
        verdicts = {motif: [dict(row) for row in history]
                    for motif, history in (run.get("verdicts") or {}).items()}
        for motif in args.accept or []:
            verdicts.setdefault(motif.strip(), []).append({"verdict": "accept", "reason": ""})
        for pair in args.reject or []:
            motif, _separator, reason = pair.partition("=")
            if not reason.strip():
                print("refused: a rejection must name its reason — a rejected gloss is regenerated "
                      "under it")
                return EXIT_REFUSED
            verdicts.setdefault(motif.strip(), []).append({"verdict": "reject",
                                                           "reason": reason.strip()})
        # A rejected row is NOT a row to write: excluding it is what makes `commit_glosses` refuse
        # until the motif has an accepted replacement, which is the regeneration contract.
        rejected = {motif for motif, history in verdicts.items()
                    if history and history[-1].get("verdict") == "reject"}
        rows = {motif: row for motif, row in (run.get("glosses") or {}).items()
                if motif not in rejected}
        write_gloss_run({**run, "verdicts": verdicts}, runs_dir=runs_dir)
        path = commit_glosses(rows, model=str(run.get("model") or ""),
                              prompt_version=str(run.get("promptVersion") or ""),
                              verdicts=verdicts, registry_path=args.registry or None)
    except ValueError as refusal:
        print(f"refused: {refusal}")
        return EXIT_REFUSED
    print(json.dumps({"runId": run_id, "registry": str(path), "committed": sorted(rows),
                      "rejected": sorted(rejected)}, ensure_ascii=False))
    return EXIT_CLEAN


def _narrative_preflight(args: argparse.Namespace) -> int:
    from ..adapters.narrative.preflight import preflight
    from ..briefkit.render import BriefRefusal
    from ..pipeline.llm_caller import resolve_live_transport

    try:
        _motifs, exemplars, _block = _narrative_gloss_inputs()
        result = preflight(config=resolve_live_transport(), exemplars=exemplars)
    except (BriefRefusal, ValueError) as refusal:
        print(f"refused: {refusal}")
        return EXIT_REFUSED
    print(json.dumps(result, ensure_ascii=False))
    return EXIT_CLEAN


def cmd_narrative(args: argparse.Namespace) -> int:
    """`seedsmith narrative gloss fill|commit` and `seedsmith narrative preflight` — the production
    host for the gloss pipeline (NS15; NS16/NS17 run through it).

    ⛔ Why this exists. `gloss/fill.py`, `gloss/commit.py` and `preflight.py` landed with their tests,
    but the shared CLI had no `narrative` subcommand tree, so nothing in the pipeline could reach them
    and the registry could only ever be written by importing a module. Same defect, same fix as the
    `creatures`, `items` and `dungeon` trees.

    Stages: `gloss fill` (default `--dry-run`: the chunk and call count, no call; `--write`: gloss with
    the RESOLVED config and persist a scratch run file — the registry is never touched here),
    `gloss commit` (write the run's glosses, with `--accept`/`--reject` recording the verdicts the
    refusal rule reads), and `preflight` (ONE call, to prove the endpoint honours the chunk schema).
    """
    command = getattr(args, "narrative_command", "")
    if command == "preflight":
        return _narrative_preflight(args)
    if command == "gloss":
        gloss = getattr(args, "gloss_command", "")
        if gloss == "fill":
            return _narrative_gloss_fill(args)
        if gloss == "commit":
            return _narrative_gloss_commit(args)
    print(f"unknown narrative command: {command} {getattr(args, 'gloss_command', '')}")
    return EXIT_CANNOT_RUN


def _add_repair_names_arguments(parser: argparse.ArgumentParser) -> None:
    """The argument set every `items repair-*names` entry takes.

    `repair-names`, `repair-materials` and `repair-charms` are ONE implementation
    (`_cmd_items_repair_names`, narrowed by `kind`), so they take ONE argument set — declared here
    once so the three cannot drift apart, which is the failure mode a hand-copied block produces the
    first time a flag is added to only one of them.
    """
    parser.add_argument("--write", action="store_true",
                        help="apply validated replacement names")
    parser.add_argument("--allow-production-tree", dest="allow_production_tree", action="store_true",
                        help="permit writes under data/seed/items/")
    parser.add_argument("--items-dir", default="",
                        help="items root to scan (default data/seed/items)")
    parser.add_argument("--answers", default="",
                        help="JSON object keyed by losing entry id, each with name and optional flavor")
    parser.add_argument("--derive", action="store_true",
                        help="derive replacement names from each losing row's OWN fields - no endpoint, "
                             "no --answers, no model. Deterministic: the same corpus always yields the "
                             "same names, so the fix survives the next content ship instead of "
                             "needing a new authored batch.")
    parser.add_argument("--endpoint", default="",
                        help="live model endpoint; omitted when --answers supplies replacements")
    parser.add_argument("--model", default="unrecorded",
                        help="live model id; falls through to configured default")
    parser.add_argument("--mode", default="", choices=("api", "delegated"),
                        help="which authorer answers: api (default) or delegated. Delegated runs a "
                             "sub-agent that MAY edit the corpus, so it is never selected implicitly "
                             "- pass it here, set `mode` in [pipeline.llm_caller], or put "
                             "SEEDSMITH_LLM_MODE in .env")
    parser.add_argument("--limit", type=int, default=0,
                        help="repair at most N losing rows (0 = every duplicate)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seedsmith")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="run metrics against a corpus")
    check.add_argument("corpus_root", nargs="?", default=None,
                       help="not used with --family (a family-scoped check needs no corpus)")
    check.add_argument("--adapter", default="stub")
    check.add_argument("--family", default="", help="a family-scoped check (e.g. PassiveTree) "
                                                    "instead of a corpus_root one (task H2)")
    check.add_argument("--plan-root", dest="plan_root", default="",
                       help="--family PassiveTree only: override the seed root the committed "
                            "plan is read under, i.e. <root>/passive-tree/plan (default data/seed)")
    check.add_argument("--gate", action="store_true",
                       help="exit non-zero only for metrics promoted with gates=True")
    check.add_argument("--json", default=None, metavar="PATH")
    check.add_argument("--metric", action="append", default=None, metavar="ID",
                       help="run only this metric id (repeatable)")
    check.set_defaults(func=cmd_check)

    report = sub.add_parser(
        "report", help="run the FULL metric registry (item-corpus and creature-dump metrics alike)")
    report.add_argument("--corpus", default=None, metavar="DIR", help="an item/seed corpus root")
    report.add_argument("--adapter", default="stub")
    report.add_argument("--creature-dump", dest="creature_dump", default=None, metavar="DIR",
                        help="a corpus-dump tree root (data/seed/creatures/_dump)")
    report.add_argument("--creature-anchors", dest="creature_anchors", default=None, metavar="DIR",
                        help="an emitted anchor tree root (data/seed/creatures/species)")
    report.add_argument("--gate", action="store_true",
                        help="exit non-zero only for metrics promoted with gates=True")
    report.add_argument("--json", default=None, metavar="PATH")
    report.add_argument("--metric", action="append", default=None, metavar="ID",
                        help="run only this metric id (repeatable)")
    report.set_defaults(func=cmd_report)

    metrics = sub.add_parser("metrics", help="list registered metrics")
    metrics.add_argument("--coverage", action="store_true",
                         help="print Appendix-A coverage: claimed / known gap / unclaimed")
    metrics.set_defaults(func=cmd_metrics)

    creatures = sub.add_parser("creatures", help="creature corpus generation entrypoints")
    creature_sub = creatures.add_subparsers(dest="creature_command", required=True)
    creature_sub.add_parser("motifs", help="re-derive motifs + the motif registry (no model calls)")
    themes = creature_sub.add_parser(
        "themes", aliases=("theme-refresh",),
        help="refresh the published theme registry over the complete species roster")
    themes.add_argument("--dry-run", action="store_true",
                        help="read and count the complete roster without writing")
    themes.add_argument("--rebuild", action="store_true",
                        help="discard published snapshots and re-derive (reviewed correction only)")
    enrich = creature_sub.add_parser(
        "theme-enrich", help="generate lore for name-basis themes (model calls; dry-run by default)")
    enrich.add_argument("--dry-run", action="store_true")
    enrich.add_argument("--write", action="store_true")
    enrich.add_argument("--endpoint", default="")
    enrich.add_argument("--model", default="")
    enrich.add_argument("--mode", default="", choices=("api", "delegated"),
                        help="which authorer answers: api (default) or delegated. Delegated runs a "
                             "sub-agent that MAY edit the corpus, so it is never selected implicitly")
    power_parse = creature_sub.add_parser(
        "power-parse", help="numeric power seed + basis per species (no model calls)")
    power_parse.add_argument("--dump", required=True, help="corpus-dump tree root")
    power_parse.add_argument("--report", action="store_true",
                             help="print the basis histogram + disagreement list")
    threat_band = creature_sub.add_parser(
        "threat-band", help="score -> threat rung -> Theta offset per species (no model calls)")
    threat_band.add_argument("--dump", required=True, help="corpus-dump tree root")
    threat_band.add_argument("--histogram", action="store_true",
                             help="print rung occupancy, including empty rungs")
    contract = creature_sub.add_parser(
        "contract", help="the species anchor JSON Schema — print or numerically audit it")
    contract.add_argument("--print", dest="print_schema", action="store_true",
                          help="print the resolved JSON Schema")
    contract.add_argument("--audit", action="store_true",
                          help="run the numeric-smuggling audit, exit 1 on a finding (default)")
    build_favour = creature_sub.add_parser(
        "build-favour",
        help="pass 2: re-label the species leading an over-cap aptitude (model calls; --write to keep)")
    build_favour.add_argument("--dry-run", dest="dry_run", action="store_true",
                              help="the default: print the candidate plan, call nothing, write nothing")
    build_favour.add_argument("--write", action="store_true",
                              help="ask the model and write the accepted re-labels into the anchors")
    build_favour.add_argument("--limit", type=int, default=0,
                              help="ask at most N species, ordinal by speciesId (0 = no limit)")
    build_favour.add_argument("--root", default="", help="repo root (default: this file's own four levels up)")
    build_favour.add_argument("--measure", default="", help="the favour measure artifact")
    build_favour.add_argument("--tuning", default="", help="the species-build tuning document")
    build_favour.add_argument("--endpoint", default="")
    build_favour.add_argument("--model", default="")
    build_favour.add_argument("--mode", default="", choices=("api", "delegated"),
                              help="which authorer answers: api (default) or delegated. Delegated is "
                                   "never selected implicitly")
    preflight = creature_sub.add_parser(
        "preflight", help="the nine run-readiness checks — refuses or asks, never guesses")
    preflight.add_argument("--json", action="store_true", help="machine-readable output")
    preflight.add_argument("--skip-model", dest="skip_model", action="store_true",
                           help="checks 1-4, 7-9 only — CI's escape hatch, refused by run-control before a real run")
    permute = creature_sub.add_parser(
        "permute", help="show the three deterministic option orders for a species/field pair")
    permute.add_argument("--species", required=True)
    permute.add_argument("--field", required=True)
    dmetrics = creature_sub.add_parser(
        "metrics", help="roster-shape metrics over the emitted anchors (element grid, threat/rarity distribution, ...)")
    dmetrics.add_argument("--anchors", default="", help="anchor tree root (default data/seed/creatures/species)")
    dmetrics.add_argument("--gate", action="store_true", help="exit non-zero only on gates=True findings")
    dmetrics.add_argument("--grid", action="store_true", help="print the 21x12 occupancy matrix")
    dmetrics.add_argument("--queue", action="store_true", help="print the threat-audit open-loop review queue")
    fam = creature_sub.add_parser("families", help="extract + consolidate creature families (model calls)")
    fam.add_argument("--dry-run", dest="dry_run", action="store_true")
    fam.add_argument("--write", action="store_true")
    fam.add_argument("--i-have-read-the-append-only-note", dest="ack", action="store_true")
    gen = creature_sub.add_parser("generate", help="generate content for a creature kind")
    gen.add_argument("--kind", default="commander-effect")
    gen.add_argument("--only", default="", help="comma-separated creature ids")
    gen.add_argument("--stale", action="store_true",
                     help="only entries whose recorded motifs no longer match")
    gen.add_argument("--force", action="store_true", help="regenerate everything")
    gen.add_argument("--dry-run", dest="dry_run", action="store_true")
    gen.add_argument("--workers", type=int, default=0)
    gen.add_argument("--endpoint", default="")
    gen.add_argument("--model", default="")
    gen.add_argument("--mode", default="", choices=("api", "delegated"),
                     help="which authorer answers: api (default) or delegated. Delegated runs a "
                          "sub-agent that MAY edit the corpus, so it is never selected implicitly")
    # --kind anchor (creature-seed module 7, classify-pipelines):
    gen.add_argument("--pipeline", default="", help="one of the 8 classify-pipelines ids (--kind anchor)")
    gen.add_argument("--species", default="", help="a speciesId (--kind anchor)")
    gen.add_argument("--dump", default="", help="corpus-dump tree root (--kind anchor, default ../../data/seed/creatures/_dump)")
    gen.add_argument("--all", action="store_true", help="refused here — use `creatures run start --all` (--kind anchor)")
    difflegacy = creature_sub.add_parser(
        "diff-legacy",
        help="field agreement between the new classification and the shipped, compiled legacy catalog")
    difflegacy.add_argument("--legacy", default="",
                            help="path to the JSON `CreatureSpeciesGen --export-legacy` produced (required)")
    difflegacy.add_argument("--anchors", default="", help="anchor tree root (default data/seed/creatures/species)")
    run = creature_sub.add_parser(
        "run", help="run-control: pause/resume/cancel/rerun/overwrite-all over the anchor classification run")
    run.add_argument("run_verb", choices=("start", "pause", "resume", "cancel", "rerun", "status",
                                          "overwrite-all", "fix-unresolved", "fix-secondary-from-fusion",
                                          "rederive-measured", "refresh-rank"))
    run.add_argument("--all", action="store_true", help="selector: every species in the dump")
    run.add_argument("--side", default="", help="selector: plant | zombie")
    run.add_argument("--family", default="", help="selector: one family id")
    run.add_argument("--species", default="", help="selector: comma-separated species ids")
    run.add_argument("--pipeline", default="", help="selector: one of the 8 classify-pipelines ids")
    run.add_argument("--basis", default="", help="selector: observed | stated | inferred | blocked")
    run.add_argument("--unresolved", action="store_true", help="selector: only fields a vote could not settle")
    run.add_argument("--stale", action="store_true", help="selector: only entries whose inputs moved")
    run.add_argument("--confirm", default="", help="overwrite-all: the confirmation token")
    run.add_argument("--dump", default="", help="corpus-dump tree root (default data/seed/creatures/_dump)")
    run.add_argument("--anchors", default="", help="anchor tree root (default data/seed/creatures/species)")
    run.add_argument("--json", action="store_true", help="machine-readable output (status)")
    run.add_argument("--workers", type=int, default=4,
                     help="parallel model-call workers for start/resume/rerun/overwrite-all "
                          "(default 4; 1 = sequential, today's original behaviour)")
    run.add_argument("--dry-run", action="store_true",
                     help="fix-unresolved/fix-secondary-from-fusion/rederive-measured/refresh-rank: "
                          "report what would change without writing anything")
    run.add_argument("--fusion-recipes", default="",
                     help="fix-secondary-from-fusion: path to the committed _fusion-recipes.json "
                          "(default data/generated/creatures/_fusion-recipes.json)")
    creatures.set_defaults(func=cmd_creatures)

    items = sub.add_parser("items", help="item corpus generation entrypoints (modules 13, 21)")
    items_sub = items.add_subparsers(dest="items_command", required=True)
    igen = items_sub.add_parser("generate", help="plan a set/charm/combination generation run")
    igen.add_argument("--kind", default="set",
                      choices=("set", "charm", "combination", "base-type",
                               "enhancement-milestone", "recipe", "drop-table", "gem",
                               "material", "consumable", "affix-family", "trophy"))
    igen.add_argument("--population", default="species", choices=("species", "build"),
                      help="set/charm only; a combination's grid is closed, so --shape selects it")
    igen.add_argument("--shape", default="strain", choices=("strain", "splice"),
                      help="combination only: 36 Strains (12 aptitudes x 3 archetypes) or 66 "
                           "Splices (C(12,2))")
    igen.add_argument("--dry-run", dest="dry_run", action="store_true",
                      help="the default and currently the only mode — assemble the plan, make no "
                           "model calls")
    igen.add_argument("--write", action="store_true",
                      help="run planned subjects through the generation graph and write seed files; "
                           "set/charm/combination need --out-dir and one of --answers or --endpoint")
    igen.add_argument("--sample-brief", dest="sample_brief", action="store_true",
                      help="print the first subject's assembled brief")
    igen.add_argument("--limit", type=int, default=0,
                      help="set/charm: plan only the first N subjects (0 = all). A small batch is "
                           "how a run is evaluated before the full population is committed to")
    igen.add_argument("--briefs-out", dest="briefs_out", default="",
                      help="set/charm: write the planned subjects and their assembled briefs to "
                           "this JSON file, for a model to answer")
    igen.add_argument("--answers", default="",
                      help="set/charm/combination --write: an authored-answer file keyed by subjectId (a list "
                           "of attempts per subject is legal — the graph's repair edge consumes "
                           "them in order). The deterministic path; mutually exclusive with "
                           "--endpoint in practice (--answers wins if both are given)")
    igen.add_argument("--out-dir", dest="out_dir", default="",
                      help="set/charm/combination --write: where the seed files land. Defaults to "
                           "the kind's production folder when SEEDSMITH_ALLOW_PRODUCTION_TREE=1 "
                           "(or --allow-production-tree). A path inside data/seed/items/ is refused "
                           "unless allow-production is on")
    igen.add_argument("--allow-production-tree", dest="allow_production_tree",
                      action="store_true",
                      help="set/charm/combination --write: permit an --out-dir inside "
                           "data/seed/items/. Also settable via SEEDSMITH_ALLOW_PRODUCTION_TREE=1")
    igen.add_argument("--endpoint", default="",
                      help="set/charm/combination --write: live model endpoint. Empty falls "
                           "through to SEEDSMITH_LLM_ENDPOINT in tools/seedsmith/.env")
    igen.add_argument("--mode", default="", choices=("api", "delegated"),
                      help="which authorer answers: api (default) or delegated. Delegated runs a "
                           "sub-agent that MAY edit the corpus, so it is never selected implicitly")
    igen.add_argument("--ledger", default="",
                      help="set/charm/combination --write: resume-ledger path (default: generator-specific "
                           "ledger inside --out-dir, so a sample never touches the real one)")
    igen.add_argument("--ignore-ledger", dest="ignore_ledger", action="store_true",
                      help="plan every generatable subject, even ones a previous run recorded")
    igen.add_argument("--retry-blocked", dest="retry_blocked", action="store_true",
                      help="re-plan only subjects ledgered as blocked/escalated; never re-run authored rows")
    igen.add_argument("--retry-label", dest="retry_label", default="",
                      help="combination: a short label for this re-run (e.g. 'widened-grants', "
                           "'r11-helm'), recorded in the still-blocked report's survivedReruns "
                           "history for any cell that answers blocked again")
    igen.add_argument("--model", default="unrecorded",
                      help="set/charm/combination --write: with --answers, metadata only — the model id "
                           "stamped into each seed file's _meta. With --endpoint, also the model "
                           "id sent on the live call (falls back to llm_caller's own default if "
                           "left unset)")
    igen.add_argument("--authored-utc", dest="authored_utc", default="1970-01-01T00:00:00Z",
                      help="set/charm/combination --write: the _meta timestamp. Injected, never read from the "
                           "clock — a wall-clock stamp is the one field that makes a generated "
                           "file non-reproducible (pipeline/provenance.py's own rule)")
    # ⛔ base-type/enhancement-milestone/recipe/drop-table, added 2026-09-08: each spec
    # (docs/architecture/item-seedgen/spec-*.md) already documented `items generate --kind <x>` as
    # the real invocation — none of the four were actually wired to it; each only had a private,
    # undocumented module path (e.g. `python -m seedsmith.adapters.items.basetypegen.run`). Every
    # flag below passes straight through to that module's own `main(argv)` (`cmd_items`'s own
    # dispatch, mirroring `cmd_effects`'s passthrough pattern for `--kind affix`) — `--write`/
    # `--endpoint`/`--model`/`--dry-run` above are reused as-is, not redeclared.
    igen.add_argument("--role", default="", help="base-type: one of core.v1.json's 15 role ids")
    igen.add_argument("--frame", default="", choices=("", "humanoid", "plant"),
                      help="base-type: the partition's frame")
    igen.add_argument("--band", default="", help="base-type: the partition's band letter")
    igen.add_argument("--slot", type=int, default=0,
                      help="drop-table: which of the 4 frozen partition slots (1-4)")
    igen.add_argument("--theme", default="",
                      help="base-type/enhancement-milestone/recipe/drop-table: an optional theme "
                           "hint in the brief")
    igen.add_argument("--count", type=int, default=None,
                      help="base-type/enhancement-milestone/recipe/drop-table: how many new "
                           "entries to draw this run. Left unset, each module keeps its OWN "
                           "default (1 for base-type/enhancement-milestone/drop-table; 0 == "
                           "reconcile-only for recipe) — this flag is never forced to a shared "
                           "default that would silently override that")
    igen.add_argument("--overwrite", "--force", default="",
                      help="base-type/enhancement-milestone/recipe/drop-table: comma-separated "
                           "draw ids to regenerate, or the literal 'all'. combination: "
                           "comma-separated entry ids ('combo.splice-x-y') or subject ids "
                           "('combination-splice-x-y'), or 'all'")
    igen.add_argument("--backfill", action="store_true",
                      help="recipe only: mint any missing container (forge) target before writing")
    igen.add_argument("--group", default="",
                      help="affix-family only: e.g. 'g.armour' — must have a shipped partition "
                           "file already")
    igen.add_argument("--affix-kind", dest="affix_kind", default="",
                      help="affix-family only: the family's fixed kindId, e.g. 'stat.modify' — "
                           "distinct from this command's own --kind, which selects which "
                           "generator runs at all")
    igen.add_argument("--max-name-attempts", dest="max_name_attempts", type=int, default=None,
                      help="material only: how many times a subject whose NAME collided with an existing "
                           "entry is re-asked, each retry quoting the collision the gate reported. Omitted "
                           "means the generator's own default (3) applies. This is the only knob that "
                           "moves the re-emit yield, and it was unreachable from here until 2026-09-28: "
                           "the flag existed on the generator's own parser and nothing forwarded it, so "
                           "an operator watching the refusal budget trip had no lever. `0` disables the "
                           "re-ask entirely, which is how the pre-fix behaviour is reproduced.")
    igen.add_argument("--max-consecutive-call-failures", dest="max_consecutive_call_failures",
                      type=int, default=None,
                      help="material only: stop calling after this many subjects fail back to back "
                           "(0 = never stop). Forwarded for the same reason as --max-name-attempts: the "
                           "generator has had this bound since 2026-09-08 and it was unreachable through "
                           "this command, so a wedged endpoint could not be bounded from the CLI.")
    ivalidate = items_sub.add_parser(
        "validate", help="pre-flight dependency checks over the real corpus (module 21)")
    ivalidate.add_argument("--deps", action="store_true",
                           help="combination: confirm every hostRole/ingredients family a run "
                                "could request resolves against real content, before any subject "
                                "is planned (acceptance 3a, spec-combination-write-unblock.md)")
    ifill = items_sub.add_parser(
        "fill",
        help="resume/fill missing item corpus subjects across kinds (uses .env for endpoint/"
             "production out-dirs; --dry-run plans only; requires --limit or --full for "
             "set/charm/combination)")
    ifill.add_argument("--dry-run", dest="dry_run", action="store_true",
                       help="print the dependency-ordered work plan; make no model calls")
    ifill.add_argument("--kinds", default="",
                       help="comma-separated kind filter (default: all fill kinds in map order)")
    ifill.add_argument("--limit", type=int, default=0,
                       help="set/charm/combination: plan only the first N subjects (required "
                            "unless --full; also bounds each --full checkpoint when supplied")
    ifill.add_argument("--count", type=int, default=None,
                       help="base-type/enhancement-milestone/recipe/drop-table draws per step "
                            "(default 1; under --full without this flag, uses an elevated pass)")
    ifill.add_argument("--batch-size", dest="batch_size", type=int, default=None,
                       help="gem: subjects per partition step (default 1; under --full without "
                            "this flag, drains remaining unauthored families in the slot)")
    ifill.add_argument("--max-partitions", dest="max_partitions", type=int, default=1,
                       help="cap discovered affix/base-type/gem/drop-table jobs (default 1; "
                            "ignored under --full)")
    ifill.add_argument("--full", action="store_true",
                       help="unbounded closed grids + all discovered partitions; open kinds "
                            "drain/elevated pass unless --count/--batch-size set (explicit opt-in)")
    ifill.add_argument("--allow-production-tree", dest="allow_production_tree",
                       action="store_true",
                       help="permit data/seed/items/ writes for set/charm/combination (also "
                            "SEEDSMITH_ALLOW_PRODUCTION_TREE=1)")
    ifill.add_argument("--continue-on-error", dest="continue_on_error", action="store_true",
                       help="keep walking after a refused/gap/error step (default: stop)")
    ifill.add_argument("--no-validate-deps", dest="validate_deps", action="store_false",
                       help="skip the combination deps preflight before fill")
    ifill.add_argument("--verify", action="store_true",
                       help="after generation, run the full items health gate; non-zero means "
                            "the corpus still has unresolved gaps")
    ifill.set_defaults(validate_deps=True)
    irepair = items_sub.add_parser(
        "repair-sets", help="bind legacy set members to existing base types (dry-run by default)")
    irepair.add_argument("--write", action="store_true",
                         help="apply the idempotent member-binding migration")
    irepair.add_argument("--allow-production-tree", dest="allow_production_tree",
                         action="store_true",
                         help="permit writes under data/seed/items/")
    irepair.add_argument("--sets-dir", default="",
                         help="set partition directory (default data/seed/items/sets)")
    irepair.add_argument("--base-types-dir", default="",
                         help="base-type directory (default data/seed/items/base-types)")
    ispecies = items_sub.add_parser(
        "repair-species",
        help="join speciesId onto every shipped set entry from the theme registry (dry-run by default)")
    ispecies.add_argument("--write", action="store_true",
                          help="apply the idempotent speciesId join")
    ispecies.add_argument("--allow-production-tree", dest="allow_production_tree",
                          action="store_true", help="permit writes under data/seed/items/")
    ispecies.add_argument("--sets-dir", default="",
                          help="set partition directory (default data/seed/items/sets)")
    isetclass = items_sub.add_parser(
        "repair-set-class",
        help="resolve setClass for every shipped set entry from its own declared topology "
             "(dry-run by default)")
    isetclass.add_argument("--write", action="store_true",
                           help="apply the idempotent setClass resolution")
    isetclass.add_argument("--allow-production-tree", dest="allow_production_tree",
                           action="store_true", help="permit writes under data/seed/items/")
    isetclass.add_argument("--sets-dir", default="",
                           help="set partition directory (default data/seed/items/sets)")

    iroles = items_sub.add_parser(
        "repair-set-roles",
        help="re-place set member rows still on a role D30 dropped from the hybrid core "
             "(dry-run by default; ISG-gap-1)")
    iroles.add_argument("--write", action="store_true",
                        help="apply the idempotent hybrid-role re-placement")
    iroles.add_argument("--allow-production-tree", dest="allow_production_tree",
                        action="store_true", help="permit writes under data/seed/items/")
    iroles.add_argument("--sets-dir", default="",
                        help="set partition directory (default data/seed/items/sets)")

    iledger = items_sub.add_parser(
        "repair-ledger",
        help="drop run-ledger rows whose emitted set row is not on disk, so subjects the ledger claims "
             "but never wrote become schedulable again (dry-run by default)")
    iledger.add_argument("--write", action="store_true",
                         help="drop the stale rows (irreversible from the ledger's own contents)")
    iledger.add_argument("--allow-production-tree", dest="allow_production_tree",
                         action="store_true", help="permit writes under data/seed/items/")
    iledger.add_argument("--sets-dir", default="",
                         help="set partition directory (default data/seed/items/sets)")
    iledger.add_argument("--ledger", default="",
                         help="run-ledger path (default data/seed/items/sets/set-charm-gen.ledger.json)")

    ireemit = items_sub.add_parser(
        "combogen-reemit",
        help="re-emit the shipped combination corpus from the run ledger (no model call; SSH7.4)")
    ireemit.add_argument("--dry-run", action="store_true",
                         help="print the plan and write nothing (the default)")
    ireemit.add_argument("--write", action="store_true", help="write the re-emitted corpus back")
    ireemit.add_argument("--shape", choices=("strain", "splice", "both"), default="both",
                         help="which partition to re-emit (default both)")
    ireemit.add_argument("--out-dir", default="", help="combinations directory (default data/seed/items/combinations)")
    ireemit.add_argument("--ledger", default="", help="run-ledger path (default beside the corpus)")
    ireemit.add_argument("--authored-utc", dest="authored_utc", default="1970-01-01T00:00:00Z",
                         help="the deterministic _meta timestamp")

    ibudget = items_sub.add_parser(
        "combo-budget",
        help="print the power-vs-price report for the shipped combinations (strain-splice-host SSH6.4)")
    ibudget.add_argument("--report", action="store_true",
                         help="print the per-frame geometry readings and per-cell verdicts")
    ibudget.add_argument("--items-dir", default="",
                         help="items root (default data/seed/items)")
    inames = items_sub.add_parser(
        "repair-names", help="rename persisted duplicate set/charm names (dry-run by default)")
    _add_repair_names_arguments(inames)
    igrammar = items_sub.add_parser(
        "repair-name-grammar",
        help="rename names ItemSeedValidator reports as failing the naming grammar, across every "
             "item kind (dry-run by default)")
    _add_repair_names_arguments(igrammar)
    imaterials = items_sub.add_parser(
        "repair-materials", help="rename persisted duplicate material names (dry-run by default)")
    _add_repair_names_arguments(imaterials)
    icharms = items_sub.add_parser(
        "repair-charms", help="rename persisted duplicate charm names (dry-run by default)")
    _add_repair_names_arguments(icharms)
    imigrate = items_sub.add_parser(
        "combogen-migrate",
        help="report or run combogen.migrate's socket-word retirement (module 21)")
    imigrate.add_argument("--dry-run", dest="dry_run", action="store_true",
                          help="reports the legality/migration-sites check, writes and deletes "
                               "nothing")
    imigrate.add_argument("--write", action="store_true",
                          help="delete data/seed/items/socket-words/sockwords.json and record the "
                               "retirement in a run ledger beside it. Deterministic and idempotent "
                               "(SSH2.3) -- a VERB, called for real only once the full combination "
                               "corpus exists to replace the 25 legacy entries (SSH2.6)")
    items.set_defaults(func=cmd_items)

    effects = sub.add_parser("effects", help="effect-pipeline generation entrypoints")
    effects_sub = effects.add_subparsers(dest="effects_command", required=True)
    gen = effects_sub.add_parser("generate", help="generate content for an effect-pipeline kind")
    gen.add_argument("--kind", default="affix")
    gen.add_argument("--only", default="", help="comma-separated atom ids narrowing the eligible pool (--kind affix)")
    gen.add_argument("--theme", default="", help="optional theme hint in the brief (--kind affix)")
    gen.add_argument("--count", type=int, default=0, help="how many independent bundles to draw (--kind affix)")
    gen.add_argument("--dry-run", dest="dry_run", action="store_true")
    gen.add_argument("--workers", type=int, default=0)
    gen.add_argument("--endpoint", default="")
    gen.add_argument("--model", default="")
    gen.add_argument("--mode", default="", choices=("api", "delegated"),
                     help="which authorer answers: api (default) or delegated. Delegated is never "
                          "selected implicitly")
    gen.add_argument(
        "--species-id", default="",
        help="task J7: author into affix.species.<speciesId>.* / "
             "data/seed/effects/affixes/species/<speciesId>.json instead of the shared corpus "
             "(--kind affix)")
    effects.set_defaults(func=cmd_effects)

    structures = sub.add_parser("structures", help="base-defense structure corpus entrypoints (module 23+)")
    structures_sub = structures.add_subparsers(dest="structures_command", required=True)
    structures_contract = structures_sub.add_parser(
        "contract", help="the structure anchor JSON Schema — print or numerically audit it")
    structures_contract.add_argument("--print", dest="print_schema", action="store_true",
                                     help="print the resolved JSON Schema")
    structures_contract.add_argument("--audit", action="store_true",
                                     help="run the numeric-smuggling audit, exit 1 on a finding (default)")
    structures.set_defaults(func=cmd_structures)

    trees = sub.add_parser("trees", help="passive-tree plan entrypoints (task B1, spec-tree-plan.md)")
    trees_sub = trees.add_subparsers(dest="trees_command", required=True)
    trees_plan = trees_sub.add_parser("plan", help="emit or check the deterministic tree plan")
    trees_plan.add_argument("--emit", action="store_true", help="write the plan (default if no flag given)")
    trees_plan.add_argument("--check", action="store_true",
                            help="regenerate in memory and diff against the committed plan")
    trees_plan.add_argument("--tree", default=None,
                            help="tree id to plan — any of the 12 primary trees named by the roster, "
                                 "or (J1) any of the roster's elemental or status tree ids "
                                 "(default: might for a single-tree emit; omitted entirely means "
                                 "every roster tree for --manifest)")
    trees_plan.add_argument("--manifest", action="store_true",
                            help="operate on the top-level manifest (plan.v1.json) + its trees[], "
                                 "not just --tree alone (task C2)")
    trees_plan.add_argument("--generate", action="store_true",
                            help="R-G1: ask stage 2 to generate content for --tree; exits 3 naming "
                                 "the tree and gate quantity if its gateState is 'pending' (task C2). "
                                 "tree-language (H1) is not built yet, so a 'carrier' tree still "
                                 "generates nothing here beyond passing the gate.")
    trees_plan.add_argument("--diff", nargs=2, metavar=("PLAN_A", "PLAN_B"),
                            help="compare two manifests: budget deltas, archetype reassignments, "
                                 "quota-cell moves, and node ids added/removed/re-minted (task C2)")
    trees_generate = trees_sub.add_parser(
        "generate", help="generate node content for a tree, or print the run's gate report "
                         "(task H2, spec-tree-language.md)")
    trees_generate.add_argument("--tree", default="", help="a single tree id")
    trees_generate.add_argument("--all", action="store_true", help="every tree with a committed plan")
    trees_generate.add_argument(
        "--node", default="",
        help="restrict a --write --supersede run to ONE node id (ip-censor T16/IC-4.1): only that "
             "subject is (re-)generated and only its ledger row superseded. Without it the run is "
             "unchanged (every stale subject is superseded). A --node id that is not a subject of "
             "the named tree is refused by name")
    trees_generate.add_argument("--dry-run", dest="dry_run", action="store_true",
                                help="the default and currently the only mode — assemble subjects "
                                     "and print the gate report, make no model calls")
    trees_generate.add_argument("--write", action="store_true",
                                help="real generation — refused unless the registry carries "
                                     "exactly one PassiveTree/* gates=True metric (§7.1)")
    trees_generate.add_argument("--sample-brief", dest="sample_brief", action="store_true",
                                help="render one real brief against the first subject's own "
                                     "resolved quota cell and permitted affix subset")
    trees_generate.add_argument("--plan-root", dest="plan_root", default="",
                                help="override the seed root the committed plan is read under, "
                                     "i.e. <root>/passive-tree/plan (default data/seed)")
    trees_generate.add_argument("--ledger-path", dest="ledger_path", default="",
                                help="override the idempotence ledger path --write reads/writes "
                                     "(default data/seed/passive-tree/_runs/tree-language.ledger.json) "
                                     "— tests point this at a temp file so a CLI wiring test never "
                                     "touches the real ledger. --write's emitted seed documents "
                                     "(data/seed/passive-tree/nodes/<treeId>.json) follow "
                                     "--plan-root, the same seed root the committed plan is read "
                                     "under, for the identical reason")
    trees_generate.add_argument("--workers", type=int, default=1,
                                help="parallel model-call workers WITHIN a (tier, nodeClass) batch "
                                     "only — batches themselves stay sequential so a later one still "
                                     "sees every earlier one's real accepted tier-siblings (§6.2). "
                                     "Default 1 = sequential, byte-identical to pre-2026-09-06 "
                                     "behaviour. Mirrors workflow.runner.MAX_WORKERS=4's own "
                                     "rationale for a local model queue, but cannot reuse that helper "
                                     "directly (it is built around a LangGraph app.invoke() interface "
                                     "this pipeline never adopted)")
    trees_generate.add_argument(
        "--supersede", action="store_true",
        help="--write companion: re-generate ledger rows whose per-record promptVersion is absent "
             "or differs from the current brief vintage (brief.PROMPT_VERSION), preserving the "
             "prior row under supersededRecord (spec-tree-review.md §8's provenance-supersede "
             "pass). Without it, already-done subjects are replayed from the ledger, never "
             "re-rolled")
    trees_review = trees_sub.add_parser(
        "review", help="tree-review entrypoints (task H7, spec-tree-review.md §5.5, §Commands)")
    trees_review.add_argument("--lot", required=True, help="the review lot id")
    trees_review.add_argument(
        "--census", action="store_true",
        help="refuse to start a census without a CURRENT sheetRead row (§5.5) — the only mode "
             "wired today; the census tiers themselves are H8+ and unbuilt")
    trees_review.add_argument(
        "--sheet-dir", dest="sheet_dir", default="",
        help="override where <lot>/sheet.json is read from (default "
             "docs/research/passive-tree/_review)")
    trees_review.add_argument(
        "--review-dir", dest="review_dir", default="",
        help="override where <lot>.json's sheetReads/entries are read from (default "
             "data/seed/passive-tree/_review)")
    trees_census = trees_sub.add_parser(
        "census", help="print the passive-tree distribution, not an aggregate (task P0.1, "
                       "tasks/passive-tree-repair-plan.md §1)")
    trees_census.add_argument("--json", action="store_true",
                              help="emit the full census as JSON (per-tree rows included)")
    trees_census.add_argument("--tree", default="", help="a single tree id (default: every planned tree)")
    trees_census.add_argument("--seed-root", dest="seed_root", default="",
                              help="override the seed root the committed plan/nodes are read under "
                                   "(default data/seed)")
    trees_census.add_argument("--out-root", dest="out_root", default="",
                              help="override where tree-binder's bound reports are read from "
                                   "(default data/generated/passive-tree)")
    trees.set_defaults(func=cmd_trees)

    numerics = sub.add_parser(
        "numerics", help="tier-bands tuning entrypoints (spec-numerics.md §3.1, §3.2)")
    numerics_sub = numerics.add_subparsers(dest="numerics_command", required=True)
    nrebalance = numerics_sub.add_parser(
        "rebalance",
        help="apply channelWeight/baseShare overrides to the latest tier-bands and, with "
             "--publish, write the next version")
    nrebalance.add_argument("--set", dest="set_pairs", action="append", default=None,
                            metavar="KEY=VALUE",
                            help="channelWeight.<id>=<ratio> or baseShare=<ratio>, repeatable "
                                 "(ratio, not per-mille: 1.0 == 1000‰)")
    nrebalance.add_argument("--set-file", dest="set_file", default="", metavar="PATH",
                            help="a file of KEY=VALUE lines (# comments allowed) — the reviewable "
                                 "form of a large --set batch")
    nrebalance.add_argument("--publish", action="store_true",
                            help="write tier-bands.v{n+1}.json; the old version stays for revert")
    nrebalance.set_defaults(func=cmd_numerics)

    dungeon = sub.add_parser("dungeon", help="Delve corpus generation entrypoints (narrative-seed NS13)")
    dungeon_sub = dungeon.add_subparsers(dest="dungeon_command", required=True)
    dungeon_events = dungeon_sub.add_parser("events", help="legacy Delve event entrypoints")
    dungeon_events_sub = dungeon_events.add_subparsers(dest="dungeon_events_command", required=True)
    regen = dungeon_events_sub.add_parser(
        "regen",
        help="regenerate the committed legacy Delve events under their own ids (NS13)")
    stage = regen.add_mutually_exclusive_group()
    stage.add_argument("--dry-run", dest="dry_run", action="store_true",
                       help="print the plan's base and worst call bounds and touch nothing (default)")
    stage.add_argument("--write", action="store_true",
                       help="draw every planned event with the RESOLVED config into a scratch run file; "
                            "the corpus is never touched here")
    stage.add_argument("--review", action="store_true",
                       help="print the seeded, stratified review sample for the run")
    stage.add_argument("--commit", action="store_true",
                       help="write only the run's ACCEPTED events through the committer")
    regen.add_argument("--ids", default="",
                       help="comma-separated committed event ids narrowing the batch")
    regen.add_argument("--run", dest="run_id", default="",
                       help="the scratch run id (default: the newest run file)")
    regen.add_argument("--accept", action="append", default=None, metavar="EVENT_ID",
                       help="record an accept verdict for the run; repeatable")
    regen.add_argument("--reject", action="append", default=None, metavar="EVENT_ID=REASON",
                       help="record a reject verdict with its reason; repeatable")
    regen.add_argument("--events-dir", dest="events_dir", default="",
                       help="override the committed events tree")
    regen.add_argument("--runs-dir", dest="runs_dir", default="",
                       help="override the scratch run directory")
    dungeon.set_defaults(func=cmd_dungeon)

    narrative = sub.add_parser("narrative",
                              help="narrative corpus entrypoints (narrative-seed NS15/NS16)")
    narrative_sub = narrative.add_subparsers(dest="narrative_command", required=True)
    ngloss = narrative_sub.add_parser("gloss", help="motif gloss entrypoints")
    ngloss_sub = ngloss.add_subparsers(dest="gloss_command", required=True)
    nfill = ngloss_sub.add_parser("fill", help="gloss every motif that has no gloss (model calls)")
    nfill_stage = nfill.add_mutually_exclusive_group()
    nfill_stage.add_argument("--dry-run", dest="dry_run", action="store_true",
                             help="report the chunk and call count and make no call (default)")
    nfill_stage.add_argument("--write", action="store_true",
                             help="gloss for real with the RESOLVED config into a scratch run file; "
                                  "the registry is never touched here")
    nfill.add_argument("--limit", type=int, default=0, help="bound the run to N chunks (0 = all)")
    nfill.add_argument("--regenerate", action="append", default=None, metavar="MOTIF",
                       help="re-gloss this motif even though the registry has a row; repeatable")
    nfill.add_argument("--runs-dir", dest="runs_dir", default="",
                       help="override the scratch run directory")
    ncommit = ngloss_sub.add_parser("commit", help="write the run's glosses into the registry")
    ncommit.add_argument("--run", dest="run_id", default="",
                         help="the fill run id (default: the newest run file)")
    ncommit.add_argument("--accept", action="append", default=None, metavar="MOTIF",
                         help="record an accept verdict; repeatable")
    ncommit.add_argument("--reject", action="append", default=None, metavar="MOTIF=REASON",
                         help="record a reject verdict with its reason; repeatable")
    ncommit.add_argument("--registry", default="", help="override the gloss registry path")
    ncommit.add_argument("--runs-dir", dest="runs_dir", default="",
                         help="override the scratch run directory")
    npreflight = narrative_sub.add_parser(
        "preflight", help="prove the endpoint honours the chunk schema with ONE call")
    npreflight.set_defaults(func=cmd_narrative)
    narrative.set_defaults(func=cmd_narrative)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # `--mode` becomes PROCESS CONFIG at the CLI boundary, rather than being threaded as an
    # argument through every subcommand that re-parses argv. Six of the authoring subcommands
    # dispatch by handing a reconstructed `passthrough` list to a child module's own `main()`
    # (theme_enrich, generate_commander_effects, materialgen, basetypegen, gemgen,
    # consumablegen, recipegen, generate_affixes), and each of those children had its own
    # `--endpoint`/`--model` but no `--mode` — so forwarding the flag alone would have made
    # argparse reject it. An audit found the consequence: `--mode delegated` was ACCEPTED on four
    # subcommands and then silently discarded, which is a broken promise even though it fails in
    # the safe direction. Setting the environment variable here reaches every child, including
    # grandchildren, through the config chain `resolve_live_transport` already reads.
    #
    # Only ever set, never defaulted: an absent flag leaves the process environment alone, so
    # nothing here can turn a run into a delegated one.
    mode = (getattr(args, "mode", "") or "").strip()
    if mode:
        os.environ["SEEDSMITH_LLM_MODE"] = mode
    return args.func(args)
