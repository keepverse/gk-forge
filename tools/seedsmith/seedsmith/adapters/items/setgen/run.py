"""seedsmith.adapters.items.setgen.run — the run plan, the resume ledger, and the dry run.

⚠ **What this module does and does not do.** It assembles the whole run *deterministically*: which
themes are in, which are held and why, the brief for each, the id each entry will take, and the
ledger that makes an interrupted run resumable. The **model call itself is not made here** — the
graph that makes it is the same `workflow` package `effects generate` and `creatures generate` use, and
this module hands it a subject list. A `--dry-run` therefore exercises everything except the call,
which is what makes the run inspectable before a token is spent.

⛔ **Resume is not optional at ~1,800 entries.** The ledger is a single JSON file keyed by subject
id, written after each subject completes. `plan_run` reads it and returns only the subjects not
already done — so re-running is idempotent and an interrupt costs the work in flight, not the run.
The creature harness's own resume path holds a real atomic file lock; this ledger reuses that
discipline by writing through a temporary file and replacing, so a killed process cannot leave a
half-written ledger behind.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ....pipeline.llm_caller import LlmCallerConfig, call_model
from . import brief as brief_mod
from . import emit, themes as themes_mod
from .themes import Theme
from .tuning import SetCharmGenTuning
from .vocab import Vocabulary

REPO_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_LEDGER = REPO_ROOT / "data" / "seed" / "items" / "_runs" / "set-charm-gen.ledger.json"
DEFAULT_SETS_DIR = REPO_ROOT / "data" / "seed" / "items" / "sets"
DEFAULT_CHARMS_DIR = REPO_ROOT / "data" / "seed" / "items" / "charms"


def _existing_charm_axis_counts(directory: Path = DEFAULT_CHARMS_DIR) -> dict[str, int]:
    """Measure authored charm axes for deterministic least-populated assignment."""
    counts: dict[str, int] = {}
    if not directory.is_dir():
        return counts
    for path in directory.glob("*.json"):
        if "ledger" in path.name:
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in document.get("entries") or ():
            axis = row.get("axis") if isinstance(row, dict) else None
            if isinstance(axis, str) and axis:
                counts[axis] = counts.get(axis, 0) + 1
    return counts


def _existing_charm_class_counts(directory: Path = DEFAULT_CHARMS_DIR) -> dict[str, int]:
    """Measure authored charm classes for deterministic weighted assignment."""
    counts: dict[str, int] = {}
    if not directory.is_dir():
        return counts
    for path in directory.glob("*.json"):
        if "ledger" in path.name:
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in document.get("entries") or ():
            charm_class = row.get("charmClass") if isinstance(row, dict) else None
            if isinstance(charm_class, str) and charm_class:
                counts[charm_class] = counts.get(charm_class, 0) + 1
    return counts


def _least_represented_charm_class(tuning: SetCharmGenTuning,
                                   counts: "dict[str, int]") -> str:
    """Choose the smallest actual/target-weight ratio using integer cross multiplication.

    Charm class determines AP cost, rolls and unique-carry semantics.  It cannot be a free model
    choice: the model is asked for identity, while this makes the corpus' scarce top tier a
    deterministic tuned allocation.  Ties retain tuning-file order for reproducible plans.
    """
    best = tuning.charm_classes[0]
    for candidate in tuning.charm_classes[1:]:
        if counts.get(candidate.id, 0) * best.target_weight < \
                counts.get(best.id, 0) * candidate.target_weight:
            best = candidate
    return best.id


def _set_entry_on_disk(entry_id: str, *, sets_dir: "Path | None" = None) -> bool:
    """True when the production (or test) sets corpus already carries this id.

    Ledger subject keys can drift when a theme/species id is renamed (e.g. creature.caltrop →
    creature.caltropnut) while the partition file still holds the minted set id. Re-planning that
    theme then regenerates a different row for the same id and `_merged_partition_rows` raises.
    Corpus presence wins — same discipline materialgen uses for hand-authored rows without a
    ledger record.
    """
    if not isinstance(entry_id, str) or "." not in entry_id:
        return False
    body = entry_id.split(".", 1)[1]
    partition = body.rsplit("-", 1)[0]
    path = (sets_dir or DEFAULT_SETS_DIR) / f"{partition}.json"
    if not path.exists():
        return False
    document = json.loads(path.read_text(encoding="utf-8"))
    return any(isinstance(row, dict) and row.get("id") == entry_id
               for row in (document.get("entries") or []))


def live_caller(live_config: LlmCallerConfig) -> "Callable[..., str]":
    """A `call(system, user, *, config, schema)` that reaches a REAL model endpoint through
    `pipeline.llm_caller.call_model`, bound to `live_config` at build time (module 13,
    `set-charm-live-endpoint`) — the transport `answers.replay_caller`'s own docstring already said
    a live run would use "the day a live run happens." That day is this module.

    Same shape `answers.ReplayTransport.__call__` already satisfies: `workflow.nodes.generate`'s
    `generate_node` calls whichever `call` it was handed as `caller(system, user, config=config,
    schema=schema)`, where `config` is whatever `build_item_set_graph` was itself built with
    (`None` unless a caller supplied one, in which case the transport resolves `.env`/
    `seedsmith.toml`/built-in defaults at call time — no adapter carries its own model id).
    This transport accepts that incoming `config` for shape parity only and ignores
    it: the endpoint/model/timeout a live run actually talks to is `live_config`, decided once at
    the CLI from `--endpoint`/`--model`, not whatever the graph's unrelated default happens to be.
    """

    def _call(system: str, user: str, *, config: "LlmCallerConfig | None" = None,
              schema: "dict | None" = None) -> str:  # noqa: ARG001 - config kept for shape parity
        return call_model(system, user, config=live_config, schema=schema)

    return _call


@dataclass(frozen=True)
class Subject:
    """One unit of work: one theme, one kind, one id already decided."""

    subject_id: str
    kind: str               # "set" | "charm"
    population: str         # "species" | "build"
    theme_key: str
    entry_id: str
    brief: str
    charm_class_hint: str = ""
    # species-gear-chain T27 (set-species-binding a) — the theme's OWN speciesId (lower-case,
    # runtime-catalog spelling, per spec-set-species-binding.md Open question 2a), carried from
    # `Theme.species_id` through to the persisted entry. Empty for a `population == "build"`
    # subject, which the emitter reads as explicit absence, never a guess.
    species_id: str = ""

    def to_dict(self) -> dict:
        row = {"subjectId": self.subject_id, "kind": self.kind, "population": self.population,
               "themeKey": self.theme_key, "entryId": self.entry_id}
        if self.charm_class_hint:
            row["charmClass"] = self.charm_class_hint
        return row


@dataclass
class RunPlan:
    subjects: "list[Subject]"
    held: "list[tuple[str, str]]"
    already_done: "list[str]"

    @property
    def complete(self) -> bool:
        """True only when there is neither pending work nor a held subject.

        Previously this checked only ``held``. That made a build plan with one or more subjects
        report ``complete: true`` and obscured interrupted or partially drained runs in the CLI.
        """
        return not self.subjects and not self.held

    def summary(self) -> dict:
        by_reason: "dict[str, int]" = {}
        for _, reason in self.held:
            by_reason[reason] = by_reason.get(reason, 0) + 1
        return {"toGenerate": len(self.subjects), "alreadyDone": len(self.already_done),
                "held": len(self.held), "heldByReason": by_reason, "complete": self.complete}


def read_ledger(path: "Path | None" = None) -> "dict[str, dict]":
    ledger_path = path or DEFAULT_LEDGER
    if not ledger_path.exists():
        return {}
    doc = json.loads(ledger_path.read_text(encoding="utf-8"))
    return dict(doc.get("done") or {})


def write_ledger(done: "dict[str, dict]", path: "Path | None" = None) -> Path:
    """Atomic replace. A killed process leaves either the old ledger or the new one, never half of
    one — which is the difference between a resumable run and a corrupt one."""
    ledger_path = path or DEFAULT_LEDGER
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"schemaVersion": 1, "done": done}, ensure_ascii=False, indent=2) + "\n"
    handle, tmp_name = tempfile.mkstemp(dir=str(ledger_path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
        os.replace(tmp_name, ledger_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return ledger_path


#: Outcomes a run ledger records that mean the subject was **NOT** emitted. `escalated` is written so
#: the fill walker can keep walking without paying for the subject again, and `blocked` is the model
#: declining it. A row carrying either is a record of work that did not happen and must never be read as
#: `already_done`. Anything else -- including the **absent** key, which is what 876 of the real ledger's
#: 937 rows carry -- is treated as a persisted claim, so a row this vocabulary has not heard of is
#: believed rather than re-paid for. Growing this set is a deliberate act; silently re-planning on an
#: unknown word would turn every future vocabulary addition into a silent re-run.
NON_PERSISTED_OUTCOMES = frozenset({"escalated", "blocked"})


def _row_claims_a_written_row(row: "Mapping[str, Any] | None") -> bool:
    """True when a ledger row asserts that the subject's row was actually written.

    Measured on the real `sets` ledger (2026-09-28): 937 rows, 876 persisted, 59 `escalated`,
    2 `blocked` -- and the 60 `species-no-set-entry` subjects are exactly the escalated and blocked
    species rows. So this predicate, not a filesystem probe, is what makes those 60 schedulable again.
    """
    outcome = str((row or {}).get("outcome") or "persisted").strip().lower()
    return outcome not in NON_PERSISTED_OUTCOMES


def plan_run(*, kind: str, population: str, tuning: SetCharmGenTuning, vocabulary: Vocabulary,
             species_themes: "list[Theme] | None" = None,
             build_themes: "list[Theme] | None" = None,
             ledger: "dict[str, dict] | None" = None,
             legacy_partitions: "frozenset[str] | None" = None,
             sets_dir: "Path | None" = None,
             reconcile: bool = False) -> RunPlan:
    """Plan the subjects a `set`/`charm` run still owes.

    `reconcile=False` (the default, and unchanged from before 2026-09-28) means **a ledger row is
    honoured as done**, which is what makes a resume cheap and idempotent — and two existing tests pin
    exactly that contract, including the case where no corpus row is present at all.

    `reconcile=True` additionally requires the emitted entry to be **on disk** before a ledger row is
    believed, so a ledger that outlived its corpus rows re-plans them. Measured need: all 60
    `species-no-set-entry` subjects are claimed done in `gk-data/packs/fusion/data/seed/items/sets/set-charm-gen.ledger.json`
    as `set-species-creature.<slug>` while **0** of their 60 entry ids appear in any of the 885 shipped
    sets files — 60 real themed species, permanently unschedulable, reported as `complete: true`.

    It is a flag rather than the default because a silent re-plan is a change to the resume contract,
    and because a caller isolating with a temporary `sets_dir` means *"not on disk" = isolated*, not
    *deleted*. Turning it on belongs to whoever knows the corpus is authoritative — the same shape as
    the existing `items repair-*` family.
    """
    if kind not in ("set", "charm"):
        raise ValueError(f"kind must be 'set' or 'charm', got {kind!r}")
    if population not in ("species", "build"):
        raise ValueError(f"population must be 'species' or 'build', got {population!r}")
    if kind == "charm" and population == "build":
        # Charms are per species by D12's own grid; there is no build charm population, and
        # inventing one here would be a design decision wearing a CLI flag.
        raise ValueError("there is no build charm population — charms are one per species")

    pool = (species_themes if species_themes is not None else themes_mod.load_species_themes()) \
        if population == "species" else \
        (build_themes if build_themes is not None else themes_mod.load_build_themes())
    partitions = (legacy_partitions if legacy_partitions is not None
                  else themes_mod.legacy_partition_ids())
    done = ledger if ledger is not None else read_ledger()

    subjects: "list[Subject]" = []
    already: "list[str]" = []
    planned_entry_ids: dict[str, str] = {}
    report = themes_mod.holdback_report(pool)
    charm_axes = ()
    if kind == "charm":
        from ..charmgen.rules import CHARM_AXES
        charm_axes = tuple(CHARM_AXES)
    axis_counts = _existing_charm_axis_counts() if kind == "charm" else {}
    class_counts = _existing_charm_class_counts() if kind == "charm" else {}

    for theme in pool:
        if theme.hold_reason:
            continue
        subject_id = f"{kind}-{population}-{theme.theme_key}"
        entry_id = _entry_id(kind, population, theme, partitions)
        if subject_id in done and _row_claims_a_written_row(done[subject_id]):
            # ⛔ **The guard was `if subject_id in done:` -- the ledger's mere PRESENCE -- and that is
            # wrong. Fixed 2026-09-28.**
            #
            # A run ledger records more than success. The real `sets` ledger holds **937** rows: **876**
            # persisted and **61 not** -- 59 `escalated`, 2 `blocked`. Both words mean the work did NOT
            # happen: an escalation is recorded precisely so the fill walker can keep walking without
            # paying for it again, and a block is the model declining the subject. Reading either as
            # "already emitted" reads a record of a failure as a record of a success.
            #
            # Measured consequence: all **60** `species-no-set-entry` subjects are exactly the escalated
            # and blocked species rows (the 61st non-persisted row is the build subject
            # `set-build-build.might-offense`), so `items fill --kind set --full --dry-run` reported
            # `toGenerate 0 | ledgered 937 | complete true` -- no work at all -- while
            # `ISG-gap-2-per-partition.json` counted the same 60 partitions empty. Two views,
            # contradictory, and neither pointing at the ledger.
            #
            # This predicate needs no filesystem read, so it cannot be confused by a caller isolating
            # with a temporary `sets_dir` -- which is what broke the first attempt at this fix, where the
            # corpus check was made unconditional and two tests that pin the resume contract failed.
            #
            # `reconcile=True` remains the safety net for the OTHER direction: a row that claims
            # persisted whose file was hand-deleted (`materialgen`'s
            # `test_reconcile_replans_a_hand_deleted_row` covers that case). It stays opt-in because
            # honouring a persisted claim is what makes a resume cheap, and a caller pointing
            # `--sets-dir` elsewhere means "not on disk" is *isolated*, not *deleted*. `items
            # repair-ledger` is its command-line counterpart.
            if (not reconcile) or kind != "set" or _set_entry_on_disk(entry_id, sets_dir=sets_dir):
                already.append(subject_id)
                continue
        if kind == "set" and entry_id in planned_entry_ids:
            other = planned_entry_ids[entry_id]
            raise ValueError(
                f"species ids {other!r} and {theme.species_id!r} normalise to the same set id "
                f"{entry_id!r}; refusing an ambiguous plan")
        if kind == "set":
            planned_entry_ids[entry_id] = theme.species_id or ""
        if kind == "set" and _set_entry_on_disk(entry_id, sets_dir=sets_dir):
            already.append(subject_id)
            continue
        assigned_class = ""
        if kind == "charm":
            assigned_class = _least_represented_charm_class(tuning, class_counts)
        text = (brief_mod.build_set_brief(theme, tuning, vocabulary) if kind == "set"
                else brief_mod.build_charm_brief(
                    theme, tuning, vocabulary,
                    axis_hint=(min(charm_axes, key=lambda axis: (axis_counts.get(axis, 0),
                                                                  charm_axes.index(axis)))
                               if charm_axes else None),
                    class_hint=assigned_class or None))
        if kind == "charm" and charm_axes:
            assigned_axis = min(charm_axes, key=lambda axis: (axis_counts.get(axis, 0),
                                                               charm_axes.index(axis)))
            axis_counts[assigned_axis] = axis_counts.get(assigned_axis, 0) + 1
            class_counts[assigned_class] = class_counts.get(assigned_class, 0) + 1
        subjects.append(Subject(subject_id=subject_id, kind=kind, population=population,
                                theme_key=theme.theme_key, entry_id=entry_id, brief=text,
                                charm_class_hint=assigned_class,
                                species_id=theme.species_id or ""))

    return RunPlan(subjects=subjects, held=list(report.held), already_done=already)


def _entry_id(kind: str, population: str, theme: Theme,
              partitions: "frozenset[str]") -> str:
    if kind == "charm":
        # The axis group is not known until the model picks the axis, so a charm's id is minted at
        # persist time, not at plan time. Recording the species keeps the plan readable without
        # pretending to know an id it cannot know yet.
        return f"charm.(axis-group)-NNN for {theme.species_id}"
    if population == "build":
        return emit.build_set_id(theme.aptitude or "", theme.archetype or "", 1)
    return emit.set_id(theme.species_id or "", 1, legacy_partitions=partitions)
