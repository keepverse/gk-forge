"""seedsmith.adapters.items.setgen.authored — plan -> graph -> priced row -> file, for one batch.

⛔ **What this closes.** Module 13 built the plan, the schema, the distributors, the id minting, the
dedup, the cell metric, the verdict and the ledger, and then recorded one gap: *"the generation graph
is not wired, and `--write` says so instead of writing nothing."* `workflow/graphs/item_set.py` is
that graph; this module is the batch driver that feeds it planned subjects and takes priced rows out
the other end. Nothing here re-implements a rule — every refusal in the report is a string one of
module 13's own functions returned.

⚠ **Its transport is an AUTHORED ANSWER FILE, not an endpoint.** The graph's `call` is injected, so
the same driver runs against `pipeline.llm_caller.call_model` the day a live run happens. What is
built here is the path that works today: the briefs are emitted, a model answers them, and the
answers come back through `answers.replay_caller`. A batch driven this way makes **zero** network
calls and a test asserts it by handing in a raising stub.

⚠ **Every metric in this report is measured over THIS BATCH, not over the corpus.** At batch sizes
below a few hundred the distinctness thresholds are granularity-bound — module 13 already recorded
that a 5‰ near-duplicate rate is unmeasurable at n = 100 — so the report carries the population it
measured beside every number, and `verdict` still refuses to call a held run a pass.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from . import cells, dedup, emit
from .answers import (AnswerExhausted, AnswerFile, AnswerMissing, ReplayTransport,
                      replay_caller)
from .brief import PROMPT_VERSION
from .run import RunPlan, Subject, read_ledger, write_ledger
from .seedfile import (SeedFileMeta, axis_group_map, charm_entry, next_charm_seq, seed_document,
                       load_base_type_candidates, set_entry, write_seed_file)
from .tuning import SetCharmGenTuning
from .verdict import GATING_METRICS, RunReport, Verdict
from .vocab import Vocabulary
from ..charmgen.rules import (CHARM_AXES, axis_gini_permille, min_axis_gini_permille,
                              smallest_measurable_axis_population)
from ..registries import load_versions
from ....pipeline.run_ledger import RunLedger

#: The batch driver never reaches these — they are the graph's, injected at build time. Imported
#: lazily inside `run_batch` so `authored.py` stays importable without the `workflow` extra
#: installed (`pyproject.toml` keeps langgraph in an optional group on purpose).


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
    kind: str
    population: str
    out_dir: Path
    outcomes: "list[SubjectOutcome]" = field(default_factory=list)
    files: "list[Path]" = field(default_factory=list)
    entries: "list[dict]" = field(default_factory=list)
    report: "RunReport | None" = None
    metrics: "dict[str, Any]" = field(default_factory=dict)

    @property
    def persisted(self) -> "list[SubjectOutcome]":
        return [o for o in self.outcomes if o.outcome == "persisted"]

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "population": self.population,
            "outDir": str(self.out_dir),
            "planned": len(self.outcomes),
            "persisted": len(self.persisted),
            "escalated": sum(1 for o in self.outcomes if o.outcome == "escalated"),
            "blocked": sum(1 for o in self.outcomes if o.outcome == "blocked"),
            "files": [str(p) for p in self.files],
            "subjects": [o.to_dict() for o in self.outcomes],
            "metrics": self.metrics,
            "verdict": self.report.to_dict() if self.report is not None else None,
        }


def _partition_of(entry_id: str) -> str:
    """`set.might-offense-001` -> `might-offense`. The partition is the id's own body minus the
    sequence, which is what `naming.v1.json`'s `idTemplate` already says it is."""
    body = entry_id.split(".", 1)[1]
    return body.rsplit("-", 1)[0]


def _merged_partition_rows(path: Path, rows: "list[dict]", *, kind: str,
                           partition: str) -> "list[dict]":
    """Preserve an existing partition while appending this batch's newly minted rows.

    The ledger tracks whether a subject was attempted; the seed file remains the source of truth
    for every row already committed to that partition. A conflicting id is corruption or an
    unsupported rewrite request, so it fails before replacing authored content.
    """
    if not path.exists():
        return rows

    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("kind") != kind:
        raise ValueError(f"{path} is not a {kind} partition")
    meta = document.get("_meta") or {}
    if meta.get("partition") != partition:
        raise ValueError(f"{path} belongs to partition {meta.get('partition')!r}, not {partition!r}")

    merged = {row["id"]: row for row in document.get("entries") or []}
    for row in rows:
        existing = merged.get(row["id"])
        if existing is not None and existing != row:
            raise ValueError(f"{path} already contains a different row for {row['id']!r}")
        merged[row["id"]] = row
    return [merged[entry_id] for entry_id in sorted(merged)]


def _reject_batch_exact_duplicates(result: BatchResult,
                                   rows_by_partition: "dict[str, list[dict]]",
                                   done: "dict[str, dict]",
                                   existing_names: "set[str] | None" = None) -> None:
    """Drop later rows that repeat a name within this batch and terminally advance their subjects.

    The quality report is intentionally measure-only: discovering a duplicate after writing is too
    late, but silently accepting both rows is worse. Keep the first answer in deterministic subject
    order (or the existing corpus row), remove every later duplicate before partition files are
    written, and record an escalated ledger outcome so a resume does not ask the model for the same
    subject forever. Existing legacy duplicates are left for the corpus repair workflow; this guard
    only prevents a new batch from adding another collision.
    """
    first_by_name: "dict[str, str]" = {
        name: "existing corpus" for name in (existing_names or ()) if name
    }
    rejected: "set[str]" = set()
    outcome_by_entry = {o.entry_id: o for o in result.outcomes
                        if o.outcome == "persisted"}
    kept: "list[dict]" = []
    for row in result.entries:
        name = str(row.get("name") or "").strip().casefold()
        entry_id = str(row.get("id") or "")
        first = first_by_name.get(name) if name else None
        if first is not None:
            rejected.add(entry_id)
            outcome = outcome_by_entry.get(entry_id)
            if outcome is not None:
                scope = "existing corpus" if first == "existing corpus" else "this batch"
                defect = f"duplicate name {row.get('name')!r} within {scope}; kept {first!r}"
                outcome.outcome = "escalated"
                outcome.defects.append(defect)
                done[outcome.subject_id] = RunLedger.terminal_row(
                    outcome="escalated", entry_id=entry_id, attempts=outcome.attempts,
                    defects=outcome.defects)
            continue
        if name:
            first_by_name[name] = entry_id
        kept.append(row)

    if not rejected:
        return
    result.entries[:] = kept
    for partition, rows in list(rows_by_partition.items()):
        rows_by_partition[partition] = [row for row in rows if row.get("id") not in rejected]
        if not rows_by_partition[partition]:
            del rows_by_partition[partition]


#: Directories under the item tree that are bookkeeping, not player-facing names. Reading their `entries`
#: would invent collisions rather than prevent them: `_registry` holds vocabularies, `_runs` holds ledgers,
#: `_exemplars` holds shape samples that DELIBERATELY reuse real shipped ids (see `Corpus.add`), and
#: `_seed`/`_tuning` are not corpora at all. The difference between the corpus and the bookkeeping is the
#: whole point, so the bookkeeping is named here rather than filtered by a shape test at every call.
_NON_CORPORA_DIRECTORIES = frozenset({"_registry", "_runs", "_exemplars", "_seed", "_tuning"})


def _name_repair_brief(brief: str, name: str, taken_by: str) -> str:
    """The subject brief plus the specific name the gate refused, shaped for the graph's OWN repair loop.

    ⛔ **A re-ask that does not change the question gets the same answer**, and that is not a hypothesis -
    it is what a live run measured. Three torch-themed species each produced 'Torch of the Stump' across
    two separate runs at `attempts: 1`, and two more each produced 'Burst of Cherry'. The brief was
    byte-identical every time, so the model was asked the identical question and gave the identical answer.

    So the retry names the refused name AND says who holds it: the two facts the model did not have.

    **The shape is the graph's own, deliberately.** `answers.REPAIR_HEADER` with `- ` prefixed lines is
    exactly what `make_generate_node` writes and exactly what `defects_in_prompt` reads back, and it is what
    makes the graph's `attempts` accounting - and therefore the escalation record - keep working. A bespoke
    second protocol would drift from it, which is the same mistake as the two pasted retry loops in
    `run_ledger` and `materialgen` that this programme already had to unpick.

    Only the NAME is asked to change. A re-ask inviting the model to revisit members, thresholds or axis
    would re-roll a shape the brief already states correctly, trading a name collision for a schema defect.
    """
    from .answers import REPAIR_HEADER

    return (
        f"{brief}\n\n{REPAIR_HEADER}\n"
        f"- duplicate name {name!r}: {taken_by}. Author a completely different name; a player scrolling a "
        f"list reads near-identical names as one. Do not reuse that name or a close variant of it.\n"
        f"- Change ONLY the name. Keep the members, thresholds and everything else you already wrote."
    )


def _existing_identity_names(out_dir: Path) -> "set[str]":
    """Read every name already in the item tree, so a new batch cannot ADD a cross-kind duplicate.

    ⛔ Real defect, measured 2026-09-28 by a live run. This used to read only `sets/` and `charms/`, on
    an explicit assumption that gem/base/drop labels *"have separate namespaces and intentionally
    repeat"*. Authoring the 61 empty `sets/*` partitions falsified it: `set.minisnowmonster-001` was
    authored as 'Relic of the Grave', which `gem.g1-029` already held. The in-batch half of the gate
    caught `set.ultimatepumpkin` when it produced the same name, and the cross-kind half could not,
    because gems were outside its namespace - so `SemanticDedup/NearDuplicate` went **4 -> 5** and
    breached the objective's no-regression criterion.

    **The gate was validating against a NARROWER namespace than the metric that judges it.** That is
    the same shape of defect as the `basetypegen` guard that consulted `partition_kind_map()` - a
    partition -> kind map - instead of the registry `check` actually reads. A gate is only as good as its
    population; a narrower population than the metric's makes the gate blind to exactly the collisions
    the metric will report.

    **Widening is measured safe, not assumed.** Across the whole item tree, exactly ONE name is held by
    both a set/charm and another kind - the one this run added. So the widened gate's expected refusal
    rate on a fresh batch is 1 in 1,919 (0.05%). A gate that refused most subjects would be worse than
    the gap it prevents; this one does not.

    **It still does not repair legacy duplicates**, which is correct and unchanged: the gate stops this
    generator from ADDING a collision, and the pre-existing ones stay a corpus-repair question, exactly as
    the previous docstring said. Note the 4 NearDuplicate GAPs the check reported before any of this are
    all *within* `recipe`, not cross-kind - so nothing here is asked to fix those.

    **Registries, plans and exemplars are excluded**, because they are not player-facing names and
    counting them would invent collisions that do not exist: `_registry` (vocabularies), `_runs`
    (ledgers), `_exemplars` (shape samples, which deliberately reuse real ids), `_seed` and `_tuning`.
    Excluding them is the difference between reading the corpus and reading the bookkeeping.

    A normal retry never reaches this guard for an existing row - `plan_run` skips corpus ids already
    present on disk - so including the target directory cannot break idempotent resume, and it is what
    stops a new subject from reusing an old name.
    """
    names: "set[str]" = set()
    root = out_dir.parent
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        if directory.name in _NON_CORPORA_DIRECTORIES:
            continue
        for path in directory.glob("*.json"):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(document, dict):
                continue
            for row in document.get("entries") or ():
                name = row.get("name") if isinstance(row, dict) else None
                if isinstance(name, str) and name.strip() and "{" not in name:
                    names.add(name.strip().casefold())
    return names


def run_batch(*, plan: RunPlan, answers: AnswerFile, tuning: SetCharmGenTuning,
              vocabulary: Vocabulary, out_dir: Path, kind: str, population: str,
              authored_utc: str, model: str,
              ledger_path: "Path | None" = None,
              call: "Callable[..., str] | None" = None,
              corpus_root: "Path | None" = None,
              max_name_attempts: int = 3) -> BatchResult:
    """Drive one planned batch through the graph and write what survived.

    `call` defaults to the replay transport over `answers`; a test hands in a raising stub to prove
    the path makes no live call.
    """
    from ....workflow.graphs.item_set import (build_item_set_graph, jewel_minor_for, plan_for_charm,
                                              plan_for_set, state_for_item)
    from ....workflow.runner import run_one
    from .schema import charm_schema, set_schema

    # ⚠ The same `member_count` `run.plan_run` briefed. The schema's threshold ladder is derived
    # from it, so a schema built on a different size would refuse answers the brief asked for —
    # which is the shape of the defect this parameter closes.
    schema = (set_schema(tuning, vocabulary=vocabulary, member_count=tuning.typical_members) if kind == "set"
              else charm_schema(tuning))
    briefs = {s.subject_id: s.brief for s in plan.subjects}
    caller = call if call is not None else replay_caller(briefs, answers)
    jewel_minor = jewel_minor_for(tuning, vocabulary) if kind == "charm" else frozenset()

    drafts: "dict[str, dict]" = {}

    def on_persist(subject_id: str, draft: dict) -> None:
        drafts[subject_id] = draft

    app = build_item_set_graph(kind=kind, schema=schema, on_persist=on_persist, call=caller)

    result = BatchResult(kind=kind, population=population, out_dir=out_dir)
    axis_groups = axis_group_map()
    base_type_candidates = (load_base_type_candidates(corpus_root=corpus_root)
                            if kind == "set" else None)
    seq_by_group: "dict[str, int]" = {}
    rows_by_partition: "dict[str, list[dict]]" = {}
    done: "dict[str, dict]" = {}
    existing_names = _existing_identity_names(out_dir)

    for subject in plan.subjects:
        if isinstance(caller, ReplayTransport):
            # ⛔ Subjects are driven one at a time, so the transport is TOLD which one it is
            # answering rather than inferring it from the prompt. Two subjects built from the same
            # theme have byte-identical briefs (module 13 guarantees it), and prefix matching alone
            # would serve one subject's answer as the other's.
            caller.current_subject_id = subject.subject_id
        state = state_for_item(subject, tuning=tuning, vocabulary=vocabulary, schema=schema)
        try:
            final = run_one(app, state)
        except (AnswerMissing, AnswerExhausted) as exc:
            # ⛔ One subject running out of authored attempts escalates THAT SUBJECT, never the
            # batch. A transport error that aborts the loop loses every row already priced and
            # tells the caller nothing about the other subjects — the same reason `run_many`
            # catches per-subject rather than letting one failure end the fan-out.
            defects = list(getattr(exc, "defects", ())) or [str(exc)]
            attempts = len(answers.attempts_for(subject.subject_id))
            result.outcomes.append(SubjectOutcome(
                subject_id=subject.subject_id, entry_id=subject.entry_id, outcome="escalated",
                attempts=attempts, defects=defects))
            # Presence alone advances set/charm resume — escalate must not re-hit forever.
            done[subject.subject_id] = RunLedger.terminal_row(
                outcome="escalated", entry_id=subject.entry_id, attempts=attempts,
                defects=defects)
            continue
        except RuntimeError as exc:
            # The live transport reports endpoint/timeout/HTTP failures as RuntimeError. Keep the
            # per-subject isolation contract for those transient failures too: one dead request
            # must not discard every other completed subject in this batch, and the terminal ledger
            # row makes the failure visible without retrying it forever on the next fill.
            attempts = len(answers.attempts_for(subject.subject_id))
            defects = [f"{type(exc).__name__}: {exc}"]
            result.outcomes.append(SubjectOutcome(
                subject_id=subject.subject_id, entry_id=subject.entry_id, outcome="escalated",
                attempts=attempts, defects=defects))
            done[subject.subject_id] = RunLedger.terminal_row(
                outcome="escalated", entry_id=subject.entry_id, attempts=attempts,
                defects=defects)
            continue
        draft = drafts.pop(subject.subject_id, None)
        attempts = int(final.get("attempts", 0))
        defects = list(final.get("defects") or [])

        # ⛔ Real gap, measured 2026-09-28 on a live run. A NAME collision was TERMINAL, and the pattern
        # was deterministic rather than random: three torch-themed species each returned 'Torch of the
        # Stump' on two separate runs at `attempts: 1`, and two more each returned 'Burst of Cherry'. Those
        # 6 partitions stayed empty across every run.
        #
        # **The root cause is PHASE ORDERING, not a wrong selector.** An earlier commit blamed
        # `--retry-blocked`, which selects only `blocked` subjects - true, and the wrong remedy, because
        # that is a PLAN-TIME re-brief which throws away the answer already paid for. The real reason is
        # that a collision is only detectable against the entries ALREADY WRITTEN, so it used to be caught
        # by `_reject_batch_exact_duplicates` AFTER the graph had produced the whole answer set - leaving
        # the graph no attempt to give. The repair mechanism already exists and was simply never told.
        #
        # **So this hands the collision to the graph's OWN repair loop** rather than building a second one,
        # exactly as SS-F26 says. `run_one` is re-driven with a subject whose brief carries the defect in
        # the shape the graph already understands, so the existing machinery asks again with the refusal in
        # front of it. Asking the identical question again is what produced 'Torch of the Stump' three
        # times. `max_name_attempts=0` reproduces the pre-fix behaviour, which is what makes the fix
        # testable rather than merely assertable.
        if draft is not None and max_name_attempts > 0:
            for _ask in range(max_name_attempts):
                name = str(draft.get("name") or "").strip()
                key = name.casefold()
                already_claimed = any(
                    str(row.get("name") or "").strip().casefold() == key
                    for rows in rows_by_partition.values() for row in rows)
                in_corpus = key in existing_names
                if not (name and (already_claimed or in_corpus)):
                    break
                taken_by = ("an earlier subject in this same batch" if already_claimed
                            else "another entry already in the corpus")
                repaired = replace(subject, brief=_name_repair_brief(subject.brief, name, taken_by))
                try:
                    final = run_one(app, state_for_item(repaired, tuning=tuning,
                                                        vocabulary=vocabulary, schema=schema))
                except (AnswerMissing, AnswerExhausted, RuntimeError):
                    # The re-ask itself failed. Keep the ORIGINAL draft and let the post-pass refusal report
                    # the collision, so the recorded defect is the collision rather than a transport error
                    # that hides why the retry was needed.
                    break
                retry_draft = drafts.pop(subject.subject_id, None)
                if retry_draft is None:
                    break
                draft = retry_draft
                attempts = int(final.get("attempts", 0))
        # No defect is appended here on purpose: `_reject_batch_exact_duplicates` stays the authority that
        # refuses a still-colliding name and escalates the subject with a named reason. This loop's only
        # job is to give the graph the chance to produce a different name first.

        if draft is None:
            result.outcomes.append(SubjectOutcome(
                subject_id=subject.subject_id, entry_id=subject.entry_id,
                outcome="escalated", attempts=attempts, defects=defects))
            done[subject.subject_id] = RunLedger.terminal_row(
                outcome="escalated", entry_id=subject.entry_id, attempts=attempts,
                defects=defects)
            continue
        # Charm axis is a deterministic coverage assignment. The model still supplies the
        # theme-specific families and wording, but its free-form axis choice must not undo the
        # planner's balancing decision. The hint is embedded by build_charm_brief and parsed here
        # so the graph/schema remains shared with replay and set generation.
        if kind == "charm":
            match = re.search(r"use axis `([^`]+)`", subject.brief)
            if match:
                draft["axis"] = match.group(1)
            if subject.charm_class_hint:
                draft["charmClass"] = subject.charm_class_hint
        if isinstance(draft.get("blocked"), str) and draft["blocked"].strip():
            reason = draft["blocked"].strip()
            result.outcomes.append(SubjectOutcome(
                subject_id=subject.subject_id, entry_id=subject.entry_id,
                outcome="blocked", attempts=attempts, blocked_reason=reason))
            # Presence alone advances set/charm resume; no seed row for a decline.
            done[subject.subject_id] = RunLedger.terminal_row(
                outcome="blocked", entry_id=subject.entry_id, attempts=attempts,
                blocked_reason=reason)
            continue

        entry_id, row = _row_for(
            subject=subject, draft=draft, kind=kind, tuning=tuning, vocabulary=vocabulary,
            jewel_minor=jewel_minor, axis_groups=axis_groups, seq_by_group=seq_by_group,
            corpus_root=corpus_root, plan_for_set=plan_for_set, plan_for_charm=plan_for_charm,
            base_type_candidates=base_type_candidates)

        rows_by_partition.setdefault(_partition_of(entry_id), []).append(row)
        result.entries.append(row)
        result.outcomes.append(SubjectOutcome(
            subject_id=subject.subject_id, entry_id=entry_id,
            outcome="persisted", attempts=attempts))
        done[subject.subject_id] = {"entryId": entry_id, "attempts": attempts}

    _reject_batch_exact_duplicates(result, rows_by_partition, done, existing_names)
    versions = load_versions()
    for partition, rows in sorted(rows_by_partition.items()):
        meta = SeedFileMeta(
            batch=f"{kind}-gen-{partition}", partition=f"{kind}s/{partition}",
            prompt_version=PROMPT_VERSION, model=model, authored_utc=authored_utc,
            source_ref="docs/architecture/item/spec-set-charm-gen.md",
            registry_versions=versions)
        target = out_dir / f"{partition}.json"
        merged_rows = _merged_partition_rows(
            target, rows, kind=kind, partition=f"{kind}s/{partition}")
        result.files.append(write_seed_file(out_dir, f"{partition}.json",
                                            seed_document(kind, merged_rows, meta)))

    result.metrics, result.report = _measure(result.entries, kind=kind, tuning=tuning,
                                             held=[key for key, _ in plan.held])
    if ledger_path is not None and done:
        # ⛔ Real incident, 2026-09-08: `done` starts empty on every call — it only ever holds
        # THIS batch's newly-persisted subjects, never `plan.already_done`'s. A resumed run that
        # (correctly) skips already-done subjects never re-adds them here, so a plain overwrite
        # erased every earlier run's ledger entries — their seed files stayed on disk untouched,
        # but a THIRD run would see them as never-generated and redo (and overwrite) them. Merged
        # with whatever is already on disk instead: this batch's own entries win on a genuine
        # collision, but nothing an earlier batch already recorded is lost.
        write_ledger({**read_ledger(ledger_path), **done}, ledger_path)
    return result


def _row_for(*, subject: Subject, draft: dict, kind: str, tuning, vocabulary, jewel_minor,
             axis_groups, seq_by_group, corpus_root, plan_for_set, plan_for_charm,
             base_type_candidates=None):
    if kind == "set":
        priced = plan_for_set(draft, tuning=tuning, vocabulary=vocabulary)
        return subject.entry_id, set_entry(entry_id=subject.entry_id, theme_key=subject.theme_key,
                                           draft=draft, plan=priced,
                                           base_type_candidates=base_type_candidates,
                                           species_id=subject.species_id or None)

    priced = plan_for_charm(draft, tuning=tuning, vocabulary=vocabulary,
                            jewel_minor_families=jewel_minor)
    group = axis_groups[priced.axis]
    if group not in seq_by_group:
        seq_by_group[group] = next_charm_seq(
            group, corpus_root=(corpus_root / "charms") if corpus_root else None)
    entry_id = emit.charm_id(group, seq_by_group[group])
    seq_by_group[group] += 1
    return entry_id, charm_entry(entry_id=entry_id, theme_key=subject.theme_key,
                                 draft=draft, plan=priced)


def _measure(entries: "list[dict]", *, kind: str, tuning: SetCharmGenTuning,
             held: "list[str]") -> "tuple[dict[str, Any], RunReport]":
    """The batch's own distinctness numbers, and the verdict that refuses to launder them.

    ⚠ A gate whose population is empty reports NOT_MEASURED, never a pass — `verdict.py`'s whole
    argument. A gate belonging to the other kind is likewise not measured here rather than
    silently cleared.
    """
    report = RunReport(held_partitions=list(held))
    names = {e["id"]: e["name"] for e in entries}
    dedup_report = dedup.dedup_report(names)
    metrics: "dict[str, Any]" = {
        "population": len(entries),
        "exactDuplicateNames": len(dedup_report.exact_duplicates),
        "nearDuplicatePairs": [
            {"a": names[p.a], "b": names[p.b], "jaccardPermille": p.jaccard_permille}
            for p in dedup_report.near_duplicates],
        "nearDuplicateRatePermille": dedup_report.rate_permille,
    }
    report.record("SemanticDedup/ExactDuplicateName", ran=bool(entries),
                  cleared=len(dedup_report.exact_duplicates) <= tuning.exact_duplicate_names_max,
                  detail=f"{len(dedup_report.exact_duplicates)} exact over {len(entries)} entries")
    report.record("SemanticDedup/NearDuplicate", ran=bool(entries),
                  cleared=dedup_report.rate_permille <= tuning.near_duplicate_rate_max_permille,
                  detail=(f"{len(dedup_report.near_duplicates)} pairs, "
                          f"{dedup_report.rate_permille}permille over {len(entries)} entries "
                          f"(granularity-bound below ~200 entries)"))

    if kind == "set":
        cell = cells.cell_report(entries)
        metrics["cells"] = {
            "cells": cell.cells, "median": cell.median, "max": cell.maximum,
            "singletons": cell.singletons,
            "singletonSharePermille": cell.singleton_share_permille,
            "capabilityUsage": [{"capability": c, "count": n} for c, n in cell.capability_usage],
        }
        report.record("Distribution/CellOccupancy", ran=cell.cells > 0,
                      cleared=cell.within(tuning.median_cell_occupancy_max),
                      detail=(f"{cell.population} sets over {cell.cells} cells: median "
                              f"{cell.median} (threshold <= {tuning.median_cell_occupancy_max}), "
                              f"max {cell.maximum}, singletons {cell.singletons}"))
        report.record("Distribution/Inequality:charm-axis", ran=False, cleared=False,
                      detail="no charm in this batch")
    else:
        axes = [e["axis"] for e in entries if "axis" in e]
        gini = axis_gini_permille(axes)
        floor = min_axis_gini_permille(len(axes))
        counts: "dict[str, int]" = {}
        for axis in axes:
            counts[axis] = counts.get(axis, 0) + 1
        metrics["axis"] = {"gini": gini, "counts": counts, "floorAtThisPopulation": floor,
                           "distinctAxes": len(counts)}
        # ⚠ The floor is printed beside the measurement for the same reason the near-duplicate row
        # carries "granularity-bound": below five charms the ceiling is unreachable at ANY
        # diversity, so a bare "400 against 133" reads as a collapse when it is the flattest a
        # batch this size can be. `cleared` is still the real comparison — nothing is softened.
        reachable_at = smallest_measurable_axis_population(tuning.charm_axis_gini_max_permille)
        reach = ("" if floor <= tuning.charm_axis_gini_max_permille
                 else f"; the ceiling is unreachable below {reachable_at} charms")
        report.record("Distribution/Inequality:charm-axis", ran=bool(axes),
                      cleared=gini <= tuning.charm_axis_gini_max_permille,
                      detail=(f"axis Gini {gini}permille over {len(axes)} charms on "
                              f"{len(counts)} of {len(CHARM_AXES)} axes "
                              f"(ceiling {tuning.charm_axis_gini_max_permille}, floor at this "
                              f"population {floor}{reach})"))
        report.record("Distribution/CellOccupancy", ran=False, cleared=False,
                      detail="cell occupancy is a set metric; no set in this batch")

    report.record("Linkage/SetCompletability", ran=False, cleared=False,
                  detail=("a corpus metric over data/seed/items — a batch written outside that "
                          "tree cannot move it; run `seedsmith check` after a production write"))
    assert set(GATING_METRICS) == {o.metric for o in report.outcomes}, (
        "every gating metric must appear in the run report, even when it did not run")
    return metrics, report


def verdict_of(result: BatchResult) -> Verdict:
    return result.report.verdict if result.report is not None else Verdict.NOT_MEASURED
