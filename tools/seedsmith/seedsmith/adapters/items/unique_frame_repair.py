"""seedsmith.adapters.items.unique_frame_repair — model-authored repair for `UniqueFrameImpossible`
(a unique's `fixedAtoms[].family` or `varianceSlot.family` restricted, by the affix-family corpus's
own `frames` list, to the OTHER frame than the unique itself — ssot-uniques.md §3.5's physics
carve-out: "a channel that only exists on the other side" is dead, not daring).

The generator-side defect is fixed separately, in `uniques.briefs.build_unique_schema` (which now
filters `fixedAtoms`/`varianceSlot` to `registries.load_atom_family_frames()`'s frame-legal set
before the model ever sees the enum) and `uniques.pipelines.run_batch`'s post-hoc `_frame_violation`
backstop — this module only repairs the rows that shipped before that filter existed. Driven by the
real validator's `--findings-json`, never a hand-derived guess about which rows are wrong.

⛔ Never hand-picks a replacement family. The model reads the SAME context a human author would
(name, flavor, frame, tags, power axis, every OTHER family already on the entry) and picks a
frame-legal replacement that fits — never a blanket substitution.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .registries import load_atom_family_frames, load_authored_affix_family_ids
from .setgen.seedfile import ITEM_SEED_ROOT
from ...tooling import run_tool


class RepairRefused(RuntimeError):
    """The validator tool could not run or returned nothing usable — refuse rather than guess."""


@dataclass(frozen=True)
class FrameFinding:
    entry_id: str
    file: str
    message: str


@dataclass(frozen=True)
class FrameRepair:
    entry_id: str
    path: Path
    frame: str
    illegal_family: str
    slot: str  # "fixedAtoms[<index>]" or "varianceSlot"
    slot_index: "int | None"  # set only for fixedAtoms
    context: "dict[str, Any]"
    other_families: "tuple[str, ...]"  # every family already on this entry, for dedup


def findings(items_root: "Path | None" = None, *,
            validator_project: "Path | None" = None) -> "tuple[FrameFinding, ...]":
    root = Path(items_root or ITEM_SEED_ROOT)
    project = validator_project or _default_validator_project(root)
    if project is None or not project.exists():
        raise RepairRefused(f"ItemSeedValidator project not found near {root}")
    proc = run_tool(
        ["dotnet", "run", "--project", str(project), "-c", "Release", "--no-build",
         "--", str(root), "--findings-json", "--codes=UniqueFrameImpossible"],
        cwd=str(root.parents[2]), refusal=RepairRefused,
        what="the UniqueFrameImpossible findings this repair plans against",
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RepairRefused(f"findings-json failed ({proc.returncode}): {proc.stderr.strip()[:400]}")
    text = proc.stdout[proc.stdout.index("{"):]
    doc = json.loads(text)
    return tuple(FrameFinding(entry_id=f["id"], file=f["file"], message=f["message"])
                for f in doc.get("findings", []) if f.get("id"))


def _default_validator_project(root: Path) -> "Path | None":
    for parent in [root, *root.parents]:
        candidate = parent / "tools" / "ItemSeedValidator" / "ItemSeedValidator.csproj"
        if candidate.exists():
            return candidate
    return None


def _locate_family(row: dict, family_id: str) -> "tuple[str, int | None] | None":
    """Where `family_id` sits on this entry: a fixedAtoms index, or the varianceSlot."""
    for i, atom in enumerate(row.get("fixedAtoms") or ()):
        if isinstance(atom, dict) and atom.get("family") == family_id:
            return "fixedAtoms", i
    variance = row.get("varianceSlot") or {}
    if variance.get("family") == family_id:
        return "varianceSlot", None
    return None


def plan(items_root: "Path | None" = None, *,
        found: "tuple[FrameFinding, ...] | None" = None) -> "tuple[FrameRepair, ...]":
    root = Path(items_root or ITEM_SEED_ROOT)
    found = found if found is not None else findings(items_root=root)

    repairs: "list[FrameRepair]" = []
    for f in found:
        path = root / f.file
        if not path.exists():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        row = next((r for r in (document.get("entries") or ())
                   if isinstance(r, dict) and r.get("id") == f.entry_id), None)
        if row is None:
            continue

        import re
        m = re.search(r"carrying family '([^']+)'", f.message)
        if not m:
            continue
        illegal_family = m.group(1)
        located = _locate_family(row, illegal_family)
        if located is None:
            continue
        slot, index = located

        other = [a.get("family") for a in (row.get("fixedAtoms") or ()) if isinstance(a, dict)]
        variance_family = (row.get("varianceSlot") or {}).get("family")
        if variance_family:
            other.append(variance_family)
        other_families = tuple(fam for fam in other if fam and fam != illegal_family)

        context = {k: row[k] for k in ("name", "flavor", "frame", "powerAxis", "tags", "rarity")
                  if k in row}
        repairs.append(FrameRepair(
            entry_id=f.entry_id, path=path, frame=str(row.get("frame") or ""),
            illegal_family=illegal_family, slot=f"{slot}[{index}]" if index is not None else slot,
            slot_index=index, context=context, other_families=other_families))
    return tuple(sorted(repairs, key=lambda r: (r.entry_id, r.slot)))


def schema() -> "dict[str, Any]":
    return {
        "type": "object", "additionalProperties": False, "required": ["family"],
        "properties": {"family": {"type": "string"}},
    }


def brief(repair: FrameRepair, *, legal_families: "frozenset[str]") -> str:
    context_lines = "\n".join(f"  {k}: {v!r}" for k, v in repair.context.items())
    already_used = ", ".join(repair.other_families) or "(none)"
    return f"""One unique carries an effect family its frame cannot legally use — the affix-family
corpus restricts `{repair.illegal_family}` to the OTHER frame, so on a `{repair.frame}` unique that
line is physically dead (the channel it writes does not exist on this frame), not merely
off-theme.

Entry id: `{repair.entry_id}`
Slot to replace: `{repair.slot}` (currently `{repair.illegal_family}`)
Already used elsewhere on this same entry (do not repeat): {already_used}

What this entry actually is:
{context_lines}

Return JSON only: `family`, a replacement effect family id from the legal list below that fits this
entry's own name/flavor/tags as closely as you reasonably can.

Legal families for a `{repair.frame}` unique ({len(legal_families)}):
{', '.join(sorted(legal_families))}"""


def validate_answer(repair: FrameRepair, answer: "dict[str, Any]", *,
                    legal_families: "frozenset[str]") -> str:
    family = answer.get("family") if isinstance(answer, dict) else None
    if not isinstance(family, str) or not family.strip():
        raise ValueError(f"{repair.entry_id}: 'family' is empty")
    family = family.strip()
    if family not in legal_families:
        raise ValueError(f"{repair.entry_id}: {family!r} is not a legal family for frame "
                         f"{repair.frame!r}")
    if family == repair.illegal_family or family in repair.other_families:
        raise ValueError(f"{repair.entry_id}: {family!r} is unchanged or already used on this entry")
    return family


def run_batch(repairs: "tuple[FrameRepair, ...]", *, caller,
             max_attempts: int = 5) -> "tuple[dict[str, str], list[dict[str, str]]]":
    # Authored, not the broader runtime catalog -- see load_authored_affix_family_ids's own
    # docstring for why the catalog produces a REPLACEMENT ReferenceUnresolved finding instead of
    # fixing one.
    all_families = load_authored_affix_family_ids()
    family_frames = load_atom_family_frames()
    answers: "dict[str, str]" = {}
    failed: "list[dict[str, str]]" = []
    for repair in repairs:
        legal = frozenset(f for f in all_families
                          if f not in family_frames or repair.frame in family_frames[f])
        prompt = brief(repair, legal_families=legal)
        resolved = None
        for _attempt in range(max_attempts):
            try:
                raw = caller(prompt, schema())
                resolved = validate_answer(repair, raw, legal_families=legal)
                break
            except (ValueError, json.JSONDecodeError):
                continue
            except RuntimeError as exc:
                failed.append({"entryId": repair.entry_id, "reason": f"model call failed: {exc}"})
                break
        if resolved is None:
            if not failed or failed[-1]["entryId"] != repair.entry_id:
                failed.append({"entryId": repair.entry_id,
                               "reason": f"no valid answer for slot {repair.slot!r} "
                                        f"after {max_attempts} attempts"})
            continue
        answers[f"{repair.entry_id}::{repair.slot}"] = resolved
    return answers, failed


def apply(answers: "dict[str, str]", repairs: "tuple[FrameRepair, ...]", *,
         write: bool) -> "tuple[Path, ...]":
    """`answers` keys are `"{entry_id}::{slot}"` (an entry can have more than one repaired slot)."""
    by_path: "dict[Path, list[tuple[FrameRepair, str]]]" = {}
    for repair in repairs:
        key = f"{repair.entry_id}::{repair.slot}"
        if key in answers:
            by_path.setdefault(repair.path, []).append((repair, answers[key]))

    changed: "list[Path]" = []
    for path, items in by_path.items():
        document = json.loads(path.read_text(encoding="utf-8"))
        touched = False
        for repair, new_family in items:
            row = next((r for r in (document.get("entries") or ())
                       if isinstance(r, dict) and r.get("id") == repair.entry_id), None)
            if row is None:
                continue
            if repair.slot_index is not None:
                atoms = row.get("fixedAtoms") or []
                if repair.slot_index < len(atoms):
                    atoms[repair.slot_index]["family"] = new_family
                    touched = True
            else:
                variance = row.get("varianceSlot")
                if isinstance(variance, dict):
                    variance["family"] = new_family
                    touched = True
        if touched:
            changed.append(path)
            if write:
                _atomic_json(path, document)
    return tuple(sorted(changed))


def _atomic_json(path: Path, document: dict) -> None:
    # ensure_ascii=True: the uniques corpus's own convention (found live: verdant-graft-90.json and
    # every file this module touches use \uXXXX-escaped non-ASCII in their flavor text). A
    # round-trip with ensure_ascii=False silently un-escapes it -- the exact bug item-seed-regen
    # cause 5 (2026-09-20) found and fixed for meta_registry_repair.py's own writer, on a corpus
    # that turned out to use the OPPOSITE convention (literal UTF-8) from this one.
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(document, ensure_ascii=True, indent=2) + "\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
