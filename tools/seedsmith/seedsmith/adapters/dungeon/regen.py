"""Legacy Delve event regeneration — the READ-ONLY planning half (NS13, spec-dungeon-generator-repair §8).

The §8 run regenerates every committed legacy event **under its own id**: `eventPool` references in the wild
rooms' files keep resolving (measured: `gk-data/packs/fusion/data/seed/dungeon/rooms/room.wild-air-001.json` names the four
committed `story` events), the `story` events keep their committed `chainRef` (which the legacy contract
forces to dangle at the tail — owner ruling 2026-09-20), and the collision check must not compare an event
against its own old name.

This module owns the planning half only: load the committed tree, rebuild its kind × theme cells, reuse the
committed ids, collect the committed story chain refs, and report the call bounds **before anything is
spent** (`docs/research/ai-native-generation/README.md` §9: one base call per event, worst
`1 + MAX_QUALITY_RETRY`). It makes no model call at all — the draw/review/commit wiring is the driver's next
half, and `plan_legacy_regen` is what a dry run prints.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...workspace_roots import content_root
from .pipelines import MAX_QUALITY_RETRY, run_event_draws
from .planner import Cell

__all__ = [
    "EVENTS_REL",
    "RegenPlan",
    "RegenRun",
    "load_committed_events",
    "plan_legacy_regen",
    "render_plan",
    "load_run",
    "latest_run_id",
]

EVENTS_REL = "data/seed/dungeon/events"


@dataclass(frozen=True)
class RegenPlan:
    """Everything a regeneration run needs, and nothing it does not: the batch's cells and ids, the
    committed chain refs to carry over, the collision set, and the call bounds."""

    events: "Mapping[str, dict]"
    cells: "tuple[Cell, ...]"
    planned_ids_by_cell: "Mapping[str, list[str]]"
    committed_chain_refs: "Mapping[str, str]"
    existing_names: "tuple[str, ...]"
    base_calls: int
    worst_calls: int

    @property
    def event_ids(self) -> "tuple[str, ...]":
        return tuple(sorted(self.events))


def _events_dir(events_dir: "Path | str | None") -> Path:
    if events_dir is not None:
        return Path(events_dir)
    return content_root() / EVENTS_REL


def load_committed_events(events_dir: "Path | str | None" = None) -> "dict[str, dict]":
    """Every committed event file, by `eventId`, read fresh on each call (`_index.json` excluded — it is
    a filename map, not an entry)."""
    directory = _events_dir(events_dir)
    events: "dict[str, dict]" = {}
    for path in sorted(directory.glob("event.*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        event_id = doc.get("eventId")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError(f"{path}: committed event has no eventId")
        events[event_id] = doc
    return events


def plan_legacy_regen(events_dir: "Path | str | None" = None, *,
                      ids: "Sequence[str] | None" = None) -> RegenPlan:
    """Plan the run for the whole committed tree, or only for `ids`.

    The batch keeps its COMMITTED ids (`gk-data/packs/fusion/data/seed/dungeon/rooms/*.json`'s `eventPool` entries, and the
    legacy `chainRef` links between `story` events, both name them), and `existing_names` holds the names
    of every event OUTSIDE the batch — so a regenerated event is never compared against its own old name
    (spec §8) while still colliding against the rest of the tree.
    """
    events = load_committed_events(events_dir)
    if ids is not None:
        unknown = [eid for eid in ids if eid not in events]
        if unknown:
            raise ValueError(f"{unknown} are not committed legacy events")
        batch = {eid: events[eid] for eid in ids}
    else:
        batch = dict(events)

    dimensions: "dict[str, tuple[str, str]]" = {}
    ids_by_cell: "dict[str, list[str]]" = {}
    for event_id in sorted(batch):
        entry = batch[event_id]
        kind, theme = entry["kind"], entry["theme"]
        cell_key = f"{kind}-{theme}"
        dimensions[cell_key] = (kind, theme)
        ids_by_cell.setdefault(cell_key, []).append(event_id)

    cells = tuple(Cell("dungeon-event", dimensions[key], key) for key in sorted(ids_by_cell))
    committed_chain_refs = {eid: str(batch[eid].get("chainRef", "none"))
                            for eid in sorted(batch) if batch[eid].get("kind") == "story"}
    existing_names = tuple(sorted(
        str(entry["name"]) for eid, entry in events.items() if eid not in batch))
    base_calls = len(batch)
    return RegenPlan(events=batch, cells=cells, planned_ids_by_cell=ids_by_cell,
                     committed_chain_refs=committed_chain_refs, existing_names=existing_names,
                     base_calls=base_calls, worst_calls=base_calls * (1 + MAX_QUALITY_RETRY))


def render_plan(plan: RegenPlan) -> str:
    """The dry-run reading: what a run would cost and what it would touch, before anything is spent."""
    return (f"legacy event regeneration: {len(plan.events)} event(s) in {len(plan.cells)} cell(s), "
            f"{plan.base_calls} base call(s) / {plan.worst_calls} worst call(s) "
            f"(1 + MAX_QUALITY_RETRY={MAX_QUALITY_RETRY} per event), "
            f"{len(plan.committed_chain_refs)} committed chainRef(s) carried over, "
            f"{len(plan.existing_names)} existing name(s) in the collision set")


@dataclass(frozen=True)
class RegenRun:
    """One regeneration run: what it drew, what stayed unresolved, and the reviewer's append-only
    verdict history. A run file is scratch — `data/seed/dungeon/_runs/<runId>.json` — and the corpus is
    only touched by `commit_reviewed`."""

    run_id: str
    events: "Mapping[str, dict]"          # event_id -> {"entry": {...}, "briefHash": str}
    unresolved: "Mapping[str, str]"       # event_id -> the pipeline's own reason
    verdicts: "Mapping[str, list]"        # event_id -> [{"verdict": "accept|reject", "reason": str}]

    def verdict_of(self, event_id: str) -> "str | None":
        history = self.verdicts.get(event_id) or []
        return history[-1]["verdict"] if history else None

    def accepted_ids(self) -> "tuple[str, ...]":
        return tuple(sorted(eid for eid in self.events if self.verdict_of(eid) == "accept"))

    def rejected_ids(self) -> "tuple[str, ...]":
        return tuple(sorted(eid for eid in self.events if self.verdict_of(eid) == "reject"))

    def to_document(self) -> dict:
        return {"runId": self.run_id, "events": {k: dict(v) for k, v in self.events.items()},
                "unresolved": dict(self.unresolved),
                "verdicts": {k: [dict(r) for r in v] for k, v in self.verdicts.items()}}


def _runs_dir(runs_dir: "Path | str | None" = None) -> Path:
    if runs_dir is not None:
        return Path(runs_dir)
    return content_root() / "data/seed/dungeon/_runs"


def _run_id(event_ids: "Sequence[str]") -> str:
    """A deterministic run id (no clock): the same batch always names the same run file, so a rerun
    reconciles with the run it repeats instead of littering `_runs/`."""
    import hashlib
    return "regen-" + hashlib.sha256("|".join(sorted(event_ids)).encode("utf-8")).hexdigest()[:12]


def write_run(run: RegenRun, runs_dir: "Path | str | None" = None) -> Path:
    directory = _runs_dir(runs_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run.run_id}.json"
    path.write_text(json.dumps(run.to_document(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def load_run(run_id: str, runs_dir: "Path | str | None" = None) -> RegenRun:
    """Read a scratch run file back — what the review and commit stages read after a `--write`.

    Refuses a missing or mismatched file rather than returning an empty run: committing nothing while
    reporting success is the failure a `--commit` must not have.
    """
    path = _runs_dir(runs_dir) / f"{run_id}.json"
    if not path.exists():
        raise ValueError(f"no run file {path} — run the draw stage (--write) first")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("runId") != run_id:
        raise ValueError(f"{path}: runId {document.get('runId')!r} does not match {run_id!r}")
    return RegenRun(run_id=run_id,
                    events={k: dict(v) for k, v in (document.get("events") or {}).items()},
                    unresolved=dict(document.get("unresolved") or {}),
                    verdicts={k: [dict(row) for row in value]
                              for k, value in (document.get("verdicts") or {}).items()})


def latest_run_id(runs_dir: "Path | str | None" = None) -> "str | None":
    """The newest scratch run file's id, or None when there is none. `_run_id` is clock-free, so
    "newest" is by file mtime — the run a reviewer just drew."""
    directory = _runs_dir(runs_dir)
    if not directory.is_dir():
        return None
    files = sorted(directory.glob("regen-*.json"), key=lambda path: path.stat().st_mtime)
    return files[-1].stem if files else None


def run_legacy_regen(events_dir: "Path | str | None" = None, *, ids: "Sequence[str] | None" = None,
                     call: "Any" = None, config: "Any" = None, glosses: "Any" = None,
                     themes: "Mapping[str, dict] | None" = None, dry_run: bool = True,
                     runs_dir: "Path | str | None" = None) -> RegenRun:
    """Plan, then (unless `dry_run`) draw every committed event under its own id.

    `dry_run=True` is the default and spends nothing: it reads the tree and returns a run with no
    events. A real run uses the RESOLVED config it is handed (never a built-in one), the committed
    chainRefs, the collision set excluding its own batch, and the planner-assigned climates; it writes a
    scratch run file and never the corpus.
    """
    plan = plan_legacy_regen(events_dir, ids=ids)
    run_id = _run_id(plan.event_ids)
    if dry_run:
        return RegenRun(run_id=run_id, events={}, unresolved={}, verdicts={})

    from ...pipeline.llm_caller import call_model, resolve_live_transport
    from ...briefkit.gloss import load_glosses
    from . import registries as _reg
    from .planner import assign_event_climates

    config = config or resolve_live_transport()
    call = call or call_model
    glosses = glosses or load_glosses()
    themes = themes if themes is not None else _reg.load_themes()
    climates = assign_event_climates(plan.planned_ids_by_cell)

    entries: "dict[str, dict]" = {}
    unresolved: "dict[str, str]" = {}
    for cell in plan.cells:
        cell_ids = plan.planned_ids_by_cell[cell.cell_key]
        results = run_event_draws([cell], dict(plan.planned_ids_by_cell), call=call, config=config,
                                  glosses=glosses, themes=themes, climates=climates,
                                  committed_chain_refs=dict(plan.committed_chain_refs),
                                  existing_names=list(plan.existing_names))
        for result in results:
            event_id = cell_ids[result.slot_index]
            if result.entry is None:
                unresolved[event_id] = result.reason or "unresolved"
            else:
                entries[event_id] = {"entry": dict(result.entry), "briefHash": result.brief_hash}

    run = RegenRun(run_id=run_id, events=entries, unresolved=unresolved, verdicts={})
    write_run(run, runs_dir)
    return run


def record_verdict(run: RegenRun, event_id: str, *, verdict: str, reason: str = "",
                   runs_dir: "Path | str | None" = None) -> RegenRun:
    """Append one reviewer verdict. Append-only: the latest record decides, the history is kept."""
    if verdict not in ("accept", "reject"):
        raise ValueError(f"verdict must be 'accept' or 'reject', got {verdict!r}")
    if event_id not in run.events:
        raise ValueError(f"{event_id!r} is not a drawn event of run {run.run_id}")
    if verdict == "reject" and not reason.strip():
        raise ValueError("a rejection must name its reason — a rejected event is regenerated under it")
    verdicts = {k: [dict(r) for r in v] for k, v in run.verdicts.items()}
    verdicts.setdefault(event_id, []).append({"verdict": verdict, "reason": reason})
    updated = RegenRun(run_id=run.run_id, events=run.events, unresolved=run.unresolved,
                       verdicts=verdicts)
    write_run(updated, runs_dir)
    return updated


def commit_reviewed(run: RegenRun, events_dir: "Path | str | None" = None, *, config: "Any" = None) -> list:
    """Write the ACCEPTED events through `commit_event_draws`. An unresolved event — and one the
    reviewer rejected or never reviewed — keeps its committed file byte-for-byte: this never writes a
    partial event."""
    from .commit import commit_event_draws
    from .pipelines import EventDrawResult

    accepted = run.accepted_ids()
    results = [
        EventDrawResult(run.events[eid]["entry"]["eventId"], 0, run.events[eid]["entry"],
                        brief_hash=run.events[eid]["briefHash"])
        for eid in accepted
    ]
    return commit_event_draws(results, _events_dir(events_dir), config=config)


def review_sample(run: RegenRun, *, sample_size: int, revision: "str | None" = None) -> "dict[str, list]":
    """A seeded, stratified sample over event KIND (`sampling.stratified_sample`), one call per stratum
    guaranteed — the reviewer's sitting is reproducible from the run id."""
    from ...sampling import stratified_sample

    by_kind: "dict[str, list]" = {}
    for event_id in sorted(run.events):
        by_kind.setdefault(str(run.events[event_id]["entry"]["kind"]), []).append(event_id)
    return stratified_sample(by_kind, sample_size, metric_id="dungeon-event-regen",
                             revision=revision or run.run_id)
