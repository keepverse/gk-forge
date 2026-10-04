"""The `run-control` execution driver (creature-seed module 9, spec-run-control.md) — ties
`machine`/`record`/`selectors` (pure, already tested) to the real classification loop
(`orchestrator.run_one_species`, which defaults to a REAL model call) and to `anchor-emit`'s
canonical file writer, so `creatures run start/resume/pause/cancel/rerun/status/overwrite-all`
means something end to end.

**Checkpoint granularity is one species** (spec §2's own warning): the run record's `completed`
list is rewritten to disk after every species, and the anchor family file that species belongs to
is rewritten too — a crash or a pause between species loses nothing, and a pause never leaves a
species half-classified across its eight pipelines.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ..anchor.derive import (
    clamp_variant_count, derive_posture, derive_pure, derive_rank, derive_species_kind,
    load_aptitude_fallback,
    load_rarity_power_fallback, resolve_secondary_element_from_fusion_lineage,
    resolve_threat_band,
    resolve_unresolved_aptitude, resolve_unresolved_rarity,
)
from ..anchor.emit import build_index, entry_for, render_index, write_family_file
from ..anchor.prompts import PIPELINES, SpeciesLore, threat_audit_spec_for_basis
from ..anchor.schema import (  # reused, never re-transcribed
    DECLARED_NULL,
    ELEMENTS,
    csharp_anchor_consumer_violations,
    seed_consumer_violations,
)
from ..anchor.provenance import PROMPT_VERSIONS, AnchorProvenance, ReleadProvenance
from ..dump_ctx import load_creature_dump_ctx
from ..power.measured import load_measured_base_stats, resolves_natively
from ..power.bands import ThreatTuning, classify as classify_threat
from ..preflight import DEFAULT_DUMP_DIR, PREFLIGHT_RECORD_NAME
from ....pipeline.llm_caller import LlmCallerConfig, load_config
from .machine import transition
from .orchestrator import run_one_species
from .record import (
    RunRecord, can_overwrite_all, can_resume, can_start, is_process_alive, new_run_id,
    overwrite_all_token, read_record, write_record,
)
from .selectors import resolve_selector

#: How many failure reasons a run record keeps, oldest dropped. The cap lives here rather than in
#: `plumbing/authorer.py`: it governs the RUN RECORD, not the refusal vocabulary, and reaching across
#: into the seam for it put the import at the wrong depth — three dots resolved to
#: `seedsmith.adapters.plumbing`, which does not exist, and four would have coupled the run machine
#: to the authoring seam for a number about its own bookkeeping.
MAX_FAILURE_REASONS = 200


def _remember_failure(record, species_id: str, reason: object) -> None:
    """Record WHY a species failed, not just which one.

    Added 2026-10-03. `failed` alone could say "Peashooter" and nothing else, which is exactly how a
    36-failure burst got written up as model flakiness when the real cause was the commit ceiling:
    0xC0000409 aborts and WinError 1455 "paging file too small", both visible in the stderr the run
    had already printed and neither of them kept by the record.

    Module level, not a nested closure of `_run_loop`: the tests exercise it directly, and a
    closure over `record` is neither reachable nor testable. Capped, oldest dropped, because the
    first failures explain the pattern and an unbounded dict in a per-species write path is its
    own problem.
    """
    record.failure_reasons[species_id] = str(reason)[:400]
    if len(record.failure_reasons) > MAX_FAILURE_REASONS:
        for stale in list(record.failure_reasons)[: len(record.failure_reasons) - MAX_FAILURE_REASONS]:
            record.failure_reasons.pop(stale, None)


REPO_ROOT = Path(__file__).resolve().parents[6]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from ....workspace_roots import owning_base, seed_root  # noqa: E402


#: The six element ids ActorElementTypes.cs declares. REUSED from anchor.schema rather than
#: written out again: this package already spells the same six ids in eight modules
#: (schema, vocab, pool, tuning, catalog, derive, registries, __init__), and every extra
#: copy is another thing that can drift from the C# enum it mirrors.
VALID_ELEMENT_PRIMARY = frozenset(ELEMENTS)


def element_primary_is_resolvable(value: object) -> bool:
    """Whether an authored elementPrimary is one of the declared ids, and may be written.

    Split out of the completion path so it is testable with no model, no network and no run
    harness - the same reasoning that made the two-mode seam testable. The comparison is
    case-insensitive because the consumer lowercases before validating
    (characteristic_pool/catalog.py:159-163), so `FIRE` resolves where `fire` does.
    """
    return isinstance(value, str) and value.strip().lower() in VALID_ELEMENT_PRIMARY




def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

DEFAULT_ANCHORS_DIR = _owned("data/seed/creatures/species")
DEFAULT_RUNS_DIR = seed_root() / "creatures" / "_runs"
DEFAULT_FAMILY_ASSIGNMENTS = seed_root() / "creatures/_generated/family-assignments.json"
#: The fusion-recipe-generator's own committed seed (`emit.py`'s `DEFAULT_OUTPUT_RELATIVE`) —
#: read-only here, never reimplemented or duplicated.
DEFAULT_FUSION_RECIPES_PATH = _owned("data/generated/creatures/_fusion-recipes.json")

#: In-progress record — gitignored, lives beside the checkpoint (spec §3: "committed only for
#: completed runs; in-progress records live beside the checkpoint DB and are gitignored").
CURRENT_RECORD_NAME = "_current.json"
PAUSE_SENTINEL_NAME = "_pause.request"

#: `start`/`resume` concurrency lock (found live, 2026-09-02 — a real duplicate-classification bug,
#: not a hypothetical: two overlapping `resume`-driving loops both read the SAME record between one
#: species' completion and the next `resume` call, both saw it as resumable, both wrote their own
#: `pid` and independently classified the same 2 species with divergent LLM output). The pre-existing
#: `record.state == "running" and is_process_alive(record.pid)` check only catches a resume racing
#: an ALREADY-recorded live process — it is a read-then-check, not a claim, so two processes that
#: both read the record before either writes can both pass it. This is a real mutual-exclusion lock,
#: acquired for the WHOLE call (through the actual classification loop, not just the record read),
#: so the existing check stays meaningful for its own purpose (crash recovery across sessions) while
#: this closes the same-session TOCTOU gap it was never meant to cover.
RESUME_LOCK_NAME = "_resume.lock"


def _acquire_run_lock(runs_dir: Path) -> None:
    """Atomic claim (`os.O_CREAT | os.O_EXCL`, portable — a POSIX and NTFS guarantee, not a
    best-effort check) on the run record before any read-check-write sequence. A lock file left by
    a process that died mid-run is stale, not a permanent lock (spec §6's own "never refuses
    forever" rule, extended to this lock the same way it already governs the record itself) —
    reclaimed once, after confirming its own recorded holder is actually dead.
    """
    runs_dir.mkdir(parents=True, exist_ok=True)
    lock_path = runs_dir / RESUME_LOCK_NAME
    for attempt in range(2):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode("utf-8"))
            finally:
                os.close(fd)
            return
        except FileExistsError:
            if attempt == 1:
                break
            try:
                holder_pid = int(lock_path.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                holder_pid = -1
            if is_process_alive(holder_pid):
                raise RunRefused(
                    f"another start/resume is already in progress (pid {holder_pid}) — wait for it "
                    "to finish, or confirm it is genuinely dead before removing "
                    f"{lock_path}")
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
    raise RunRefused(f"could not acquire the run lock at {lock_path}")


def _release_run_lock(runs_dir: Path) -> None:
    try:
        (runs_dir / RESUME_LOCK_NAME).unlink()
    except FileNotFoundError:
        pass

Progress = Callable[[str, int, int], None]  # (species_id, done_count, total_count) -> None


class RunRefused(RuntimeError):
    """Every refusal names the reason (record.py's own discipline) — never a bare exit code."""


def _species_rows(dump_dir: Path) -> "list[dict]":
    plant = json.loads((dump_dir / "almanac" / "plant.json").read_text(encoding="utf-8"))
    zombie = json.loads((dump_dir / "almanac" / "zombie.json").read_text(encoding="utf-8"))
    rows = plant + zombie
    for r in rows:
        r.setdefault("speciesId", r.get("typeName") or f"{r['side']}-{r['typeId']}")
    return rows


def _power_seed_by_species(dump_dir: Path) -> "dict[str, Any]":
    """speciesId -> PowerSeed from the CURRENT dump (threat-band-fill T3: score first needs the
    seed the classifier itself would have seen). Best-effort by design: an absent or unreadable
    dump is a real outcome (test fixtures, offline use), never an error — species without a
    seed take the sanctioned default with "default" provenance, exactly as before."""
    dump = load_creature_dump_ctx(dump_dir)
    if dump is None:
        return {}
    seed_by_key = {f"{s.side}:{s.type_id}": s for s in dump.seeds}
    out: "dict[str, Any]" = {}
    for row in _species_rows(dump_dir):
        key = f"{row.get('side')}:{row.get('typeId')}"
        species_id = row.get("speciesId")
        if species_id and key in seed_by_key:
            out[species_id] = seed_by_key[key]
    return out


def _lore_for(row: Mapping[str, Any]) -> SpeciesLore:
    return SpeciesLore(
        species_id=row["speciesId"], side=row["side"], display_name=row.get("displayName"),
        flavor_info=row.get("flavorInfo"), flavor_introduce=row.get("flavorIntroduce"),
        enrichment=row.get("enrichment"))


def _load_existing_anchors(anchors_dir: Path) -> "list[dict]":
    """Every real anchor entry on disk — scans the tree directly, never trusts `_index.json`'s own
    value set to know which files exist (fixed 2026-09-04, creature-corpus-self-heal C2's own real
    finding, not theorized: the OLD version only read files `_index.json` currently pointed at,
    so a species whose file the index had drifted away from — the exact class of staleness A1/A2
    exist to fix — became invisible to every future run, and `_rewrite_index` then rebuilt the
    index FROM that already-incomplete read, making the loss permanent and self-reinforcing rather
    than one-off. `_index.json` stays the fast O(1) lookup `run-control`'s own spec wants for
    `resume`; this function is the ground truth it should never drift from)."""
    if not anchors_dir.exists():
        return []
    out: "list[dict]" = []
    for path in sorted(anchors_dir.rglob("*.json"), key=lambda p: str(p)):
        if path.name.startswith("_"):
            continue  # _index.json and any future notes/exemplars file, matching AtomImporter's own convention
        out.extend(json.loads(path.read_text(encoding="utf-8")))
    return out


def _load_families(path: Path) -> "dict[str, list[str]]":
    """Keyed lower-case: `family-assignments.json` (generate_families.py) writes lower-case
    speciesIds, but the corpus-dump's own `speciesId` is the captured `typeName` (TitleCase, e.g.
    'Peashooter') — a case-sensitive lookup here silently missed every real species and dropped
    everything into the 'unclassified' bucket (caught on a real 2026-09-02 proof run)."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k.lower(): v for k, v in raw.items()}


def _slugify_family(name: str) -> str:
    """Lowercase kebab-case filename from an LLM-proposed family string ("Apex Predator Flora" ->
    "apex-predator-flora"), matching the id grammar every other kebab-case id in this repo already
    uses. Collapses whitespace/punctuation runs into single hyphens; empty after stripping falls
    back to the caller's own "unclassified" default rather than writing a blank filename."""
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "unclassified"


def _family_for(
    species_id: str, families: "dict[str, list[str]]", *, classified_family: "list[str] | None" = None,
) -> str:
    """The anchor's OWN `family` field — the `identity` pipeline's real, per-species LLM proposal
    (spec-classify-pipelines.md pipeline 8) — is the primary source (fixed 2026-09-02: previously
    this only ever consulted `family-assignments.json`, a lookup built for the unrelated
    fusion-product `creature` corpus, so every base species not coincidentally sharing an id with a
    fused creature landed in the generic "unclassified" bucket despite the identity pipeline already
    having classified a real family for it — found live, 2026-09-02, T2.11's own 20-species run).
    `family-assignments.json` stays a fallback for the handful of species it happens to cover with
    a hand-tuned short name (`cherrybomb` -> `cherry`), and "unclassified" is the last resort only
    when neither source has anything."""
    if classified_family:
        first = next((f for f in classified_family if f and f.strip()), None)
        if first is not None:
            return _slugify_family(first)
    return (families.get(species_id.lower()) or ["unclassified"])[0]


def _compute_dump_hash(dump_dir: Path) -> str:
    """The snapshot key every `_provenance.dumpHash` records, read from the manifest's `dataHash`.

    It is the DATA hash and not `contentHash` because the payloads carry 986 stamp fields (677 plant
    + 227 zombie `rebuiltUtc`, 82 spawn-baseline `capturedUtc`), so `contentHash` moves every time the
    dump is re-captured. Keying staleness on it made every derived entry stale on every capture.
    spec-anchor-emit.md requires the opposite - "an entry is stale when what it was derived from has
    changed, compared by recorded value, not by timestamp" - and this is what finally satisfies it.

    Delegates to `preflight` so `run-control`'s dump-pinning is the SAME value `dump-preflight`
    verified: two independently-computed hashes of one tree would be a second source of truth.

    A manifest with no `dataHash` is a NAMED failure, never a quiet fall back to `contentHash`. That
    fallback would reintroduce exactly the clock-dependence this function exists to remove, and it
    would do so invisibly, by making entries look current that are not."""
    from ..preflight import MissingDataHash, manifest_data_hash
    try:
        return manifest_data_hash(dump_dir)
    except MissingDataHash as exc:
        raise MissingDataHash(
            f"{exc} Re-capture the dump once so the envelope carries both hashes, then re-run. "
            "Falling back to contentHash here would make staleness track the capture clock again."
        ) from exc


def _read_preflight(dump_dir: Path) -> "dict | None":
    path = dump_dir / PREFLIGHT_RECORD_NAME
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class RunPaths:
    dump_dir: Path = DEFAULT_DUMP_DIR
    anchors_dir: Path = DEFAULT_ANCHORS_DIR
    runs_dir: Path = DEFAULT_RUNS_DIR
    family_assignments: Path = DEFAULT_FAMILY_ASSIGNMENTS

    @property
    def current_record_path(self) -> Path:
        return self.runs_dir / CURRENT_RECORD_NAME

    @property
    def pause_sentinel_path(self) -> Path:
        return self.runs_dir / PAUSE_SENTINEL_NAME


def _violation_names_any(violation: str, fields: "set[str]") -> bool:
    """Whether a predicate violation is ABOUT one of `fields`.

    The predicates return human-readable strings, not structured findings, and changing that shape
    would break every caller that joins them into a failure reason. So this matches on the two forms
    the predicates actually emit — a presence guard names its key QUOTED
    (`anchor: missing or non-string 'reach'`) and a membership guard leads with the field name
    followed by a space (`attackTempo '' has no entry in creature-shape.v1.json`). Both are matched
    on a WORD boundary so `elementPrimary` can never match an `elementSecondary` violation.

    Asserted against the predicates' real output in `test_run_element_guard.py`, because a guard
    that silently matches nothing would stop blocking anything and look green.
    """
    for field in fields:
        if f"'{field}'" in violation or violation.startswith(f"{field} "):
            return True
    return False


def _write_species_entry(
    row: Mapping[str, Any], merged_fields: "dict[str, Any]", *, dump_hash: str,
    families: "dict[str, list[str]]", anchors_dir: Path,
    existing_by_file: "dict[str, list[dict]]",
    votes: "dict[str, Any] | None" = None, pipeline_attempts: "dict[str, int] | None" = None,
    merge_from: "Mapping[str, Any] | None" = None, dirty: "set[str] | None" = None,
) -> str:
    """Writes/updates the one family file this species belongs to, returns the relative path
    written (for the index). Merges into whatever that file already holds — sibling species in
    the same family file are never dropped by writing one more.

    `votes`/`pipeline_attempts` come from `orchestrator.run_one_species`'s `_votes`/
    `_pipelineAttempts` — real disagreement/repair signal, not left at the provenance dataclass's
    empty-dict defaults (found live, 2026-09-02: every real anchor written before this had
    `attempts: {}` / `confidence: {}`, silently discarding the exact data `pipeline-health`'s
    disagreement-rate/repair-rate metrics (T2.12) need to work at all).

    `dirty` (2026-09-17) BATCHES the file I/O instead of removing it: pass a set and this function
    mutates `existing_by_file` exactly as before but writes nothing, recording every family file it
    touched so the caller can flush each ONE time via `_flush_family_files`. The merge stays a
    single implementation — this is a deferral, not a second writer. It exists because a pass that
    touches every species rewrites its family file once PER SPECIES: `zombie/undead.json` is 136 KB
    and holds most of a side, so a corpus-wide pass rewrote it a hundred-odd times in a tight loop
    and Windows returned a transient `OSError: [Errno 22]` mid-run (observed twice, 2026-09-17, at
    different files each time). Per-species checkpointing is load-bearing for a MODEL run, where a
    crash costs real call budget; it buys nothing for a deterministic pass that is idempotent and
    re-runnable for free.

    `merge_from` (creature-corpus-self-heal B1, 2026-09-04): the species' EXISTING full entry, passed
    only for a pipeline-scoped rerun (`_run_loop`'s `pipeline_scope`). `merged_fields` there holds
    ONLY the reran pipeline's own output — every other field, and every other pipeline's own
    `attempts`/`confidence`/`minorityValues`/`promptVersions` entry, is carried over from
    `merge_from` untouched. `None` (the default, every other caller) keeps today's exact
    full-replace behaviour."""
    species_id = row["speciesId"]

    if merge_from is not None:
        full_fields = {k: v for k, v in merge_from.items() if not k.startswith("_")}
        full_fields.update(merged_fields)
        # rank is a function of the MERGED (threatBand, rarity), so it is recomputed on every subset
        # merge: `merged_fields` here holds ONLY the pass's own output, and a threat/rarity-only
        # pipeline-scoped rerun would otherwise leave the species' old rank sitting beside its new
        # rarity (spec-species-rank.md §1 — a stale rank is exactly what this line exists to stop).
        full_fields["rank"] = derive_rank(full_fields.get("threatBand"), full_fields.get("rarity"))
        old_prov = dict(merge_from.get("_provenance") or {})
        confidence = dict(old_prov.get("confidence") or {})
        minority = dict(old_prov.get("minorityValues") or {})
        for field, v in (votes or {}).items():
            confidence[field] = v["confidence"]
            if v.get("minority"):
                minority[field] = v["minority"]
            else:
                minority.pop(field, None)
        attempts = dict(old_prov.get("attempts") or {})
        attempts.update(dict(pipeline_attempts or {}))
        prompt_versions = dict(old_prov.get("promptVersions") or {})
        prompt_versions.update({p: v for p, v in PROMPT_VERSIONS.items() if p in (pipeline_attempts or {})})
        # `relead` is another pass's provenance, not this merge's to drop. It is carried over
        # verbatim because the constructor below starts from scratch: leaving it out silently erased
        # `lead-relabel-pass`'s record from every entry a deterministic pass rewrote (found live
        # 2026-09-23 by the `refresh-rank` regen — 104 of 904 real entries lost the block).
        old_relead = old_prov.get("relead")
        provenance = AnchorProvenance(
            dump_hash=dump_hash, prompt_versions=prompt_versions,
            basis=full_fields.get("basis", old_prov.get("basis", "blocked")),
            confidence=confidence, minority_values=minority,
            audit_verdict=old_prov.get("auditVerdict"),
            attempts=attempts,
            emitted_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            relead=ReleadProvenance.from_dict(old_relead) if old_relead else None)
        merged_fields = full_fields
    else:
        votes = votes or {}
        provenance = AnchorProvenance(
            dump_hash=dump_hash, prompt_versions=dict(PROMPT_VERSIONS),
            basis=merged_fields.get("basis", "blocked"),
            confidence={field: v["confidence"] for field, v in votes.items()},
            minority_values={field: v["minority"] for field, v in votes.items() if v.get("minority")},
            attempts=dict(pipeline_attempts or {}),
            emitted_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    family = _family_for(species_id, families, classified_family=merged_fields.get("family"))
    rel_path = f"{row['side']}/{family}.json"
    entry = entry_for(species_id, merged_fields, provenance=provenance)

    # A reclassification can move a species into a DIFFERENT family file (family is model-decided,
    # not stable across runs) — found live at corpus scale, 2026-09-04 (CreatureQualityReport: 217 of
    # 833 species had a stale copy left behind in their OLD file). Every other file this species
    # might already live in must lose its copy too, not just the one being written now, or the
    # stale entry sits on disk forever with _index.json correctly pointing past it while
    # CreatureSpeciesGen/AtomImporter-style direct-file readers still see both.
    for other_path, other_bucket in existing_by_file.items():
        if other_path == rel_path:
            continue
        before = len(other_bucket)
        other_bucket[:] = [e for e in other_bucket if e.get("speciesId") != species_id]
        if len(other_bucket) == before:
            continue
        if dirty is not None:
            dirty.add(other_path)
        elif other_bucket:
            write_family_file(anchors_dir / other_path, other_bucket)
        else:
            (anchors_dir / other_path).unlink(missing_ok=True)  # no species left — no orphan file either

    bucket = existing_by_file.setdefault(rel_path, [])
    bucket[:] = [e for e in bucket if e.get("speciesId") != species_id]
    bucket.append(entry)
    if dirty is not None:
        dirty.add(rel_path)
    else:
        write_family_file(anchors_dir / rel_path, bucket)
    return rel_path


def _flush_family_files(
    anchors_dir: Path, existing_by_file: "dict[str, list[dict]]", dirty: "set[str]",
) -> None:
    """Write every family file a batched pass touched, exactly once each. Same two outcomes
    `_write_species_entry`'s own immediate path has — a file with entries is written, a file left
    with none is unlinked rather than committed as an orphan."""
    for rel_path in sorted(dirty):
        bucket = existing_by_file.get(rel_path) or []
        if bucket:
            write_family_file(anchors_dir / rel_path, bucket)
        else:
            (anchors_dir / rel_path).unlink(missing_ok=True)


def _rewrite_index(anchors_dir: Path, existing_by_file: "dict[str, list[dict]]") -> None:
    index = build_index(existing_by_file)
    (anchors_dir / "_index.json").write_bytes(render_index(index))


def _resolve_config(config: "LlmCallerConfig | None") -> LlmCallerConfig:
    """`None` means "use the project's own settings" — `load_config()`'s own layering
    (`.env` overrides `seedsmith.toml` overrides `LlmCallerConfig`'s built-in defaults), read
    fresh on every call so an edited `.env`/`seedsmith.toml` takes effect on the next `start`/
    `resume` without needing a code change or a restart of anything but the CLI invocation."""
    return config if config is not None else load_config()


def start(
    selector: Mapping[str, Any], *, paths: RunPaths = RunPaths(),
    call: "Callable[..., str] | None" = None, progress: "Progress | None" = None,
    force_selector_ignores_existing: bool = False, config: "LlmCallerConfig | None" = None,
    workers: int = 1,
) -> RunRecord:
    """`run start <selector>` (spec §2 `start`, §4 selectors). Refuses without a matching, real
    (non-`--skip-model`) preflight record for the CURRENT dump. On success, classifies every
    selected species not already present in the anchor tree (unless
    `force_selector_ignores_existing`, which is what `rerun`/`overwrite-all` pass), writing each
    species' family file and the run record after every single species.

    `workers` (default 1, sequential — unchanged behaviour) fans the model-call phase out across
    N threads; see `_run_loop`'s own docstring for why that phase specifically is safe to
    parallelise and the write phase deliberately is not."""
    _acquire_run_lock(paths.runs_dir)
    try:
        dump_hash = _compute_dump_hash(paths.dump_dir)
        preflight = _read_preflight(paths.dump_dir)
        existing_record = read_record(paths.current_record_path)
        ok, reason = can_start(preflight, dump_hash=dump_hash, existing_record=existing_record)
        if not ok:
            raise RunRefused(reason)

        rows = _species_rows(paths.dump_dir)
        creature_dump = load_creature_dump_ctx(paths.dump_dir)
        if creature_dump is None:
            raise RunRefused(f"no readable corpus-dump tree at {paths.dump_dir}")
        seed_by_species = {s.side + ":" + str(s.type_id): s for s in creature_dump.seeds}
        threat_tuning = ThreatTuning.load()

        existing_anchors = _load_existing_anchors(paths.anchors_dir)
        already_done = {a["speciesId"] for a in existing_anchors} if not force_selector_ignores_existing else set()

        ids = resolve_selector(
            selector, dump_species=[{"speciesId": r["speciesId"], "side": r["side"]} for r in rows],
            anchors=existing_anchors, current_dump_hash=dump_hash,
            current_prompt_versions=PROMPT_VERSIONS)
        ids = [i for i in ids if i not in already_done]

        record = RunRecord(
            run_id=new_run_id(), state="idle", preflight=dict(preflight), dump_hash=dump_hash,
            selector=dict(selector), prompt_versions=dict(PROMPT_VERSIONS), pid=os.getpid(),
            started_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        return _run_loop(record, ids, rows, seed_by_species, threat_tuning, paths=paths, call=call,
                         progress=progress, config=_resolve_config(config), workers=workers)
    finally:
        _release_run_lock(paths.runs_dir)


def resume(*, paths: RunPaths = RunPaths(), call: "Callable[..., str] | None" = None,
          progress: "Progress | None" = None, config: "LlmCallerConfig | None" = None,
          workers: int = 1) -> RunRecord:
    """`run resume` (spec §2 `resume`, TRANSIENT semantics — no species already in `completed` is
    ever re-classified). Also the crash-recovery path (spec §6): a `running` record whose pid is
    dead is resumable, never a silent takeover and never a permanent refusal.

    `workers` need not match the original `start`'s value — it is a resource knob for THIS process,
    not a property of the run itself, and nothing in `RunRecord` depends on it."""
    _acquire_run_lock(paths.runs_dir)
    try:
        record = read_record(paths.current_record_path)
        if record is None:
            raise RunRefused("no in-progress run to resume — use `start`")
        dump_hash = _compute_dump_hash(paths.dump_dir)
        ok, reason = can_resume(record, current_dump_hash=dump_hash)
        if not ok:
            raise RunRefused(reason)
        if record.state == "running" and is_process_alive(record.pid):
            raise RunRefused(f"run {record.run_id} is still running (pid {record.pid})")

        if record.state == "running":
            # spec §6: "A killed process leaves the record in `running`... offers `resume`... it does
            # not silently take over." We already proved above the recorded pid is dead — this IS the
            # crash-recovery case, semantically identical to `failed`, so it takes the same path.
            # `machine.transition` has no `("running", "resume")` edge on purpose (a LIVE "running"
            # record must never be resumed out from under its own process) — bypassing it here is
            # deliberate, not a shortcut around the state machine.
            record.state = "running"
        else:
            verb = "resume" if record.state in ("paused", "failed") else None
            if verb is None:
                raise RunRefused(f"run {record.run_id} is in state {record.state!r}, not resumable")
            record.state = transition(record.state, verb)
        record.pid = os.getpid()

        rows = _species_rows(paths.dump_dir)
        creature_dump = load_creature_dump_ctx(paths.dump_dir)
        if creature_dump is None:
            raise RunRefused(f"no readable corpus-dump tree at {paths.dump_dir}")
        seed_by_species = {s.side + ":" + str(s.type_id): s for s in creature_dump.seeds}
        threat_tuning = ThreatTuning.load()

        full_selection = resolve_selector(
            record.selector, dump_species=[{"speciesId": r["speciesId"], "side": r["side"]} for r in rows],
            anchors=_load_existing_anchors(paths.anchors_dir), current_dump_hash=dump_hash,
            current_prompt_versions=PROMPT_VERSIONS)
        remaining = [i for i in full_selection if i not in set(record.completed) and i not in set(record.failed)]
        if paths.pause_sentinel_path.exists():
            paths.pause_sentinel_path.unlink()
        return _run_loop(record, remaining, rows, seed_by_species, threat_tuning, paths=paths, call=call,
                         progress=progress, resuming=True, config=_resolve_config(config), workers=workers)
    finally:
        _release_run_lock(paths.runs_dir)


def rerun(
    selector: Mapping[str, Any], *, paths: RunPaths = RunPaths(),
    call: "Callable[..., str] | None" = None, progress: "Progress | None" = None,
    config: "LlmCallerConfig | None" = None, workers: int = 1,
) -> RunRecord:
    """`run rerun <selector>` (spec §2 `rerun`) — re-generates a named subset, ignoring "already
    emitted." Unlike `start`, a species the selector names is classified again even if an anchor
    entry already exists for it (still refuses on a missing/mismatched preflight, same as `start`
    — a rerun is still a real run and needs the same gate)."""
    return start(selector, paths=paths, call=call, progress=progress, config=config,
                force_selector_ignores_existing=True, workers=workers)


def overwrite_all(
    confirm_token: str, *, paths: RunPaths = RunPaths(),
    call: "Callable[..., str] | None" = None, progress: "Progress | None" = None,
    config: "LlmCallerConfig | None" = None, workers: int = 1,
) -> RunRecord:
    """`run overwrite-all --confirm <token>` (spec §2 `overwrite-all`, §5: "discards work that cost
    14 hours... gets a typed token"). The token is derived from the CURRENT dump hash
    (`record.overwrite_all_token`) so a stale token from a prior dump snapshot cannot authorize
    overwriting today's — call `status`/read the refusal message to get the right one."""
    dump_hash = _compute_dump_hash(paths.dump_dir)
    ok, reason = can_overwrite_all(confirm_token, dump_hash=dump_hash)
    if not ok:
        raise RunRefused(reason)
    return start({"kind": "all"}, paths=paths, call=call, progress=progress, config=config,
                force_selector_ignores_existing=True, workers=workers)


def fix_unresolved(*, paths: RunPaths = RunPaths(), dry_run: bool = False) -> "list[dict[str, Any]]":
    """creature-corpus-self-heal F1 (2026-09-04) / Phase H+I (2026-09-07, owner-directed) — a
    deliberate FIX STEP, run on demand after a classification pass, never automatically during
    `start`/`resume`/`rerun`. A human reads `CreatureQualityReport`'s own unresolved-rate finding,
    then runs this to close what remains. Three fields have a fallback today, of two different
    kinds:

    - `threatBand` — SCORE-FIRST (threat-band-fill T3): `resolve_threat_band` tries
      `classify` on the species' own `PowerSeed` from the current dump before falling back to
      `creature-threat.v1.json`'s `inferredDefaultRung`, and stamps WHICH happened
      (`"scored"` / `"default"` — never faked as a real LLM judgment).
    - `rarity` — DERIVED: `resolve_unresolved_rarity`, reusing `threatBand` (this SAME pass's own
      just-fixed value, so the two chain: a species with both unresolved gets threatBand defaulted
      first, then rarity derived from it) via `creature-rarity-power-fallback.v1.json`'s
      rank-preserving correspondence. Rarity is this game's own invented mechanism, not an
      almanac/PvZ property — the owner's direction (2026-09-07) is that an LLM vote never
      converging is not a reason to leave it unresolved forever when a deterministic engine can
      close the gap; stronger species land on rarer rungs.
    - `aptitudePrimary` — INVENTED, not derived: measured directly (F≈1.34 over species with a
      computable power score; 10 of 11 real unresolved species have no computable score at all),
      no real signal exists to derive from. `resolve_unresolved_aptitude` applies a single flat,
      undisguised default from `creature-aptitude-fallback.v1.json` — on the owner's own explicit
      direction that this is fine for a game-invented mechanism when a real derivation genuinely
      does not exist. Never chained from another field, because nothing informs the pick.

    `elementPrimary` still has no fallback of either kind and correctly stays
    `"unresolved"`/reported (currently moot — 0/840 unresolved as of 2026-09-07). No model calls,
    no lock needed (this never runs concurrently with a classification pass in practice, and
    re-running it is idempotent — a species already resolved is a no-op).

    Every fixed field's `_provenance.confidence[field]` is stamped honestly: threatBand
    carries the resolver's own triple (`"scored"` / `"default"`); rarity and aptitudePrimary
    carry `"deterministic-fallback"`; nothing here pretends a judgment happened. Returns one
    dict per (species, field) actually fixed (or that WOULD be fixed, when
    `dry_run=True`): `{"speciesId", "field", "before", "after"}` — a species with more than one
    field unresolved produces one entry per field.
    """
    threat_tuning = ThreatTuning.load()
    rarity_fallback = load_rarity_power_fallback()
    aptitude_default = load_aptitude_fallback()
    seed_by_species = _power_seed_by_species(paths.dump_dir)
    anchors = _load_existing_anchors(paths.anchors_dir)
    families = _load_families(paths.family_assignments)

    existing_by_file: "dict[str, list[dict]]" = {}
    for entry in anchors:
        family = _family_for(entry.get("speciesId", ""), families, classified_family=entry.get("family"))
        side = entry.get("side", "unclassified")
        existing_by_file.setdefault(f"{side}/{family}.json", []).append(entry)

    fixed: "list[dict[str, Any]]" = []
    for entry in anchors:
        species_id = entry.get("speciesId")
        # Score first (threat-band-fill T3): the species' own PowerSeed from the CURRENT dump.
        # Absent from the dump (or an unscorable basis) is a real outcome, not an error — the
        # resolver lands those on the sanctioned default with "default" provenance.
        seed = seed_by_species.get(species_id) if species_id else None
        before_threat = entry.get("threatBand")
        after_threat, threat_provenance = resolve_threat_band(
            before_threat, seed, tuning=threat_tuning)
        threat_was_fixed = threat_provenance in ("scored", "default")

        before_rarity = entry.get("rarity")
        after_rarity, rarity_was_fixed = resolve_unresolved_rarity(
            before_rarity, after_threat, mapping=rarity_fallback)

        before_aptitude = entry.get("aptitudePrimary")
        after_aptitude, aptitude_was_fixed = resolve_unresolved_aptitude(
            before_aptitude, default=aptitude_default)

        # An ABSENT optional-secondary key is a fourth gap, and the only one with a legal answer
        # rather than a fallback pick. Measured 2026-10-04: 172 entries (88 `elementSecondary`,
        # 84 `aptitudeSecondary`) had no such key at all although their own pipeline had run at the
        # current prompt version — a reply that omitted a `required` attribute, merged as-is. Both
        # fields declare `"none"` as their own vocabulary member (`_enum_prop(nullable=True)`), which
        # both consumers already map to null, so "the model offered no second nature" is a complete
        # and honest answer for an absent key.
        #
        # It has to be closed here, deterministically and with no model call, because the pre-write
        # guard judges the MERGED entry: a species whose `reach` is also absent could be written by
        # NEITHER pipeline — `kit-shape` was refused for the missing secondary, the secondary
        # pipeline for the missing `reach` — and 71 of 134 `kit-shape` reruns failed that way. This
        # pass is the only one that can write a field NO pipeline produced.
        #
        # Deliberately NOT touching an entry whose `elementSecondary` is already `"none"`: that is a
        # resolved answer, `fix-secondary-from-fusion` is the pass that may improve it with real
        # fusion-lineage signal, and rewriting it here would be a no-op with a false provenance claim.
        # Only a genuinely ABSENT key is filled.
        secondary_fills = {
            field: DECLARED_NULL for field in ("elementSecondary", "aptitudeSecondary")
            if field not in entry
        }

        if (not threat_was_fixed and not rarity_was_fixed and not aptitude_was_fixed
                and not secondary_fills):
            continue

        species_id = entry.get("speciesId")
        updates: "dict[str, Any]" = {}
        votes: "dict[str, Any]" = {}
        for field, value in secondary_fills.items():
            fixed.append({"speciesId": species_id, "field": field,
                          "before": None, "after": value})
            updates[field] = value
            # Not "deterministic-fallback": nothing was derived and nothing was picked. There was no
            # answer, and this records exactly that — the same honesty standard the resolvers above
            # stamp ("scored"/"default" say WHICH happened rather than faking a judgement).
            votes[field] = {"confidence": "declared-null", "minority": None}
        if "aptitudeSecondary" in secondary_fills:
            # `pure` is DERIVED from the pair; it was computed from a missing key before, so it is
            # stale now that the key exists.
            updates["pure"] = derive_pure(
                after_aptitude, updates.get("aptitudeSecondary", entry.get("aptitudeSecondary")))
        if threat_was_fixed:
            fixed.append({"speciesId": species_id, "field": "threatBand",
                          "before": before_threat, "after": after_threat})
            updates["threatBand"] = after_threat
            votes["threatBand"] = {"confidence": threat_provenance, "minority": None}
        if rarity_was_fixed:
            fixed.append({"speciesId": species_id, "field": "rarity",
                         "before": before_rarity, "after": after_rarity})
            updates["rarity"] = after_rarity
            votes["rarity"] = {"confidence": "deterministic-fallback", "minority": None}
        if aptitude_was_fixed:
            fixed.append({"speciesId": species_id, "field": "aptitudePrimary",
                         "before": before_aptitude, "after": after_aptitude})
            updates["aptitudePrimary"] = after_aptitude
            votes["aptitudePrimary"] = {"confidence": "deterministic-fallback", "minority": None}
            # Same recompute `_finalize` runs at classification time (line ~758) — posture/pure
            # are functions of aptitudePrimary and must not go stale now that it changed.
            updates["posture"] = derive_posture(after_aptitude)
            # Read the SECONDARY from `updates` first, not from `entry`: this pass may have just
            # filled an absent `aptitudeSecondary` above, and `entry` still lacks the key. The two
            # happen to agree today only because the declared null and the reader's default are both
            # `"none"` — which is exactly the kind of coincidence that rots the day one of them moves.
            updates["pure"] = derive_pure(
                after_aptitude,
                updates.get("aptitudeSecondary", entry.get("aptitudeSecondary", "none")))

        if threat_was_fixed or rarity_was_fixed:
            # Same recompute `_finalize` runs at classification time, one field over from
            # posture/pure above: rank reads threatBand and rarity, and this pass just changed one
            # of them, so the entry's old rank must not be left standing beside the new value.
            updates["rank"] = derive_rank(after_threat, after_rarity)

        if dry_run:
            continue

        row = {"speciesId": species_id, "side": entry.get("side", "unclassified")}
        # dump_hash is PRESERVED from the entry's own original classification, never re-stamped.
        # This fix DOES read the current dump for power seeds (threat-band-fill T3) — but a score
        # is a pure function of dump facts, not a re-classification, and the entry's other fields
        # remain its original era's, so claiming a fresh dump_hash would overstate what happened.
        # A species scored from a newer dump than its own era keeps its era's hash AND a "scored"
        # stamp: the stamp says how the rung was chosen, the hash says when the rest was written.
        original_dump_hash = entry.get("_provenance", {}).get("dumpHash", "")
        _write_species_entry(
            row, updates, dump_hash=original_dump_hash, families=families,
            anchors_dir=paths.anchors_dir, existing_by_file=existing_by_file,
            votes=votes,
            pipeline_attempts={},  # no pipeline ran — the old attempts record must stay untouched
            merge_from=entry)

    if not dry_run and fixed:
        _rewrite_index(paths.anchors_dir, existing_by_file)
    return fixed


def rederive_from_measured_capture(
    *, paths: RunPaths = RunPaths(), dry_run: bool = False,
) -> "list[dict[str, Any]]":
    """creature-seed R-CS1 + R-CS3/R-CS4 (owner-ruled 2026-09-17) — a deterministic, on-demand
    re-derivation of the two DERIVED fields the game's own static stat table now answers. **No model
    calls, ever**, and idempotent: a second run over the same capture is a no-op.

    Two fields, and only two:

    - **`basis`** — re-derived from `type-base-stats.json`, the committed capture of the game's own
      `type_base_stats` sweep. This is the upgrade the four-value ordinal was designed for: *"a later
      capture upgrades a species from `inferred` -> `stated` -> `observed`, and provenance says
      exactly which rows to re-derive."* R-CS1 ruled it runs NOW rather than waiting behind a balance
      answer — *"we will tune later by deterministic engine and data collecting instead of defer,
      that is our principle"* — because deferring keeps a known-wrong corpus in place to protect an
      unmade decision.
    - **`speciesKind`** — the R-CS3 MARK, derived by `derive_species_kind`. Marking, never deleting:
      *"a deleted id is untracked, and an untracked id can be silently re-used or re-derived."* An
      `excluded` row stays present and joinable, so `type-weights.json`, `_species-build-plan.json`
      and family memberships keep working; it is excluded from roster READINGS, not from the corpus.

    ⛔ **`threatBand` is deliberately NOT re-scored here, and that is a real, measured boundary, not
    an oversight.** R-CS1's own summary expects 170 `inferred` species to "stop being LLM
    judgements", and re-scoring is what would deliver that. Measured against the real corpus
    (2026-09-18) before deciding: re-scoring every species from the measured stats against the
    SHIPPED `creature-threat.v1.json` moves 498 of 904 rows and collapses the rung spread — `raider`
    and `warden` take 476 between them while `marauder` and `pest` fall to one occupant each. The
    cause is not the measurement; it is that v1's rung boundaries are, by its own `_note`, the real
    p10..p90 deciles of the OLD almanac-parsed score distribution, where ~280 species had no parsed
    toughness at all and the game's universal 300-hp plant floor was invisible. Applying better
    inputs to thresholds fitted on worse ones empties rungs the tuning file explicitly exists to keep
    occupied.

    Re-fitting those boundaries is a `creature-threat.v2.json` publish through
    `gk-core/tools/tuning/publish.py` — a balance change that moves every species' `Theta`, therefore every
    magnitude in `gk-data/packs/fusion/data/generated/creatures/**`, therefore the build plans and fusion eligibility
    downstream. That is an owner decision with a cascade, not a mechanical re-derivation, so this
    pass stops at the boundary and leaves the measurement visible rather than executing half of a
    balance change under the name of a data upgrade.

    Returns one dict per (species, field) actually changed (or that WOULD change, under
    `dry_run=True`): `{"speciesId", "field", "before", "after"}`.
    """
    measured = load_measured_base_stats(paths.dump_dir)
    seed_by_species = _power_seed_by_species(paths.dump_dir)
    anchors = _load_existing_anchors(paths.anchors_dir)
    families = _load_families(paths.family_assignments)

    existing_by_file: "dict[str, list[dict]]" = {}
    for entry in anchors:
        family = _family_for(entry.get("speciesId", ""), families, classified_family=entry.get("family"))
        side = entry.get("side", "unclassified")
        existing_by_file.setdefault(f"{side}/{family}.json", []).append(entry)

    changed: "list[dict[str, Any]]" = []
    dirty: "set[str]" = set()
    for entry in anchors:
        species_id = entry.get("speciesId")
        side = entry.get("side", "")
        game_type_id = entry.get("gameTypeId")

        updates: "dict[str, Any]" = {}
        votes: "dict[str, Any]" = {}

        # `basis` comes from the SAME seed every other consumer reads (`dump_ctx` overlays the
        # measured capture once), never from a second, private join — one place decides what the
        # dump says about a species' power.
        seed = seed_by_species.get(species_id) if species_id else None
        before_basis = entry.get("basis")
        if seed is not None and seed.basis != before_basis:
            changed.append({"speciesId": species_id, "field": "basis",
                            "before": before_basis, "after": seed.basis})
            updates["basis"] = seed.basis
            votes["basis"] = {"confidence": "measured-base-stats", "minority": None}

        # The mark. `measured` empty means the dump carries no capture at all — there is no oracle,
        # so nothing is marked rather than everything being marked `excluded`.
        if measured and isinstance(game_type_id, int):
            before_kind = entry.get("speciesKind")
            after_kind = derive_species_kind(
                resolves_natively=resolves_natively(side, game_type_id, measured),
                current=before_kind)
            if after_kind != before_kind:
                changed.append({"speciesId": species_id, "field": "speciesKind",
                                "before": before_kind, "after": after_kind})
                updates["speciesKind"] = after_kind
                votes["speciesKind"] = {"confidence": "native-type-resolution", "minority": None}

        if not updates or dry_run:
            continue

        # dump_hash is PRESERVED from the entry's own classification era, the same rule
        # `fix_unresolved` holds and for the same reason: this pass reads a capture, it does not
        # re-classify, and claiming a fresh hash would overstate what happened to the other fields.
        original_dump_hash = entry.get("_provenance", {}).get("dumpHash", "")
        _write_species_entry(
            {"speciesId": species_id, "side": side}, updates, dump_hash=original_dump_hash,
            families=families, anchors_dir=paths.anchors_dir, existing_by_file=existing_by_file,
            votes=votes,
            pipeline_attempts={},  # no pipeline ran — the old attempts record must stay untouched
            merge_from=entry, dirty=dirty)

    if not dry_run and changed:
        _flush_family_files(paths.anchors_dir, existing_by_file, dirty)
        _rewrite_index(paths.anchors_dir, existing_by_file)
    return changed


def refresh_rank(*, paths: RunPaths = RunPaths(), dry_run: bool = False) -> "list[dict[str, Any]]":
    """Deterministic corpus-wide refresh of the anchor tree's DERIVED `rank` (spec-species-rank.md §1, §4).

    Why this pass exists rather than a fourth shape of the three already here: rank is derived from two
    fields every anchor ALREADY carries, so a corpus-wide rank backfill needs no model call, no dump
    read and no capture — only the anchor tree it is rewriting. The other three deterministic passes
    each rewrite ONLY the entries whose field they change (`fix_unresolved` skips an already-resolved
    field; `rederive_from_measured_capture` skips an unchanged basis/speciesKind), so none of them can
    put a rank on a corpus whose classified fields are all already resolved. Measured on the real tree
    2026-09-23: 904 of 904 anchors carry a resolved (threatBand, rarity) pair and none carried a `rank`
    key, so this is the one field with no other route to a corpus-wide backfill.

    Deliberately RANK-ONLY. `posture`/`pure`/`variants`/`basis`/`speciesKind` are derived from inputs
    that are not all on the entry (`basis`/`speciesKind` read the dump capture), so re-deriving them
    here would be a second, unaudited opinion about fields this pass has no business touching.

    Idempotent and byte-stable: a species whose rank already equals the table's own cell is skipped
    with NO write, and `render_family_file` is canonical (sorted keys and entries), so a second run
    over an unchanged tree produces no diff at all. The FIRST run moves each touched entry's
    `_provenance.emittedUtc` — the merge path's own established behaviour for every deterministic pass,
    and an honest record that a pass ran; nothing else in `_provenance` is touched (`votes={}` because
    rank is DERIVED — nothing was judged).
    """
    anchors = _load_existing_anchors(paths.anchors_dir)
    families = _load_families(paths.family_assignments)

    existing_by_file: "dict[str, list[dict]]" = {}
    for entry in anchors:
        family = _family_for(entry.get("speciesId", ""), families, classified_family=entry.get("family"))
        side = entry.get("side", "unclassified")
        existing_by_file.setdefault(f"{side}/{family}.json", []).append(entry)

    changed: "list[dict[str, Any]]" = []
    dirty: "set[str]" = set()
    for entry in anchors:
        species_id = entry.get("speciesId", "")
        before_rank = entry.get("rank")
        after_rank = derive_rank(entry.get("threatBand"), entry.get("rarity"))
        if before_rank == after_rank:
            continue  # already current — no write, so a second run is a true no-op

        changed.append({"speciesId": species_id, "field": "rank",
                        "before": before_rank, "after": after_rank})
        if dry_run:
            continue

        # dump_hash is PRESERVED from the entry's own classification era, the same rule
        # `fix_unresolved`/`rederive_from_measured_capture` hold and for the same reason: this pass
        # reads the entry's own already-classified fields, it does not re-classify.
        original_dump_hash = entry.get("_provenance", {}).get("dumpHash", "")
        _write_species_entry(
            {"speciesId": species_id, "side": entry.get("side", "unclassified")}, {},
            dump_hash=original_dump_hash, families=families, anchors_dir=paths.anchors_dir,
            existing_by_file=existing_by_file,
            votes={},  # rank is DERIVED — nothing was judged, so no confidence entry is written
            pipeline_attempts={},  # no pipeline ran — the old attempts record must stay untouched
            merge_from=entry, dirty=dirty)

    if not dry_run and dirty:
        _flush_family_files(paths.anchors_dir, existing_by_file, dirty)
        _rewrite_index(paths.anchors_dir, existing_by_file)
    return changed


def fix_secondary_from_fusion_lineage(
    *, paths: RunPaths = RunPaths(), recipes_path: Path = DEFAULT_FUSION_RECIPES_PATH,
    dry_run: bool = False,
) -> "list[dict[str, Any]]":
    """Owner-directed follow-up (2026-09-07) to combat-unification's F2 ("author more real
    `ElementSecondary` content") — a deterministic pass, run on demand AFTER
    `fusion-recipe-reconcile` has produced a committed `_fusion-recipes.json` (never before: this
    reads that file, never reimplements the recipe-assignment logic). Reuses
    `resolve_secondary_element_from_fusion_lineage`'s pure derivation (see its own docstring for
    the full rationale and the owner's "not every creature needs a secondary" boundary); this
    function is only the anchor-tree read/write orchestration, matching `fix_unresolved`'s own
    established shape one field over.

    Sized against the real 713-recipe corpus before this was built (2026-09-07): 431 of 693
    outputs missing a secondary gain a clean, single-candidate one from this pass; 259 correctly
    stay `"none"` (both parents already agree with the output); 3 stay `"none"` on the same
    honesty standard (neither parent's own `elementPrimary` can be trusted as "the other element"
    with any confidence — see the derivation function's own docstring for why).

    Idempotent and safe to re-run: a species whose `elementSecondary` is no longer `"none"` (either
    already real, or already fixed by an earlier run of this same function) is a no-op. Never
    touches `elementPrimary`, `rarity`, or `acquisition` — the three fields `fusion-recipe-generator`
    itself depends on — so this pass can never invalidate an already-committed recipe and the
    creature-seed cascade's usual "regenerate downstream of an anchor edit" rule applies only as far as
    `CreatureSpeciesGen`/`CreatureSpeciesImport`/`CreatureBuildPlanGen`, never back to the fusion-recipe step.
    """
    recipes = json.loads(recipes_path.read_text(encoding="utf-8")) if recipes_path.exists() else {}
    anchors = _load_existing_anchors(paths.anchors_dir)
    families = _load_families(paths.family_assignments)

    element_by_species_lower = {
        entry.get("speciesId", "").lower(): entry.get("elementPrimary")
        for entry in anchors if entry.get("speciesId")
    }
    recipe_by_output_lower = {
        r["outputSpeciesId"].lower(): r for r in recipes.values()
    }

    existing_by_file: "dict[str, list[dict]]" = {}
    for entry in anchors:
        family = _family_for(entry.get("speciesId", ""), families, classified_family=entry.get("family"))
        side = entry.get("side", "unclassified")
        existing_by_file.setdefault(f"{side}/{family}.json", []).append(entry)

    fixed: "list[dict[str, Any]]" = []
    for entry in anchors:
        species_id = entry.get("speciesId", "")
        recipe = recipe_by_output_lower.get(species_id.lower())
        if recipe is None:
            continue  # not a fusion output — no lineage signal to derive from

        before_secondary = entry.get("elementSecondary", "none")
        element_primary = entry.get("elementPrimary", "none")
        input_a_element = element_by_species_lower.get(recipe["inputSpeciesIdA"].lower())
        input_b_element = element_by_species_lower.get(recipe["inputSpeciesIdB"].lower())

        after_secondary, was_fixed = resolve_secondary_element_from_fusion_lineage(
            before_secondary, element_primary,
            input_a_element=input_a_element, input_b_element=input_b_element)
        if not was_fixed:
            continue

        fixed.append({"speciesId": species_id, "field": "elementSecondary",
                     "before": before_secondary, "after": after_secondary})
        if dry_run:
            continue

        original_dump_hash = entry.get("_provenance", {}).get("dumpHash", "")
        row = {"speciesId": species_id, "side": entry.get("side", "unclassified")}
        _write_species_entry(
            row, {"elementSecondary": after_secondary}, dump_hash=original_dump_hash,
            families=families, anchors_dir=paths.anchors_dir, existing_by_file=existing_by_file,
            votes={"elementSecondary": {"confidence": "fusion-lineage-derived", "minority": None}},
            pipeline_attempts={}, merge_from=entry)

    if not dry_run and fixed:
        _rewrite_index(paths.anchors_dir, existing_by_file)
    return fixed


def request_pause(*, paths: RunPaths = RunPaths()) -> None:
    """`run pause` — a SEPARATE process signals the running one via a sentinel file, polled only
    between species (never mid-species, spec §2's own warning). Does nothing to a run that is not
    currently `running`; the sentinel is inert until a loop is polling it."""
    paths.runs_dir.mkdir(parents=True, exist_ok=True)
    paths.pause_sentinel_path.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), encoding="utf-8", newline="\n")


def cancel(*, paths: RunPaths = RunPaths()) -> RunRecord:
    """`run cancel` — stops and marks the run terminal (spec §2: "emitted species stay, they are
    already valid seeds"). Unlike `pause`, cancel does not expect the loop to still be alive; it
    marks the LAST WRITTEN record terminal directly, since a cancel is meant to work even against
    a dead process (matching `record.py`'s own crash-recovery discipline)."""
    record = read_record(paths.current_record_path)
    if record is None:
        raise RunRefused("no in-progress run to cancel")
    if record.state not in ("running", "paused"):
        raise RunRefused(f"run {record.run_id} is in state {record.state!r}, not cancellable")
    record.state = transition(record.state, "cancel")
    record.updated_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_record(record, paths.current_record_path)
    _commit_completed_record(record, paths)
    if paths.pause_sentinel_path.exists():
        paths.pause_sentinel_path.unlink()
    return record


def status(*, paths: RunPaths = RunPaths()) -> "dict[str, Any]":
    """`run status` — state, progress, and an ETA derived from `callsMade` (spec's own Commands
    section). Reads only the record; makes no model call and touches no anchor file."""
    record = read_record(paths.current_record_path)
    if record is None:
        return {"state": "idle", "message": "no in-progress or paused run"}
    elapsed = None
    try:
        started = time.strptime(record.started_utc, "%Y-%m-%dT%H:%M:%SZ")
        elapsed = time.mktime(time.gmtime()) - time.mktime(started)
    except ValueError:
        pass
    return {
        "runId": record.run_id, "state": record.state, "completed": len(record.completed),
        "failed": len(record.failed), "callsMade": record.calls_made,
        "processAlive": is_process_alive(record.pid), "elapsedSec": elapsed,
    }


def _commit_completed_record(record: RunRecord, paths: RunPaths) -> None:
    """Terminal states get a COMMITTED record (spec §3: "committed only for completed runs") —
    written to the tracked `_runs/<runId>.json` in addition to the gitignored in-progress one, and
    the in-progress pointer is cleared so a later `status`/`start` sees a clean slate."""
    from .machine import is_terminal
    if not is_terminal(record.state):
        return
    write_record(record, paths.runs_dir / f"{record.run_id}.json")
    try:
        paths.current_record_path.unlink()
    except FileNotFoundError:
        pass


def _run_loop(
    record: RunRecord, ids: "list[str]", rows: "list[dict]", seed_by_species: "dict[str, Any]",
    threat_tuning: ThreatTuning, *, paths: RunPaths, call: "Callable[..., str] | None",
    progress: "Progress | None", resuming: bool = False, config: "LlmCallerConfig | None" = None,
    workers: int = 1,
) -> RunRecord:
    """`workers` (2026-09-03, real throughput finding: the model-call phase is the entire cost of
    a run and was fully serial) splits each species into two phases that run on different sides of
    one boundary:

    - `_classify_one` — the SLOW phase (all eight pipelines' model calls for one species). Reads
      only per-call-local state (`row`, `seed`, `lore`) plus read-only closures (`by_species`,
      `seed_by_species`, `threat_tuning`, `call`, `config`) and touches no shared mutable state —
      confirmed by tracing `run_one_species` → `orchestrator._invoke` → `llm_caller`'s own request
      construction (a fresh `urllib.request.Request` per call, no session/cache/counter) and
      `permute.order_for` (seeds a fresh `random.Random` per call). Safe to run on N threads at
      once — this is genuinely the only part worth parallelising.
    - `_finalize` — the FAST phase (derive posture/pure/variants, write the family file, rewrite
      the index, update and persist `record`). Still called from exactly ONE thread for every
      species, in the SAME order and with the SAME per-species-checkpoint guarantee the sequential
      path always had (spec §2: "the run record's `completed` list is rewritten to disk after
      every species") — no lock is needed around it because nothing else ever touches it
      concurrently, and no two species' writes can interleave.

    `workers=1` keeps today's exact sequential path (same call order, same checkpoint timing) —
    the branch below is not exercised and nothing about single-worker behaviour changes.
    """
    config = _resolve_config(config)
    by_species = {r["speciesId"]: r for r in rows}
    families = _load_families(paths.family_assignments)
    existing_by_file: "dict[str, list[dict]]" = {}
    for entry in _load_existing_anchors(paths.anchors_dir):
        # `classified_family=entry.get("family")` (fixed 2026-09-04, creature-corpus-self-heal A1):
        # without it, this rebuild used ONLY the external family-assignments.json fallback, which
        # for most species resolves to "unclassified" — a DIFFERENT path than the one the entry
        # actually lives at on disk (which `_write_species_entry` computes WITH the real
        # classified family). The stale-duplicate cross-file cleanup below only works if this
        # dict's keys are the species' REAL on-disk paths, not a phantom re-bucketing of them.
        family = _family_for(entry.get("speciesId", ""), families, classified_family=entry.get("family"))
        side = entry.get("side", "unclassified")
        existing_by_file.setdefault(f"{side}/{family}.json", []).append(entry)

    if not resuming:
        record.state = transition(record.state, "start")
    paths.runs_dir.mkdir(parents=True, exist_ok=True)
    write_record(record, paths.current_record_path)

    total = len(ids) + len(record.completed)

    # Pipeline-scoped rerun (creature-corpus-self-heal B1, 2026-09-04): `record.selector` carries a
    # `pipeline` key whenever the caller asked for one — whether the selector's own `kind` IS
    # "pipeline" (picks every classified species AND scopes to it) or a DIFFERENT kind narrowed
    # WHICH species while `pipeline` narrows execution for them (`cli.py`'s own
    # `_selector_from_args` attaches it either way — checked directly here rather than gated on
    # `kind`, after finding live that gating on kind=="pipeline" silently dropped a combined
    # `--species X --pipeline Y` request into a full reclassification instead of a scoped one). No
    # new RunRecord field needed either way — a paused-then-resumed scoped rerun keeps its scope
    # automatically since the selector is what persists. Redeploying a fixed prompt corpus-wide
    # used to mean either accepting the stale field forever or paying for a full reclassify (~8x
    # the calls) — this re-runs ONLY the named pipeline and merges its own fields into the existing
    # entry, every other pipeline's work untouched.
    pipeline_scope = record.selector.get("pipeline")
    existing_entry_by_id: "dict[str, dict]" = {}
    if pipeline_scope:
        for bucket in existing_by_file.values():
            for entry in bucket:
                sid = entry.get("speciesId")
                if sid:
                    existing_entry_by_id[sid] = entry

    def _classify_one(species_id: str):
        row = by_species.get(species_id)
        if row is None:
            return species_id, None, None, None, None

        existing_entry = existing_entry_by_id.get(species_id) if pipeline_scope else None
        if pipeline_scope and existing_entry is None:
            # Nothing to merge a scoped rerun's own partial output into — a scoped rerun is for
            # ALREADY-classified species only, never a backdoor first classification.
            return species_id, row, None, None, ValueError(
                f"{species_id!r} has no existing anchor entry — a pipeline-scoped rerun cannot "
                f"merge into content that was never classified; use `start`/`rerun` without "
                f"--pipeline for a first classification")

        seed = seed_by_species.get(row["side"] + ":" + str(row["typeId"]))
        basis = seed.basis if seed else "blocked"
        threat_rung = None
        if basis in ("observed", "stated") and seed is not None:
            rung = classify_threat(seed, threat_tuning)
            if rung is not None:
                threat_rung = (rung.id, rung.rung)
        if threat_rung is None and basis in ("observed", "stated"):
            basis = "blocked"  # no computable score — the audited-rung pipeline needs one

        lore = _lore_for(row)
        try:
            if pipeline_scope:
                initial_context = {k: v for k, v in existing_entry.items() if not k.startswith("_")}
                merged = run_one_species(
                    species_id, lore, basis=basis, threat_rung=threat_rung, call=call, config=config,
                    pipelines=[pipeline_scope], initial_context=initial_context)
            else:
                merged = run_one_species(species_id, lore, basis=basis, threat_rung=threat_rung,
                                         call=call, config=config)
            return species_id, row, basis, merged, None
        except Exception as e:  # noqa: BLE001 — a dead species falls into `failed`, never aborts the run
            return species_id, row, basis, None, e

    def _finalize(species_id: str, row, basis, merged, err) -> None:
        if row is None:
            record.failed.append(species_id)
            _remember_failure(record, species_id, "no row in the dump for this species id")
            write_record(record, paths.current_record_path)
            return
        if err is not None:
            # A real observability gap found while diagnosing creature-corpus-self-heal C2 (2026-09-04,
            # 199 real failures with no recorded reason): the RunRecord only ever stored a species
            # id in `failed`, never WHY. Printed once per failure, matching the pattern the
            # `_run_parallel` unexpected-exception backstop already established.
            print(f"seedsmith: {species_id}: {err}", file=sys.stderr)
            record.failed.append(species_id)
            _remember_failure(record, species_id, err)
            record.calls_made += 1
            write_record(record, paths.current_record_path)
            if progress:
                progress(species_id, len(record.completed) + len(record.failed), total)
            return

        merged["speciesId"] = species_id
        merged["side"] = row["side"]
        merged["gameTypeId"] = row.get("typeId")
        if basis is not None:
            merged["basis"] = basis
        merged.pop("_pipelineOutcomes", None)
        species_votes = merged.pop("_votes", None)
        species_attempts = merged.pop("_pipelineAttempts", None)
        species_calls_made = merged.pop("_callsMade", 1 if pipeline_scope else len(PIPELINES))

        # DERIVED fields (spec-classify-pipelines.md §4) — never authored by a model, computed
        # here from what the pipelines DID decide. Nothing else in the codebase calls these
        # (confirmed by grep before wiring this in) — this loop is their one real caller.
        if "aptitudePrimary" in merged:
            merged["posture"] = derive_posture(merged["aptitudePrimary"])
            merged["pure"] = derive_pure(merged["aptitudePrimary"], merged.get("aptitudeSecondary", "none"))
        if "variants" in merged and "rarity" in merged:
            merged["variants"] = clamp_variant_count(merged["variants"], merged["rarity"])
        # rank is a pure function of the two CLASSIFIED fields it reads (spec §1), computed here
        # from what the pipelines actually decided — never authored, never voted. Written even when
        # an input is missing/unresolved (an observed-basis pass whose threat-audit returned a
        # verdict rather than a rung), matching emit.py's rule that a missing key must never mean
        # "unsure"; a scoped rerun's own partial `merged` is corrected by the merge path below.
        merged["rank"] = derive_rank(merged.get("threatBand"), merged.get("rarity"))

        # FAIL CLOSED on a required enum this pipeline could not resolve. Measured live
        # 2026-10-03: a run marked 42 of 904 species `completed` while their entries carried an
        # elementPrimary outside the six declared ids - 37 absent-or-empty, 5 the literal
        # "unresolved" - and characteristic_pool's `_live_row` raises ValueError on exactly
        # that. Written-then-scored-green is the shape of bug that reaches a commit, so the
        # refusal happens BEFORE the write: the bad entry is never persisted, and the species
        # lands in `failed` with a reason a rerun can act on.
        # Judge the fields that WILL BE WRITTEN, not the pass's own output. A pipeline-scoped
        # rerun's `merged` holds ONLY that pipeline's fields - the rest arrive via merge_from
        # INSIDE _write_species_entry. Checking `merged` alone made this guard refuse every
        # scoped rerun of a pipeline that does not itself author elementPrimary: measured, a
        # 111-species `identity` rerun failed 110 of them with THIS refusal, on an element that
        # was present and valid in the entry that would have been written.
        merge_from = existing_entry_by_id.get(species_id) if pipeline_scope else None
        effective = {k: v for k, v in (merge_from or {}).items() if not k.startswith("_")}
        effective.update(merged)
        violations = seed_consumer_violations(effective)
        # The SECOND consumer, as a sibling and never as an extension: the C# anchor reader
        # (`AnchorRowReader.ReadOne` + `SpeciesExpander.Expand`) is a different reader with a
        # different raise set, and the corpus was valid for consumer 1 while failing consumer 2 on
        # 222 entries - which took gk-core's `RealAnchorCorpusFixture` static initialiser down with
        # it, 133 tests, over one missing `aptitudeSecondary`. Its own CLI is fail-fast (first
        # rejection prints and returns 1), so every guard is evaluated and every violation joined
        # into the ONE refusal below: a caller fixing a species must not have to discover the next
        # guard on the next run. `+=` keeps the consumer-1 line above verbatim - the two predicates
        # stay independently testable, and merging them would widen consumer 1's refuse set to
        # fields it does not read.
        violations += csharp_anchor_consumer_violations(effective)
        # WHICH violations BLOCK this write. A full run authors every field, so any violation is
        # this pass's own and every one blocks — unchanged behaviour, and what the test above
        # pins.
        #
        # A pipeline-scoped rerun authors ONLY its own attributes, and refusing it over a defect in
        # a field it never touched makes corpus repair deadlock against itself. Measured
        # 2026-10-04, three separate deadlocks from this one rule, each ending a repair round early:
        # `kit-shape` refused for a still-absent `aptitudeSecondary` while the secondary pipeline was
        # refused for the still-absent `reach` (71 of 134 `kit-shape` reruns); and finally
        # `deployMode: ""` blocking `kit-shape` while `attackTempo: ""` blocked `deployment`, seven
        # species that no rerun of anything could ever write. A violation in a field this pass did
        # not author is not this pass's to refuse on — refusing does not repair it, it only stops
        # progress — so it is reported on stderr, following the per-species failure precedent in
        # `_run_parallel`, and the write proceeds.
        #
        # Whole-entry conformance is not lost by this: it is the CORPUS gate's job, not the write
        # path's. `csharp_anchor_corpus_violations` checks a whole document in one pass and is what a
        # validator or CI runs; the per-species guard exists to stop a pass from persisting its OWN
        # bad output, which is exactly what this still refuses.
        own_attributes = set(PIPELINES[pipeline_scope].attributes) if pipeline_scope else None
        blocking = violations if own_attributes is None else tuple(
            v for v in violations if _violation_names_any(v, own_attributes))
        if violations and not blocking:
            print(f"seedsmith: {species_id}: writing with a defect this pipeline does not own: "
                  + "; ".join(violations), file=sys.stderr)
        if blocking:
            record.failed.append(species_id)
            _remember_failure(
                record, species_id,
                "; ".join(blocking) + "; not written")
            write_record(record, paths.current_record_path)
            if progress:
                progress(species_id, len(record.completed) + len(record.failed), total)
            return
        _write_species_entry(
            row, merged, dump_hash=record.dump_hash, families=families,
            anchors_dir=paths.anchors_dir, existing_by_file=existing_by_file,
            votes=species_votes, pipeline_attempts=species_attempts,
            merge_from=merge_from)
        _rewrite_index(paths.anchors_dir, existing_by_file)

        record.completed.append(species_id)
        record.calls_made += species_calls_made
        record.updated_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        write_record(record, paths.current_record_path)
        if progress:
            progress(species_id, len(record.completed) + len(record.failed), total)

    try:
        if workers <= 1:
            paused = False
            for species_id in ids:
                if paths.pause_sentinel_path.exists():
                    paths.pause_sentinel_path.unlink()
                    paused = True
                    break
                _finalize(*_classify_one(species_id))
        else:
            paused = _run_parallel(ids, workers, _classify_one, _finalize, paths)

        if paused:
            record.state = transition(record.state, "pause")
            write_record(record, paths.current_record_path)
            return record
    except BaseException:
        record.state = "failed"
        write_record(record, paths.current_record_path)
        raise

    record.state = transition(record.state, "complete")
    write_record(record, paths.current_record_path)
    _commit_completed_record(record, paths)
    return record


def _run_parallel(
    ids: "list[str]", workers: int,
    classify_one: "Callable[[str], tuple]", finalize: "Callable[..., None]",
    paths: RunPaths,
) -> bool:
    """Runs `classify_one` for every id across `workers` daemon threads (the slow, independent
    model-call phase) and calls `finalize` for each result ONE AT A TIME from THIS thread only (the
    fast write phase — `_run_loop`'s own docstring covers why no lock is needed for either side).

    Pause semantics match the sequential loop's own rule (spec §2: "a species half-classified... is
    not a resumable unit") extended to N workers: once the pause sentinel is seen, workers stop
    PULLING new work, but anything already in flight finishes and still gets finalized — so a pause
    with `workers=4` may complete up to 3 more species than the exact moment `pause` was requested,
    never a partial one. Every worker puts exactly one `None` sentinel on `result_q` as its last
    action (whether it stopped because the queue emptied or because `stop` was set), so the count of
    sentinels received — not a fixed total — is what proves every worker has truly exited; relying
    on a fixed result count instead would hang forever on a pause, since some queued species then
    never produce a result at all.
    """
    import queue
    import threading

    work_q: "queue.Queue[str]" = queue.Queue()
    for species_id in ids:
        work_q.put(species_id)

    result_q: "queue.Queue[tuple | None]" = queue.Queue()
    stop = threading.Event()

    def worker() -> None:
        while not stop.is_set():
            try:
                species_id = work_q.get_nowait()
            except queue.Empty:
                break
            # `classify_one` (the real one, wired from `_run_loop`) already catches everything it
            # can predict and returns the error as data. This second net is for what it CANNOT
            # predict — a genuine bug — because an uncaught exception in a worker thread does not
            # propagate to the main thread; it would kill this worker silently, its final `None`
            # sentinel would never be sent, and `_run_parallel`'s exit loop would then wait forever
            # for a sentinel that is never coming. A hang on a run meant to take hours is far worse
            # than one more species landing in `failed`.
            try:
                result_q.put(classify_one(species_id))
            except Exception as e:  # noqa: BLE001 — see above: this is the backstop, not the path
                import sys
                print(f"seedsmith: {species_id}: unexpected error in classify_one worker: {e}",
                      file=sys.stderr)
                result_q.put((species_id, None, None, None, e))
        result_q.put(None)  # this worker is done, permanently — never another result from it

    threads = [threading.Thread(target=worker, daemon=True, name=f"seedsmith-classify-{i}")
               for i in range(workers)]
    for t in threads:
        t.start()

    paused = False
    finished_workers = 0
    try:
        while finished_workers < workers:
            if not paused and paths.pause_sentinel_path.exists():
                paths.pause_sentinel_path.unlink()
                stop.set()
                paused = True
            item = result_q.get()
            if item is None:
                finished_workers += 1
                continue
            finalize(*item)
    finally:
        stop.set()
        for t in threads:
            t.join()

    return paused
