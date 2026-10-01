"""seedsmith.adapters.items.droptablegen.run — the run plan, `RunLedger` wiring, and the partition
file writer for `drop-tables-gen` (docs/architecture/item-seedgen/spec-drop-tables-gen.md).

Mirrors `basetypegen.run`'s own docstring: this module assembles a batch deterministically and
hands back a plan a caller executes against an `answer_fn` / `call`. The model call itself is not
made here -- that is the shared `workflow`/`Pipeline` graph's job. Resume/reconcile/overwrite go
through `pipeline.run_ledger.RunLedger` (module 1, `generator-harness`), never a second mechanism.

**One ledger, one of the four frozen partition slots per run** -- `droptable-draw-d{slot}-{i:03d}`
subject ids, mirroring `basetypegen.run`'s own "open-ended draw slots scoped per partition"
discipline, since a drop table is authored content with no closed universe the way a gem's affix
family or a base type's role+frame pair are.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import brief as brief_mod
from . import emit as emit_mod
from . import schema as schema_mod
from . import tuning
from ....pipeline.provenance import provenance_model
from ....pipeline.run_ledger import RunLedger
from ....workspace_roots import owned_path

REPO_ROOT = tuning.REPO_ROOT
DEFAULT_LEDGER_PATH = owned_path("data/seed/items/_runs/drop-tables-gen.ledger.json", REPO_ROOT)


def _partition_file(slot: int, *, drop_tables_dir: "Path | None" = None) -> Path:
    directory = drop_tables_dir or tuning.DROP_TABLES_DIR
    return directory / f"d{slot}.json"


def load_existing(slot: int, *, drop_tables_dir: "Path | None" = None) -> "dict[str, dict]":
    p = _partition_file(slot, drop_tables_dir=drop_tables_dir)
    if not p.exists():
        return {}
    doc = json.loads(p.read_text(encoding="utf-8"))
    return {e["id"]: e for e in doc.get("entries", [])}


def _draw_prefix(slot: int) -> str:
    return f"droptable-draw-d{slot}-"


@dataclass(frozen=True)
class Subject:
    subject_id: str
    seq: int
    plan: "brief_mod.RowSlotPlan"
    brief: str
    schema: dict


@dataclass(frozen=True)
class RunPlan:
    slot: int
    subjects: "tuple[Subject, ...]"
    existing: "dict[str, dict]"

    @property
    def complete(self) -> bool:
        return True  # open-ended content: a plan for N new draws is always "complete" for that N

    def summary(self) -> dict:
        return {"slot": self.slot, "toGenerate": len(self.subjects),
                "existingEntries": len(self.existing)}


def _seq_from_subject(subject_id: str, prefix: str) -> "int | None":
    if not subject_id.startswith(prefix):
        return None
    suffix = subject_id[len(prefix):]
    return int(suffix) if suffix.isdigit() else None


def _next_draw_index(done: "dict[str, dict]", prefix: str) -> int:
    indices = [i for sid in done if (i := _seq_from_subject(sid, prefix)) is not None]
    return (max(indices) + 1) if indices else 0


def _draw_indices(done: "dict[str, dict]", prefix: str, count: int,
                  existing: "dict[str, dict]") -> "list[int]":
    """Repair invalid ledger slots before allocating new open-ended draws."""
    indexed = {
        idx: (sid, row) for sid, row in done.items()
        if (idx := _seq_from_subject(sid, prefix)) is not None
    }
    invalid = [idx for idx, (sid, row) in indexed.items() if not is_valid(sid, row, existing=existing)]
    next_index = max(indexed, default=-1) + 1
    selected = sorted(invalid)
    while len(selected) < count:
        selected.append(next_index)
        next_index += 1
    return selected[:count]


def is_valid(_subject_id: str, entry: dict, *, existing: "dict[str, dict]") -> bool:
    """The reconcile half `RunLedger.plan` exists for: a ledger row counts as done only if its
    recorded table id still exists in the CURRENT on-disk partition file AND still carries the same
    `name` -- a hand edit that renamed or deleted the table resurfaces the draw as needing work."""
    # Terminal model outcomes are deliberate checkpoints without corpus content. They must not be
    # requeued forever by the open-ended draw planner; an explicit retry/overwrite can revisit them.
    if entry.get("outcome") in {"blocked", "escalated"}:
        return True
    table_id = entry.get("entryId")
    if not table_id or table_id not in existing:
        return False
    return existing[table_id].get("name") == entry.get("name")


def plan_run(*, slot: int, count: int, ledger: RunLedger,
            drop_tables_dir: "Path | None" = None, theme_hint: str = "") -> RunPlan:
    if slot not in tuning.LEGAL_SLOTS:
        raise ValueError(f"slot must be one of {tuning.LEGAL_SLOTS}, got {slot}")
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")

    existing = load_existing(slot, drop_tables_dir=drop_tables_dir)
    done = ledger.read_done()
    prefix = _draw_prefix(slot)
    draw_indices = _draw_indices(done, prefix, count, existing)
    start_entry_seq = emit_mod.next_seq(tuple(existing), slot)

    subjects = []
    for i in range(count):
        draw_index = draw_indices[i]
        # seq_index for the row-slot rotation is the TABLE's own minted sequence position, so two
        # different partition slots (which start their own entry-seq counters independently) still
        # each rotate deterministically over their own history rather than colliding on index 0.
        seq_index = start_entry_seq + i - 1
        b = brief_mod.build_drop_table_brief(seq_index, theme_note=theme_hint)
        subjects.append(Subject(
            subject_id=f"{prefix}{draw_index:03d}", seq=start_entry_seq + i,
            plan=b.plan, brief=b.render(), schema=dict(b.schema)))

    return RunPlan(slot=slot, subjects=tuple(subjects), existing=existing)


def resolve_answer(answer: dict, *, plan: "brief_mod.RowSlotPlan", table_id: str) -> "dict | None":
    """One model answer -> one finished drop-table entry dict, or `None` if the model set
    `blocked`. Re-validates the answer's own structure first ("validate before accept",
    `pipeline.model`'s guardrail 5) -- `assemble_entry`'s checks are defense in depth against an
    illegal VALUE, not a substitute for this structural pass."""
    if answer.get("blocked"):
        return None
    errors = schema_mod.validate_answer(
        answer, row_count=plan.row_count, drop_band_enum=plan.drop_band_enum,
        rarity_ids=plan.rarity_ids, offer_rarity_floor=True)
    if errors:
        raise ValueError(f"invalid drop-table answer: {'; '.join(errors)}")
    return emit_mod.assemble_entry(
        table_id=table_id, name=answer["name"], drop_bands=list(answer["rowBands"]),
        equipment_slots=list(plan.equipment_slots), material_refs=list(plan.material_refs),
        consumable_refs=list(plan.consumable_refs), gem_refs=list(plan.gem_refs),
        rarity_floor=answer.get("rarityFloor"), legal_role_frames=plan.legal_role_frames,
        legal_material_refs=plan.legal_material_refs,
        legal_consumable_refs=plan.legal_consumable_refs, legal_gem_refs=plan.legal_gem_refs,
        legal_drop_bands=plan.drop_band_enum, legal_rarity_ids=plan.rarity_ids,
    )


def run_draws(plan: RunPlan, *, ledger: RunLedger,
             call: "Callable[[str, dict], dict]",
             persist: "Callable[[dict], None] | None" = None
             ) -> "tuple[dict[str, dict], dict[str, dict]]":
    """Executes every subject in `plan`, marking each resolved draw done in `ledger` as it
    completes -- not all-or-nothing, mirroring `basetypegen.run.run_draws`."""
    fresh: "dict[str, dict]" = {}
    blocked: "dict[str, dict]" = {}

    for subject in plan.subjects:
        table_id = emit_mod.mint_table_id(plan.slot, subject.seq)
        try:
            answer = call(subject.brief, subject.schema)
        except ValueError as exc:
            reason = f"invalid model response: {exc}"
            ledger.mark_terminal(subject.subject_id, outcome="escalated", entry_id=table_id,
                                 attempts=1, defects=[reason])
            blocked[subject.subject_id] = {"reason": reason}
            continue
        if answer.get("blocked"):
            reason = str(answer["blocked"])
            ledger.mark_terminal(subject.subject_id, outcome="blocked", entry_id=table_id,
                                 attempts=1, blocked_reason=reason)
            blocked[subject.subject_id] = {"reason": reason}
            continue
        try:
            entry = resolve_answer(answer, plan=subject.plan, table_id=table_id)
        except ValueError as exc:
            reason = f"invalid model response: {exc}"
            ledger.mark_terminal(subject.subject_id, outcome="escalated", entry_id=table_id,
                                 attempts=1, defects=[reason])
            blocked[subject.subject_id] = {"reason": reason}
            continue
        if entry is None:
            blocked[subject.subject_id] = {"reason": "no reason given"}
            continue
        if persist is not None:
            # Corpus first, ledger second. A kill between these operations leaves the draw
            # unledgered and therefore safely retryable instead of creating a ledger/file split.
            persist(entry)
        fresh[entry["id"]] = entry
        ledger.mark_done(subject.subject_id, {"entryId": entry["id"], "name": entry["name"]})

    return fresh, blocked


def write_corpus(slot: int, fresh: "dict[str, dict]", *, existing: "dict[str, dict] | None" = None,
                 drop_tables_dir: "Path | None" = None, model: str,
                 authored_utc: str = "") -> Path:
    """Merges `fresh` into the existing `dN.json` and writes it back -- additive only, matching
    the spec's acceptance #3 ('through generator-harness's ledger, into the existing d1..d4.json
    corpus shape'). `_meta` is preserved verbatim when the file already exists, matching
    `basetypegen.run.write_corpus`'s own discipline."""
    model = provenance_model(model)
    p = _partition_file(slot, drop_tables_dir=drop_tables_dir)
    ex = existing if existing is not None else load_existing(slot, drop_tables_dir=drop_tables_dir)
    merged = {**ex, **fresh}
    entries = [merged[k] for k in sorted(merged)]
    if p.exists():
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["entries"] = entries
    else:
        doc = {
            "schemaVersion": 1, "kind": "drop-table",
            "_meta": {
                "partition": f"drop-tables/{slot}", "contractVersion": 1, "exemplarVersion": 1,
                "promptVersion": 1, "batch": f"drop-tables-{slot}-droptablegen", "model": model,
                "authoredUtc": authored_utc, "sourceRef": "docs/architecture/item/entry-shapes.md#9",
            },
            "entries": entries,
        }
    return _write_document(p, doc)


def _write_document(path: Path, doc: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        # newline="": json already emits \n; without this the Windows text-mode
        # translation rewrites the whole file to \r\n on every append, breaking
        # the byte-identity proof (found 2026-09-13 via Task 1.3c's append run).
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as fh:
            fh.write(payload)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Author new drop tables for one frozen partition slot.")
    ap.add_argument("--slot", type=int, required=True, choices=list(tuning.LEGAL_SLOTS))
    ap.add_argument("--dry-run", action="store_true", help="assemble briefs, make no model calls")
    ap.add_argument("--count", type=int, default=1, help="how many new tables to draw this run")
    ap.add_argument("--theme", default="", help="an optional theme hint in the brief")
    ap.add_argument("--write", action="store_true", help="write the merged partition back to disk")
    ap.add_argument("--overwrite", "--force", default="",
                    help="comma-separated draw ids to regenerate, or the literal 'all' "
                         "(--force is an accepted alias, matching content-completeness-core's "
                         "own naming convention -- RunLedger.force()/generate_commander_effects.py "
                         "--force)")
    ap.add_argument("--endpoint", default="", help="live model endpoint; enables a real run")
    ap.add_argument("--model", default="", help="overrides load_config()'s own model for this run")
    args = ap.parse_args(argv)

    ledger = RunLedger(DEFAULT_LEDGER_PATH)

    if args.dry_run:
        plan = plan_run(slot=args.slot, count=args.count, ledger=ledger, theme_hint=args.theme)
        print(json.dumps(plan.summary(), ensure_ascii=False, indent=2))
        if plan.subjects:
            print("--- sample brief ---")
            print(plan.subjects[0].brief)
        return 0

    if args.overwrite:
        done = ledger.read_done()
        ids_needing_work = ledger.force(list(done), args.overwrite) if args.overwrite == "all" \
            else ledger.force([s.strip() for s in args.overwrite.split(",") if s.strip()], "ids")
        print(json.dumps({"overwrite": ids_needing_work}, ensure_ascii=False))
        return 0

    if not args.write:
        raise SystemExit(
            "seedsmith: refused -- no --write. Use --dry-run to inspect the plan first, "
            "then re-run with --write --endpoint <url> to actually call a model and persist.")

    # ⛔ Real gap, closed 2026-09-08 -- see basetypegen.run.main's own identical fix for the full
    # account: this branch used to be an unconditional refusal even though `plan_run`/`run_draws`/
    # `write_corpus` were all real and tested.
    import dataclasses

    from ....pipeline.llm_caller import live_answer_caller, resolve_live_transport

    config = resolve_live_transport(args.endpoint, args.model)
    if not config.endpoint:
        raise SystemExit(
            "seedsmith: --write refused — no live endpoint. Pass --endpoint <url> or set "
            "SEEDSMITH_LLM_ENDPOINT in tools/seedsmith/.env; --dry-run needs neither.")
    plan = plan_run(slot=args.slot, count=args.count, ledger=ledger, theme_hint=args.theme)
    persisted = dict(plan.existing)

    def persist(entry: dict) -> None:
        write_corpus(args.slot, {entry["id"]: entry}, existing=persisted, model=config.model)
        persisted[entry["id"]] = entry

    fresh, blocked = run_draws(plan, ledger=ledger, call=live_answer_caller(config),
                               persist=persist)
    print(json.dumps({"planned": len(plan.subjects), "fresh": len(fresh),
                      "blocked": len(blocked), "blockedReasons": blocked},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
