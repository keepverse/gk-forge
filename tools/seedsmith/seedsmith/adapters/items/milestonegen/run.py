"""seedsmith.adapters.items.milestonegen.run — the run plan, the ledger wiring, and the dry run.

⚠ **What this module does and does not do.** It assembles the run deterministically: which draw
slots need work (via `RunLedger.plan`), the brief for each, and — once an answer comes back — the
finished entry (`emit.entry_for`). The **model call itself is not made here**: `call` is injected
(never imported directly), the same contract every generator in this program already honours, so a
test proves the exact number of calls made without reaching a network.

**Subject ids are draw slots, not fixed grid cells.** Unlike `combogen` (a closed 102-cell grid) or
`setgen` (a fixed theme list), this corpus is open-ended new content — there is no pre-known set of
"things to generate." `milestone-draw-{i:03d}` mirrors `generate_affixes.py`'s own
`next_draw_start_index` discipline: continuing one past the highest draw index any past run (recorded
in the ledger) already committed, so re-running never overwrites a previous draw's accepted entry by
coincidence.

`is_valid` (the ledger's own reconcile hook) checks that a "done" draw's recorded output id still
exists in the current on-disk corpus with the SAME runtimeFamily the ledger recorded — so a corpus a
hand edit broke (the id renamed, or the entry deleted) resurfaces as needing work on the next run
rather than being silently trusted forever.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ....pipeline.run_ledger import RunLedger
from . import brief as brief_mod
from . import emit as emit_mod
from .schema import TAG_VOCAB, answer_schema, channel_vocab

REPO_ROOT = Path(__file__).resolve().parents[6]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from ....workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

OUTPUT_PATH = _owned("data/seed/items/enhancement-milestones/milestones.json")
#: Matches `RunLedger`'s own documented convention: "each generator module gets its own ledger under
#: `gk-data/packs/fusion/data/seed/items/_runs/<module-id>.ledger.json`, matching `setgen`'s own convention."
DEFAULT_LEDGER_PATH = _owned("data/seed/items/_runs/enhancement-milestones-gen.ledger.json")

PROMPT_VERSION = brief_mod.PROMPT_VERSION
DRAW_PREFIX = "milestone-draw-"


def load_existing(path: "Path | None" = None) -> "dict[str, dict]":
    p = path or OUTPUT_PATH
    if not p.exists():
        return {}
    doc = json.loads(p.read_text(encoding="utf-8"))
    return {e["id"]: e for e in doc.get("entries", [])}


def _existing_ids(existing: "dict[str, dict]") -> "set[str]":
    return set(existing)


def _existing_families(existing: "dict[str, dict]") -> "set[str]":
    return {e.get("runtimeFamily", "") for e in existing.values()}


def _existing_names(existing: "dict[str, dict]") -> "tuple[str, ...]":
    return tuple(sorted(e.get("name", "") for e in existing.values() if e.get("name")))


@dataclass(frozen=True)
class Subject:
    """One draw: one brief already assembled, one slot id."""

    subject_id: str
    draw_index: int
    brief: str
    schema: dict


@dataclass(frozen=True)
class RunPlan:
    subjects: "tuple[Subject, ...]"
    existing: "dict[str, dict]"

    @property
    def complete(self) -> bool:
        return True  # open-ended content: a plan for N new draws is always "complete" for that N

    def summary(self) -> dict:
        return {"toGenerate": len(self.subjects), "existingEntries": len(self.existing)}


def _draw_index(subject_id: str) -> "int | None":
    if not subject_id.startswith(DRAW_PREFIX):
        return None
    suffix = subject_id[len(DRAW_PREFIX):]
    return int(suffix) if suffix.isdigit() else None


def _next_draw_index(done: "dict[str, dict]") -> int:
    indices = [i for sid in done if (i := _draw_index(sid)) is not None]
    return (max(indices) + 1) if indices else 0


def _draw_indices(done: "dict[str, dict]", count: int,
                  existing: "dict[str, dict]") -> "list[int]":
    """Repair ledger slots whose entry is absent or changed before allocating new draws."""
    indexed = {
        idx: (sid, row) for sid, row in done.items()
        if (idx := _draw_index(sid)) is not None
    }
    invalid = [idx for idx, (sid, row) in indexed.items() if not is_valid(sid, row, existing=existing)]
    next_index = max(indexed, default=-1) + 1
    selected = sorted(invalid)
    while len(selected) < count:
        selected.append(next_index)
        next_index += 1
    return selected[:count]


def is_valid(subject_id: str, entry: dict, *, existing: "dict[str, dict] | None" = None) -> bool:
    """The reconcile check `RunLedger.plan` runs against every "done" ledger row: the recorded
    output id must still exist in the current on-disk corpus, carrying the SAME runtimeFamily the
    ledger recorded at mint time — a hand edit that renamed or deleted the entry resurfaces the draw
    as needing work rather than being trusted forever."""
    ex = existing if existing is not None else load_existing()
    entry_id = entry.get("entryId")
    runtime_family = entry.get("runtimeFamily")
    if not entry_id or entry_id not in ex:
        return False
    return ex[entry_id].get("runtimeFamily") == runtime_family


def plan_run(*, count: int, ledger: RunLedger,
             existing: "dict[str, dict] | None" = None,
             theme_hint: str = "") -> RunPlan:
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")
    ex = existing if existing is not None else load_existing()
    done = ledger.read_done()
    draw_indices = _draw_indices(done, count, ex)
    channels = channel_vocab()
    schema = answer_schema(channels=channels, tags=TAG_VOCAB)
    existing_names = _existing_names(ex)

    subjects = tuple(
        Subject(
            subject_id=f"{DRAW_PREFIX}{i:03d}",
            draw_index=i,
            brief=brief_mod.build_brief(channels, TAG_VOCAB, existing_names, theme_hint=theme_hint),
            schema=schema,
        )
        for i in draw_indices
    )
    return RunPlan(subjects=subjects, existing=ex)


def resolve_answer(answer: dict, *, existing_ids: "set[str]",
                    existing_families: "set[str]") -> "dict | None":
    """One model answer -> one finished entry dict (real corpus shape), or `None` if the model set
    `blocked`. Refuses (raises) rather than silently coercing a `runtimeFamily` collision with an
    already-existing family — a name collision is a real authoring conflict, not something to
    resolve by picking an arbitrary suffix."""
    if answer.get("blocked"):
        return None
    name = answer["name"]
    slug = emit_mod.slug_from_name(name)
    family = emit_mod.runtime_family_for(slug)
    if family in existing_families:
        raise emit_mod.MintRefused(
            f"{family!r} already exists in the corpus — the model must pick a name that slugs to "
            f"a new family, never one already minted")
    entry_id = emit_mod.next_entry_id(existing_ids)
    entry = emit_mod.entry_for(
        entry_id=entry_id, name=name, channel=answer["channel"],
        flavor=answer.get("flavor", ""), tags=answer.get("tags") or [],
    )
    return entry.to_dict()


def run_draws(plan: RunPlan, *, ledger: RunLedger,
              call: "Callable[[str, dict], dict]",
              persist: "Callable[[dict], None] | None" = None
              ) -> "tuple[dict[str, dict], dict[str, dict]]":
    """Executes every subject in `plan`, marking each resolved draw done in `ledger` as it completes
    (so a kill mid-run leaves every already-resolved draw committed, per `RunLedger`'s own atomic
    write guarantee) — not all-or-nothing.

    Returns `(fresh, blocked)`: `fresh` keyed by the new entry's own `id`, `blocked` keyed by
    subject id for any draw the model declined (its own `blocked` reason recorded verbatim).
    """
    existing_ids = _existing_ids(plan.existing)
    existing_families = _existing_families(plan.existing)
    fresh: "dict[str, dict]" = {}
    blocked: "dict[str, dict]" = {}

    for subject in plan.subjects:
        answer = call(subject.brief, subject.schema)
        if answer.get("blocked"):
            blocked[subject.subject_id] = {"reason": answer["blocked"]}
            continue
        try:
            entry = resolve_answer(answer, existing_ids=existing_ids,
                                   existing_families=existing_families)
        except ValueError as exc:
            blocked[subject.subject_id] = {"reason": f"invalid model response: {exc}"}
            continue
        if entry is None:
            blocked[subject.subject_id] = {"reason": "no reason given"}
            continue
        if persist is not None:
            # Write the corpus before checkpointing the draw. A killed process can then only leave
            # an unledgered, retryable draw; it cannot advance past a row that was never written.
            persist(entry)
        fresh[entry["id"]] = entry
        existing_ids.add(entry["id"])
        existing_families.add(entry["runtimeFamily"])
        ledger.mark_done(subject.subject_id, {
            "entryId": entry["id"], "runtimeFamily": entry["runtimeFamily"],
        })

    return fresh, blocked


def write_corpus(fresh: "dict[str, dict]", *, existing: "dict[str, dict] | None" = None,
                  path: "Path | None" = None) -> Path:
    """Merges `fresh` into the existing corpus and writes it back — additive only, never dropping an
    existing entry (`base-types-gen`'s own `enhanceTrack[].family` references must keep resolving)."""
    p = path or OUTPUT_PATH
    ex = existing if existing is not None else load_existing(p)
    merged = {**ex, **fresh}
    entries = [merged[k] for k in sorted(merged)]
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schemaVersion": 1,
        "kind": "enhancement-milestone",
        "_meta": {"partition": "enhancement-milestones"},
        "entries": entries,
    }
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Author enhancement-milestone families.")
    ap.add_argument("--dry-run", action="store_true", help="assemble briefs, make no model calls")
    ap.add_argument("--count", type=int, default=1, help="how many new families to draw this run")
    ap.add_argument("--theme", default="", help="an optional theme hint in the brief")
    ap.add_argument("--write", action="store_true", help="write the merged corpus back to disk")
    ap.add_argument("--overwrite", "--force", default="",
                     help="comma-separated draw ids to regenerate, or the literal 'all' "
                          "(--force is an accepted alias, matching content-completeness-core's "
                          "own naming convention -- RunLedger.force()/generate_commander_effects.py "
                          "--force)")
    ap.add_argument("--endpoint", default="", help="live model endpoint; enables a real run")
    ap.add_argument("--model", default="", help="overrides load_config()'s own model for this run")
    args = ap.parse_args(argv)

    ledger = RunLedger(DEFAULT_LEDGER_PATH)
    existing = load_existing()

    if args.dry_run:
        plan = plan_run(count=args.count, ledger=ledger, existing=existing, theme_hint=args.theme)
        print(f"{len(plan.subjects)} draw(s) planned; no model calls made.")
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

    # ⛔ Real gap, closed 2026-09-08 — see basetypegen.run.main's own identical fix for the full
    # account: this branch used to be an unconditional refusal even though `plan_run`/`run_draws`/
    # `write_corpus` were all real and tested.
    import dataclasses

    from ....pipeline.llm_caller import live_answer_caller, resolve_live_transport

    config = resolve_live_transport(args.endpoint, args.model)
    if not config.endpoint:
        raise SystemExit(
            "seedsmith: --write refused — no live endpoint. Pass --endpoint <url> or set "
            "SEEDSMITH_LLM_ENDPOINT in tools/seedsmith/.env; --dry-run needs neither.")
    plan = plan_run(count=args.count, ledger=ledger, existing=existing, theme_hint=args.theme)
    persisted = dict(existing)

    def persist(entry: dict) -> None:
        write_corpus({entry["id"]: entry}, existing=persisted)
        persisted[entry["id"]] = entry

    fresh, blocked = run_draws(plan, ledger=ledger, call=live_answer_caller(config),
                               persist=persist)
    print(json.dumps({"planned": len(plan.subjects), "fresh": len(fresh),
                      "blocked": len(blocked), "blockedReasons": blocked},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
