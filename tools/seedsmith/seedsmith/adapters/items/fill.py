"""seedsmith.adapters.items.fill — cross-kind resume/fill driver for `items fill`.

Walks item kinds in item-seedgen-map dependency order. Closed grids (set/charm/combination/
material) run once with `--write` and rely on RunLedger resume. Partitioned kinds walk
*discovered* corpus partitions only — never invent a new (role,frame,band) / slot / group.
Gem slots are destinations for one global unauthored-family pool, so a fill walk schedules that
pool once rather than duplicating it for every gN file.

Batch controls (`--limit` / `--count` / `--batch-size` / `--max-partitions` / `--full`) exist so a
first live run can stay small; unbounded set/charm/combination without `--limit` or `--full` is
refused at plan time.

Under bare `--full`, set/charm are dispatched in bounded internal checkpoints and reconciled until
their finite plans are exhausted; this is an orchestration detail, not a reduction of full scope.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .defaults import FILL_KIND_ORDER, ITEM_SEED_ROOT

DispatchFn = Callable[[list[str]], int]

#: Kinds that write under gk-data/packs/fusion/data/seed/items/ via --out-dir (need allow-production).
PRODUCTION_KINDS = frozenset({"set", "charm", "combination"})

#: Closed grids that explode without --limit unless --full.
BOUNDED_GRID_KINDS = frozenset({"set", "charm", "combination"})

#: Hard edges from item-seedgen-map.md §3 (kind → must precede these dependents).
#: Used by topo tests; FILL_KIND_ORDER must be a valid linearization.
MAP_DEPENDENCY_EDGES: "tuple[tuple[str, str], ...]" = (
    ("affix-family", "base-type"),
    ("enhancement-milestone", "base-type"),
    ("material", "recipe"),
    ("material", "drop-table"),
    ("gem", "combination"),
    ("gem", "drop-table"),
    ("consumable", "drop-table"),
    ("base-type", "set"),
    ("base-type", "charm"),
    ("base-type", "recipe"),
    ("base-type", "combination"),
    ("base-type", "drop-table"),
)


@dataclass
class FillLimits:
    """Batch bounds for one fill invocation."""

    limit: int = 0          # set/charm/combination subjects (0 = refuse unless full)
    count: int = 1          # base-type / milestone / recipe / drop-table draws
    batch_size: int = 1     # gem partition batch
    max_partitions: int = 1  # cap discovered partition jobs (0 = all when full)
    full: bool = False      # unbounded closed grids + all partitions
    # When --full and the operator did not pass --count / --batch-size, open kinds drain
    # (gem: remaining unauthored families) or use an elevated pass size (open-ended draws).
    count_explicit: bool = False
    batch_size_explicit: bool = False


#: Open-ended generators (base-type / milestone / drop) have no corpus "empty"; under
#: --full without an explicit --count, one meaningful pass is this many draws per step.
_FULL_OPEN_PASS = 8

# Full set/charm walks are still finite but can contain hundreds of model calls. Keep each
# dispatch resumable and observable; an explicit ``--limit`` remains the operator's override.
_FULL_GRID_CHECKPOINT = 10

#: Upper probe for gem unauthored-family drain under --full (pool is closed and far smaller).
_GEM_DRAIN_PROBE = 50_000


def _effective_open_count(limits: FillLimits) -> int:
    if limits.full and not limits.count_explicit:
        return _FULL_OPEN_PASS
    return max(limits.count, 1)


def _gem_remaining(slot: int) -> int:
    """How many unauthored gem families remain for this slot (0 = nothing to draw)."""
    from .gemgen.run import plan_partition
    try:
        plan = plan_partition(f"gems/{slot}", batch_size=_GEM_DRAIN_PROBE)
        return len(plan.subjects)
    except Exception:
        return -1  # unknown — treat as has work


def _effective_gem_batch(limits: FillLimits, slot: int) -> int:
    if limits.full and not limits.batch_size_explicit:
        remaining = _gem_remaining(slot)
        return max(remaining, 1) if remaining else 1
    return max(limits.batch_size, 1)


@dataclass
class FillStep:
    kind: str
    argv: "list[str]"
    note: str = ""
    seq: int = 0  # stable discovery order within a kind


@dataclass
class FillStepResult:
    kind: str
    argv: "list[str]"
    status: str  # planned | ran | skipped | escalated | refused | gap | error
    exit_code: int = 0
    note: str = ""


@dataclass
class FillReport:
    dry_run: bool
    refused_reason: str = ""
    steps: "list[FillStepResult]" = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dryRun": self.dry_run,
            "refusedReason": self.refused_reason or None,
            "steps": [asdict(s) for s in self.steps],
        }

    @property
    def worst_exit_code(self) -> int:
        from ...report.cli import (EXIT_CANNOT_RUN, EXIT_CLEAN, EXIT_ESCALATED, EXIT_GAP,
                                   EXIT_REFUSED)
        if self.refused_reason:
            return EXIT_REFUSED
        codes = [s.exit_code for s in self.steps
                 if s.status in ("escalated", "refused", "gap", "error")]
        if not codes:
            return EXIT_CLEAN
        if EXIT_REFUSED in codes:
            return EXIT_REFUSED
        if EXIT_CANNOT_RUN in codes:
            return EXIT_CANNOT_RUN
        if EXIT_GAP in codes or any(c == 1 for c in codes):
            return EXIT_GAP
        if EXIT_ESCALATED in codes:
            return EXIT_ESCALATED
        return max(codes)


def generation_completion(*, kinds: "tuple[str, ...] | None" = None) -> dict:
    """Reconcile the finite fill populations after a walk.

    Generator exit code only says that the scheduled batch ran without a refusal.  It does not
    say that a closed population has no held subjects left.  Keep this check deterministic and
    model-free: read the same production ledgers that the CLI write path uses, then expose the
    pending/held counts and zero-tolerance identity debt which make a resume genuinely complete
    (or explain why it is not).

    Open-ended draw kinds are intentionally omitted.  ``--full`` gives those kinds one elevated
    pass; they have no finite exhaustion condition (see spec-fill-runner.md).
    """
    from . import defaults
    from .combogen import authored as combo_authored
    from .combogen import run as combo_run
    from .combogen import supply as combo_supply
    from .combogen import tuning as combo_tuning
    from .setgen import run as set_run
    from .setgen import tuning as set_tuning
    from .setgen import vocab as set_vocab
    from ...pipeline.run_ledger import RunLedger

    selected = set(kinds) if kinds is not None else set(defaults.FILL_KIND_ORDER)
    checks: list[dict] = []
    exact_duplicate_names = _set_charm_exact_duplicate_count() if selected & {"set", "charm"} else 0

    if selected & {"set", "charm"}:
        tuning = set_tuning.load()
        vocabulary = set_vocab.build(tuning)
        if "set" in selected:
            for population in ("species", "build"):
                out = Path(defaults.default_out_dir("set"))
                ledger = set_run.read_ledger(out / "set-charm-gen.ledger.json")
                plan = set_run.plan_run(
                    kind="set", population=population, tuning=tuning, vocabulary=vocabulary,
                    ledger=ledger)
                checks.append({
                    "kind": "set", "population": population,
                    "toGenerate": len(plan.subjects), "held": len(plan.held),
                    "ledgered": len(ledger),
                    "heldByReason": plan.summary()["heldByReason"],
                    "exactDuplicateNames": exact_duplicate_names,
                    "complete": plan.complete and exact_duplicate_names == 0,
                })
        if "charm" in selected:
            out = Path(defaults.default_out_dir("charm"))
            ledger = set_run.read_ledger(out / "set-charm-gen.ledger.json")
            plan = set_run.plan_run(
                kind="charm", population="species", tuning=tuning, vocabulary=vocabulary,
                ledger=ledger)
            placeholders = sum(
                1 for row in ledger.values()
                if isinstance(row, dict) and "(axis-group)-NNN" in str(row.get("entryId", ""))
            )
            terminal = sum(
                1 for row in ledger.values()
                if isinstance(row, dict) and row.get("outcome") in {"blocked", "escalated"}
            )
            checks.append({
                "kind": "charm", "population": "species",
                "toGenerate": len(plan.subjects), "held": len(plan.held),
                "ledgered": len(ledger), "terminalLedgered": terminal,
                "placeholderLedgered": placeholders,
                "heldByReason": plan.summary()["heldByReason"],
                "exactDuplicateNames": exact_duplicate_names,
                "complete": plan.complete and exact_duplicate_names == 0,
            })

    if "combination" in selected:
        tuning = combo_tuning.load()
        supply = combo_supply.build()
        out = Path(defaults.default_out_dir("combination"))
        ledger = RunLedger(out / combo_authored.DEFAULT_LEDGER_NAME)
        for shape in combo_run.SHAPES:
            plan = combo_run.plan_run(shape=shape, tuning=tuning, supply=supply)
            needing = combo_authored.plan_needing_work(plan, ledger)
            checks.append({
                "kind": "combination", "shape": shape,
                "toGenerate": len(needing), "held": 0,
                "heldByReason": {}, "complete": not needing,
            })

    if "gem" in selected:
        slots = discover_gem_slots()
        remaining = sum(max(_gem_remaining(slot), 0) for slot in slots)
        checks.append({
            "kind": "gem", "slots": slots, "toGenerate": remaining, "held": 0,
            "heldByReason": {}, "complete": bool(slots) and remaining == 0,
        })

    if "affix-family" in selected:
        jobs = discover_affix_family_jobs()
        runnable = [(g, k) for g, k in jobs if _affix_has_free_pairs(g, k)]
        checks.append({
            "kind": "affix-family", "partitions": len(jobs), "toGenerate": len(runnable),
            "held": 0, "heldByReason": {}, "complete": not runnable,
        })

    return {"complete": all(row["complete"] for row in checks), "checks": checks}


def _set_charm_exact_duplicate_count() -> int:
    """Count duplicate player-facing names across the two shared identity corpora.

    New batches reject this before writing, but old rows can predate that guard.  A completed
    ledger must not hide such a repair debt: the next fill cannot repair it by appending, and the
    operator needs an explicit name-repair pass rather than a false green completion report.
    """
    from .setgen import dedup

    names: dict[str, str] = {}
    for directory_name in ("sets", "charms"):
        directory = ITEM_SEED_ROOT / directory_name
        if not directory.is_dir():
            continue
        for path in directory.glob("*.json"):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if document.get("kind") not in {"set", "charm"}:
                continue
            for row in document.get("entries") or ():
                if not isinstance(row, dict):
                    continue
                entry_id, name = row.get("id"), row.get("name")
                if isinstance(entry_id, str) and isinstance(name, str) and name.strip():
                    names[entry_id] = name
    return len(dedup.dedup_report(names).exact_duplicates)


def discover_base_type_partitions(
        base_types_dir: Path | None = None) -> "list[tuple[str, str, str]]":
    """Every existing base-type partition, derived from entry fields not filename conventions."""
    from .basetypegen import partitions
    from .basetypegen.tuning import load_role_registry

    directory = base_types_dir or (ITEM_SEED_ROOT / "base-types")
    return partitions.discover(directory, legal_roles=frozenset(load_role_registry()))


def discover_drop_table_slots(drop_tables_dir: Path | None = None) -> "list[int]":
    directory = drop_tables_dir or (ITEM_SEED_ROOT / "drop-tables")
    slots: "list[int]" = []
    if not directory.is_dir():
        return slots
    for path in sorted(directory.glob("d*.json")):
        stem = path.stem
        if len(stem) >= 2 and stem[1:].isdigit():
            slots.append(int(stem[1:]))
    return slots


def discover_gem_slots(gems_dir: Path | None = None) -> "list[int]":
    directory = gems_dir or (ITEM_SEED_ROOT / "gems")
    slots: "list[int]" = []
    if not directory.is_dir():
        return slots
    for path in sorted(directory.glob("g*.json")):
        stem = path.stem
        if len(stem) >= 2 and stem[1:].isdigit():
            slots.append(int(stem[1:]))
    return slots


def discover_affix_family_jobs(
        families_dir: Path | None = None) -> "list[tuple[str, str]]":
    """`(group_id, kind_id)` pairs already present in shipped partition files.

    Only `stat.modify` / `stat.derived` — the only kinds affixfamgen authors
    (`opvocab.legal_ops` / spec-affix-families-gen Acceptance #3). Other kindIds in the
    corpus (e.g. `status.apply`) must not become fill jobs.
    """
    legal = frozenset({"stat.modify", "stat.derived"})
    directory = families_dir or (ITEM_SEED_ROOT / "affix-families")
    jobs: "list[tuple[str, str]]" = []
    if not directory.is_dir():
        return jobs
    seen: set[tuple[str, str]] = set()
    for path in sorted(directory.glob("g-*.json")):
        stem = path.stem
        if not stem.startswith("g-"):
            continue
        group_id = "g." + stem[2:]
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        kinds: set[str] = set()
        for entry in doc.get("entries", []):
            kid = entry.get("kindId") or entry.get("kind")
            if isinstance(kid, str) and kid in legal:
                kinds.add(kid)
        for kid in sorted(kinds):
            key = (group_id, kid)
            if key not in seen:
                seen.add(key)
                jobs.append(key)
    return jobs


def _cap_partitions(items: list, limits: FillLimits) -> list:
    if limits.full or limits.max_partitions <= 0:
        return items
    return items[: limits.max_partitions]


def _affix_has_free_pairs(group_id: str, affix_kind: str) -> bool:
    """True when the partition is below its registry target and has a free (channel, op).

    The mechanical free-pair check alone is insufficient: quarantined ``stat.derived`` groups can
    expose hundreds of registered channels while already exceeding the naming registry's ``~7``
    family budget.  Scheduling those partitions made ``items fill --full`` spend calls on content
    the survey had already classified as over-target.
    """
    from .affixfamgen import brief as affix_brief
    try:
        # Inspect the mechanical slot set directly. Building the model brief also validates the
        # schema and raises for a full partition; that terminal condition must not become a
        # runnable job merely because planning catches the exception.
        partition = affix_brief.load_partition_context(group_id)
    except Exception:
        # Unreadable / illegal kind — let the generate step surface the real refuse.
        return True
    if not affix_brief.free_channel_ops(partition, affix_kind):
        return False
    # Registry sizing is configuration, not model input. Let a malformed target fail the plan
    # loudly instead of treating it as permission to schedule an unbounded pass.
    return len(partition.existing_ids) < affix_brief.load_target_family_count()


def _gem_slot_has_work(slot: int, batch_size: int) -> bool:
    """True when gemgen plan_partition still has subjects for this slot."""
    remaining = _gem_remaining(slot)
    if remaining < 0:
        return True
    return remaining > 0


def plan_fill_steps(*, kinds: "tuple[str, ...] | None" = None,
                    allow_production: bool = True,
                    limits: FillLimits | None = None) -> "tuple[list[FillStep], str]":
    """Build argv lists. Returns `(steps, refuse_reason)` — refuse_reason non-empty means do not run.

    Stable within-kind order = discovery/append order (strain before splice). Cross-kind order =
    FILL_KIND_ORDER. Never sort by note string.
    """
    limits = limits or FillLimits()
    selected = set(kinds) if kinds is not None else set(FILL_KIND_ORDER)
    steps: "list[FillStep]" = []
    seq = 0
    open_count = _effective_open_count(limits)

    def want(kind: str) -> bool:
        return kind in selected

    def add(kind: str, argv: list[str], note: str = "") -> None:
        nonlocal seq
        steps.append(FillStep(kind=kind, argv=argv, note=note, seq=seq))
        seq += 1

    # Refuse unbounded closed grids unless --limit or --full.
    if selected & BOUNDED_GRID_KINDS and not limits.full and limits.limit <= 0:
        return [], (
            "items fill refused — set/charm/combination need --limit N (smoke) or --full "
            "(unbounded). A default fill without a bound is thousands of model calls.")

    if want("affix-family"):
        all_jobs = discover_affix_family_jobs()
        runnable = [(g, k) for g, k in all_jobs if _affix_has_free_pairs(g, k)]
        full_count = len(all_jobs) - len(runnable)
        jobs = _cap_partitions(runnable, limits)
        if not all_jobs:
            add("affix-family", [],
                "SKIPPED — no affix-family partition files with kindId to discover")
        elif not runnable:
            add("affix-family", [],
                "SKIPPED — every discovered affix partition has no free (channel, op)")
        else:
            for group_id, affix_kind in jobs:
                add("affix-family",
                    ["--kind", "affix-family", "--group", group_id,
                     "--affix-kind", affix_kind, "--write"],
                    f"group={group_id} affix-kind={affix_kind}")
            if full_count and limits.max_partitions > 0 and not limits.full:
                add("affix-family", [],
                    f"SKIPPED — {full_count} partition(s) have no free (channel, op)")

    if want("material"):
        add("material", ["--kind", "material", "--write"])

    if want("gem"):
        all_slots = discover_gem_slots()
        # Gem families are a single global vocabulary: ``unauthored_families`` excludes a family
        # found in *any* gN file, while the requested slot only chooses the destination file. Plan
        # one destination per fill walk, otherwise a full plan duplicates the same remaining pool
        # for every slot and later steps reconcile to zero after the first writer consumes it.
        runnable_slots = [s for s in all_slots if _gem_slot_has_work(s, limits.batch_size)]
        empty_count = len(all_slots) - len(runnable_slots)
        slots = _cap_partitions(runnable_slots, limits)
        if slots:
            slots = slots[:1]
        if not all_slots:
            add("gem", [], "SKIPPED — no gems/gN.json partitions discovered")
        elif not runnable_slots:
            add("gem", [],
                "SKIPPED — every gems/N partition alreadyDone (toGenerate=0)")
        else:
            for slot in slots:
                batch = _effective_gem_batch(limits, slot)
                # Outer `items generate` accepts shared `--count`; cli remaps to
                # gemgen `--batch-size`. Emitting `--batch-size` here makes
                # argparse SystemExit → refused.
                add("gem",
                    ["--kind", "gem", "--slot", str(slot),
                     "--count", str(batch), "--write"],
                    f"slot={slot} batch={batch}")
            if empty_count and limits.max_partitions > 0 and not limits.full:
                add("gem", [],
                    f"SKIPPED — {empty_count} slot(s) alreadyDone (toGenerate=0)")
            if len(runnable_slots) > 1:
                add("gem", [],
                    f"SKIPPED — {len(runnable_slots) - 1} slot(s) share the global unauthored-family pool; "
                    f"slot {slots[0]} owns this fill pass")

    if want("consumable"):
        add("consumable", ["--kind", "consumable"],
            "reconcile-only (pass --theme on generate to mint)")

    if want("enhancement-milestone"):
        add("enhancement-milestone",
            ["--kind", "enhancement-milestone", "--count", str(open_count), "--write"])

    if want("base-type"):
        parts = _cap_partitions(discover_base_type_partitions(), limits)
        if not parts:
            add("base-type", [], "SKIPPED — no base-types/*.json partitions discovered")
        for role, frame, band in parts:
            add("base-type",
                ["--kind", "base-type", "--role", role, "--frame", frame,
                 "--band", band, "--count", str(open_count), "--write"],
                f"{frame}/{role}/{band}")

    if want("set"):
        for population in ("species", "build"):
            argv = ["--kind", "set", "--population", population, "--write"]
            # An explicit --limit remains a deliberate checkpoint even under --full.  This keeps
            # the full walk resumable in bounded model-call batches; omitting it retains the
            # unbounded drain semantics.
            if limits.limit > 0:
                argv += ["--limit", str(limits.limit)]
            if allow_production:
                argv.append("--allow-production-tree")
            add("set", argv, f"population={population}")

    if want("charm"):
        argv = ["--kind", "charm", "--population", "species", "--write"]
        if limits.limit > 0:
            argv += ["--limit", str(limits.limit)]
        if allow_production:
            argv.append("--allow-production-tree")
        add("charm", argv, "population=species")

    if want("recipe"):
        # recipegen's specified default is a no-model vocabulary/reference reconciliation.  A
        # broad fill has no approved forge-coverage target or partition scope, so forcing an
        # open-ended draw here only produces arbitrary mutation recipes and cannot make more base
        # types forgeable.  Targeted recipe authoring remains the explicit generate command.
        add("recipe", ["--kind", "recipe"],
            "reconcile only — targeted recipe generation requires an approved forge coverage plan")

    if want("combination"):
        for shape in ("strain", "splice"):  # strain first — never lexicographic note sort
            argv = ["--kind", "combination", "--shape", shape, "--write"]
            if limits.limit > 0:
                argv += ["--limit", str(limits.limit)]
            if allow_production:
                argv.append("--allow-production-tree")
            add("combination", argv, f"shape={shape}")

    if want("drop-table"):
        slots = _cap_partitions(discover_drop_table_slots(), limits)
        if not slots:
            add("drop-table", [], "SKIPPED — no drop-tables/dN.json partitions discovered")
        for slot in slots:
            add("drop-table",
                ["--kind", "drop-table", "--slot", str(slot),
                 "--count", str(open_count), "--write"],
                f"slot={slot}")

    # Cross-kind order only — within-kind order is append/seq (stable).
    order_index = {k: i for i, k in enumerate(FILL_KIND_ORDER)}
    steps.sort(key=lambda s: (order_index.get(s.kind, 99), s.seq))
    return steps, ""


def run_fill(*, kinds: "tuple[str, ...] | None" = None, dry_run: bool = False,
             allow_production: bool = True,
             limits: FillLimits | None = None,
             dispatch: DispatchFn | None = None,
             stop_on_error: bool = True) -> FillReport:
    """Execute (or print) the fill plan. `dispatch` receives argv after `items generate`."""
    from ...report import cli as cli_mod

    report = FillReport(dry_run=dry_run)
    limits = limits or FillLimits()
    steps, refuse = plan_fill_steps(
        kinds=kinds, allow_production=allow_production, limits=limits)
    if refuse:
        report.refused_reason = refuse
        return report

    def default_dispatch(argv: list[str]) -> int:
        args = cli_mod.build_parser().parse_args(["items", "generate", *argv])
        return cli_mod.cmd_items(args)

    run = dispatch or default_dispatch
    stop_statuses = frozenset({"refused", "gap", "error"})

    for step in steps:
        if not step.argv:
            report.steps.append(FillStepResult(
                kind=step.kind, argv=[], status="skipped", note=step.note))
            continue
        checkpointed = limits.full and limits.limit <= 0 and step.kind in {
            "set", "charm", "combination"
        }
        checkpoint_argv = (step.argv + ["--limit", str(_FULL_GRID_CHECKPOINT)]
                           if checkpointed else step.argv)
        if dry_run:
            report.steps.append(FillStepResult(
                kind=step.kind, argv=checkpoint_argv, status="planned",
                note=(step.note + "; " if step.note else "")
                     + (f"internal checkpoint={_FULL_GRID_CHECKPOINT}" if checkpointed else "")))
            continue
        previous_remaining: "int | None" = None
        while True:
            if checkpointed:
                current = generation_completion(kinds=(step.kind,))
                shape = None
                if step.kind == "combination" and "--shape" in step.argv:
                    shape = step.argv[step.argv.index("--shape") + 1]
                previous_remaining = sum(
                    int(row.get("toGenerate", 0)) + int(row.get("held", 0))
                    for row in current.get("checks", ())
                    if row.get("kind") == step.kind
                    and (shape is None or row.get("shape") == shape))
                if current.get("complete"):
                    break
            try:
                code = run(checkpoint_argv)
            except SystemExit as exc:
                # Passthrough mains raise SystemExit(str) — map to refused, keep the report.
                code = exc.code if isinstance(exc.code, int) else cli_mod.EXIT_REFUSED
                if code is None:
                    code = cli_mod.EXIT_REFUSED
                report.steps.append(FillStepResult(
                    kind=step.kind, argv=checkpoint_argv, status="refused",
                    exit_code=int(code) if isinstance(code, int) else cli_mod.EXIT_REFUSED,
                    note=step.note or (str(exc) if exc.args else "SystemExit")))
                # A refusal/error cannot make progress in this step.  Leave it recorded and let
                # continue-on-error advance to the next dependency-ordered step.
                break
            except Exception as exc:
                report.steps.append(FillStepResult(
                    kind=step.kind, argv=checkpoint_argv, status="error",
                    exit_code=cli_mod.EXIT_CANNOT_RUN,
                    note=f"{step.note + '; ' if step.note else ''}{type(exc).__name__}: {exc}"))
                break

            if code == cli_mod.EXIT_CLEAN:
                status = "ran"
            elif code == cli_mod.EXIT_ESCALATED:
                status = "escalated"
            elif code == cli_mod.EXIT_GAP:
                status = "gap"
            elif code in (cli_mod.EXIT_REFUSED, cli_mod.EXIT_CANNOT_RUN):
                status = "refused"
            else:
                status = "error"
            report.steps.append(FillStepResult(
                kind=step.kind, argv=checkpoint_argv, status=status,
                exit_code=code, note=step.note))
            if status in stop_statuses and (stop_on_error or status != "escalated"):
                break
            if not checkpointed:
                break
            updated = generation_completion(kinds=(step.kind,))
            remaining = sum(
                int(row.get("toGenerate", 0)) + int(row.get("held", 0))
                for row in updated.get("checks", ())
                if row.get("kind") == step.kind
                and (shape is None or row.get("shape") == shape))
            if updated.get("complete") or remaining == 0:
                break
            if previous_remaining is not None and remaining >= previous_remaining:
                # A clean batch that made no deterministic progress would otherwise spin forever.
                report.steps.append(FillStepResult(
                    kind=step.kind, argv=checkpoint_argv, status="error",
                    exit_code=cli_mod.EXIT_CANNOT_RUN,
                    note=f"{step.note + '; ' if step.note else ''}full checkpoint made no progress"))
                break
            previous_remaining = remaining
        # The loop above owns classification and stop handling for both ordinary and checkpointed
        # steps. Continue with the next dependency-ordered step after a recorded escalation.
        continue
    return report
