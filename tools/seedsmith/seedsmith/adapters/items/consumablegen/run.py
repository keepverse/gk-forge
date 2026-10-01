"""seedsmith.adapters.items.consumablegen.run — the run plan, the ledger, and the reconcile report.

Two separate jobs live here, and they read two different corpora:

1. **Reconcile the real 60-entry corpus** (`load_corpus` / `reconcile_grants_and_cooldowns`) —
   acceptance criterion 2. This is a pure read: it never writes into
   `gk-data/packs/fusion/data/seed/items/consumables/*.json` (out of scope per the spec's own Boundaries — "deciding
   whether/how those 60 specific rows should grant an action is a content decision... not this
   generator's to make unprompted").
2. **Plan and persist newly generated rows** through `pipeline.run_ledger.RunLedger` — acceptance
   criterion 3 ("output through generator-harness's ledger"), with `family` checked against the real
   `atom-family-library.md` vocabulary via `pipeline.dependency_validator`'s `EXTERNAL` reference
   kind before anything is marked done.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import brief as brief_mod
from . import emit as emit_mod
from . import schema
from .. import registries
from ....pipeline.dependency_validator import EXTERNAL, ReferenceManifestEntry, validate
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

CONSUMABLES_DIR = _owned("data/seed/items/consumables")
DEFAULT_LEDGER = _owned("data/seed/items/_runs/consumables-gen.ledger.json")

# --- reconcile: the real, shipped 60-entry corpus -------------------------------------------------


def load_corpus(directory: "Path | None" = None) -> "dict[str, dict]":
    """Every `*.json` partition file in `directory` (default: the real shipped consumables
    directory), `{entry_id: entry}` in filename-then-list order — deterministic and stable across
    runs, per `dependency_validator`'s own "pass an already-sorted dict" contract. Read-only: this
    function never writes anything."""
    dir_path = directory if directory is not None else CONSUMABLES_DIR
    entries: "dict[str, dict]" = {}
    for path in sorted(dir_path.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for entry in doc.get("entries") or ():
            entries[entry["id"]] = entry
    return entries


@dataclass(frozen=True)
class ReconcileReport:
    total: int
    missing_grants_action_id: "tuple[str, ...]"
    missing_cooldown_key: "tuple[str, ...]"
    missing_both: "tuple[str, ...]"

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "missingGrantsActionId": list(self.missing_grants_action_id),
            "missingGrantsActionIdCount": len(self.missing_grants_action_id),
            "missingCooldownKey": list(self.missing_cooldown_key),
            "missingCooldownKeyCount": len(self.missing_cooldown_key),
            "missingBoth": list(self.missing_both),
            "missingBothCount": len(self.missing_both),
        }


def reconcile_grants_and_cooldowns(entries: "dict[str, dict]") -> ReconcileReport:
    """Acceptance criterion 2, verbatim: "reports precisely which rows are schema-eligible but
    unauthored." Both fields are legal on every `consumable` row (`kinds.py:100-101`'s `extra` set)
    so every row is schema-eligible; this reports which ones are missing the field outright (absent
    key, or present and `None` — a row that explicitly authored `null` is exactly as unauthored as
    one that never mentioned the field)."""
    missing_grants: "list[str]" = []
    missing_cooldown: "list[str]" = []
    missing_both: "list[str]" = []
    for entry_id, entry in entries.items():
        has_grants = entry.get("grantsActionId") is not None
        has_cooldown = entry.get("cooldownKey") is not None
        if not has_grants:
            missing_grants.append(entry_id)
        if not has_cooldown:
            missing_cooldown.append(entry_id)
        if not has_grants and not has_cooldown:
            missing_both.append(entry_id)
    return ReconcileReport(
        total=len(entries),
        missing_grants_action_id=tuple(missing_grants),
        missing_cooldown_key=tuple(missing_cooldown),
        missing_both=tuple(missing_both),
    )


# --- family: the EXTERNAL reference, via the shared dependency_validator --------------------------

#: The one manifest entry this module declares: `family` is a HARD-shaped id into a corpus this
#: program does not own (`atom-family-library.md`), so it is EXTERNAL — validated exactly like a
#: hard reference, but `dependency_validator.plan_backfill` never emits a request for it (this
#: program has no standing to author effect-atom's own content).
FAMILY_REFERENCE_MANIFEST = (
    ReferenceManifestEntry("family", EXTERNAL, "atom-family-library"),
)


def _resolve_hard(_target_module: str, value: object) -> bool:
    return schema.is_real_atom_family(value)


def _resolve_categorical(_target_module: str, _value: object) -> int:
    # `family` is the only manifest entry and it is HARD-shaped (EXTERNAL); no CATEGORICAL
    # reference exists in this module, so this is never actually called, and it raises rather than
    # silently returning a count if that ever stops being true.
    raise NotImplementedError("consumablegen declares no CATEGORICAL reference")


def validate_family_references(entries: "dict[str, dict]"):
    """`dependency_validator.validate` over every entry's `family` field. `.unresolved` on the
    result names exactly the rows whose `family` is not a real, shipped `atom-family-library.md`
    name — the Boundaries' own "verify before emitting" check, run here so it can also be pointed at
    the real 60-row corpus as a live audit, not only at freshly generated rows."""
    return validate(entries, list(FAMILY_REFERENCE_MANIFEST), _resolve_hard, _resolve_categorical)


class FamilyNotReal(ValueError):
    """Raised instead of emitting an entry whose `family` is not in `atom-family-library.md`'s real,
    shipped vocabulary. This program has no standing to author or guess at effect-atom's own
    content — dependency_validator's own EXTERNAL contract, enforced at the one call site that mints
    new rows."""


# --- generate: ledger-backed, family-checked ------------------------------------------------------


@dataclass(frozen=True)
class GenerateOutcome:
    subject_id: str
    outcome: str  # "persisted" | "refused"
    entry: "dict | None" = None
    defects: "tuple[str, ...]" = ()


def _ledger_entry_is_valid(_subject_id: str, ledger_entry: dict) -> bool:
    """`RunLedger.plan`'s `is_valid` — a ledger row claiming "done" is requeued if the entry it
    recorded no longer resolves against the CURRENT, live family library (effect-atom can rename or
    retire a family out from under an old ledger row; re-checking here is what makes that a
    reconcile hit rather than a silent drift)."""
    entry = ledger_entry.get("entry")
    return isinstance(entry, dict) and schema.is_real_atom_family(entry.get("family"))


def plan_generate(subject_ids: "list[str]", ledger: RunLedger) -> "list[str]":
    return ledger.plan(subject_ids, is_valid=_ledger_entry_is_valid)


def generate_one(subject_id: str, answer: dict, *, entry_id: str, seq: int,
                  ledger: RunLedger) -> GenerateOutcome:
    """One subject, start to finish: validate the answer's own shape (`emit.validate_answer`), then
    validate `family` as an EXTERNAL reference (never auto-backfilled — refuse rather than invent),
    then emit and mark the ledger done. A defect at either stage refuses without touching the
    ledger."""
    defects = [str(d) for d in emit_mod.validate_answer(answer)]
    family = answer.get("family")
    if isinstance(family, str) and not schema.is_real_atom_family(family):
        defects.append(
            f"family: {family!r} is not a real, shipped family in atom-family-library.md — this "
            f"program has no standing to author it (EXTERNAL reference, never backfilled)")
    if defects:
        return GenerateOutcome(subject_id, "refused", defects=tuple(defects))

    entry = emit_mod.build_entry(answer, entry_id=entry_id, seq=seq)
    ledger.mark_done(subject_id, {"entry": entry})
    return GenerateOutcome(subject_id, "persisted", entry=entry)


# --- persist: a real corpus-shaped partition file, atomically -------------------------------------

#: `naming.v1.json`'s registered classes registry moved to `classes.v2.json` (item-ideal.md base-
#: types module 6, D35) — `adapters.items.registries.load_versions()` still reads `classes.v1.json`
#: (registryVersion 3), which is stale relative to what `ItemSeedValidator` actually loads
#: (registryVersion 4, confirmed 2026-09-07 via `dotnet run --project gk-forge/tools/ItemSeedValidator`).
#: Fixing that drift is outside this module's scope (consumablegen only); this override exists so a
#: freshly WRITTEN partition file declares the version the real validator checks it against, rather
#: than inheriting a stale reading that would cost it an avoidable MetaRegistryVersionBehind warning.
_CLASSES_VERSION_OVERRIDE = 4


def _current_registry_versions() -> "dict[str, int]":
    versions = dict(registries.load_versions())
    versions["classes"] = _CLASSES_VERSION_OVERRIDE
    return versions


def write_partition_file(entries: "list[dict]", *, path: Path, partition: str, batch_name: str,
                          model: str, authored_utc: str, source_ref: str) -> Path:
    """Writes ONE new `gk-data/packs/fusion/data/seed/items/consumables/*.json` file: same top-level shape as the shipped
    `k1.json`/`k2.json`/`k3.json` (`schemaVersion`, `kind`, `_meta`, `entries`), same atomic
    temp-file-then-`os.replace` discipline `RunLedger.write_done` and `gemgen/run.py`'s own
    `write_partition_file` both use — a killed process leaves either no file or a complete one, never
    a half-written one.

    Deliberately never overwrites or appends into an EXISTING partition file (`k1.json` etc.) — this
    module has no standing to rewrite the shipped 60-row corpus unprompted (the same boundary
    `reconcile_grants_and_cooldowns`'s own docstring states for that corpus), and `IdentityCheck`'s
    `PartitionMixed` rule requires one allocated partition per file, so a caller passing entries from
    more than one `consumable.k{slot}-*` prefix into the same `path` would fail validation by
    construction — that is `ItemSeedValidator`'s own check catching it, not a check duplicated here.
    """
    doc = {
        "schemaVersion": 1,
        "kind": "consumable",
        "_meta": {
            "batch": batch_name,
            "partition": partition,
            "contractVersion": 1,
            "registryVersions": _current_registry_versions(),
            "exemplarVersion": 1,
            "promptVersion": brief_mod.PROMPT_VERSION,
            "model": model,
            "authoredUtc": authored_utc,
            "sourceRef": source_ref,
        },
        "entries": entries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return path


def _next_seq_for_partition(entries: "dict[str, dict]", prefix: str) -> int:
    indices = [int(eid[len(prefix):]) for eid in entries
              if eid.startswith(prefix) and eid[len(prefix):].isdigit()]
    return (max(indices) + 1) if indices else 1


def main(argv=None) -> int:
    """`seedsmith items generate --kind consumable` (item-seedgen module `consumables-gen`).

    ⛔ **Real gap, closed 2026-09-08.** This module had `reconcile_grants_and_cooldowns`/
    `generate_one`/`write_partition_file` and a spec (`docs/architecture/item-seedgen/
    spec-consumables-gen.md`) documenting `items generate --kind consumable --brief <theme-file>
    --write` as the real invocation, but no CLI entrypoint of any kind. Default (no `--theme`, no
    `--overwrite`) reconciles the real 60-row corpus and makes no model call — the spec's own stated
    default. `--theme` mints exactly ONE new consumable into the partition `--slot` names (this
    module never had an id-minting helper for a NEW entry — `--slot`'s own next-free seq is scanned
    fresh here, the same convention `basetypegen`/`droptablegen` already establish for their own
    open-ended partitions). No schema exists yet for this module's own answer shape (unlike its
    siblings) — constrained decoding is honestly skipped (`schema={}`) rather than inventing one.
    """
    import argparse
    import dataclasses

    ap = argparse.ArgumentParser(description="Reconcile the consumables corpus, or author one new "
                                             "entry into a named partition.")
    ap.add_argument("--slot", type=int, default=0, help="the k<N> partition a new entry lands in")
    ap.add_argument("--theme", default="", help="an inline theme hint; mints one new entry")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --theme, print the one-entry brief without calling a model")
    ap.add_argument("--write", action="store_true", help="write the new partition entry to disk")
    ap.add_argument("--overwrite", default="",
                    help="a full existing consumable id to regenerate in place (needs --theme too)")
    ap.add_argument("--endpoint", default="", help="live model endpoint; enables a real run")
    ap.add_argument("--model", default="", help="overrides load_config()'s own model for this run")
    args = ap.parse_args(argv)

    if not args.theme:
        entries = load_corpus()
        report = reconcile_grants_and_cooldowns(entries)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.dry_run:
        print(brief_mod.build_consumable_brief(args.theme))
        return 0

    if not args.write:
        raise SystemExit(
            "seedsmith: refused — no --write. --theme with no --write has nothing further to "
            "inspect (this module has no --dry-run brief preview yet); re-run with --write "
            "--endpoint <url> to actually call a model and persist.")

    if args.overwrite:
        entry_id = args.overwrite
    else:
        if not args.slot:
            raise SystemExit("seedsmith: a new entry needs --slot (which k<N> partition it lands in)")
        entries = load_corpus()
        prefix = f"consumable.k{args.slot}-"
        entry_id = f"{prefix}{_next_seq_for_partition(entries, prefix):03d}"

    seq = int(entry_id.rsplit("-", 1)[-1])

    from ....pipeline.llm_caller import live_answer_caller, resolve_live_transport

    config = resolve_live_transport(args.endpoint, args.model)
    if not config.endpoint:
        raise SystemExit(
            "seedsmith: --write refused — no live endpoint. Pass --endpoint <url> or set "
            "SEEDSMITH_LLM_ENDPOINT in tools/seedsmith/.env; --dry-run needs neither.")
    caller = live_answer_caller(config)
    brief = brief_mod.build_consumable_brief(args.theme)
    answer = caller(brief, {})

    ledger = RunLedger(DEFAULT_LEDGER)
    outcome = generate_one(entry_id, answer, entry_id=entry_id, seq=seq, ledger=ledger)
    if outcome.outcome == "persisted":
        slot = args.slot or int(entry_id.split("-")[0].removeprefix("consumable.k"))
        # Additive: this module's own `write_partition_file` writes exactly the entries handed to
        # it (never merges) — a fresh CLI-authored partition accumulates across runs the same way
        # every sibling module's own `write_corpus` does, so a second run does not wipe the first.
        cli_partition_path = CONSUMABLES_DIR / f"k{slot}-cli.json"
        existing = {}
        if cli_partition_path.exists():
            existing = {e["id"]: e for e in
                       json.loads(cli_partition_path.read_text(encoding="utf-8")).get("entries", [])}
        merged = {**existing, outcome.entry["id"]: outcome.entry}
        write_partition_file(
            [merged[k] for k in sorted(merged)], path=cli_partition_path,
            partition=f"consumables/k{slot}", batch_name=f"consumables-k{slot}-cli",
            model=config.model, authored_utc="", source_ref="entry-shapes.md#8")
    print(json.dumps({"entryId": entry_id, "outcome": outcome.outcome,
                      "defects": list(outcome.defects)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
