"""seedsmith.adapters.items.basetypegen.run — the run plan, the ledger wiring, and the dry run.

Wires `pipeline.run_ledger.RunLedger` for the spec's own acceptance #2 ("Output writes to the
existing corpus path ... through generator-harness's ledger — append+reconcile by default, explicit
`--overwrite` for a full redo") and testing strategy ("Harness tests: resume/reconcile/overwrite").

**One ledger, every partition.** A `(role, frame, band)` triple is not a closed grid the way
`setgen`'s themes or `affixfamgen`'s partitions are pre-declared — a caller may run this against any
of the 30 role-frames × however many bands exist, so subject ids are open-ended DRAW SLOTS scoped
per partition, mirroring `milestonegen.run`'s own `milestone-draw-{i:03d}` discipline rather than a
fixed subject list.

`is_valid` (the ledger's own reconcile hook) checks that a "done" draw's recorded output id still
exists in the CURRENT on-disk partition file, carrying the SAME `class`/`implicitFamily` the ledger
recorded — a hand edit that renamed, deleted, or reclassified the entry resurfaces the draw as
needing work rather than being trusted forever.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from seedsmith.pipeline.run_ledger import RunLedger

from ....pipeline.provenance import provenance_model

from . import brief as brief_mod
from . import emit as emit_mod
from . import partitions
from . import successor_edges, tuning
from ..registries import load_vocabularies
from ....workspace_roots import owned_path


class PartitionNameNotAllocated(ValueError):
    """The partition name this generator would declare is not one the registry allocates.

    A distinct type rather than a bare `ValueError` so a caller can tell "you gave me a role/frame/band
    that does not exist" (bad input, retry with different values) from "the name I am about to write is
    invisible to the metric" (a generator bug, do not retry). Failing closed here is deliberate: the
    alternative is writing rows no check can see, which is the failure this whole function exists to
    prevent.
    """

REPO_ROOT = tuning.REPO_ROOT
DEFAULT_LEDGER_PATH = owned_path("data/seed/items/_runs/base-types-gen.ledger.json", REPO_ROOT)


def _partition_file(role: str, frame: str, band: str, *,
                    base_types_dir: "Path | None" = None) -> Path:
    directory = base_types_dir or tuning.BASE_TYPES_DIR
    return partitions.file_for(role, frame, band, base_types_dir=directory)


def load_existing(role: str, frame: str, band: str, *,
                  base_types_dir: "Path | None" = None) -> "dict[str, dict]":
    p = _partition_file(role, frame, band, base_types_dir=base_types_dir)
    if not p.exists():
        return {}
    doc = json.loads(p.read_text(encoding="utf-8"))
    return {e["id"]: e for e in doc.get("entries", [])}


def load_corpus_names(*, base_types_dir: "Path | None" = None) -> "dict[str, str]":
    """`collision_key -> existing entry id`, over EVERY base-type partition, not just one.

    ⛔ 2026-09-12: `brief.py` used to list only the CURRENT partition file's names, and the model
    was told to avoid those. That is why 65 display names shipped twice across partitions (e.g.
    "Tungsten Spiker" in both `humanoid-armament-primary-a.json` and `-b.json`): the second
    partition's brief never mentioned the first partition's name. `seed-contract.md` §6 makes
    `nameKey` uniqueness GLOBAL and `NamingCheck` collides names corpus-wide, so generation must
    see the corpus-wide set. The brief cannot be handed all 860 names (that is ~16k chars of prompt
    per draw), so the guard is the reject below, not prompt bloat — the same disposition
    `trees/nodegen/run.py` `_derive_unique_name_key` reached for the identical failure.

    The key matches `NameNormalizer`'s shape closely enough for seed-time rejection: case-folded,
    non-alphanumerics collapsed, word order preserved (the validator's full normalization also
    sorts tokens and folds a small synonym set; a superset here would over-reject, so this keeps the
    conservative subset and the validator remains the authority).
    """
    directory = base_types_dir or tuning.BASE_TYPES_DIR
    by_key: "dict[str, str]" = {}
    for path in sorted(directory.glob("**/*.json")):
        if path.name.startswith("_") or path.parent.name.startswith("_"):
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for entry in doc.get("entries", []):
            name = entry.get("name")
            if isinstance(name, str) and name.strip():
                by_key.setdefault(collision_key(name), entry["id"])
    return by_key


def collision_key(name: str) -> str:
    """Case-folded, non-alphanumeric-collapsed comparison key for a display name."""
    import re as _re
    return " ".join(_re.findall(r"[a-z0-9]+", name.casefold()))


def _draw_prefix(role: str, frame: str, band: str) -> str:
    return f"basetype-draw-{role}-{frame}-{band}-"


@dataclass(frozen=True)
class Subject:
    subject_id: str
    seq: int
    brief: str
    schema: dict


@dataclass(frozen=True)
class RunPlan:
    partition: "brief_mod.PartitionContext"
    subjects: "tuple[Subject, ...]"
    existing: "dict[str, dict]"

    @property
    def complete(self) -> bool:
        return True  # open-ended content: a plan for N new draws is always "complete" for that N

    def summary(self) -> dict:
        return {"partition": self.partition.partition_key, "toGenerate": len(self.subjects),
                "existingEntries": len(self.existing)}


def _seq_from_subject(subject_id: str, prefix: str) -> "int | None":
    if not subject_id.startswith(prefix):
        return None
    suffix = subject_id[len(prefix):]
    return int(suffix) if suffix.isdigit() else None


def _next_seq_from_ledger(done: "dict[str, dict]", prefix: str) -> int:
    indices = [i for sid in done if (i := _seq_from_subject(sid, prefix)) is not None]
    return (max(indices) + 1) if indices else 0


def _draw_indices(done: "dict[str, dict]", prefix: str, count: int,
                  existing: "dict[str, dict]") -> "list[int]":
    """Choose invalid/uncheckpointed draw slots first, then append new slots.

    A prior process can have checkpointed a row before its corpus write completed. Reusing the
    lowest invalid slot lets resume repair that hole instead of advancing forever past it.
    """
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


def is_valid(subject_id: str, entry: dict, *, existing: "dict[str, dict]") -> bool:
    entry_id = entry.get("entryId")
    if not entry_id or entry_id not in existing:
        return False
    real = existing[entry_id]
    return (real.get("class") == entry.get("class")
            and real.get("implicit", {}).get("family") == entry.get("implicitFamily"))


def plan_run(*, role: str, frame: str, band: str, count: int, ledger: RunLedger,
            base_types_dir: "Path | None" = None, theme_hint: str = "") -> RunPlan:
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")
    brief_obj0 = brief_mod.build_base_type_brief(role, frame, band, theme_note=theme_hint,
                                                 base_types_dir=base_types_dir)
    partition = brief_obj0.partition
    existing = load_existing(role, frame, band, base_types_dir=base_types_dir)
    done = ledger.read_done()
    prefix = _draw_prefix(role, frame, band)
    draw_indices = _draw_indices(done, prefix, count, existing)
    # The entry's own minted-id sequence continues past the real corpus, never the draw counter —
    # the two are independent numbers (a draw may be blocked and mint nothing).
    start_entry_seq = emit_mod.next_seq(tuple(existing))

    subjects = []
    for i in range(count):
        draw_index = draw_indices[i]
        b = brief_mod.build_base_type_brief(role, frame, band, theme_note=theme_hint,
                                            base_types_dir=base_types_dir)
        subjects.append(Subject(
            subject_id=f"{prefix}{draw_index:03d}", seq=start_entry_seq + i,
            brief=b.render(), schema=dict(b.schema)))

    return RunPlan(partition=partition, subjects=tuple(subjects), existing=existing)


def resolve_answer(answer: dict, *, partition: "brief_mod.PartitionContext", seq: int,
                   gen_tuning: "tuning.GenTuning | None" = None) -> "dict | None":
    """One model answer -> one finished entry dict, or `None` if the model set `blocked`."""
    if answer.get("blocked"):
        return None
    return emit_mod.assemble_entry(answer, partition, seq=seq, gen_tuning=gen_tuning)


def run_draws(plan: RunPlan, *, ledger: RunLedger,
             call: "Callable[[str, dict], dict]",
             persist: "Callable[[dict], None] | None" = None,
             corpus_names: "dict[str, str] | None" = None
             ) -> "tuple[dict[str, dict], dict[str, dict]]":
    """Executes every subject in `plan`, marking each resolved draw done in `ledger` as it
    completes — not all-or-nothing, mirroring `milestonegen.run.run_draws`.

    `corpus_names` is the corpus-wide `collision_key -> entry id` map (see `load_corpus_names`).
    When supplied, a draw whose accepted `name` collides with an already-shipped name is re-asked
    once, then refused — the generator never writes a duplicate display name (the defect the
    2026-09-12 name-collision audit found 65 of). A refused draw is recorded as blocked with its
    reason, never as a silent duplicate.
    """
    gt = tuning.load_gen_tuning()
    existing = dict(plan.existing)
    names = dict(corpus_names) if corpus_names is not None else None
    fresh: "dict[str, dict]" = {}
    blocked: "dict[str, dict]" = {}

    for subject in plan.subjects:
        try:
            answer = call(subject.brief, subject.schema)
        except ValueError as exc:
            # A local model can ignore constrained decoding and return text rather than JSON.
            # This is one draw's failed answer, not a reason to discard the rest of a batch.
            blocked[subject.subject_id] = {"reason": f"invalid model response: {exc}"}
            continue
        if answer.get("blocked"):
            blocked[subject.subject_id] = {"reason": answer["blocked"]}
            continue

        # Re-ask once on a corpus-wide name collision (the brief cannot list all 860 names).
        if names is not None and _name_collides(answer, names):
            answer = _reask_for_distinct_name(call, subject, answer, names)
            if answer.get("blocked"):
                blocked[subject.subject_id] = {"reason": answer["blocked"]}
                continue
            if _name_collides(answer, names):
                blocked[subject.subject_id] = {
                    "reason": f"name {answer.get('name')!r} already exists in the base-type corpus"}
                continue

        try:
            entry = resolve_answer(answer, partition=plan.partition, seq=subject.seq, gen_tuning=gt)
        except ValueError as exc:
            blocked[subject.subject_id] = {"reason": f"invalid model response: {exc}"}
            continue
        if entry is None:
            blocked[subject.subject_id] = {"reason": "no reason given"}
            continue
        if persist is not None:
            # Corpus first, ledger second. If the process dies between these operations, the next
            # resume retries the unledgered draw instead of advancing past content that was never
            # written to disk.
            persist(entry)
        fresh[entry["id"]] = entry
        existing[entry["id"]] = entry
        if names is not None:
            names[collision_key(entry["name"])] = entry["id"]
        ledger.mark_done(subject.subject_id, {
            "entryId": entry["id"], "class": entry["class"],
            "implicitFamily": entry["implicit"]["family"],
        })

    return fresh, blocked


def _name_collides(answer: dict, names: "dict[str, str]") -> bool:
    name = answer.get("name")
    return bool(isinstance(name, str) and name.strip() and collision_key(name) in names)


def _reask_for_distinct_name(call: "Callable[[str, dict], dict]", subject: Subject,
                             answer: dict, names: "dict[str, str]") -> dict:
    """One repair ask naming the colliding name, mirroring `llm_caller`'s own one-repair discipline."""
    taken = answer.get("name")
    repair_brief = (
        f"{subject.brief}\n\n"
        f"Your previous answer named {taken!r}, which an already-shipped base type uses. "
        "Return exactly one JSON object with a DIFFERENT, specific name for this same object "
        "(and its matching flavor); keep the class, implicitFamily and tags you already chose.\n"
    )
    try:
        return call(repair_brief, subject.schema)
    except ValueError:
        return {"blocked": f"name {taken!r} collides; repair ask failed"}


def write_corpus(role: str, frame: str, band: str, fresh: "dict[str, dict]", *,
                 existing: "dict[str, dict] | None" = None,
                 base_types_dir: "Path | None" = None,
                 source_ref: str = "", model: str,
                 authored_utc: str = "") -> Path:
    """Merges `fresh` into the existing partition file and writes it back — additive only, matching
    `spec-base-types-gen.md` acceptance #2's 'append+reconcile by default'."""
    model = provenance_model(model)
    p = _partition_file(role, frame, band, base_types_dir=base_types_dir)
    ex = existing if existing is not None else load_existing(role, frame, band,
                                                             base_types_dir=base_types_dir)
    merged = {**ex, **fresh}
    entries = [merged[k] for k in sorted(merged)]
    if p.exists():
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["entries"] = entries
    else:
        doc = emit_mod.emit_document(
            entries, batch=f"base-types-gen-{role}-{frame}-{band}",
            partition=registry_partition_name(role, frame, band),
            source_ref=source_ref, model=model, authored_utc=authored_utc)
    return emit_mod.write_document(p, doc)


def registry_partition_name(role: str, frame: str, band: str) -> str:
    """The partition name the REGISTRY allocates for this (role, frame, band) - the only spelling a
    generated file may declare.

    ⛔ Real defect, measured 2026-09-28. This used to be an inline
    `f"base-types/{frame}-{role}-{band}"` - a DASH form, frame-first. Three vocabularies are in play
    for one partition, and the generator matched NONE of the other two:

      * the registry allocates `base-types/<role>/<frame>/<band>`. **62** base-types partitions are
        allocated and **0** of them are dash forms;
      * **60 of the 62** shipped files declare a name that is in the allocated set, character for
        character (`base-types/armament-primary/humanoid/a` and so on);
      * the two that do not are the two `seedsmith check` reports as EMPTY partitions, and they are
        wrong in two different ways - `humanoid-manipulator-b.json` declares `humanoid/manipulator/b`
        (transposed AND prefix-less) while holding 28 rows, and `mantle/humanoid/a.json` declares
        `mantle/humanoid/a` (prefix-less) while holding 12.

    Why that is a correctness bug and not a cosmetic one: `Corpus.model:190` reads `entry.partition` from
    `_meta.partition` (`provenance.get("partition", "(none)")`), and `Coverage/EmptyPartition` computes
    `sorted(allocated - ctx.corpus.partitions)`. So a base-type run writing the dash form would produce
    rows the metric CANNOT SEE, under a partition name the registry has never heard of - it would ADD a
    phantom EmptyPartition gap rather than close the one it was run to close. The rows would be
    invisible to the very check credited for generating them.

    The function asserts membership rather than trusting the format string: a name the registry does not
    allocate is refused at write time, which fails closed instead of writing a file nothing can see.
    That is the check that would have caught this, and it is why the test asserts the property (every
    emitted name is allocated) rather than the literal spelling.
    """
    candidate = f"base-types/{role}/{frame}/{band}"
    # The SAME source `Coverage/EmptyPartition` reads (`coverage.py:32`:
    # `ctx.adapter.registries().vocabularies.get("partitions", frozenset())`). Reading a different
    # registry would make this gate answer a different question than the metric it exists to satisfy -
    # and did: an earlier version consulted `partition_kind_map()`, which maps partition -> KIND and so
    # has no "partitions" key at all. That returned an empty set, the guard never fired, and the first
    # version of the test caught it by asserting a refusal that never came.
    allocated = set(load_vocabularies().get("partitions", frozenset()))
    if not allocated:
        # No registry at all is a different failure from "this name is not in it": refuse rather than
        # wave an unverifiable name through, because the whole point is to not write invisible rows.
        raise PartitionNameNotAllocated(
            f"the registry allocated no partitions, so {candidate!r} cannot be verified as allocated. "
            f"Refusing rather than writing a file Coverage/EmptyPartition cannot see."
        )
    if candidate not in allocated:
        # Fail closed, and say what the registry actually calls it - a bare refusal leaves the
        # operator with no next move, and this is a bug in the caller, not in the operator's input.
        near = sorted(p for p in allocated if isinstance(p, str) and band in p and frame in p)
        raise PartitionNameNotAllocated(
            f"partition {candidate!r} for role={role!r} frame={frame!r} band={band!r} is not one the "
            f"registry allocates, so a file declaring it would be invisible to Coverage/EmptyPartition. "
            f"Registry names matching this frame and band: {near[:6]}"
        )
    return candidate


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Author base-type identities for one (role, frame, "
                                             "band) partition.")
    ap.add_argument("--role", required=True, help="one of core.v1.json's 15 body role ids")
    ap.add_argument("--frame", required=True, choices=list(tuning.FRAMES))
    ap.add_argument("--band", required=True, help="the partition's band letter, e.g. 'a' or 'b'")
    ap.add_argument("--dry-run", action="store_true", help="assemble briefs, make no model calls")
    ap.add_argument("--count", type=int, default=1, help="how many new entries to draw this run")
    ap.add_argument("--theme", default="", help="an optional theme hint in the brief")
    ap.add_argument("--write", action="store_true", help="write the merged partition back to disk")
    ap.add_argument("--overwrite", "--force", default="",
                    help="comma-separated draw ids to regenerate, or the literal 'all' "
                         "(--force is an accepted alias, matching content-completeness-core's "
                         "own naming convention -- RunLedger.force()/generate_commander_effects.py "
                         "--force)")
    ap.add_argument("--endpoint", default="", help="live model endpoint; enables a real run")
    ap.add_argument("--model", default="", help="overrides load_config()'s own model for this run")
    ap.add_argument("--authored-utc", default="", dest="authored_utc",
                    help="stamped into a NEW partition file's _meta.authoredUtc; an existing "
                         "partition keeps its own")
    args = ap.parse_args(argv)

    # species-gear-chain T38: validate the authored edge table against the WHOLE SHIPPED base-type
    # corpus before this run emits anything. A dangling or cross-frame edge would otherwise surface as
    # a refusal on a player's item instead of as a generator failure. The shipped tree is named by
    # `successor_edges.SHIPPED_BASE_TYPES_DIR`, not by `tuning.BASE_TYPES_DIR`: a caller that redirects
    # this run's output (tests, a private tree) does not change what the authored table is about, and
    # validating the table against that private tree would refuse every edge it cannot see.
    edge_violations = successor_edges.violations_in_corpus(
        successor_edges.SHIPPED_BASE_TYPES_DIR, successor_edges.load())
    if edge_violations:
        for line in edge_violations:
            print(f"[EDGE] {line}")
        print(f"successor-edges: {len(edge_violations)} violation(s) - refusing this run")
        return 2

    ledger = RunLedger(DEFAULT_LEDGER_PATH)

    if args.dry_run:
        plan = plan_run(role=args.role, frame=args.frame, band=args.band, count=args.count,
                        ledger=ledger, theme_hint=args.theme)
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
            "seedsmith: refused — no --write. Use --dry-run to inspect the plan first, "
            "then re-run with --write --endpoint <url> to actually call a model and persist.")

    # ⛔ Real gap, closed 2026-09-08: this branch used to be an unconditional `raise SystemExit`
    # ("REFUSING TO RUN: no model call is wired into this CLI entrypoint yet") — `plan_run`/
    # `run_draws`/`write_corpus` were all real and tested, but nothing in this file ever built the
    # `call` `run_draws` already declares and tests against. `live_answer_caller` is that piece.
    import dataclasses

    from ....pipeline.llm_caller import live_answer_caller, resolve_live_transport

    config = resolve_live_transport(args.endpoint, args.model)
    if not config.endpoint:
        raise SystemExit(
            "seedsmith: --write refused — no live endpoint. Pass --endpoint <url> or set "
            "SEEDSMITH_LLM_ENDPOINT in tools/seedsmith/.env; --dry-run needs neither.")
    plan = plan_run(role=args.role, frame=args.frame, band=args.band, count=args.count,
                    ledger=ledger, theme_hint=args.theme)
    persisted = dict(plan.existing)

    def persist(entry: dict) -> None:
        write_corpus(args.role, args.frame, args.band, {entry["id"]: entry}, existing=persisted,
                     model=config.model, authored_utc=args.authored_utc)
        persisted[entry["id"]] = entry

    fresh, blocked = run_draws(plan, ledger=ledger, call=live_answer_caller(config),
                               persist=persist, corpus_names=load_corpus_names())
    print(json.dumps({"planned": len(plan.subjects), "fresh": len(fresh),
                      "blocked": len(blocked), "blockedReasons": blocked},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
