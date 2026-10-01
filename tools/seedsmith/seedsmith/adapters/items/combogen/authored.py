"""seedsmith.adapters.items.combogen.authored — plan -> graph -> assembled entry -> ledger -> file,
for one combination batch (item module 21, `combination-write-unblock`).

⛔ **What this file closes.** `run.plan_run` already assembles the whole grid deterministically
(102 subjects, real briefs, real ids); `workflow/graphs/item_combination.py` already connects one
subject's brief to an LLM caller. Nothing before this module actually DROVE a subject through that
graph and turned the result into a seed file — this is the batch driver, mirroring
`setgen.authored.run_batch`'s own shape.

⚠ **Resume/reconcile/overwrite go through `pipeline.run_ledger.RunLedger`** (module 1,
`generator-harness`), never a second ledger mechanism — the harness this module was built to wire in,
per the spec's own Project Structure line for `run.py`. `combogen.run.plan_run`'s own docstring
argues a ledger is unneeded BECAUSE re-running the whole (cheap, 102-cell) grid is byte-identical;
that argument is about `plan_run` (the deterministic PLAN), and stays true — it is not an argument
against resuming the separate, real-money WRITE step, which is exactly what every other harness-using
generator in this program (gemgen, basetypegen, materialgen, consumablegen, milestonegen) already
uses `RunLedger` for.

⚠ **Transport stays injected.** The default is an authored-answer file; the CLI may instead pass
the shared live caller. `authored` itself remains transport-agnostic and never imports the live
model client, so replay-based tests cannot reach the network. `setgen.answers` is reused directly
rather than duplicated — nothing in `AnswerFile`/`schema_defects`/`ReplayTransport` is set-specific;
it is a generic authored-answer reader and JSON-Schema walker.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import emit, run as run_mod
from . import schema as schema_mod
from .brief import PROMPT_VERSION
from .run import RunPlan, Subject
from .tuning import ComboTuning
from .. import registries
from ....pipeline.run_ledger import RunLedger

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

COMBINATIONS_DIR = _owned("data/seed/items/combinations")
DEFAULT_LEDGER_NAME = "combination-gen.ledger.json"


def _ledger_is_valid(_subject_id: str, entry: dict) -> bool:
    """The reconcile half `RunLedger.plan` exists for — mirrors `gemgen.run._ledger_is_valid`
    for persisted rows, plus explicit `blocked` / `escalated` completions so resume advances
    (affix returns clean on blocked; combination used to re-hit the same cell forever)."""
    if not isinstance(entry, dict):
        return False
    if (isinstance(entry.get("entry"), dict)
            and isinstance(entry["entry"].get("id"), str) and bool(entry["entry"].get("id"))):
        return True
    outcome = entry.get("outcome")
    if outcome == "blocked":
        reason = entry.get("blockedReason")
        return isinstance(reason, str) and bool(reason.strip())
    if outcome == "escalated":
        return True
    return False


def plan_needing_work(plan: RunPlan, ledger: RunLedger) -> "list[Subject]":
    ids = [s.subject_id for s in plan.subjects]
    needing = set(ledger.plan(ids, _ledger_is_valid))
    return [s for s in plan.subjects if s.subject_id in needing]


def plan_overwrite(plan: RunPlan, target: "str | list[str]", ledger: RunLedger) -> "list[Subject]":
    """`target` is the literal `"all"` or an explicit subject-id list. The guard against any OTHER
    bare string is HERE, not inside `RunLedger.force` (whose own `scope` parameter only ever sees
    the literal `"all"`/`"ids"` this function already resolved to) — mirrors `gemgen.run.
    plan_overwrite`'s own precedent exactly: a bare string would otherwise silently iterate its
    CHARACTERS as subject ids, which is the "a typo'd --overwrite fails loudly" boundary."""
    if isinstance(target, str) and target != "all":
        raise ValueError(
            f"overwrite target must be the literal 'all' or a list of subject ids, got {target!r} "
            f"— a bare string here would silently iterate its CHARACTERS as ids")
    ids = [s.subject_id for s in plan.subjects]
    scope = "all" if target == "all" else "ids"
    wanted = ids if scope == "all" else list(target)
    forced = set(ledger.force(wanted, scope=scope))
    return [s for s in plan.subjects if s.subject_id in forced]


@dataclass
class SubjectOutcome:
    subject_id: str
    entry_id: str
    outcome: str                      # "persisted" | "escalated" | "blocked"
    attempts: int
    defects: "list[str]" = field(default_factory=list)
    blocked_reason: str = ""

    def to_dict(self) -> dict:
        row = {"subjectId": self.subject_id, "entryId": self.entry_id,
               "outcome": self.outcome, "attempts": self.attempts}
        if self.defects:
            row["defects"] = list(self.defects)
        if self.blocked_reason:
            row["blockedReason"] = self.blocked_reason
        return row


@dataclass
class BatchResult:
    shape: str
    out_dir: Path
    outcomes: "list[SubjectOutcome]" = field(default_factory=list)
    file: "Path | None" = None
    entries: "list[dict]" = field(default_factory=list)

    @property
    def persisted(self) -> "list[SubjectOutcome]":
        return [o for o in self.outcomes if o.outcome == "persisted"]

    def to_dict(self) -> dict:
        return {
            "shape": self.shape,
            "outDir": str(self.out_dir),
            "planned": len(self.outcomes),
            "persisted": len(self.persisted),
            "escalated": sum(1 for o in self.outcomes if o.outcome == "escalated"),
            "blocked": sum(1 for o in self.outcomes if o.outcome == "blocked"),
            "file": str(self.file) if self.file else None,
            "totalEntriesInFile": len(self.entries),
            "subjects": [o.to_dict() for o in self.outcomes],
        }


def write_seed_file(shape: str, entries: "list[dict]", *, out_dir: Path, model: str,
                    authored_utc: str) -> Path:
    """Writes `<out_dir>/<shape>s.json` — same top-level envelope shape the retired
    `socket-words/sockwords.json` used (`schemaVersion`, `kind`, `_meta`, `entries`), same atomic
    temp-file-then-replace discipline every other generator in this program uses, so a killed
    process leaves either the old file or the new one, never half of one.
    """
    target = out_dir / f"{shape}s.json"
    doc = {
        "schemaVersion": 1,
        "kind": "combination",
        "_meta": {
            "batch": f"combination-gen-{shape}",
            # "combinations/{shape}", not bare `shape` -- matches the established multi-file-directory
            # convention `gems` already uses ("gems/1", "gems/2"), confirmed 2026-09-07 against a real
            # generated file: a bare partition id is exactly the bug found (and fixed) the same day in
            # base-types/footing/plant/{a,b}.json, where a missing directory prefix made real content
            # invisible to Corpus.partitions' occupancy lookup.
            "partition": f"combinations/{shape}",
            "contractVersion": 1,
            "registryVersions": registries.load_versions(),
            "exemplarVersion": 1,
            "promptVersion": PROMPT_VERSION,
            "model": model,
            "authoredUtc": authored_utc,
            "sourceRef": "docs/architecture/item-seedgen/spec-combination-write-unblock.md",
        },
        "entries": sorted(entries, key=lambda e: e["id"]),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    handle, tmp_name = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return target


def run_batch(*, plan: RunPlan, answers, tuning: ComboTuning, out_dir: Path,
             authored_utc: str, model: str,
             ledger_path: "Path | None" = None,
             call: "Callable[..., str] | None" = None,
             overwrite: "str | list[str] | None" = None,
             taken_keys: "set[str] | None" = None,
             key_of: "Callable[[list[str]], dict[str, str]] | None" = None,
             name_defects: "Callable[[list[str]], dict[str, list[str]]] | None" = None,
             write_file: bool = True) -> BatchResult:
    """Drive one planned shape (36 Strains or 66 Splices) through the graph and write what
    survived. `call` defaults to the replay transport over `answers`; a test hands in a raising stub
    to prove the path makes no live call — the same proof `setgen.authored.run_batch` gives.
    """
    from ....workflow.graphs.item_combination import (build_item_combination_graph,
                                                       state_for_combination)
    from ....workflow.runner import run_one
    from ..setgen.answers import AnswerExhausted, AnswerMissing, ReplayTransport, replay_caller

    ledger = RunLedger(ledger_path or (out_dir / DEFAULT_LEDGER_NAME))
    if overwrite:
        subjects = plan_overwrite(plan, overwrite, ledger)
    else:
        subjects = plan_needing_work(plan, ledger)

    granted = run_mod.granted_family_vocabulary()
    schema = schema_mod.combination_schema(
        tuning, supplied_families=plan.supply.families, host_roles=plan.host_roles,
        granted_families=granted)

    briefs = {s.subject_id: s.brief for s in subjects}
    caller = call if call is not None else replay_caller(briefs, answers)

    drafts: "dict[str, dict]" = {}

    def on_persist(subject_id: str, draft: dict) -> None:
        drafts[subject_id] = draft

    app = build_item_combination_graph(schema=schema, on_persist=on_persist, call=caller)

    result = BatchResult(shape=plan.shape, out_dir=out_dir)
    for subject in subjects:
        if isinstance(caller, ReplayTransport):
            # ⛔ Same reason `setgen.authored.run_batch` sets this per subject: two subjects can
            # produce byte-identical briefs (unlikely here since every cell's brief embeds its own
            # aptitude/archetype prose, but the discipline is cheap and the failure mode expensive).
            caller.current_subject_id = subject.subject_id
        state = state_for_combination(subject, schema=schema, taken_keys=taken_keys,
                                      key_of=key_of, name_defects=name_defects)
        try:
            final = run_one(app, state)
        except (AnswerMissing, AnswerExhausted) as exc:
            defects = list(getattr(exc, "defects", ())) or [str(exc)]
            attempts = len(answers.attempts_for(subject.subject_id))
            result.outcomes.append(SubjectOutcome(
                subject_id=subject.subject_id, entry_id=subject.entry_id, outcome="escalated",
                attempts=attempts, defects=defects))
            ledger.mark_terminal(subject.subject_id, outcome="escalated",
                                 entry_id=subject.entry_id, attempts=attempts, defects=defects)
            continue

        draft = drafts.pop(subject.subject_id, None)
        attempts = int(final.get("attempts", 0))
        defects = list(final.get("defects") or [])
        if draft is None:
            result.outcomes.append(SubjectOutcome(
                subject_id=subject.subject_id, entry_id=subject.entry_id,
                outcome="escalated", attempts=attempts, defects=defects))
            ledger.mark_terminal(subject.subject_id, outcome="escalated",
                                 entry_id=subject.entry_id, attempts=attempts, defects=defects)
            continue
        if isinstance(draft.get("blocked"), str) and draft["blocked"].strip():
            reason = draft["blocked"].strip()
            result.outcomes.append(SubjectOutcome(
                subject_id=subject.subject_id, entry_id=subject.entry_id,
                outcome="blocked", attempts=attempts, blocked_reason=reason))
            # No seed entry — but ledger the decline so --limit / resume advances past this cell.
            ledger.mark_terminal(subject.subject_id, outcome="blocked",
                                 entry_id=subject.entry_id, attempts=attempts,
                                 blocked_reason=reason)
            continue

        entry = emit.assemble_entry(
            entry_id=subject.entry_id, name_key=subject.name_key, name=str(draft["name"]),
            flavor=str(draft["flavor"]), shape=subject.shape, aptitudes=subject.aptitudes,
            archetype=subject.archetype, ingredient_families=list(draft["ingredients"]),
            grants=list(draft["grants"]), tuning=tuning,
            host_role=draft.get("hostRole"), host_frame=draft.get("hostFrame"))

        result.outcomes.append(SubjectOutcome(
            subject_id=subject.subject_id, entry_id=subject.entry_id,
            outcome="persisted", attempts=attempts))
        ledger.mark_done(subject.subject_id, {"entryId": subject.entry_id, "entry": entry})

    # The written file always reflects EVERY entry the ledger holds for this shape, not just the
    # ones this run produced — a run interrupted after `mark_done` but before the file write must
    # not lose already-completed subjects on the next pass (the same split `gemgen.run.
    # entries_from_ledger` / `write_partition_file` already draw).
    result.entries = entries_from_ledger(plan.shape, ledger=ledger)
    if write_file and result.entries:
        result.file = write_seed_file(plan.shape, result.entries, out_dir=out_dir, model=model,
                                      authored_utc=authored_utc)
    return result


def entries_from_ledger(shape: str, *, ledger: "RunLedger | None" = None,
                        ledger_path: "Path | None" = None) -> "list[dict]":
    """Every assembled entry the ledger already holds for `shape`, sorted by entry id — a pure
    resume/flush read distinct from `run_batch`'s own answer-collecting loop, mirroring
    `gemgen.run.entries_from_ledger` exactly."""
    real_ledger = ledger or RunLedger(ledger_path or (COMBINATIONS_DIR / DEFAULT_LEDGER_NAME))
    done = real_ledger.read_done()
    prefix = f"combination-{shape}-"
    rows = [row["entry"] for key, row in done.items()
           if key.startswith(prefix) and isinstance(row, dict) and isinstance(row.get("entry"), dict)]
    return sorted(rows, key=lambda e: e["id"])


def subject_id_for_entry(entry_id: str) -> str:
    """`combo.splice-x-y` (the validator's and the seed file's id) -> `combination-splice-x-y`
    (the ledger key). `emit.combo_id` and `run.Subject.subject_id` differ by exactly that prefix,
    by construction."""
    if not entry_id.startswith("combo."):
        raise ValueError(f"not a combination entry id: {entry_id!r}")
    return "combination-" + entry_id[len("combo."):]


def sync_repair_to_ledger(seed_path: Path, repaired_rows: dict[str, dict[str, Any]], *,
                          write: bool) -> Path | None:
    """Push a direct seed-file repair of a COMBINATION file into the run ledger that owns it.

    ⛔ **Why this exists.** `combinations/*.json` is a full rewrite of `entries_from_ledger` on every
    `run_batch --write`, so a repair that edits only the JSON is silently reverted by the next
    generation run. That is exactly what happened to `fae533a519` (2026-09-13): it renamed 20
    combination entries in the seed file and left `combination-gen.ledger.json` holding the old
    names, so SSH2.5's first `--write` put all 20 back (SSH2.5 finding 1). Every repair module that
    edits a combination row — `naming_grammar_repair`, `setgen.name_repair`, `combogen.grant_repair`
    — routes the change through here.

    `repaired_rows` maps entry id -> the fields that changed (only those are written). Returns the
    ledger path when something changed, else `None`. `write=False` reports without touching disk.
    """
    ledger_path = seed_path.parent / DEFAULT_LEDGER_NAME
    ledger = RunLedger(ledger_path)
    done = ledger.read_done()
    touched = False
    for entry_id, fields in repaired_rows.items():
        row = done.get(subject_id_for_entry(entry_id))
        if not isinstance(row, dict) or not isinstance(row.get("entry"), dict):
            continue
        for key, value in fields.items():
            if row["entry"].get(key) != value:
                row["entry"][key] = value
                touched = True
    if not touched:
        return None
    if write:
        ledger.write_done(done)
    return ledger_path


def reconcile_ledger_from_seed_files(*, out_dir: Path | None = None,
                                     ledger_path: Path | None = None,
                                     write: bool = True) -> dict:
    """One-time, deterministic, model-free alignment: make every persisted ledger row equal the row
    the seed file actually SHIPS.

    ⛔ **Why this is needed and which direction is right.** The file is the validated corpus — the
    artefact `ItemSeedValidator` passes and the game imports. The ledger is only the store
    `entries_from_ledger` rewrites that file FROM on the next `--write`. `fae533a519` (2026-09-13)
    renamed 20 combination entries directly in the seed file and never touched the ledger, so the
    ledger still holds the old, collision-prone names for those rows: any later `run_batch --write`
    silently reverts all 20 (SSH2.5 finding 1, measured again 2026-09-20 as 37 -> 44 validator
    errors). `sync_repair_to_ledger` keeps NEW repairs in step; this reconciles the history that
    predates it. No field is invented and nothing is hand-edited — every byte comes from the seed
    file the generator already wrote.

    Returns `{"updated": n, "ledger": str(path)}`. `write=False` reports without touching disk.
    """
    directory = out_dir or COMBINATIONS_DIR
    path = ledger_path or (directory / DEFAULT_LEDGER_NAME)
    ledger = RunLedger(path)
    done = ledger.read_done()
    updated = 0
    for shape in ("strain", "splice"):
        seed = directory / f"{shape}s.json"
        if not seed.exists():
            continue
        try:
            document = json.loads(seed.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in document.get("entries") or ():
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                continue
            if not row["id"].startswith("combo."):
                continue
            subject = subject_id_for_entry(row["id"])
            current = done.get(subject)
            if not isinstance(current, dict) or current.get("entry") == row:
                continue
            current["entryId"] = row["id"]
            current["entry"] = row
            done[subject] = current
            updated += 1
    if updated and write:
        ledger.write_done(done)
    return {"updated": updated, "ledger": str(path)}


def reemit_entry(entry: dict, tuning) -> dict:
    """One ledger entry, re-emitted through the CURRENT emit shape.

    ⛔ **The model's answers are the input, never the emitted row.** Families (expanded from the row's
    quantities), grants, name, flavor, shape, aptitudes, archetype and the host pins are carried
    across verbatim; `emit.assemble_entry` rebuilds `minSockets` and the ingredient rows, and no tier
    number is written (SSH7.3). Nothing here calls a model: the fields a model authored are already in
    the ledger.
    """
    from . import emit as emit_mod

    families: "list[str]" = []
    for row in entry.get("ingredients") or ():
        families.extend([row["family"]] * int(row.get("quantity", 1)))

    return emit_mod.assemble_entry(
        entry_id=entry["id"],
        name_key=entry["nameKey"],
        name=entry["name"],
        flavor=entry["flavor"],
        shape=entry["shape"],
        aptitudes=tuple(entry.get("aptitudes") or ()),
        archetype=entry.get("archetype"),
        ingredient_families=families,
        grants=list(entry.get("grants") or ()),
        tuning=tuning,
        host_role=entry.get("hostRole"),
        host_frame=entry.get("hostFrame"))


def reemit(shape: str, *, tuning, ledger: "RunLedger | None" = None,
           ledger_path: "Path | None" = None) -> "list[dict]":
    """Every entry the ledger holds for `shape`, re-emitted in the current shape, sorted by id —
    deterministic and idempotent: re-emitting the result produces the same rows byte for byte, so a
    second run plans no change."""
    return [reemit_entry(entry, tuning)
            for entry in entries_from_ledger(shape, ledger=ledger, ledger_path=ledger_path)]
