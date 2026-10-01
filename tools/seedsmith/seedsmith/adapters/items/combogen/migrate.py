"""seedsmith.adapters.items.combogen.migrate — what retiring the `socket-word` corpus actually
touches, computed rather than transcribed.

> ✅ **RULED 2026-09-04: regenerate, do not retain.** The 25 legacy socket-words go; keeping them
> alongside the 102 takes the catalogue to 152 and deepens the learnability failure §4.4 named.
> ⚠ **`Registration/IngredientUnsatisfiable` must follow the kind**, or a `gates = True` check
> quietly stops gating.

⛔ **The rename is a BUNDLE, and only part of it is deterministic.** Five things move together:

| # | site | deterministic? |
|---|---|---|
| 1 | the gating metric's kind lookup (`metrics/linkage.py`) | ✅ **done** — it now reads BOTH ids |
| 2 | the Python `KindSpec` id/directory (`adapters/items/kinds.py`) | with (5) |
| 3 | the C# `KindCatalog` row (`gk-forge/tools/ItemSeedValidator/Registries/KindCatalog.cs`) | with (5) |
| 4 | `naming.v1.json`'s `idNamespaces.socketWords` — **`registryVersion 4, frozen: true`** | ✅ **done** (item-seed-gen ISG7, 2026-09-20: retired to `_socketWords` at registryVersion 10) |
| 5 | the 25 shipped entries themselves | ⛔ **model calls** |

Not one of (2)-(5) is separable without leaving the corpus worse than either endpoint: renaming the
kind over the legacy rows gives a `combination` kind whose every row fails its own required fields;
renaming the namespace without bumping the frozen registry breaks
`NamespaceAllocation.ByNamespace`; and deleting the 25 with nothing to replace them empties the only
input a `gates = True` metric has. So the bundle lands **with** the regeneration run, and this
module ships (1) — the half that removes the risk the ruling actually named — plus this analysis, so
the run is a `--write` away rather than a rediscovery.

`legality_report()` is the evidence for "regenerate, not retain": it measures the 25 against the
rules they would have to satisfy, and the answer is that **not one of them is a legal combination
today.**
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .tuning import ComboTuning

REPO_ROOT = Path(__file__).resolve().parents[6]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from ....workspace_roots import owned_path, owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

LEGACY_FILE = _owned("data/seed/items/socket-words") / "sockwords.json"

LEGACY_KIND = "socket-word"
TARGET_KIND = "combination"

#: The retired runtime-id prefix. D27 renames combination containers `combo.*`; `definitions.md` §1
#: forces the prefix to match the kind, so a `gem.word-*` runtime id is a combination wearing an
#: insert's prefix.
LEGACY_RUNTIME_PREFIX = "gem.word-"

#: Every file the bundle above touches, as (path, why). Asserted to EXIST by a test — a migration
#: plan naming a file that has since moved is worse than no plan, because it reads as done.
#:
#: strain-splice-host SSH2.6: site #5 (the 25 legacy `sockwords.json` entries) is retired for real
#: now (`retire_legacy_partition`, `combogen-migrate --write`, 95 real `combination` entries replace
#: them) and is deliberately NOT listed here any more — this list is "files the STILL-LIVE bundle
#: touches," and a retired file's own absence is the bundle's success for that site, not a defect
#: `missing_sites()` should ever flag.
MIGRATION_SITES: "tuple[tuple[str, str], ...]" = (
    ("tools/seedsmith/seedsmith/metrics/linkage.py",
     "the gating metric Registration/IngredientUnsatisfiable — ✅ reads `combination` alone since "
     "SSH2.6 (socket-word retired for real)"),
    ("tools/seedsmith/seedsmith/adapters/items/kinds.py",
     "the KindSpec id/directory/namespace, and the 16-kind assertion that must still hold"),
    ("tools/seedsmith/seedsmith/planner/schedule.py",
     "the kind ordering used to schedule authoring waves"),
    ("tools/seedsmith/seedsmith/metrics/quality.py",
     "the never-seen-by-a-player kind list"),
    ("tools/ItemSeedValidator/Registries/KindCatalog.cs",
     "the C# port the Python KindSpec list mirrors — both move or the ports diverge; `socket-word`'s "
     "own row is gone here too since SSH2.6"),
    ("data/seed/items/_registry/naming.v1.json",
     "idNamespaces.socketWords + its sockword.{seq:03} template — retired to `_socketWords` at "
     "registryVersion 10 (item-seed-gen ISG7, 2026-09-20): the file the allocation existed for is "
     "gone and `socket-word` is gone from both kind tables, so a live allocation with no kind "
     "would only keep the validator's own stop-the-fleet `NamespaceUncovered` red"),
)


@dataclass(frozen=True)
class LegacyEntry:
    id: str
    name: str
    runtime_id: str
    host_role: "str | None"
    host_frame: "str | None"
    min_sockets: int
    ingredient_families: "tuple[str, ...]"
    has_position: bool

    @property
    def ingredient_count(self) -> int:
        return len(self.ingredient_families)


@dataclass(frozen=True)
class LegalityReport:
    entries: "tuple[LegacyEntry, ...]"
    #: entry id -> every reason it is not a legal combination today
    problems: "dict[str, tuple[str, ...]]"

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def legal(self) -> "tuple[str, ...]":
        return tuple(e.id for e in self.entries if not self.problems.get(e.id))

    @property
    def illegal(self) -> "tuple[str, ...]":
        return tuple(e.id for e in self.entries if self.problems.get(e.id))

    def to_dict(self) -> dict:
        return {
            "kind": LEGACY_KIND,
            "targetKind": TARGET_KIND,
            "entries": self.total,
            "legalAsCombinationsToday": len(self.legal),
            "illegal": len(self.illegal),
            "ruling": "regenerate, do not retain (2026-09-04)",
            "problemsByEntry": {k: list(v) for k, v in sorted(self.problems.items())},
        }


def load_legacy(path: "Path | None" = None) -> "tuple[LegacyEntry, ...]":
    """The legacy `socket-word` corpus, before its retirement (SSH2.3's `retire_legacy_partition`
    verb, invoked for real by SSH2.6). Empty, not an error, once the file is gone — retirement is
    the SUCCESS state this function's own caller (`legality_report`) reports on: "0 of 0 remaining
    legacy entries are illegal" is the vacuously-true, correct answer once there is nothing left to
    measure, not a crash to route around."""
    target = path or LEGACY_FILE
    if not target.exists():
        return ()
    doc = json.loads(target.read_text(encoding="utf-8"))
    if doc.get("kind") not in (LEGACY_KIND, TARGET_KIND):
        raise ValueError(
            f"{(path or LEGACY_FILE).name} declares kind {doc.get('kind')!r}, neither "
            f"{LEGACY_KIND!r} nor {TARGET_KIND!r}")
    out: "list[LegacyEntry]" = []
    for row in doc.get("entries", []):
        ingredients = row.get("ingredients") or []
        out.append(LegacyEntry(
            id=row["id"],
            name=row.get("name", row["id"]),
            runtime_id=row.get("runtimeId", ""),
            host_role=row.get("hostRole"),
            host_frame=row.get("hostFrame"),
            min_sockets=int(row.get("minSockets", 0)),
            ingredient_families=tuple(i.get("family", "") for i in ingredients),
            has_position=any("position" in i for i in ingredients),
        ))
    return tuple(out)


def legality_report(tuning: ComboTuning, *, host_roles: "tuple[str, ...]",
                    path: "Path | None" = None) -> LegalityReport:
    """Measure the 25 against the rules a combination must satisfy. Every reason, not the first."""
    entries = load_legacy(path)
    problems: "dict[str, tuple[str, ...]]" = {}
    for entry in entries:
        reasons: "list[str]" = []
        if entry.ingredient_count != tuning.ingredient_count:
            reasons.append(
                f"takes {entry.ingredient_count} ingredients, not D20's "
                f"{tuning.ingredient_count} (§2f.2)")
        if entry.has_position:
            reasons.append(
                "its ingredients carry `position` — D41 makes a recipe an unordered multiset and "
                "module 16's ComboIngredient has no position field")
        if entry.runtime_id.startswith(LEGACY_RUNTIME_PREFIX):
            reasons.append(
                f"its runtimeId {entry.runtime_id!r} uses the retired {LEGACY_RUNTIME_PREFIX!r} "
                f"spelling; D27 gives combinations the `combo.` prefix")
        if entry.host_role and entry.host_role not in host_roles:
            reasons.append(
                f"is hosted on {entry.host_role!r}, whose socket ceiling cannot reach "
                f"{tuning.ingredient_count} inserts — no item of that role could ever fire it")
        if entry.min_sockets != tuning.ingredient_count:
            reasons.append(
                f"declares minSockets {entry.min_sockets}; a {tuning.ingredient_count}-ingredient "
                f"recipe derives {tuning.ingredient_count}")
        if reasons:
            problems[entry.id] = tuple(reasons)
    return LegalityReport(entries=entries, problems=problems)


def missing_sites(root: "Path | None" = None) -> "list[str]":
    """Any file in `MIGRATION_SITES` that no longer exists. Empty is the healthy answer.

    ⛔ Every rel resolved against ONE base is wrong, because `MIGRATION_SITES` is not all one
    repository. Six entries are gk-forge's own `tools/seedsmith/**` sources, but
    `data/seed/items/_registry/naming.v1.json` is gk-data's content pack and gk-forge carries
    neither `data/seed/**` nor `data/tuning/**`. Joining every rel to `REPO_ROOT` therefore reported
    that one file missing on a machine where it is present, so the migration plan read as broken
    for the one site the `socket-word` retirement actually left behind.

    Resolution is PER FILE through `owned_path`, never per directory: `owning_base` asks
    `(base / rel).exists()`, which needs a specific file, and gk-forge holds an untracked
    `data/seed/creatures/` that alone makes a directory lookup answer "gk-forge carries
    data/seed". The fail-closed fallback is unchanged — a rel no repository carries comes back as the
    caller spelled it, so a genuinely moved file is still reported MISSING rather than silently
    satisfied somewhere else.
    """
    base = Path(root) if root is not None else REPO_ROOT
    return [rel for rel, _ in MIGRATION_SITES
            if not owned_path(rel, base).exists()]


# ── SSH2.3: the `--write` verb ─────────────────────────────────────────────────────────────────
#
# ⛔ **A VERB, never a hand deletion.** This module still does not decide WHEN it is safe to call
# this — that is SSH2.6's own job (retire only once the real 102-entry corpus exists to replace the
# 25 legacy entries, after the widened `--retry-blocked` regen). What this gives the retirement is
# the property a hand `rm` never has: deterministic (no model call), idempotent (a second call
# reproduces the identical ledger record and no-ops the delete), and ledgered, so a future session
# reads WHY the file is gone instead of rediscovering it from a bare `git log`.

RETIREMENT_RULING = "regenerate, do not retain (2026-09-04)"
#: One fixed key -- this is a single, whole-corpus retirement, not a per-entry ledger (unlike
#: `combogen.authored`'s per-subject rows), so `RunLedger.mark_done` overwrites the SAME row every
#: call rather than accumulating one row per invocation.
RETIREMENT_LEDGER_KEY = "socket-words-retirement"
DEFAULT_MIGRATE_LEDGER = LEGACY_FILE.parent / "combogen-migrate.ledger.json"


@dataclass(frozen=True)
class RetirementRecord:
    deleted_file: str
    legacy_kind: str
    target_kind: str
    ruling: str

    def to_dict(self) -> dict:
        return {"deletedFile": self.deleted_file, "legacyKind": self.legacy_kind,
                "targetKind": self.target_kind, "ruling": self.ruling}


def retire_legacy_partition(*, legacy_path: "Path | None" = None,
                            ledger_path: "Path | None" = None) -> "tuple[RetirementRecord, bool]":
    """Delete the legacy socket-words file and ledger the retirement. Returns `(record,
    file_deleted_this_call)`.

    **Idempotent by construction, not merely "safe to call twice."** Deleting an already-deleted
    file is a no-op (`Path.unlink(missing_ok=True)`); `record.to_dict()` carries NO wall-clock
    field (`pipeline/provenance.py`'s own rule: an injected/absent timestamp is what makes a run
    reproducible — `authored_utc` elsewhere in this program is injected for the same reason), so
    two calls produce the IDENTICAL dict, and `RunLedger.write_done`'s own `sort_keys=True` then
    makes the ledger FILE byte-identical across both calls, not just logically equal.
    `legacy_path`/`ledger_path` default to the real production locations; a test overrides both to
    stay off the real corpus entirely (this function performs a real filesystem delete, so it is
    never exercised against `LEGACY_FILE` itself except by the real, owner-sequenced retirement).
    """
    from ....pipeline.run_ledger import RunLedger

    path = legacy_path or LEGACY_FILE
    file_existed = path.exists()
    if file_existed:
        path.unlink()
    try:
        deleted_file = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        deleted_file = str(path)  # a test's own temp path, outside REPO_ROOT -- not committed
    record = RetirementRecord(deleted_file=deleted_file, legacy_kind=LEGACY_KIND,
                              target_kind=TARGET_KIND, ruling=RETIREMENT_RULING)
    ledger = RunLedger(ledger_path or DEFAULT_MIGRATE_LEDGER)
    ledger.mark_done(RETIREMENT_LEDGER_KEY, record.to_dict())
    return record, file_existed
