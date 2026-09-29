"""seedsmith.adapters.items.recipegen.run — the run plan, ledger wiring, reconcile, and the
container-backfill mechanism (`generator-harness`, acceptance #3/#4/#5).

⭐ **Real finding, confirmed against the shipped `gk-data/packs/fusion/data/seed/items/recipes/recipes.json` while
building this module (2026-09-07):**

1. **Acceptance #3's own evidence, positive:** every one of the 30 real `operation` values already
   matches `opvocab.ALL_OPERATIONS` — `reconcile_operations_against_real_corpus()` returns `[]`
   today. The 2026-09-05 hand patch (`"reroll"` -> `"reroll-one"`/`"reroll-all"`) is why: it already
   fixed the one drift this check exists to catch, so today's corpus is clean. Had this run BEFORE
   that patch, it would have flagged `recipe.015`-`018`/`026`-`028` (`operation: "reroll"`) as
   outside the real vocabulary — exactly the mechanical catch the spec asks this module to prove.

2. **Corrected 2026-09-07 (was reported here as a real hard-reference gap; verified false):**
   `recipe.004`'s `outputRef` (`"item.plant-stem-b-001"`) DOES exist —
   `gk-data/packs/fusion/data/seed/items/base-types/plant-stem-b.json` (role `core-guard`, frame `plant`, band `b`).
   `base_type_id_exists()`'s original check only tried the role-id-based filename
   (`plant-core-guard-b.json`), which is genuinely absent — but the real, shipped file for that
   partition was authored under the display word (`frameRoleName: "stem"`), a filename
   inconsistency base-types-gen's own report already documented across the corpus's older,
   pre-generator content. Fixed by adding a frame-role-name-shaped filename fallback (read-only,
   never changes where a NEW entry gets written); `build_reference_reports()` now correctly
   reports zero unresolved `container` references against the real corpus — every `container`/
   `material` outputRef in the 30 entries resolves cleanly.

3. **FIXED 2026-09-07, later the same day, by a sibling module:** seven cost lines
   (`recipe.009`/`010`/`011`/`017`/`018`/`025`/`029`) named one of the four LEGACY shard ids
   (`shard.common`/`rare`/`epic`/`legendary`). `MaterialCatalog.IsLegacyShardId` was `true` for
   these, so `MaterialRecipeCatalog.Load` refused all seven at real C# import time
   (`MaterialUnissuableRule`) — matching that class's own doc comment, *"Refusals ... Never empty
   against today's shipped corpus"* (tasks/item-todo.md P4.1). `materialgen.vocab.require_issuable`
   already refuses a legacy id at GENERATION time (acceptance #1's own gate), so this generator
   could never reproduce the defect — but it also could never repair it, since it only mints NEW
   recipes, never re-authors the 30 pre-existing hand-authored ones. See sibling module
   `recipegen.migrate_legacy_shards` (detect + fix, mirroring `LegacyCreatureRarityIds.ForwardMap`
   exactly), now applied to the real corpus — `build_reference_reports()`'s `cost_lines.unresolved`
   is `[]` today.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from seedsmith.pipeline.dependency_validator import (
    HARD,
    BackfillRequest,
    ReferenceManifestEntry,
    ValidationReport,
    plan_backfill,
    validate,
)
from seedsmith.pipeline.run_ledger import RunLedger

from ....pipeline.provenance import provenance_model

from ..basetypegen import emit as basetype_emit
from ..basetypegen import run as basetype_run
from ..basetypegen import tuning as basetype_tuning
from ..materialgen import vocab as material_vocab
from . import forgegem
from . import imbue
from . import opvocab
from . import repair
from . import schema as schema_mod
from .brief import ForgeTarget, RecipeBrief, build_recipe_brief
from .emit import assemble_entry, emit_document, next_seq, write_document

REPO_ROOT = Path(__file__).resolve().parents[6]
RECIPES_CORPUS_PATH = REPO_ROOT / "data" / "seed" / "items" / "recipes" / "recipes.json"
DEFAULT_LEDGER_PATH = REPO_ROOT / "data" / "seed" / "items" / "_runs" / "recipes-gen.ledger.json"

CONTAINER_MANIFEST = [ReferenceManifestEntry("outputRef", HARD, "base-types-gen")]
MATERIAL_OUTPUT_MANIFEST = [ReferenceManifestEntry("outputRef", HARD, "materials-gen")]
COST_LINE_MANIFEST = [ReferenceManifestEntry("costLines[].material", HARD, "materials-gen")]

_TARGET_ID_RE = re.compile(r"^item\.(humanoid|plant)-(.+)-([a-z])-(\d{3,})$")


class BackfillTargetError(ValueError):
    """A missing container reference cannot be parsed back into a `(role, frame, band, seq)`
    partition request, or the parsed seq does not match the partition's own next-mintable id."""


# ---------------------------------------------------------------------------------------------
# Loading the real corpus
# ---------------------------------------------------------------------------------------------


def load_entries(path: "Path | None" = None) -> "dict[str, dict]":
    p = path or RECIPES_CORPUS_PATH
    if not p.exists():
        return {}
    doc = json.loads(p.read_text(encoding="utf-8"))
    return {e["id"]: e for e in doc.get("entries", []) if isinstance(e.get("id"), str)}


# ---------------------------------------------------------------------------------------------
# Acceptance #3 — reconcile `operation` against the real, current CraftOperations vocabulary
# ---------------------------------------------------------------------------------------------


def reconcile_operations_against_real_corpus(path: "Path | None" = None) -> "list[tuple[str, str]]":
    """`[]` today (see module docstring finding #1) — a non-empty result names exactly the entries
    whose `operation` a future C# rename left behind, the mechanical catch that would have caught
    2026-09-05's drift before it needed a hand patch."""
    entries = load_entries(path)
    return opvocab.reconcile_operations(dict(sorted(entries.items())))


# ---------------------------------------------------------------------------------------------
# Acceptance #5 — HARD reference validation, split by outputKind (see module docstring: `outputRef`
# means a DIFFERENT target module depending on a SIBLING field, which `dependency_validator`'s own
# single-target-per-field-path manifest cannot express directly — so this module validates each
# outputKind subset against its own manifest, rather than one manifest against every entry.)
# ---------------------------------------------------------------------------------------------


def base_type_id_exists(entry_id: str, *, base_types_dir: "Path | None" = None) -> bool:
    """True if `entry_id` (an `item.*` id) exists in base-types-gen's real, current corpus. Parses
    the id back into its owning `(role, frame, band)` partition via `naming.v1.json`'s own
    `item.<frame>-<frameRoleName>-<band>-<seq>` grammar, then reads that partition — never a
    full-corpus scan, matching how `basetypegen.run.load_existing` already loads one partition at
    a time. An id that does not even match the grammar, or whose frame-role-name maps to no real
    role, is simply not found — never an error, since a validator checking "does X exist" must
    treat "not even well-formed" as "no" and nothing else.

    ⭐ **Real, previously-undiscovered false positive, found and fixed 2026-09-07** (this session's
    own follow-up verification, going past this module's original report): `basetypegen.run.
    load_existing`'s own `_partition_file` builds exactly one filename,
    `{frame}-{role}-{band}.json` — but a real, shipped file this exact check needs to see,
    `gk-data/packs/fusion/data/seed/items/base-types/plant-stem-b.json` (role `core-guard`, containing the real, valid
    `item.plant-stem-b-001` `recipe.004`'s own `outputRef` names), was authored under the DISPLAY
    WORD (`stem`, `frame_role_name`) instead — a real, already-documented inconsistency
    `base-types-gen`'s own module (`tasks/item-seedgen-todo.md`, base-types-gen's real findings)
    found across the corpus's OLDER, pre-generator content: "filenames don't consistently follow
    either roleId or frameRoleName". The original single-filename check reported `recipe.004`'s real,
    existing target as missing. Fixed with a second, frame-role-name-shaped filename as a fallback —
    read-only, never changes which filename a NEW entry is written under (that stays
    `basetypegen`'s own `{frame}-{role}-{band}.json` convention going forward), only widens what
    counts as "found" when checking EXISTING, possibly inconsistently-named content.
    """
    m = _TARGET_ID_RE.match(entry_id)
    if not m:
        return False
    frame, frame_role_name, band, _seq = m.groups()
    role = _role_for_frame_role_name(frame, frame_role_name)
    if role is None:
        return False
    existing = basetype_run.load_existing(role, frame, band, base_types_dir=base_types_dir)
    if entry_id in existing:
        return True
    return entry_id in _load_by_frame_role_name(frame, frame_role_name, band, base_types_dir=base_types_dir)


def _load_by_frame_role_name(frame: str, frame_role_name: str, band: str, *,
                             base_types_dir: "Path | None" = None) -> "dict[str, dict]":
    """The fallback filename shape older, pre-generator content used:
    `{frame}-{frameRoleName}-{band}.json` (the display word, e.g. `plant-stem-b.json`), rather than
    `basetypegen`'s own forward-going `{frame}-{role}-{band}.json`. Read-only lookup, same shape as
    `basetypegen.run.load_existing`, deliberately not merged into that function since it must stay
    the single source of truth for where a NEW entry gets WRITTEN — this is a widened READ only."""
    directory = base_types_dir or basetype_tuning.BASE_TYPES_DIR
    p = directory / f"{frame}-{frame_role_name}-{band}.json"
    if not p.exists():
        return {}
    doc = json.loads(p.read_text(encoding="utf-8"))
    return {e["id"]: e for e in doc.get("entries", []) if isinstance(e.get("id"), str)}


def _role_for_frame_role_name(frame: str, frame_role_name: str) -> "str | None":
    for role_id, info in basetype_tuning.load_role_registry().items():
        if info.frame_role_name(frame) == frame_role_name:
            return role_id
    return None


@dataclass(frozen=True)
class ReferenceReports:
    container: ValidationReport
    material_output: ValidationReport
    cost_lines: ValidationReport

    @property
    def all_unresolved(self) -> "list":
        return [*self.container.unresolved, *self.material_output.unresolved,
                *self.cost_lines.unresolved]


def build_reference_reports(entries: "dict[str, dict]", *,
                            base_types_dir: "Path | None" = None) -> ReferenceReports:
    """Validates the reference manifest table from spec-recipes-gen.md, split by `outputKind`
    exactly as that table requires: `container` rows' `outputRef` against base-types-gen,
    `material` rows' `outputRef` against materials-gen's issuable vocabulary, and EVERY row's
    `costLines[].material` against that same issuable vocabulary. `mutation` rows carry no
    `outputRef` at all (real corpus confirmed), so they are simply absent from both outputRef
    subsets — `dependency_validator._extract` returns `None` for a missing field and `validate`
    skips it, so this needs no special-casing beyond the subset split itself."""
    container_entries = {k: v for k, v in entries.items() if v.get("outputKind") == "container"}
    material_entries = {k: v for k, v in entries.items() if v.get("outputKind") == "material"}

    container_report = validate(
        container_entries, CONTAINER_MANIFEST,
        resolve_hard=lambda _module, value: base_type_id_exists(value, base_types_dir=base_types_dir),
        resolve_categorical=lambda _module, _value: 0)
    material_output_report = validate(
        material_entries, MATERIAL_OUTPUT_MANIFEST,
        resolve_hard=lambda _module, value: material_vocab.is_issuable(value),
        resolve_categorical=lambda _module, _value: 0)
    cost_line_report = validate(
        entries, COST_LINE_MANIFEST,
        resolve_hard=lambda _module, value: material_vocab.is_issuable(value),
        resolve_categorical=lambda _module, _value: 0)

    return ReferenceReports(container=container_report, material_output=material_output_report,
                            cost_lines=cost_line_report)


def plan_container_backfill(entries: "dict[str, dict]", *,
                            base_types_dir: "Path | None" = None) -> "list[BackfillRequest]":
    """The exact `plan_backfill` contract acceptance #5 names: every missing `container` target,
    deduped, never touching `material`/`mutation` rows (those have no backfillable HARD reference
    into base-types-gen at all)."""
    reports = build_reference_reports(entries, base_types_dir=base_types_dir)
    return plan_backfill(reports.container)


def mint_forge_backfill(request: BackfillRequest, *, base_types_dir: "Path | None" = None,
                        ledger: "RunLedger | None" = None, model: str,
                        call: Callable[[str, dict], dict]) -> "dict[str, dict]":
    """Mints EXACTLY the missing base-type id a `plan_container_backfill` request names — the
    "--backfill triggers base-types-gen to mint that exact target first" half of acceptance #5.

    Parses the requested id back into its `(role, frame, band, seq)` partition, and refuses (rather
    than minting the wrong thing) if the requested seq is not the partition's own next-mintable
    one — this generator never asks base-types-gen to mint an ARBITRARY id, only the next one in
    sequence, so "exact target" is a real guarantee rather than a coincidence.
    """
    if request.target_module != "base-types-gen" or request.kind != HARD:
        raise BackfillTargetError(f"unexpected backfill request: {request}")
    missing_id = str(request.id_or_selector)
    m = _TARGET_ID_RE.match(missing_id)
    if not m:
        raise BackfillTargetError(f"{missing_id!r} does not match the item.<frame>-<slot>-<band>-<seq> grammar")
    frame, frame_role_name, band, seq_str = m.groups()
    role = _role_for_frame_role_name(frame, frame_role_name)
    if role is None:
        raise BackfillTargetError(
            f"{missing_id!r} names frame-role-name {frame_role_name!r}, which maps to no real "
            f"core.v1.json role on frame {frame!r}")

    existing = basetype_run.load_existing(role, frame, band, base_types_dir=base_types_dir)
    expected_seq = basetype_emit.next_seq(tuple(existing))
    if expected_seq != int(seq_str):
        raise BackfillTargetError(
            f"{missing_id!r} asks for seq {int(seq_str)}, but partition {role}:{frame}:{band}'s "
            f"own next-mintable seq is {expected_seq} — this generator only ever mints the next id "
            f"in sequence, never an arbitrary gap")

    ledger = ledger or RunLedger(DEFAULT_LEDGER_PATH.parent / "base-types-gen.backfill.ledger.json")
    plan = basetype_run.plan_run(role=role, frame=frame, band=band, count=1, ledger=ledger,
                                 base_types_dir=base_types_dir)
    fresh, blocked = basetype_run.run_draws(plan, ledger=ledger, call=call)
    if blocked:
        raise BackfillTargetError(f"backfill mint for {missing_id!r} was blocked: {blocked}")
    (minted_id, minted_entry), = fresh.items()
    if minted_id != missing_id:
        raise BackfillTargetError(
            f"backfill minted {minted_id!r}, not the requested {missing_id!r} — base-types-gen's "
            f"own sequence moved between planning and minting this backfill")
    basetype_run.write_corpus(role, frame, band, fresh, existing=plan.existing,
                              base_types_dir=base_types_dir, model=model)
    return {minted_id: minted_entry}


def run_container_backfill_loop(entries: "dict[str, dict]", *, base_types_dir: "Path | None" = None,
                                call: Callable[[str, dict], dict], model: str,
                                max_depth: int = 3) -> "tuple[list[BackfillRequest], list[BackfillRequest]]":
    """Mints every currently-missing container target, then RE-VALIDATES — matching
    `dependency_validator.run_backfill_loop`'s own cascade-guard discipline (a freshly-minted base
    type could in principle still fail to resolve if the mint itself is refused). Returns
    `(originally_requested, still_unresolved_after)`."""
    requested = plan_container_backfill(entries, base_types_dir=base_types_dir)
    for req in requested:
        mint_forge_backfill(req, base_types_dir=base_types_dir, call=call, model=model)
        if max_depth <= 0:
            break
    remaining = plan_container_backfill(entries, base_types_dir=base_types_dir)
    return requested, remaining


# ---------------------------------------------------------------------------------------------
# Open-ended generation — RunLedger-backed sequential draws (mirrors `materialgen.run`'s own
# "one ledger, upsert on reconcile/overwrite" discipline; recipe ids are corpus-sequential, not
# partitioned the way base-types-gen's role/frame/band triples are).
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Subject:
    subject_id: str
    seq: int
    brief: "RecipeBrief"


@dataclass(frozen=True)
class RunPlan:
    subjects: "tuple[Subject, ...]"
    existing: "dict[str, dict]"


def _draw_prefix() -> str:
    return "recipe-draw-"


def _draw_index(subject_id: str, prefix: str) -> "int | None":
    if not subject_id.startswith(prefix):
        return None
    suffix = subject_id[len(prefix):]
    return int(suffix) if suffix.isdigit() else None


def _draw_indices(done: "dict[str, dict]", prefix: str, count: int,
                  existing: "dict[str, dict]") -> "list[int]":
    """Repair invalid ledger slots before allocating new open-ended draws."""
    indexed = {
        idx: (sid, row) for sid, row in done.items()
        if (idx := _draw_index(sid, prefix)) is not None
    }
    invalid = [idx for idx, (sid, row) in indexed.items() if not is_valid(sid, row, existing=existing)]
    next_index = max(indexed, default=-1) + 1
    selected = sorted(invalid)
    while len(selected) < count:
        selected.append(next_index)
        next_index += 1
    return selected[:count]


def plan_run(*, count: int, ledger: RunLedger, forge_target: "ForgeTarget | None" = None,
            theme_hint: str = "", recipes_path: "Path | None" = None) -> RunPlan:
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")
    existing = load_entries(recipes_path)
    done = ledger.read_done()
    prefix = _draw_prefix()
    draw_indices = _draw_indices(done, prefix, count, existing)
    start_seq = next_seq(tuple(existing))

    subjects = tuple(
        Subject(subject_id=f"{prefix}{draw_index:03d}", seq=start_seq + i,
               brief=build_recipe_brief(forge_target=forge_target, theme_note=theme_hint,
                                        recipes_path=recipes_path))
        for i, draw_index in enumerate(draw_indices))
    return RunPlan(subjects=subjects, existing=existing)


def run_draws(plan: RunPlan, *, ledger: RunLedger,
             call: Callable[[str, dict], dict],
             persist: "Callable[[dict], None] | None" = None
             ) -> "tuple[dict[str, dict], dict[str, dict]]":
    """Mirrors `basetypegen.run.run_draws`: not all-or-nothing, each resolved draw marked done as it
    completes."""
    fresh: "dict[str, dict]" = {}
    blocked: "dict[str, dict]" = {}

    for subject in plan.subjects:
        try:
            answer = call(subject.brief.render(), dict(subject.brief.schema))
        except ValueError as exc:
            blocked[subject.subject_id] = {"reason": f"invalid model response: {exc}"}
            continue
        defects = schema_mod.validate_answer(answer, subject.brief.schema)
        if defects:
            blocked[subject.subject_id] = {"reason": "invalid model response: " + "; ".join(defects)}
            continue
        if answer.get("blocked"):
            blocked[subject.subject_id] = {"reason": answer["blocked"]}
            continue
        try:
            entry = assemble_entry(answer, seq=subject.seq,
                                   forge_target=subject.brief.forge_target)
        except ValueError as exc:
            blocked[subject.subject_id] = {"reason": f"invalid model response: {exc}"}
            continue
        if persist is not None:
            # Corpus first, ledger second, so a write failure leaves the draw retryable on resume.
            persist(entry)
        fresh[entry["id"]] = entry
        ledger.mark_done(subject.subject_id, {"entryId": entry["id"], "operation": entry["operation"]})

    return fresh, blocked


def is_valid(subject_id: str, entry: dict, *, existing: "dict[str, dict]") -> bool:
    """The ledger's own reconcile hook — a "done" draw whose recorded entry id no longer exists, or
    whose `operation` was hand-edited out from under it, resurfaces as needing work."""
    entry_id = entry.get("entryId")
    if not entry_id or entry_id not in existing:
        return False
    return existing[entry_id].get("operation") == entry.get("operation")


def _next_seq(existing: "dict[str, dict]") -> int:
    """One past the highest `recipe.NNN` id in the corpus — the seq a new deterministic row takes."""
    top = 0
    for key in existing:
        if key.startswith("recipe.") and key[7:].isdigit():
            top = max(top, int(key[7:]))
    return top + 1


#: The deterministic step's own amendment batch id — one record per write, keyed by the STEP rather
#: than by which emitter happened to plan rows, so a later deterministic emitter joins the same record
#: instead of minting a second vocabulary.
DETERMINISTIC_AMENDMENT_BATCH = "recipegen/deterministic-emit-1"


def record_deterministic_amendment(ids: "list[str]", *, recipes_path: "Path | None" = None,
                                   authored_utc: str = "1970-01-01T00:00:00Z") -> Path:
    """Append this write's `_meta.amendments` record.

    ⛔ <b>`write_corpus` merges ENTRIES and leaves an existing document's `_meta` alone</b>, so without
    this the deterministic rows would land with no record of HOW they were made — the same
    generator-provenance requirement every generated tree carries (a tree whose entries came from a
    generator must say so). Mechanical, no model call, no prompt."""
    path = recipes_path or RECIPES_CORPUS_PATH
    doc: "dict[str, Any]" = json.loads(path.read_text(encoding="utf-8"))
    amendment = {
        "batch": DETERMINISTIC_AMENDMENT_BATCH,
        "note": (
            "Rows emitted by the DETERMINISTIC step (`--emit-deterministic`): every one carries no "
            "authored choice, so a model call would only retype facts. `forgegem` plans one forge-gem "
            "row per (family, tier -> tier+1) step, and `imbue` (strain-splice-host SSH8.1/SSH8.2) plans "
            "one row per (bore frame, concrete element) from the bore row's own substrate + catalyst "
            "lines and its band VERBATIM, plus essence.<element>. Idempotent by construction: a step the "
            "corpus already carries is skipped, so re-running plans nothing and writes no second "
            "record. `omni` is never an imbue element (it is the absence of an affinity)."
        ),
        "promptVersion": "n/a-deterministic",
        "model": DETERMINISTIC_AMENDMENT_BATCH,
        "authoredUtc": authored_utc,
        "sourceRef": "docs/architecture/strain-splice-host/spec-socket-pricing.md",
        "entries": sorted(ids),
    }
    meta = {**doc["_meta"], "amendments": [*doc["_meta"].get("amendments", []), amendment]}
    return write_document(path, {**doc, "_meta": meta})


def write_corpus(fresh: "dict[str, dict]", *, existing: "dict[str, dict] | None" = None,
                 recipes_path: "Path | None" = None, source_ref: str = "",
                 model: str, authored_utc: str = "") -> Path:
    """Additive: merges `fresh` into the existing corpus, matching every sibling module's
    'append+reconcile by default' contract."""
    model = provenance_model(model)
    p = recipes_path or RECIPES_CORPUS_PATH
    ex = existing if existing is not None else load_entries(recipes_path)
    merged = {**ex, **fresh}
    entries = [merged[k] for k in sorted(merged)]
    if p.exists():
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["entries"] = entries
    else:
        doc = emit_document(entries, batch="recipes-gen", source_ref=source_ref, model=model,
                            authored_utc=authored_utc)
    return write_document(p, doc)


# ---------------------------------------------------------------------------------------------
# CLI — mirrors `basetypegen.run.main`'s/`materialgen`'s own shape: `--dry-run` inspects the plan
# and makes no model calls; a live run REFUSES with no `call` wired in (this file has no transport
# of its own, the same division of labor every sibling module's `main()` states); default with no
# flag at all reconciles the real corpus's `operation` field against the current vocabulary
# (acceptance's own stated default: "reconcile the existing 30 against the current operation
# vocabulary").
# ---------------------------------------------------------------------------------------------


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Author or reconcile the crafting-recipe corpus (item-seedgen module 14).")
    ap.add_argument("--brief", default="", help="an optional theme-hint file")
    ap.add_argument("--dry-run", action="store_true", help="assemble briefs, make no model calls")
    ap.add_argument("--count", type=int, default=0,
                    help="how many new recipes to draw this run (0 == reconcile only, the default)")
    ap.add_argument("--write", action="store_true", help="write the merged corpus back to disk")
    ap.add_argument("--overwrite", "--force", default="",
                    help="comma-separated recipe ids to regenerate, or the literal 'all' "
                         "(--force is an accepted alias, matching content-completeness-core's "
                         "own naming convention -- RunLedger.force()/generate_commander_effects.py "
                         "--force)")
    ap.add_argument("--backfill", action="store_true",
                    help="mint any missing container (forge) target before writing")
    ap.add_argument("--emit-deterministic", action="store_true",
                    help="emit the DERIVED recipe rows (forge-gem, repair) — no model call, "
                         "idempotent; add --write to persist them into the corpus")
    ap.add_argument("--endpoint", default="", help="live model endpoint; enables a real run")
    ap.add_argument("--model", default="", help="overrides load_config()'s own model for this run")
    args = ap.parse_args(argv)

    ledger = RunLedger(DEFAULT_LEDGER_PATH)

    if args.overwrite:
        done = ledger.read_done()
        ids_needing_work = ledger.force(list(done), args.overwrite) if args.overwrite == "all" \
            else ledger.force([s.strip() for s in args.overwrite.split(",") if s.strip()], "ids")
        print(json.dumps({"overwrite": ids_needing_work}, ensure_ascii=False))
        return 0

    if args.emit_deterministic:
        # species-gear-chain T23: the DERIVED rows had an emitter each but no caller, so a row could
        # only reach the corpus by hand — which the generated-data rule forbids. This is that caller:
        # idempotent (each emitter skips a step the corpus already carries), no model call, and it
        # writes through the same `write_corpus` every briefed row uses.
        existing = load_entries()
        rows: "dict[str, dict]" = {}
        seq = _next_seq(existing)
        for row in forgegem.plan_rows(forgegem.load_gem_entries(), existing=existing, start_seq=seq):
            rows[row["id"]] = row
        # strain-splice-host SSH8.1: imbue rows are a DERIVATION too (frame x concrete element from the
        # shipped bore rows), so they ride the same deterministic step rather than a brief.
        for row in imbue.plan_rows(existing={**existing, **rows}, start_seq=seq + len(rows)):
            rows[row["id"]] = row
        for row in repair.plan_rows(existing={**existing, **rows}, start_seq=seq + len(rows)):
            rows[row["id"]] = row
        if not args.write:
            print(json.dumps({"planned": sorted(rows)}, ensure_ascii=False, indent=2))
            return 0
        if rows:
            write_corpus(rows, existing=existing, model="none",
                         source_ref="species-gear-chain T23 (deterministic rows)")
            record_deterministic_amendment(sorted(rows))
        print(json.dumps({"written": sorted(rows)}, ensure_ascii=False, indent=2))
        return 0

    if args.count == 0:
        # The spec's own stated default: "reconcile the existing 30 against the current operation
        # vocabulary" — no model call needed, so this runs regardless of --dry-run/--write.
        drift = reconcile_operations_against_real_corpus()
        reports = build_reference_reports(load_entries())
        print(json.dumps({
            "operationDrift": [{"id": i, "operation": op} for i, op in drift],
            "unresolvedReferences": len(reports.all_unresolved),
        }, ensure_ascii=False, indent=2))
        return 0

    theme_hint = ""
    if args.brief:
        theme_hint = Path(args.brief).read_text(encoding="utf-8")

    if args.dry_run:
        plan = plan_run(count=args.count, ledger=ledger, theme_hint=theme_hint)
        print(json.dumps({"toGenerate": len(plan.subjects), "existingEntries": len(plan.existing)},
                         ensure_ascii=False, indent=2))
        if plan.subjects:
            print("--- sample brief ---")
            print(plan.subjects[0].brief.render())
        return 0

    if not args.write:
        raise SystemExit(
            "seedsmith: refused — no --write. Use --dry-run to inspect the plan first, "
            "then re-run with --write --endpoint <url> to actually call a model and persist.")

    # ⛔ Real gap, closed 2026-09-08 — see basetypegen.run.main's own identical fix for the full
    # account: this branch used to be an unconditional refusal even though `plan_run`/`run_draws`/
    # `write_corpus` were all real and tested. `--backfill` (declared above, never referenced
    # anywhere in this function) is wired too — the same live caller mints any missing forge
    # container target through `run_container_backfill_loop`, the cross-module call into
    # `basetypegen.run` this module's own docstring already names.
    import dataclasses

    from ....pipeline.llm_caller import live_answer_caller, resolve_live_transport

    config = resolve_live_transport(args.endpoint, args.model)
    if not config.endpoint:
        raise SystemExit(
            "seedsmith: --write refused — no live endpoint. Pass --endpoint <url> or set "
            "SEEDSMITH_LLM_ENDPOINT in tools/seedsmith/.env; --dry-run needs neither.")
    caller = live_answer_caller(config, validator=schema_mod.validate_answer)
    plan = plan_run(count=args.count, ledger=ledger, theme_hint=theme_hint)
    persisted = dict(plan.existing)

    def persist(entry: dict) -> None:
        write_corpus({entry["id"]: entry}, existing=persisted, model=config.model)
        persisted[entry["id"]] = entry

    fresh, blocked = run_draws(plan, ledger=ledger, call=caller, persist=persist)
    merged = {**plan.existing, **fresh}
    backfill_result = None
    if args.backfill and fresh:
        requested, remaining = run_container_backfill_loop(merged, call=caller,
                                                           model=config.model)
        backfill_result = {"requested": len(requested), "stillUnresolved": len(remaining)}
    summary = {"planned": len(plan.subjects), "fresh": len(fresh), "blocked": len(blocked),
              "blockedReasons": blocked}
    if backfill_result is not None:
        summary["backfill"] = backfill_result
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
