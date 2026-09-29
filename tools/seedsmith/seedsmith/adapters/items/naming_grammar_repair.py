"""seedsmith.adapters.items.naming_grammar_repair — model-authored repair for names that fail
naming.v1.json's naming grammar (`NameGrammarViolation` / `PossessiveForbidden` /
`InventedConnective` / `PluralForbidden` / `GeneratedOnlyNamePattern` / `FusionNotDecomposable`).

Unlike `setgen.name_repair` (duplicate-name collisions, grouped by the validator's
`--collision-groups`), this repair is driven directly by
`ItemSeedValidator --findings-json --codes=...`, because the defect here is not a collision but a
grammar violation on an ALREADY-UNIQUE name. It spans every item-family kind `NamingCheck.cs`
applies to (set, charm, base-type, drop-table, combination, affix-family, gem) rather than being
scoped to one generator, since the repair only ever changes the persisted `name` field directly — it
needs no per-kind generation machinery.

⛔ Reads the REAL corpus and the REAL validator's findings, never a hand-derived list of "which names
look wrong" — the C# `NamingCheck`/`NameNormalizer` is the sole authority on what fails and what a
repaired name must satisfy; this module never re-implements that grammar in Python, the same
discipline `name_repair.py`'s own docstring states for the collision normalizer
(`gk-forge/tools/ItemSeedValidator/Naming/NameNormalizer.cs`).
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .naming_grammar import NAMING_GRAMMAR_RULES
from .setgen.seedfile import ITEM_SEED_ROOT
from ...tooling import run_tool

#: Every NamingCheck.cs code this repair can fix — a `name` field problem, never an id/reference/
#: structural one. Passed to `--findings-json --codes=` so the C# side does the filtering.
NAMING_GRAMMAR_CODES: tuple[str, ...] = (
    "NameGrammarViolation", "PossessiveForbidden", "InventedConnective",
    "PluralForbidden", "GeneratedOnlyNamePattern", "FusionNotDecomposable",
)


class RepairRefused(RuntimeError):
    """The validator tool could not run or returned nothing usable — refuse rather than guess."""


@dataclass(frozen=True)
class NamingGrammarFinding:
    entry_id: str
    code: str
    file: str
    message: str


@dataclass(frozen=True)
class NamingGrammarRepair:
    entry_id: str
    path: Path
    kind: str
    old_name: str
    codes: tuple[str, ...]


def findings(items_root: Path | None = None, *, validator_project: Path | None = None,
            codes: tuple[str, ...] = NAMING_GRAMMAR_CODES,
            build: bool = False) -> tuple[NamingGrammarFinding, ...]:
    """The validator's authoritative findings for the naming-grammar codes. Raises `RepairRefused`
    if the tool cannot run — a repair planned against a guessed list is worse than no repair."""
    root = Path(items_root or ITEM_SEED_ROOT)
    project = validator_project or _default_validator_project(root)
    if project is None or not project.exists():
        raise RepairRefused(f"ItemSeedValidator project not found near {root}")
    args = ["dotnet", "run", "--project", str(project), "-c", "Release"]
    if not build:
        args.append("--no-build")
    args += ["--", str(root), "--findings-json", f"--codes={','.join(codes)}"]
    proc = run_tool(
        args, cwd=str(root.parents[2]), refusal=RepairRefused,
        what="the naming-grammar findings this repair plans against",
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RepairRefused(f"findings-json failed ({proc.returncode}): {proc.stderr.strip()[:400]}")
    # `dotnet run` can print build/restore lines before our JSON; the payload starts at the first
    # brace, the same convention `name_repair.collision_groups` already established.
    text = proc.stdout[proc.stdout.index("{"):]
    doc = json.loads(text)
    return tuple(
        NamingGrammarFinding(entry_id=f["id"], code=f["code"], file=f["file"], message=f["message"])
        for f in doc.get("findings", []) if f.get("id"))


def _default_validator_project(root: Path) -> Path | None:
    for parent in [root, *root.parents]:
        candidate = parent / "tools" / "ItemSeedValidator" / "ItemSeedValidator.csproj"
        if candidate.exists():
            return candidate
    return None


def plan(items_root: Path | None = None, *,
        found: tuple[NamingGrammarFinding, ...] | None = None
        ) -> tuple[NamingGrammarRepair, ...]:
    """One repair per distinct failing entry, deduped across every naming-grammar code it triggered
    (a name can fail more than one check at once, e.g. NameGrammarViolation + PossessiveForbidden on
    the same `Kirov's Tethered Husk`)."""
    root = Path(items_root or ITEM_SEED_ROOT)
    found = found if found is not None else findings(items_root=root)

    codes_by_id: dict[str, list[str]] = {}
    file_by_id: dict[str, str] = {}
    for f in found:
        codes_by_id.setdefault(f.entry_id, []).append(f.code)
        file_by_id.setdefault(f.entry_id, f.file)

    repairs: list[NamingGrammarRepair] = []
    for entry_id, codes in codes_by_id.items():
        path = root / file_by_id[entry_id]
        if not path.exists():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        kind = str(document.get("kind") or "")
        row = next((r for r in (document.get("entries") or ())
                    if isinstance(r, dict) and r.get("id") == entry_id), None)
        if row is None:
            continue
        name = row.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        repairs.append(NamingGrammarRepair(entry_id=entry_id, path=path, kind=kind,
                                           old_name=name.strip(), codes=tuple(sorted(set(codes)))))
    return tuple(sorted(repairs, key=lambda r: r.entry_id))


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }


def brief(repair: NamingGrammarRepair, *, refused: tuple[str, ...] = ()) -> str:
    refusal_note = ""
    if refused:
        refusal_note = (f"\n\nYour previous answer(s) were refused: {', '.join(refused)}. Return a "
                        "DIFFERENT name that is not any of those and does not already exist "
                        "elsewhere in the game. Use only English words — no CJK characters, no "
                        "digits, no punctuation beyond a single apostrophe-free space.")
    # Shape C is the one the validator checks against a CLOSED vocabulary, not just the shape rules:
    # a joined compound must decompose into exactly one pair of the game's own words. A model that
    # only knows "two real English words" produces `Shattershield` and fails again — say which half
    # is actually constrained.
    fusion_note = ""
    if "FusionNotDecomposable" in repair.codes:
        fusion_note = (
            "\n⛔ `FusionNotDecomposable` means shape C is checked against the game's own WORD "
            "POOL, not against English: the compound must split into exactly TWO words that both "
            "already exist in the game's vocabulary, and a hyphen is read as a fusion too. Unless "
            "you are certain both halves are existing game words, choose shape A or shape B "
            "instead — a space-separated pair (or `X of [the] Y`) is never checked this way.\n")
    return f"""Rename one {repair.kind} display name so it satisfies the naming grammar below. Change
ONLY the name — every gameplay field on this entry (class, tiers, families, roles, members,
thresholds, everything except `name`) stays exactly as it already is.

Entry id: `{repair.entry_id}`
Current (illegal) name: `{repair.old_name}`
Why it is illegal: {', '.join(repair.codes)}

{NAMING_GRAMMAR_RULES}
{fusion_note}
Return JSON only: a replacement `name` that fits this {repair.kind}'s existing theme as closely as
you reasonably can while obeying every rule above. The replacement must not reuse the illegal name's
exact wording and must not already exist elsewhere in the game.{refusal_note}"""


def validate_answer(repair: NamingGrammarRepair, answer: dict[str, Any], *,
                    items_root: Path | None = None,
                    extra_taken: set[str] | None = None) -> str:
    """Returns the clean, stripped name or raises `ValueError` naming why the answer is refused."""
    name = answer.get("name") if isinstance(answer, dict) else None
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{repair.entry_id}: replacement name is empty")
    name = name.strip()
    if name.casefold() == repair.old_name.casefold():
        raise ValueError(f"{repair.entry_id}: replacement name is unchanged")
    current = _current_names(Path(items_root or ITEM_SEED_ROOT))
    if extra_taken:
        current |= {n.casefold() for n in extra_taken}
    if name.casefold() in current:
        raise ValueError(f"{repair.entry_id}: replacement name {name!r} already exists")
    return name


def run_batch(repairs: tuple[NamingGrammarRepair, ...], *, caller, items_root: Path | None = None,
             max_attempts: int = 5) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Call `caller(prompt, schema)` once per repair, with bounded per-row retries on a refused
    answer (the same "a single bad answer never discards the whole batch" resilience
    `_cmd_items_repair_names` already established). `caller` is normally
    `seedsmith.pipeline.llm_caller.live_answer_caller(transport)`, injected here so a test can pass a
    fake without a live endpoint. Returns `(answers, failed)`; only answered rows are ever written by
    `apply` — a row that still fails after `max_attempts` is reported and left for the next run."""
    root = Path(items_root or ITEM_SEED_ROOT)
    answers: dict[str, str] = {}
    failed: list[dict[str, str]] = []
    taken: set[str] = set()
    for repair in repairs:
        refused: list[str] = []
        for attempt in range(1, max_attempts + 1):
            prompt = brief(repair, refused=tuple(refused))
            raw: Any = None
            try:
                raw = caller(prompt, schema())
                name = validate_answer(repair, raw, items_root=root, extra_taken=taken)
                answers[repair.entry_id] = name
                taken.add(name.casefold())
                break
            except (ValueError, json.JSONDecodeError) as exc:
                candidate = raw.get("name") if isinstance(raw, dict) else None
                refused.append(str(candidate) if candidate else "?")
                if attempt == max_attempts:
                    failed.append({"entryId": repair.entry_id, "reason": str(exc)})
            except RuntimeError as exc:
                # A transport failure is not the row's fault; report and move on.
                failed.append({"entryId": repair.entry_id, "reason": f"model call failed: {exc}"})
                break
    return answers, failed


def apply(answers: dict[str, str], repairs: tuple[NamingGrammarRepair, ...], *,
         write: bool) -> tuple[Path, ...]:
    """Writes only the `name` field of each answered entry. `write=False` reports what would change
    without touching disk."""
    repair_by_id = {r.entry_id: r for r in repairs}
    by_path: dict[Path, dict[str, str]] = {}
    for entry_id, new_name in answers.items():
        repair = repair_by_id.get(entry_id)
        if repair is None:
            continue
        by_path.setdefault(repair.path, {})[entry_id] = new_name

    changed: list[Path] = []
    for path, mapping in by_path.items():
        document = json.loads(path.read_text(encoding="utf-8"))
        repaired: dict[str, dict[str, str]] = {}
        for row in document.get("entries") or ():
            if isinstance(row, dict) and row.get("id") in mapping:
                row["name"] = mapping[row["id"]]
                repaired[row["id"]] = {"name": row["name"]}
        if repaired:
            changed.append(path)
            if write:
                _atomic_json(path, document)
                # A combination file is a full rewrite of `entries_from_ledger` on every
                # `run_batch --write`, so the rename must land in the ledger too or it is reverted
                # (the defect `fae533a519` left — SSH2.5 finding 1). Other kinds have no such
                # ledger; `authored.subject_id_for_entry` refuses a non-`combo.` id, so guard.
                if str(document.get("kind")) == "combination":
                    from .combogen import authored as authored_mod

                    authored_mod.sync_repair_to_ledger(path, repaired, write=True)
    return tuple(sorted(changed))


def _current_names(root: Path) -> set[str]:
    names: set[str] = set()
    for path in root.glob("**/*.json"):
        if path.name.startswith("_") or "_runs" in path.parts or "_exemplars" in path.parts:
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in document.get("entries") or ():
            if isinstance(row, dict):
                name = row.get("name")
                if isinstance(name, str) and name.strip():
                    names.add(name.strip().casefold())
    return names


def _atomic_json(path: Path, document: dict) -> None:
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        # newline="\n": see namekey_repair._atomic_json's own note — text-mode fdopen otherwise
        # writes the OS default line ending (CRLF on Windows) regardless of the source file's LF.
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
