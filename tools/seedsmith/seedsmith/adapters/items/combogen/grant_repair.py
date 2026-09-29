"""seedsmith.adapters.items.combogen.grant_repair — model-authored repair for a combination entry
whose `grants[]` names a family the production atom catalog cannot resolve (`ReferenceUnresolved`).

**Generator defect, fixed separately.** `granted_family_vocabulary()` used to return
`registries.load_atom_families()` — all of `gk-data/packs/fusion/data/seed/atoms/**`, including the hand-authored
`aura-content.json` (`atom.aura-*`) and `fx-*.json` (`atom.fx-*`) sources that no affix family
carries. A combination grant resolves through `AtomRow.DeriveId(family, "", tier)` against the
affix-family catalog expanded by `FamilyExpansion` (`spec-combo-bind.md` §1), so those families
never bind. The vocabulary is now `load_authored_affix_family_ids()`; this module repairs the rows
that already shipped before that fix.

⛔ **This is NOT a full re-author, and that is the point.** Re-running a cell through the generation
graph re-authors its name, flavor and ingredients too. Measured 2026-09-20 on the real corpus with
the owner's local model: ten re-authored cells reintroduced far more naming defects
(`FusionNotDecomposable` 1 -> 14, `NameGrammarViolation` 1 -> 7, `PossessiveForbidden` 2) than the
grant fix removed — a small quantized model under many similar briefs has a narrow creative range.
Only the offending `grants[]` entries are rewritten here; name, flavor, ingredients, hostRole and
every other field stay byte-for-byte intact.

⚠ **Writes the SAME grant change into both stores.** `combinations/*.json` is
`authored.run_batch`'s output and every `--write` rewrites the whole file from the ledger
(`entries_from_ledger`), so a repair that edited only the JSON would be reverted by the next
generation run — the defect `fae533a519` left behind (SSH2.5 finding 1). `apply` updates the ledger
row AND the shipped row, in place, and leaves every other field alone.

⛔ **It deliberately does NOT re-emit the file from the ledger.** The ledger is stale relative to
the shipped corpus: `fae533a519` renamed 20 combination entries directly in the seed file without
updating `combination-gen.ledger.json`, so the ledger still holds the old, collision-prone names
for those rows. `entries_from_ledger` + `write_seed_file` would therefore revert all 20 — measured
2026-09-20: 37 validator errors -> 44. Reconciling those names is the SSH2.5 follow-up (make the
name repair write the ledger, then re-run it), and is not this repair's business.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import authored as authored_mod
from .. import registries
from ..setgen.seedfile import ITEM_SEED_ROOT
from ....pipeline.run_ledger import RunLedger
from ....tooling import run_tool

#: The fields a repair reads to decide what mechanism the entry is for. Deliberately the entry's own
#: authored evidence, so the model picks a family that fits THIS entry rather than a blanket rule.
CONTEXT_KEYS: "tuple[str, ...]" = (
    "name", "flavor", "shape", "aptitudes", "archetype", "hostRole", "hostFrame", "ingredients",
)


class RepairRefused(RuntimeError):
    """The validator tool could not run or returned nothing usable — refuse rather than guess."""


#: `ReferenceCheck`'s message shape: "'grants[1]' references 'atom.aura-composure', which no seed
#: file authors and no registry ships". The target is read from here rather than recomputed as
#: "not in the affix-family catalog": a milestone MINTS `atom.enhance-*`, which resolves through the
#: validator's own <c>MintedRuntimeIds</c> path and is perfectly legal — the catalog check would
#: flag it as bad. The validator's findings are the authority on what does not resolve.
_REFERENCE_RE = re.compile(r"references '([^']+)'")


@dataclass(frozen=True)
class GrantFinding:
    entry_id: str
    file: str
    message: str


@dataclass(frozen=True)
class GrantRepair:
    entry_id: str
    subject_id: str
    shape: str
    path: Path
    grants: "tuple[str, ...]"
    bad_families: "tuple[str, ...]"
    context: "dict[str, Any]"

def subject_id_for(entry_id: str) -> str:
    """The ledger key for a combination entry id — one definition, shared with `authored`."""
    return authored_mod.subject_id_for_entry(entry_id)


def findings(items_root: "Path | None" = None, *,
             validator_project: "Path | None" = None) -> "tuple[GrantFinding, ...]":
    """The real validator's `ReferenceUnresolved` findings, never a hand-derived guess about which
    rows are wrong. Only `combinations/**` findings are returned — the same code reaches every kind,
    and another kind's unresolved reference is that kind's own repair's business."""
    root = Path(items_root or ITEM_SEED_ROOT)
    project = validator_project or _default_validator_project(root)
    if project is None or not project.exists():
        raise RepairRefused(f"ItemSeedValidator project not found near {root}")
    proc = run_tool(
        ["dotnet", "run", "--project", str(project), "-c", "Release", "--no-build",
         "--", str(root), "--findings-json", "--codes=ReferenceUnresolved"],
        cwd=str(root.parents[2]), refusal=RepairRefused,
        what="the ReferenceUnresolved findings this repair plans against",
    )
    if proc.returncode not in (0, 1) or not proc.stdout.strip():
        raise RepairRefused(f"findings-json failed ({proc.returncode}): {proc.stderr.strip()[:400]}")
    text = proc.stdout[proc.stdout.index("{"):]
    doc = json.loads(text)
    return tuple(
        GrantFinding(entry_id=f["id"], file=f["file"], message=f["message"])
        for f in doc.get("findings", [])
        if f.get("id") and str(f.get("file", "")).startswith("combinations/"))


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
    return {k: row[k] for k in CONTEXT_KEYS if k in row}


def plan(items_root: "Path | None" = None, *,
         found: "tuple[GrantFinding, ...] | None" = None,
         catalog: "frozenset[str] | None" = None) -> "tuple[GrantRepair, ...]":
    """One repair per affected entry: its current grants, the subset the validator reported as
    unresolved, and the entry's own authored context. A finding is intersected with the row's actual
    grants, so a stale finding (the row was fixed since the validator ran) cannot send the model
    after a family that is already fine, and two findings on one entry collapse to one model call.

    `catalog` is accepted so a caller can pin the vocabulary it wants the answer closed against;
    it is NOT used to compute the bad set."""
    root = Path(items_root or ITEM_SEED_ROOT)
    found = found if found is not None else findings(items_root=root)

    targets: "dict[str, set[str]]" = {}
    files: "dict[str, str]" = {}
    for f in found:
        match = _REFERENCE_RE.search(f.message)
        if match is None:
            continue
        targets.setdefault(f.entry_id, set()).add(match.group(1))
        files.setdefault(f.entry_id, f.file)

    repairs: "list[GrantRepair]" = []
    for entry_id, bad_targets in sorted(targets.items()):
        path = root / files[entry_id]
        if not path.exists():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        row = _row_for(document, entry_id)
        if row is None:
            continue
        grants = tuple(str(g) for g in (row.get("grants") or ()))
        bad = tuple(g for g in grants if g in bad_targets)
        if not bad:
            continue
        repairs.append(GrantRepair(
            entry_id=entry_id, subject_id=subject_id_for(entry_id),
            shape=str(row.get("shape")
                      or (document.get("_meta") or {}).get("partition", "")).rsplit("/", 1)[-1],
            path=path, grants=grants, bad_families=bad, context=_context_for(row)))
    return tuple(repairs)


def bad_positions(repair: GrantRepair) -> "tuple[int, ...]":
    """The indices in `grants` the validator reported as unresolved. Positions, not names: a family
    may legitimately appear twice, and the answer replaces slots."""
    return tuple(i for i, g in enumerate(repair.grants) if g in repair.bad_families)


def schema(repair: GrantRepair, catalog: "frozenset[str]") -> "dict[str, Any]":
    """The catalog as a CLOSED enum, and one replacement per BAD SLOT pinned — the shape prevents a
    wrong-length or out-of-catalog answer at decode time, and asking only for the bad slots is what
    makes the change surgical: the already-resolvable grants never leave the code's hands."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["replacements"],
        "properties": {
            "replacements": {
                "type": "array",
                "minItems": len(bad_positions(repair)),
                "maxItems": len(bad_positions(repair)),
                "items": {"type": "string", "enum": sorted(catalog)},
            },
        },
    }


def brief(repair: GrantRepair, catalog: "frozenset[str]") -> str:
    context_lines = "\n".join(f"  {k}: {v!r}" for k, v in repair.context.items())
    bad = [repair.grants[i] for i in bad_positions(repair)]
    kept = [g for i, g in enumerate(repair.grants) if i not in bad_positions(repair)]
    return f"""One item combination grants atom families that do not exist in the game's real atom
catalog, so the combination can never bind. Only the families listed as broken may change; the
others are already correct and are NOT yours to touch.

Entry id: `{repair.entry_id}`
Its current grants: {list(repair.grants)}
Broken families, in the order you must answer them: {bad}
Families that already resolve (do not return these): {kept}

What this combination is:
{context_lines}

Return JSON only: `replacements`, a list of EXACTLY {len(bad)} family ids — one for each broken
family above, in that order. Each must be taken verbatim from the legal catalog below (never
invented, never a spelling variant) and must express the SAME mechanism the entry's own name,
flavor, aptitudes and ingredients already describe.

Legal catalog ({len(catalog)} ids):
{chr(10).join('  ' + f for f in sorted(catalog))}"""


def validate_answer(repair: GrantRepair, catalog: "frozenset[str]",
                    answer: "dict[str, Any]") -> "tuple[str, ...]":
    replacements = answer.get("replacements") if isinstance(answer, dict) else None
    if not isinstance(replacements, list) or not all(isinstance(g, str) for g in replacements):
        raise ValueError(f"{repair.entry_id}: 'replacements' must be a list of strings")
    expected = len(bad_positions(repair))
    if len(replacements) != expected:
        raise ValueError(f"{repair.entry_id}: expected {expected} replacements, got {len(replacements)}")
    outside = [g for g in replacements if g not in catalog]
    if outside:
        raise ValueError(f"{repair.entry_id}: {outside} are not in the production atom catalog")
    unresolved = [g for g in replacements if g in repair.bad_families]
    if unresolved:
        raise ValueError(f"{repair.entry_id}: {unresolved} do not resolve")
    return tuple(replacements)


def resolved_grants(repair: GrantRepair, replacements: "tuple[str, ...]") -> "tuple[str, ...]":
    """The entry's grants with every bad slot filled and every already-resolvable grant untouched,
    order preserved."""
    out = list(repair.grants)
    for position, family in zip(bad_positions(repair), replacements):
        out[position] = family
    return tuple(out)


def run_batch(repairs: "tuple[GrantRepair, ...]", *, caller, catalog: "frozenset[str] | None" = None,
              max_attempts: int = 5) -> "tuple[dict[str, tuple[str, ...]], list[dict[str, str]]]":
    """One model call per affected entry. Returns (entry_id -> repaired grants, failed)."""
    known = catalog if catalog is not None else registries.load_materialised_affix_family_ids()
    answers: "dict[str, tuple[str, ...]]" = {}
    failed: "list[dict[str, str]]" = []
    for repair in repairs:
        resolved = None
        for _attempt in range(max_attempts):
            try:
                raw = caller(brief(repair, known), schema(repair, known))
                resolved = resolved_grants(repair, validate_answer(repair, known, raw))
                break
            except (ValueError, json.JSONDecodeError):
                continue
            except RuntimeError as exc:
                failed.append({"entryId": repair.entry_id, "reason": f"model call failed: {exc}"})
                break
        if resolved is None:
            if not any(f["entryId"] == repair.entry_id for f in failed):
                failed.append({"entryId": repair.entry_id,
                               "reason": f"no valid answer after {max_attempts} attempts"})
            continue
        answers[repair.entry_id] = resolved
    return answers, failed


def apply(answers: "dict[str, tuple[str, ...]]", repairs: "tuple[GrantRepair, ...]", *,
          write: bool, ledger_path: "Path | None" = None) -> "tuple[Path, ...]":
    """Write each answered entry's `grants` into BOTH the ledger row and its shipped row, leaving
    every other field of both untouched. `write=False` reports what would change without touching
    disk.

    The shipped row is read from the FILE the corpus actually ships (the one the validator passes),
    never from the ledger's copy — a stale ledger must not be able to revert a field this repair is
    not changing. Only `grants` is taken from the answer.
    """
    by_id = {r.entry_id: r for r in repairs}
    if ledger_path is None:
        # The ledger sits beside the seed file it describes (`authored.DEFAULT_LEDGER_NAME`), so a
        # repair derived from one filesystem location can never accidentally move the PRODUCTION
        # ledger while rewriting a temp copy.
        parents = {r.path.parent for r in repairs}
        if len(parents) != 1:
            raise RepairRefused(f"repairs span {len(parents)} directories; pass ledger_path")
        ledger_path = parents.pop() / authored_mod.DEFAULT_LEDGER_NAME
    ledger = RunLedger(ledger_path)
    done = ledger.read_done()

    # Group by file so each document is read, edited and written once.
    by_path: "dict[Path, dict[str, list[str]]]" = {}
    for entry_id, grants in answers.items():
        repair = by_id.get(entry_id)
        if repair is None or not isinstance(done.get(repair.subject_id), dict):
            continue
        by_path.setdefault(repair.path, {})[entry_id] = list(grants)

    changed: "list[Path]" = []
    for path, mapping in by_path.items():
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        touched = False
        repaired: "dict[str, dict[str, Any]]" = {}
        for row in document.get("entries") or ():
            if not isinstance(row, dict) or row.get("id") not in mapping:
                continue
            grants = mapping[row["id"]]
            if list(row.get("grants") or ()) == grants:
                continue
            row["grants"] = grants
            repaired[row["id"]] = {"grants": grants}
            touched = True
        if touched:
            changed.append(path)
            if write:
                _atomic_json(path, document)
                # Ledger and file move together, or the next `--write` reverts the grants.
                authored_mod.sync_repair_to_ledger(path, repaired, write=True)
    return tuple(sorted(changed))


def _atomic_json(path: Path, document: dict) -> None:
    """Temp-file-then-`os.replace`, the discipline every generator in this program uses, so a
    killed process leaves either the old file or the new one."""
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
