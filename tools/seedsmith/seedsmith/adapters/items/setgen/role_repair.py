"""seedsmith.adapters.items.setgen.role_repair — the backward pass for D30's hybrid-role drop.

⛔ **The defect this closes is a DATED one, and the forward path is already correct.** `core.v1.json`
v2 (frozen 2026-09-04, D30) drops `ward-array`, `head-guard` and `sense` from the hybrid role core;
`roles.HYBRID_CORE_ROLES` enumerates the surviving twelve and `brief.build_set_brief` prints *only*
those to the model, so `SetRoleNotUniversal` is unproducible from a well-formed answer and the twelve
shipped `set-charm-gen/*` partitions (`_meta.promptVersion` set-charm-gen/1) claim no dropped role.
The five `sets-1c` partitions were authored **2026-08-22, thirteen days before the drop**
(`_meta.model` claude-sonnet-5, `_meta.promptVersion` 1, `_meta.registryVersions.core` 2's predecessor
1) — they predate the cap that makes the defect unproducible, and nothing has ever migrated them.
All five are the legacy `theme.*` partitions (`themes.legacy_partition_ids`, `themes.py:125`), which
the forward run keeps OUT of its planning pool (`run.py:224-228`: `load_species_themes()` +
`load_build_themes()`, with the five legacy ids entering only as the id-collision set), so a re-run
cannot repair them either: no `theme.verdant-graft` subject is ever planned again.

⛔ **What the defect actually costs is hybrid completability, and that is a guarantee, not a niceity.**
`ssot-sets.md` §3.7: *"A composable set's member roles must all be in the hybrid role core"* — because
a hybrid body hosts the twelve eligible roles only (`ItemRole.HybridEligible`,
`FrameMixPredicate.HybridCoreBudget`), a member row on a dropped role is a slot no hybrid can fill, so
a hybrid can never reach a threshold that counts it. A pure humanoid or pure plant wearer still can,
which is why this is a *hybrid-completability* defect and not an "unobtainable content" one — the
`Linkage/SetCompletability` GAP's own message is precise about that ("a hybrid frame could never
complete this set") and this module does not restate it more strongly.

⛔ **Deterministic and model-free**, the same posture `repair.py` (member binding), `species_repair.py`
(`speciesId`) and `topology_repair.py` (`setClass`) already established for this corpus. A legacy
partition's dropped role is re-placed onto a role the registry itself names as the content's host —
`core.v1.json`'s own `hybridDropReason` sentence per role, parsed rather than transcribed, so a v3
that moves the hosts moves this repair — and every member's `baseType` is re-bound through
`seedfile.bind_member_base_types`, the ONE resolver, rather than carried across a role change it no
longer matches.

⛔ **Cardinality is preserved, never reduced.** Membership is counted per ROLE (`ssot-sets.md` §4.5;
`topology.memberRoleCount`), so replacing a role with one already claimed, or dropping a member row,
would shorten the role list and strand the entry's top threshold — trading `SetRoleNotUniversal` for
`SetShortOfThreshold`. A replacement is therefore always a role the entry does not already claim, and
the distinct-role count is asserted unchanged before anything is written.

⛔ **Two phases, so a refusal writes nothing.** Every partition is repaired and validated in memory
first; only when the whole corpus is legal does the second pass write. The same reasoning
`topology_repair.py` states: a single-pass repair would leave the first half of the five-file corpus
rewritten when the last one turned out to be unmappable.

Idempotent by construction: an entry claiming only hybrid-core roles is left byte-identical, so a
second run reports zero changed entries and writes nothing at all.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .roles import DROPPED_ROLES, HYBRID_CORE_ROLES, refuse_roles
from .seedfile import ITEM_SEED_ROOT, bind_member_base_types, load_base_type_candidates
from .species_repair import plan_set_partitions, write_document

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

CORE_REGISTRY = _owned("data/seed/items/_registry/core.v1.json")

#: The sentence `core.v1.json` states each drop's hand-off in, e.g. *"its shield families migrate to
#: core-guard at a reduced tier cap instead."* Read, not transcribed: the registry is the authority
#: on where a dropped role's content went, and a registry v3 that moves a host must move this repair
#: with it. A reason string this pattern cannot read is a REFUSAL (see `migration_hosts`), never a
#: silent fall back to "any hybrid-core role".
_MIGRATION_SENTENCE = re.compile(r"migrate to (.*?) at a reduced tier cap")

#: The two separators a multi-host sentence uses ("manipulator and jewel-major").
_HOST_SEPARATORS = re.compile(r"\s+and\s+|,\s*")

#: How a mechanical pass records itself in `_meta.amendments` — the shape `batch`/`promptVersion`/
#: `model`/`authoredUtc`/`sourceRef` already ships in this corpus (the `resocket` pass). A repair
#: makes no model call and has no authored moment, so `authoredUtc` is the epoch that same precedent
#: uses: a wall-clock stamp here would make the diff irreproducible, which is the whole property that
#: lets a reviewer re-run the command and get the same bytes.
AMENDMENT_BATCH = "repair-set-roles"
AMENDMENT_PROMPT_VERSION = "n/a-mechanical-repair-set-roles"
AMENDMENT_MODEL = "repair-set-roles"
AMENDMENT_AUTHORED_UTC = "1970-01-01T00:00:00Z"
AMENDMENT_SOURCE_REF = "docs/architecture/item/ssot-sets.md#3.7"


#: The two roles `refuse_roles` allows at most ONE of (`roles.ARMAMENT_ROLES`, `ssot-sets.md`
#: §3.5 rule 4: *"Weapons are where build identity lives; a set that owns both owns the build"*).
#: **No armament role is ever a fallback candidate.** A dropped head/face slot becoming the main hand
#: would be this repair inventing the one decision the design reserves for the author — the set's
#: weapon — and there are always at least ten non-armament hybrid-core roles to choose from, so the
#: pool can never run dry by excluding them.
ARMAMENT_ROLES: "frozenset[str]" = frozenset({"armament-primary", "armament-secondary"})


class SetRoleRepairError(ValueError):
    """A dropped role this repair cannot re-place. Raised, never guessed around: an entry left on a
    dropped role is the defect itself, so choosing an arbitrary host would hide it."""


def migration_hosts(path: "Path | None" = None) -> "dict[str, tuple[str, ...]]":
    """`droppedRole -> the hybrid-core roles core.v1.json says its content migrated to`.

    Read fresh from the registry on every call rather than cached (the same discipline
    `species_repair.load_theme_species_registry` states), and ordered as the registry's own sentence
    orders them — `head-guard` names `core-guard and mantle`, so `core-guard` is preferred.

    Raises rather than degrading in three directions, each of which would otherwise become a silently
    wrong host: a role with no `hybridDropReason`, a reason the sentence pattern cannot read, and a
    named host that is not itself in the hybrid core.
    """
    doc = json.loads((path or CORE_REGISTRY).read_text(encoding="utf-8"))
    rows = {row["roleId"]: row for row in doc["roles"]["list"]}
    out: "dict[str, tuple[str, ...]]" = {}
    for role in sorted(DROPPED_ROLES):
        row = rows.get(role)
        if row is None:
            raise SetRoleRepairError(
                f"core.v1.json has no row for dropped role {role!r} — the registry and "
                f"roles.DROPPED_ROLES disagree")
        if row.get("hybridEligible"):
            raise SetRoleRepairError(
                f"core.v1.json marks {role!r} hybridEligible, but roles.DROPPED_ROLES lists it as "
                f"dropped — the role table moved under this repair")
        reason = row.get("hybridDropReason")
        if not isinstance(reason, str):
            raise SetRoleRepairError(
                f"core.v1.json's {role!r} row carries no hybridDropReason, so this repair has no "
                f"registry-stated host to re-place it on")
        match = _MIGRATION_SENTENCE.search(reason)
        if match is None:
            raise SetRoleRepairError(
                f"core.v1.json's {role!r} hybridDropReason does not name its hosts in the "
                f"'migrate to <roles> at a reduced tier cap' form this repair reads: {reason!r}")
        hosts = tuple(h for h in _HOST_SEPARATORS.split(match.group(1).strip()) if h)
        if not hosts:
            raise SetRoleRepairError(
                f"core.v1.json's {role!r} hybridDropReason names no host: {reason!r}")
        off_core = [h for h in hosts if h not in HYBRID_CORE_ROLES]
        if off_core:
            raise SetRoleRepairError(
                f"core.v1.json's {role!r} migrates to {off_core}, which is not in the hybrid role "
                f"core — a host that cannot host the content is not a host")
        out[role] = hosts
    return out


def _role_weights(path: "Path | None" = None) -> "dict[str, int]":
    """`roleId -> budgetWeightMilli`, read fresh from the same registry.

    Every row, INCLUDING the three dropped roles: a dropped role's own weight is what its
    replacement is measured against (`_preference_pool`'s tier 2), so filtering to the hybrid core
    here would throw away the one number that tier needs.
    """
    doc = json.loads((path or CORE_REGISTRY).read_text(encoding="utf-8"))
    return {row["roleId"]: int(row["budgetWeightMilli"]) for row in doc["roles"]["list"]}


def _preference_pool(role: str, hosts: "dict[str, tuple[str, ...]]",
                     weights: "dict[str, int]") -> "tuple[str, ...]":
    """A dropped role's candidate replacements, best first.

    Two tiers, in this order:

    1. **The hosts `core.v1.json` itself names**, in the order its sentence names them. An explicit
       registry statement about where the content went outranks any heuristic here — `head-guard`
       names `core-guard and mantle`, and `core-guard` is preferred even though `mantle` is the
       closer weight.
    2. **The remaining non-armament hybrid-core roles, nearest budget weight first** — lighter on a
       tie, `HYBRID_CORE_ROLES` order last. Tier 2 exists because an entry may already claim every
       host its role names — `set.thorned-chassis-002` claims both `core-guard` and `mantle` before
       its `head-guard` member is reached — and refusing there would leave a repairable entry
       unrepairable. Nearest weight is the slot-level analogue of the reduced-tier repricing D3
       already applies to the moved content: the replacement should not silently move the slot into
       a much heavier or lighter part of the body. Lighter rather than heavier on a tie for the same
       reason — a heavier slot raises that frame's side of `FrameMixPredicate`'s minority budget, so
       the conservative direction is down. Tier 2 is exercised by the real corpus (4 of the 18
       entries) rather than being a branch nobody reaches.
    """
    named = hosts[role]
    index = {r: i for i, r in enumerate(HYBRID_CORE_ROLES)}
    dropped_weight = weights[role]
    rest = sorted(
        (r for r in HYBRID_CORE_ROLES
         if r not in named and r not in ARMAMENT_ROLES),
        key=lambda r: (abs(weights[r] - dropped_weight), weights[r], index[r]))
    return named + tuple(rest)


def _replacement_roles(distinct: "list[str]", hosts: "dict[str, tuple[str, ...]]",
                       weights: "dict[str, int]") -> "dict[str, str]":
    """`droppedRole -> its replacement`, one per DISTINCT dropped role in the entry.

    Distinct-role granularity is load-bearing, not incidental: a two-frame entry declares its dropped
    role twice (once on `humanoid`, once on `plant`) and both rows must land on the SAME replacement —
    otherwise the entry gains a role it never declared, or two rows collide on one.

    `claimed` starts as the entry's LEGAL roles so a replacement can never duplicate one, and is
    extended as replacements are chosen. `refuse_roles` re-checks the finished list (the caller does
    that), which is the backstop for every rule in the vocabulary — including the one-armament rule
    `_preference_pool` already keeps out of reach.

    ⚠ **Distinct roles only — the loop must skip a role it has already resolved.** A two-frame entry
    lists its dropped role TWICE, so iterating the raw member roles would re-enter the candidate
    search for the second row and walk one step further down the preference list (measured on the
    real corpus: `set.verdant-graft-001`'s `head-guard` landed on `girdle` instead of its named host
    `mantle`, because the second member row re-ran the search). The two rows of one role must move
    together or the entry silently gains a role it never declared.
    """
    claimed = list(dict.fromkeys(r for r in distinct if r not in DROPPED_ROLES))
    chosen: "dict[str, str]" = {}
    for role in distinct:
        if role not in DROPPED_ROLES or role in chosen:
            continue
        for candidate in _preference_pool(role, hosts, weights):
            if candidate in claimed:
                continue
            chosen[role] = candidate
            claimed.append(candidate)
            break
        if role not in chosen:
            raise SetRoleRepairError(
                f"no hybrid-core role is free to re-place {role!r} — every candidate is already "
                f"claimed by {sorted(set(claimed))}")
    return chosen


@dataclass(frozen=True)
class RoleRepairFile:
    path: Path
    changed_entries: int
    total_entries: int
    changed_members: int


@dataclass(frozen=True)
class RoleRepairResult:
    files: "tuple[RoleRepairFile, ...]"
    entries: int
    changed_entries: int
    changed_members: int
    #: (dropped role, replacement) -> how many entries took that move. A READING: it moves whenever
    #: content ships, and nothing asserts its size (`validation-ssot.md`).
    relocations: "dict[tuple[str, str], int]" = field(default_factory=dict)

    @property
    def changed_files(self) -> int:
        return len(self.files)


def _repair_entry(entry: dict, *, path: Path,
                  hosts: "dict[str, tuple[str, ...]]", weights: "dict[str, int]",
                  candidates: "dict[tuple[str, str], tuple[str, ...]]",
                  all_candidates: "dict[tuple[str, str], tuple[str, ...]]",
                  ) -> "list[dict[str, str]]":
    """Re-place one entry's dropped member roles in place; return its amendment rows (empty = untouched).

    Returns `[]` for an entry that needs nothing — the caller counts that as no change, which is what
    makes the whole pass idempotent.
    """
    entry_id = entry.get("id")
    if not isinstance(entry_id, str) or not entry_id:
        raise SetRoleRepairError(f"{path}: set entry has no string id")
    members = entry.get("members") or []
    distinct = [str(m.get("role")) for m in members if isinstance(m, dict)]
    if not distinct or not any(role in DROPPED_ROLES for role in distinct):
        return []

    replacements = _replacement_roles(distinct, hosts, weights)
    new_members: "list[dict]" = []
    for member in members:
        if not isinstance(member, dict):
            raise SetRoleRepairError(f"{path}: {entry_id} member is not an object")
        role, frame = member.get("role"), member.get("frame")
        if not isinstance(role, str) or not isinstance(frame, str):
            raise SetRoleRepairError(f"{path}: {entry_id} member needs string role and frame")
        if role in replacements:
            # The base type belonged to the OLD role's slot; rebinding is not optional, so the stale
            # binding is dropped here and `bind_member_base_types` re-resolves it below.
            new_members.append({"role": replacements[role], "frame": frame})
        else:
            new_members.append(dict(member))

    before = sorted(set(distinct))
    after = sorted({m["role"] for m in new_members})
    # Cardinality is the entry's topology. A repair that shortened the role list would strand the top
    # threshold, so this is asserted rather than trusted to the loop above.
    if len(after) != len(before):
        raise SetRoleRepairError(
            f"{path}: {entry_id} had {len(before)} distinct roles and the repair produced "
            f"{len(after)} ({before} -> {after}) — membership is counted per role, so a shortened "
            f"list moves the threshold ladder")
    problems = refuse_roles(after)
    if problems:
        raise SetRoleRepairError(
            f"{path}: {entry_id} is still illegal after the repair — {problems}")

    entry["members"] = bind_member_base_types(
        entry_id, new_members, candidates, existing_candidates=all_candidates)
    return [{"from": role, "to": replacements[role]} for role in sorted(replacements)]


def repair_set_roles(*, sets_dir: "Path | None" = None,
                     base_types_dir: "Path | None" = None,
                     registry_path: "Path | None" = None,
                     write: bool = False) -> RoleRepairResult:
    """Plan, or apply, the hybrid-role re-placement for every production `set` partition.

    `write=False` is a read-only plan, the contract every sibling repair already established. When
    writing, each changed file is replaced atomically through `species_repair.write_document` — the
    SAME writer `repair-species` and `repair-set-class` use, so the three repairs agree byte for byte
    about escaping and line endings and a later run of either produces no spurious diff. Untouched
    files are not rewritten at all.
    """
    target = Path(sets_dir or (ITEM_SEED_ROOT / "sets")).resolve()
    hosts = migration_hosts(registry_path)
    weights = _role_weights(registry_path)
    corpus_root = Path(base_types_dir).resolve() if base_types_dir is not None else None
    candidates = load_base_type_candidates(corpus_root=corpus_root)
    all_candidates = load_base_type_candidates(corpus_root=corpus_root, include_unique=True)

    pending: "list[tuple[Path, dict, int, int, int]]" = []
    entries = 0
    relocated: "dict[tuple[str, str], int]" = {}

    # Phase 1 — resolve and validate the whole corpus in memory.
    for path, document in plan_set_partitions(target):
        partition_entries = document.get("entries") or []
        changed_entries = 0
        changed_members = 0
        amendment_rows: "list[dict[str, Any]]" = []
        for entry in partition_entries:
            if not isinstance(entry, dict):
                raise SetRoleRepairError(f"{path}: set partition holds a non-object entry")
            rows = _repair_entry(entry, path=path, hosts=hosts, weights=weights,
                                 candidates=candidates, all_candidates=all_candidates)
            if not rows:
                continue
            for row in rows:
                relocation = (row["from"], row["to"])
                relocated[relocation] = relocated.get(relocation, 0) + 1
            changed_members += len(rows)
            amendment_rows.append({"entryId": entry["id"], "relocations": rows})
            changed_entries += 1

        entries += len(partition_entries)
        if changed_entries:
            _stamp_amendment(document, amendment_rows)
            pending.append((path, document, changed_members, changed_entries,
                            len(partition_entries)))

    # Phase 2 — every entry above was legal, so the corpus can be written as one unit.
    if write:
        for path, document, _members, _changed, _total in pending:
            write_document(path, document)

    return RoleRepairResult(
        files=tuple(RoleRepairFile(path=path, changed_entries=changed, total_entries=total,
                                   changed_members=members)
                    for path, _document, members, changed, total in pending),
        entries=entries,
        changed_entries=sum(changed for _p, _d, _m, changed, _t in pending),
        changed_members=sum(members for _p, _d, members, _c, _t in pending),
        relocations=dict(sorted(relocated.items())),
    )


def _stamp_amendment(document: dict, rows: "list[dict[str, Any]]") -> None:
    """Record the mechanical pass in `_meta.amendments` — the file's own provenance, not a ledger
    beside it (`seed-contract.md` §9; the `resocket` pass is this shape's precedent).

    The file's REQUIRED `_meta` keys are untouched: `model`/`promptVersion` still name the batch that
    authored the entry, and the amendment names what moved it since. Overwriting the author fields
    would make the file's own provenance ledger describe a run that never happened.
    """
    meta = document.setdefault("_meta", {})
    amendments = meta.setdefault("amendments", [])
    amendments.append({
        "batch": AMENDMENT_BATCH,
        "note": ("member roles re-placed off D30's dropped hybrid roles (ward-array/head-guard/sense) "
                 "onto the hosts core.v1.json's own hybridDropReason names; member baseTypes re-bound "
                 "through seedfile.bind_member_base_types. No live model call — a mechanical repair, "
                 "no prompt. Ids, nameKeys, names, thresholds, tags, notes and flavours preserved."),
        "promptVersion": AMENDMENT_PROMPT_VERSION,
        "model": AMENDMENT_MODEL,
        "authoredUtc": AMENDMENT_AUTHORED_UTC,
        "sourceRef": AMENDMENT_SOURCE_REF,
        "entries": rows,
    })


def repair_report(result: RoleRepairResult, *, write: bool) -> "dict[str, Any]":
    """The run's own numbers. `relocations` is printed and never asserted — it is how a human reads
    which hosts the shipped corpus actually landed on."""
    return {
        "write": write,
        "entries": result.entries,
        "changedEntries": result.changed_entries,
        "changedFiles": result.changed_files,
        "changedMembers": result.changed_members,
        "relocations": [{"from": old, "to": new, "entries": count}
                        for (old, new), count in result.relocations.items()],
        "files": [{"path": str(f.path), "changedEntries": f.changed_entries,
                   "totalEntries": f.total_entries, "changedMembers": f.changed_members}
                  for f in result.files],
    }
