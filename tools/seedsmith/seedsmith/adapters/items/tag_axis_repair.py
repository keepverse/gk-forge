"""seedsmith.adapters.items.tag_axis_repair — model-authored repair for `TagAxisExclusive`
(two tags from the same closed, mutually-exclusive `tags.v1.json` axis on one entry, e.g. both
`defensive` and `utility` on `combat-posture`).

The generator-side defect is fixed separately, in each kind's own `emit.py`/`brief.py`
(`registries.tag_axis_violation`/`tag_axis_brief_note`) — this module only repairs the rows that
already shipped before that check existed. Like `naming_grammar_repair`, it is driven by the real
validator's `--findings-json`, never a hand-derived guess about which rows are wrong.

⛔ **Never hand-picks a winner.** The owner's own instruction (item-seed-regen cause 8, 2026-09-20):
"let each item's own evidence choose" — the model reads the SAME context a human author would
(name, flavor, class/role/family, the item's other tags) and picks which of the two conflicting tags
actually fits, rather than a blanket policy ("defensive always wins") that would hand-pick an
identity for every row from outside its own evidence.

`gem` is a special case: gems never author their own tags, they copy a source affix-family's tags
verbatim at generation time (`gemgen.brief`'s own docstring: "a straight copy of the family's OWN
authored, VALIDATED tags"). A gem whose source family is ALSO in this repair's scope is fixed by
copying the family's own resolved tags, never a separate model call for the same decision twice.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .registries import load_tag_axes, tag_axis_violation
from .setgen.seedfile import ITEM_SEED_ROOT
from ...tooling import run_tool

#: Kinds whose tags this module may rewrite directly. `gem` is handled by copying its source
#: family's resolved tags instead (see `plan`/`apply`) — never asked to choose independently, since
#: gemgen's own contract is "copy the family verbatim", not "author its own tags".
DIRECT_KINDS: "tuple[str, ...]" = ("base-type", "affix-family")


class RepairRefused(RuntimeError):
    """The validator tool could not run or returned nothing usable — refuse rather than guess."""


@dataclass(frozen=True)
class TagAxisFinding:
    entry_id: str
    file: str
    message: str


@dataclass(frozen=True)
class TagAxisRepair:
    entry_id: str
    path: Path
    kind: str
    tags: "tuple[str, ...]"
    conflicts: "tuple[tuple[str, tuple[str, ...]], ...]"  # (axis, member tags present) per axis
    context: "dict[str, Any]"  # name/flavor/class/role/family — whatever the entry itself carries
    source_family_id: "str | None" = None  # set only for kind == "gem"


def findings(items_root: "Path | None" = None, *,
            validator_project: "Path | None" = None) -> "tuple[TagAxisFinding, ...]":
    root = Path(items_root or ITEM_SEED_ROOT)
    project = validator_project or _default_validator_project(root)
    if project is None or not project.exists():
        raise RepairRefused(f"ItemSeedValidator project not found near {root}")
    proc = run_tool(
        ["dotnet", "run", "--project", str(project), "-c", "Release", "--no-build",
         "--", str(root), "--findings-json", "--codes=TagAxisExclusive"],
        cwd=str(root.parents[2]), refusal=RepairRefused,
        what="the TagAxisExclusive findings this repair plans against",
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RepairRefused(f"findings-json failed ({proc.returncode}): {proc.stderr.strip()[:400]}")
    text = proc.stdout[proc.stdout.index("{"):]
    doc = json.loads(text)
    return tuple(TagAxisFinding(entry_id=f["id"], file=f["file"], message=f["message"])
                for f in doc.get("findings", []) if f.get("id"))


def _default_validator_project(root: Path) -> "Path | None":
    for parent in [root, *root.parents]:
        candidate = parent / "tools" / "ItemSeedValidator" / "ItemSeedValidator.csproj"
        if candidate.exists():
            return candidate
    return None


def _row_for(document: dict, entry_id: str) -> "dict | None":
    return next((r for r in (document.get("entries") or ())
                if isinstance(r, dict) and r.get("id") == entry_id), None)


def _context_for(row: dict) -> "dict[str, Any]":
    keys = ("name", "flavor", "class", "role", "roles", "kindId", "displayTemplate", "params")
    return {k: row[k] for k in keys if k in row}


def plan(items_root: "Path | None" = None, *,
        found: "tuple[TagAxisFinding, ...] | None" = None) -> "tuple[TagAxisRepair, ...]":
    root = Path(items_root or ITEM_SEED_ROOT)
    found = found if found is not None else findings(items_root=root)

    repairs: "list[TagAxisRepair]" = []
    for f in found:
        path = root / f.file
        if not path.exists():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        kind = str(document.get("kind") or "")
        row = _row_for(document, f.entry_id)
        if row is None:
            continue
        tags = tuple(row.get("tags") or ())
        axes = load_tag_axes(applies_to=kind) if kind else {}
        conflicts: "list[tuple[str, tuple[str, ...]]]" = []
        tag_to_axis = {t: axis for axis, ids in axes.items() for t in ids}
        by_axis: "dict[str, list[str]]" = {}
        for t in tags:
            axis = tag_to_axis.get(t)
            if axis:
                by_axis.setdefault(axis, []).append(t)
        for axis, members in by_axis.items():
            if len(set(members)) > 1:
                conflicts.append((axis, tuple(members)))
        if not conflicts:
            continue

        source_family_id = row.get("family") if kind == "gem" else None
        repairs.append(TagAxisRepair(
            entry_id=f.entry_id, path=path, kind=kind, tags=tags,
            conflicts=tuple(conflicts), context=_context_for(row),
            source_family_id=source_family_id))
    return tuple(sorted(repairs, key=lambda r: r.entry_id))


def schema() -> "dict[str, Any]":
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["keep"],
        "properties": {"keep": {"type": "string"}},
    }


def brief(repair: TagAxisRepair) -> str:
    conflict_lines = "\n".join(
        f"  - axis `{axis}`: currently carries both {', '.join(repr(m) for m in members)} "
        f"(exactly one is legal)"
        for axis, members in repair.conflicts)
    context_lines = "\n".join(f"  {k}: {v!r}" for k, v in repair.context.items())
    return f"""One {repair.kind} entry carries two tags from the same closed, mutually-exclusive
axis — exactly one is legal, and the choice must fit THIS entry, not a blanket rule.

Entry id: `{repair.entry_id}`
Its current tags: {list(repair.tags)}
Conflict(s):
{conflict_lines}

What this entry actually is:
{context_lines}

Return JSON only: `keep`, the ONE tag from the conflicting set that best fits this entry's own
name/flavor/class/role/family above. Do not invent a tag outside the ones already listed as
conflicting for that axis."""


def validate_answer(repair: TagAxisRepair, answer: "dict[str, Any]") -> str:
    keep = answer.get("keep") if isinstance(answer, dict) else None
    if not isinstance(keep, str) or not keep.strip():
        raise ValueError(f"{repair.entry_id}: 'keep' is empty")
    keep = keep.strip()
    legal = {m for _, members in repair.conflicts for m in members}
    if keep not in legal:
        raise ValueError(f"{repair.entry_id}: 'keep' {keep!r} is not one of the conflicting tags "
                         f"{sorted(legal)}")
    return keep


def resolved_tags(repair: TagAxisRepair, keep_by_axis: "dict[str, str]") -> "tuple[str, ...]":
    """The entry's tag list with exactly one winner per conflicting axis, every other tag
    untouched, order preserved."""
    losers: "set[str]" = set()
    for axis, members in repair.conflicts:
        keep = keep_by_axis[axis]
        losers |= {m for m in members if m != keep}
    return tuple(t for t in repair.tags if t not in losers)


def run_batch(repairs: "tuple[TagAxisRepair, ...]", *, caller,
             max_attempts: int = 5) -> "tuple[dict[str, tuple[str, ...]], list[dict[str, str]]]":
    """Calls `caller(prompt, schema)` once per (repair, axis) conflict — most repairs have exactly
    one. Returns (entry_id -> resolved tag tuple, failed)."""
    answers: "dict[str, tuple[str, ...]]" = {}
    failed: "list[dict[str, str]]" = []
    for repair in repairs:
        keep_by_axis: "dict[str, str]" = {}
        ok = True
        for axis, members in repair.conflicts:
            single = TagAxisRepair(entry_id=repair.entry_id, path=repair.path, kind=repair.kind,
                                   tags=repair.tags, conflicts=((axis, members),),
                                   context=repair.context, source_family_id=repair.source_family_id)
            resolved = None
            for _attempt in range(max_attempts):
                try:
                    raw = caller(brief(single), schema())
                    resolved = validate_answer(single, raw)
                    break
                except (ValueError, json.JSONDecodeError):
                    continue
                except RuntimeError as exc:
                    failed.append({"entryId": repair.entry_id,
                                   "reason": f"model call failed: {exc}"})
                    ok = False
                    break
            if resolved is None:
                if ok:
                    failed.append({"entryId": repair.entry_id,
                                   "reason": f"no valid answer for axis {axis!r} "
                                            f"after {max_attempts} attempts"})
                ok = False
                break
            keep_by_axis[axis] = resolved
        if ok:
            answers[repair.entry_id] = resolved_tags(repair, keep_by_axis)
    return answers, failed


def apply(answers: "dict[str, tuple[str, ...]]", repairs: "tuple[TagAxisRepair, ...]", *,
         write: bool) -> "tuple[Path, ...]":
    """Writes only the `tags` field of each answered entry. `write=False` reports what would
    change without touching disk."""
    repair_by_id = {r.entry_id: r for r in repairs}
    by_path: "dict[Path, dict[str, tuple[str, ...]]]" = {}
    for entry_id, tags in answers.items():
        repair = repair_by_id.get(entry_id)
        if repair is None:
            continue
        by_path.setdefault(repair.path, {})[entry_id] = tags

    changed: "list[Path]" = []
    for path, mapping in by_path.items():
        document = json.loads(path.read_text(encoding="utf-8"))
        touched = False
        for row in document.get("entries") or ():
            if isinstance(row, dict) and row.get("id") in mapping:
                row["tags"] = list(mapping[row["id"]])
                touched = True
        if touched:
            changed.append(path)
            if write:
                _atomic_json(path, document)
    return tuple(sorted(changed))


def sync_gem_from_family(gem_repair: TagAxisRepair, resolved_family_tags: "tuple[str, ...]", *,
                         write: bool) -> "Path | None":
    """Mechanical, no model call: copies a resolved family's tags onto its dependent gem, matching
    gemgen's own "straight copy" contract. Returns the changed path, or `None` if the gem's tags
    already match."""
    if tuple(gem_repair.tags) == resolved_family_tags:
        return None
    document = json.loads(gem_repair.path.read_text(encoding="utf-8"))
    touched = False
    for row in document.get("entries") or ():
        if isinstance(row, dict) and row.get("id") == gem_repair.entry_id:
            row["tags"] = list(resolved_family_tags)
            touched = True
    if not touched:
        return None
    if write:
        _atomic_json(gem_repair.path, document)
    return gem_repair.path


def _atomic_json(path: Path, document: dict) -> None:
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
