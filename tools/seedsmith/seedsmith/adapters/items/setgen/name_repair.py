"""Explicit repair for persisted duplicate item display names, across every colliding kind.

Generation rejects a new collision before it writes. This module handles the older corpus rows that
predate that guard: it changes only a losing row's surface `name`, its derived `nameKey`, and
optionally its `flavor`. Class, atoms, costs, tiers, members and every other gameplay field stay
byte-for-byte intact.

⛔ **Why the groups come from the validator, not from this module.** The collision rule is
`naming.v1.json`'s normalization (lowercase, tokenize, whole-token resolution, drop connectives,
sort, compare) implemented in `gk-forge/tools/ItemSeedValidator/Naming/NameNormalizer.cs`. Reimplementing
that in Python would fork the authority: a repair computed against a slightly different algorithm
could leave the validator still reporting collisions, or rename rows that never collided. So the
plan consumes `dotnet run --project gk-forge/tools/ItemSeedValidator -- <root> --collision-groups`, which
prints the authoritative groups using that exact normalizer.

**Scope (2026-09-12).** Originally `sets` + `charms` only, matched on the exact casefolded string —
which found 0 rows, because the real rule is token-set based ("Rolling Grave Nut" collides with
"Rolling Grave-Nut"). It now covers every kind the validator checks and uses its groups.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .seedfile import ITEM_SEED_ROOT, derive_name_key, NameKeyUnsluggable
from ..naming_grammar import NAMING_GRAMMAR_RULES
from ....tooling import run_tool


@dataclass(frozen=True)
class NameRepair:
    entry_id: str
    kind: str
    path: Path
    old_name: str
    keeper_id: str
    #: The KEEPER's own surface name, or "" when there is no keeper to name (a placeholder
    #: `nameKey` group). The brief used to name the keeper by id alone (`combo.splice-fortitude-
    #: ferocity`), which hides the one string the model must avoid: the keeper's DISPLAY name.
    #: Measured 2026-09-21 on the real corpus — with only the id and the old name in the prompt,
    #: five attempts at renaming `combo.strain-ferocity-balance` produced nothing but the keeper's
    #: own idea in the other word order ("Ferocity Bastion" / "Bastion of Ferocity"), and the
    #: repair could not complete. Naming the keeper in words is what makes the refusal actionable.
    keeper_name: str = ""
    cluster_size: int = 2


def collision_groups(items_root: Path | None = None, *,
                     validator_project: Path | None = None) -> list[dict]:
    """The validator's authoritative collision groups. Raises RuntimeError if the tool cannot run,
    because a repair planned against a guessed grouping is worse than no repair."""
    root = Path(items_root or ITEM_SEED_ROOT)
    project = validator_project or _default_validator_project(root)
    if project is None or not project.exists():
        raise RuntimeError(f"ItemSeedValidator project not found near {root}")
    proc = run_tool(
        ["dotnet", "run", "--project", str(project), "--", str(root), "--collision-groups"],
        cwd=str(root.parents[2]), refusal=RuntimeError,
        what="the validator's authoritative collision groups",
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"collision-groups failed ({proc.returncode}): {proc.stderr.strip()[:400]}")
    # `dotnet run` can print build/restore lines before our JSON; the payload starts at the first
    # brace, and a JSON document is otherwise the last thing on stdout.
    text = proc.stdout[proc.stdout.index("{"):]
    try:
        return json.loads(text).get("groups", [])
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"collision-groups returned unparseable JSON ({exc}); head: {text[:200]!r}") from exc


def validator_keys(names: "list[str] | tuple[str, ...]", *, items_root: Path | None = None,
                   validator_project: Path | None = None) -> dict[str, str]:
    """The validator's AUTHORITATIVE normalized key for each of `names` (`NameNormalizer.Normalize`,
    `--normalize-names`). The replacement-name check needs the same authority the collision gate
    uses: `validate_answers`'s own casefold comparison accepted "Ferocity Bulwark" against the
    shipped set "Bulwark of Ferocity" (measured 2026-09-21) and the repair minted a fresh collision.
    Raises RuntimeError if the tool cannot run — checking a candidate against a guessed key is worse
    than refusing the repair."""
    root = Path(items_root or ITEM_SEED_ROOT)
    project = validator_project or _default_validator_project(root)
    if project is None or not project.exists():
        raise RuntimeError(f"ItemSeedValidator project not found near {root}")
    payload = json.dumps(sorted({str(n) for n in names}), ensure_ascii=False)
    proc = run_tool(
        ["dotnet", "run", "--project", str(project), "--", str(root), "--normalize-names"],
        cwd=str(root.parents[2]), refusal=RuntimeError, input=payload,
        what="the validator's authoritative name normalisation",
    )
    if proc.returncode != 0 or "{" not in proc.stdout:
        raise RuntimeError(f"normalize-names failed ({proc.returncode}): {proc.stderr.strip()[:400]}")
    text = proc.stdout[proc.stdout.index("{"):]
    try:
        return {str(k): str(v) for k, v in json.loads(text).get("keys", {}).items()}
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"normalize-names returned unparseable JSON ({exc}); head: {text[:200]!r}") from exc


def shipped_name_keys(*, items_root: Path | None = None,
                     validator_project: Path | None = None) -> set[str]:
    """Every normalized key the SHIPPED corpus already uses, from the validator's own normalizer.
    A new row's name may not reuse one: the shipped corpus cannot be edited to accommodate it."""
    names = sorted(_current_names(Path(items_root or ITEM_SEED_ROOT)))
    return {key for key in validator_keys(names, items_root=items_root,
                                         validator_project=validator_project).values() if key}


def name_defects(names: "list[str] | tuple[str, ...]", *, items_root: Path | None = None,
                 validator_project: Path | None = None) -> dict[str, list[str]]:
    """The validator's own naming-grammar defects for each candidate name
    (`gk-forge/tools/ItemSeedValidator --check-names`, `NamingCheck.CandidateNameDefects`).

    ⛔ Same authority rule as `validator_keys`: the naming patterns are a C# check, and a Python copy of
    them would fork the grammar — a generator that accepts what the gate refuses is the defect
    strain-splice-host SSH5.13-P1 measured (`Ironstead`, `Ironheart`: single-word fusions that do not
    decompose into two pool words). Raises RuntimeError if the tool cannot run, because refusing a name
    against a guessed grammar is worse than not authoring it."""
    root = Path(items_root or ITEM_SEED_ROOT)
    project = validator_project or _default_validator_project(root)
    if project is None or not project.exists():
        raise RuntimeError(f"ItemSeedValidator project not found near {root}")
    payload = json.dumps(sorted({str(n) for n in names}), ensure_ascii=False)
    proc = run_tool(
        ["dotnet", "run", "--project", str(project), "--", str(root), "--check-names"],
        cwd=str(root.parents[2]), refusal=RuntimeError, input=payload,
        what="the validator's authoritative name check",
    )
    if proc.returncode != 0 or "{" not in proc.stdout:
        raise RuntimeError(f"check-names failed ({proc.returncode}): {proc.stderr.strip()[:400]}")
    text = proc.stdout[proc.stdout.index("{"):]
    try:
        rows = json.loads(text).get("names", [])
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"check-names returned unparseable JSON ({exc}); head: {text[:200]!r}") from exc
    return {str(row.get("name", "")): [str(d) for d in row.get("defects", [])] for row in rows}


def _default_validator_project(root: Path) -> Path | None:
    for parent in [root, *root.parents]:
        candidate = parent / "tools" / "ItemSeedValidator" / "ItemSeedValidator.csproj"
        if candidate.exists():
            return candidate
    return None


def plan(items_root: Path | None = None, *, groups: list[dict] | None = None) -> tuple[NameRepair, ...]:
    """Keep the lexically first id in each authoritative collision group; return every later row.

    Two group reasons exist. `name` collides on the normalized name (the repair renames the losing
    rows). `nameKey` collides on the derived key while the names differ — the placeholder-key defect
    (`set.item`/`charm.item` on rows with distinct Chinese names). A nameKey collision is fixed by
    re-deriving the key from the row's own name, NOT by renaming it, so those rows are renamed only
    when the model returns an answer; the deterministic key repair is `repair_name_keys`.
    """
    root = Path(items_root or ITEM_SEED_ROOT)
    groups = groups if groups is not None else collision_groups(items_root=root)

    # id -> (path, kind, name); built once so each losing row can be located.
    index: dict[str, tuple[Path, str, str]] = {}
    for path in sorted(root.glob("**/*.json")):
        if path.name.startswith("_") or "_exemplars" in path.parts or "_runs" in path.parts:
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        kind = document.get("kind")
        for row in document.get("entries") or ():
            if not isinstance(row, dict):
                continue
            entry_id, name = row.get("id"), row.get("name")
            if isinstance(entry_id, str) and isinstance(name, str) and name.strip():
                index[entry_id] = (path, str(kind or ""), name.strip())

    repairs: list[NameRepair] = []
    for group in groups:
        members = sorted(group.get("members") or [], key=lambda m: m.get("id") or "")
        if len(members) < 2:
            continue
        keeper = members[0]["id"]
        for member in members[1:]:
            entry_id = member.get("id")
            located = index.get(entry_id)
            if located is None:
                continue
            path, kind, name = located
            if group.get("reason") == "nameKey":
                stored = (member.get("nameKey") or "")
                if stored not in PLACEHOLDER_KEYS:
                    continue
                # Every row in a placeholder group has a DISTINCT name; the collision is the shared
                # literal key, so there is no "keeper name" to avoid. Rename each losing row (all but
                # the first, which keeps its name but also needs its key re-derived).
                repairs.append(NameRepair(entry_id=entry_id, kind=kind, path=path,
                                          old_name=name, keeper_id="(placeholder key)",
                                          cluster_size=len(members)))
                continue
            repairs.append(NameRepair(entry_id=entry_id, kind=kind, path=path,
                                      old_name=name, keeper_id=keeper,
                                      keeper_name=str(index.get(keeper, (None, None, ""))[2]),
                                      cluster_size=len(members)))
    return tuple(sorted(repairs, key=lambda r: r.entry_id))


@dataclass(frozen=True)
class NameKeyRepair:
    entry_id: str
    path: Path
    old_key: str
    new_key: str


PLACEHOLDER_KEYS = frozenset({"set.item", "charm.item"})


def repair_name_keys(*, items_root: Path | None = None, write: bool = False
                     ) -> tuple[NameKeyRepair, ...]:
    """Re-derive the `nameKey` of every row carrying a PLACEHOLDER key, from that row's own name.

    Deterministic, no model. Scope is deliberately narrow: the finding this fixes is a whole
    population (52 rows) sharing one literal key — `set.item` / `charm.item` — which a generation run
    minted when the model's name had no ASCII slug and the old `_slugify` fell back to `"item"` (see
    `seedfile._slugify`'s own 2026-09-12 note). Those names are fine; only the key is wrong, so
    re-deriving fixes the duplicate-key finding WITHOUT touching the row's identity — the correct
    disposition for `seed-contract.md` §7.2's "entry is wrong, same identity".

    It does NOT rewrite every key that disagrees with its name: 1,400+ keys follow per-kind
    conventions (`affix.<x>`, `base.<x>`, …) that `derive_name_key` does not know, so a general
    rewrite would corrupt them. Only the two placeholder literals are unambiguously wrong.
    """
    root = Path(items_root or ITEM_SEED_ROOT)
    repairs: list[NameKeyRepair] = []
    for path in sorted(root.glob("**/*.json")):
        if path.name.startswith("_") or "_exemplars" in path.parts or "_runs" in path.parts:
            continue
        document = _load(path)
        if document is None:
            continue
        kind = document.get("kind")
        if kind not in ("set", "charm"):
            continue
        touched = False
        for row in document.get("entries") or ():
            if not isinstance(row, dict):
                continue
            name, stored = row.get("name"), row.get("nameKey")
            if stored not in PLACEHOLDER_KEYS:
                continue
            if not isinstance(name, str) or not name.strip():
                continue
            try:
                derived = derive_name_key(kind, name.strip())
            except NameKeyUnsluggable:
                continue  # reported by the Core validator; never silently placeholdered
            if derived != stored:
                repairs.append(NameKeyRepair(row["id"], path, stored, derived))
                if write:
                    row["nameKey"] = derived
                    touched = True
        if write and touched:
            _atomic_json(path, document)
    return tuple(sorted(repairs, key=lambda r: r.entry_id))


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["name"],
        "properties": {
            "name": {"type": "string"},
            "flavor": {"type": "string"},
        },
    }


def brief(repair: NameRepair, *, cluster_size: int = 0) -> str:
    cluster_note = ""
    if cluster_size > 2:
        # A large cluster (up to 12 rows share one keeper) needs N DISTINCT new names, and a local
        # model converges on the same obvious replacement ("Twisted Tendril") for every row when
        # asked one at a time. Saying so, and asking for a name specific to THIS row, breaks the tie.
        cluster_note = (f"\n⚠ {cluster_size} rows share this name. Many other rows are being renamed "
                        f"in parallel and will propose the obvious alternatives, so choose a "
                        f"distinctive name specific to THIS entry's own id and materials rather than "
                        f"the most natural one.\n")
    # A combination's name is still checked against `naming.v1.json`'s grammar by the C# validator,
    # but this module's own brief never stated it — so a rename could clear the collision and mint a
    # grammar violation instead (the trade SSH2.5's regen actually made, and the one measured again
    # on ISG6's first pass: three fused names cleared 13 collisions and added 3
    # `FusionNotDecomposable`). State the rule, and the fusion half of it.
    grammar_note = ""
    if repair.kind == "combination":
        grammar_note = (
            f"\n{NAMING_GRAMMAR_RULES}\n"
            "⛔ Shape C is read as a FUSION and checked against the game's own word pools: a "
            "hyphenated or joined compound is refused unless it is exactly TWO words that both "
            "already exist in the game's vocabulary. Prefer shape A or shape B (a space between the "
            "words), and do not invent a compound.\n")
    keeper_note = (f" — its display name is `{repair.keeper_name}`; no word order or spelling of "
                   "that same idea is a legal answer" if repair.keeper_name else "")
    return f"""Rename one {repair.kind} display name without changing its gameplay data.

Entry id: `{repair.entry_id}`
Current duplicate name: `{repair.old_name}`
The name is already kept by `{repair.keeper_id}`{keeper_note}.
{cluster_note}{grammar_note}
Return JSON only: a specific, distinct replacement `name`, and optionally a replacement `flavor`.
The new name must be a legal {repair.kind} name (a thing a player picks up, not a sentence or an
id), must not reuse the old name's idea in a different word order, and must not mention ids, costs,
tiers, mechanics, or numbers."""


def validate_answers(repairs: tuple[NameRepair, ...], answers: dict[str, dict], *,
                     items_root: Path | None = None,
                     extra_taken: set[str] | None = None,
                     key_of: "Callable[[list[str]], dict[str, str]] | None" = None) -> dict[str, dict]:
    """Validate replacement answers. `key_of` supplies the validator's authoritative normalized
    key for a batch of names (`validator_keys`); without it only the casefold comparison runs, which
    cannot see two names that share every token in a different order — pass it on every real repair."""
    expected = {repair.entry_id for repair in repairs}
    if set(answers) != expected:
        missing = sorted(expected - set(answers))
        extra = sorted(set(answers) - expected)
        raise ValueError(f"name-repair answers must name exactly the {len(expected)} losing rows "
                         f"(missing {missing[:5]}, unexpected {extra[:5]})")
    current_names = _current_names(Path(items_root or ITEM_SEED_ROOT))
    # Names already accepted for OTHER rows in the same batch. Without this a batch can hand two
    # rows the same replacement, and the collision only surfaces at apply time after the whole run.
    if extra_taken:
        current_names |= {n.casefold() for n in extra_taken}
    candidates = [str(answer.get("name", "")).strip() for answer in answers.values()
                  if isinstance(answer, dict)]
    computed = key_of(sorted(current_names) + candidates) if key_of is not None else {}
    taken_keys = {computed[name] for name in current_names if computed.get(name)}
    clean: dict[str, dict] = {}
    for repair in repairs:
        answer = answers[repair.entry_id]
        name = answer.get("name") if isinstance(answer, dict) else None
        flavor = answer.get("flavor") if isinstance(answer, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{repair.entry_id}: replacement name is empty")
        if flavor is not None and not isinstance(flavor, str):
            raise ValueError(f"{repair.entry_id}: flavor must be a string when present")
        normalized = name.strip().casefold()
        if normalized in current_names:
            raise ValueError(f"{repair.entry_id}: replacement name {name!r} already exists")
        key = computed.get(name.strip(), "")
        if key and key in taken_keys:
            raise ValueError(f"{repair.entry_id}: replacement name {name!r} normalizes to {key!r}, "
                             f"the same idea as a name already in the corpus")
        current_names.add(normalized)
        if key:
            taken_keys.add(key)
        # A name the grammar cannot slug cannot mint a legal nameKey; catch it here rather than at
        # the write, where a partial apply would be worse.
        try:
            derive_name_key(repair.kind, name.strip())
        except NameKeyUnsluggable as exc:
            raise ValueError(f"{repair.entry_id}: {exc}") from exc
        clean[repair.entry_id] = {"name": name.strip(),
                                  **({"flavor": flavor} if flavor is not None else {})}
    return clean


def apply(repairs: tuple[NameRepair, ...], answers: dict[str, dict], *, write: bool,
          items_root: Path | None = None,
          key_of: "Callable[[list[str]], dict[str, str]] | None" = None) -> tuple[Path, ...]:
    """Apply validated answers, preserving every field unrelated to player-facing identity."""
    clean = validate_answers(repairs, answers, items_root=items_root, key_of=key_of)
    by_path: dict[Path, list[NameRepair]] = {}
    for repair in repairs:
        by_path.setdefault(repair.path, []).append(repair)
    changed: list[Path] = []
    for path in by_path:
        document = _load(path)
        if document is None:
            continue
        kind = str(document.get("kind") or "")
        repaired: dict[str, dict[str, Any]] = {}
        for row in document.get("entries") or ():
            if not isinstance(row, dict) or row.get("id") not in clean:
                continue
            answer = clean[row["id"]]
            row["name"] = answer["name"]
            fields: dict[str, Any] = {"name": row["name"]}
            if kind == "combination":
                # ⛔ A combination's `nameKey` is PLANNED from its grid cell (`emit.name_key` mints
                # `combination.<shape>-<cell>`), never derived from the display name. Re-deriving it
                # here would break that contract and `entries_from_ledger`'s own identity — the
                # second half of the defect `fae533a519` left (SSH2.5 finding 1). Leave the key as
                # the generator minted it.
                pass
            else:
                row["nameKey"] = derive_name_key(kind, answer["name"])
                fields["nameKey"] = row["nameKey"]
                # `iconKey` is DERIVED from `nameKey` (`gemgen.emit.icon_key` does `f"icon.{nameKey}"`),
                # so a rename that updates the key but leaves the icon stale ships an icon pointing
                # at the row's former identity — caught by test_sockets_gen on gem.g2-022/g2-025.
                # Any row carrying the field gets it re-derived here.
                if "iconKey" in row:
                    row["iconKey"] = f"icon.{row['nameKey']}"
                    fields["iconKey"] = row["iconKey"]
            if "flavor" in answer:
                row["flavor"] = answer["flavor"]
                fields["flavor"] = row["flavor"]
            repaired[row["id"]] = fields
        changed.append(path)
        if write:
            _atomic_json(path, document)
            if kind == "combination":
                # Ledger and file move together, or the next `run_batch --write` reverts the rename.
                _sync_combination_ledger(path, repaired)
    return tuple(changed)


def _sync_combination_ledger(path: Path, repaired: dict[str, dict[str, Any]]) -> None:
    """Push this rename into `combination-gen.ledger.json`, so `authored.entries_from_ledger`
    agrees with the shipped file. Imported lazily: `combogen` sits above `setgen` in the adapter
    graph (`combogen.authored` imports `setgen.answers`), so a module-level import would cycle."""
    from ..combogen import authored as authored_mod

    authored_mod.sync_repair_to_ledger(path, repaired, write=True)


def _current_names(root: Path) -> set[str]:
    names: set[str] = set()
    for path in root.glob("**/*.json"):
        if path.name.startswith("_") or "_runs" in path.parts:
            continue
        document = _load(path)
        if document is None:
            continue
        for row in document.get("entries") or ():
            if isinstance(row, dict):
                name = row.get("name")
                if isinstance(name, str) and name.strip():
                    names.add(name.strip().casefold())
    return names


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _atomic_json(path: Path, document: dict) -> None:
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        # newline="\n" pins the literal byte this repo's committed JSON already uses on every
        # platform — without it, Python's text-mode universal-newline translation silently writes
        # the OS default (CRLF on Windows) regardless of what was on disk before (item-seed-regen
        # cause 3, 2026-09-20: caught by a real byte-identical round-trip test after the sibling
        # namekey_repair module hit the exact same bug).
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
