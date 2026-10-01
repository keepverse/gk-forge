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
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .seedfile import ITEM_SEED_ROOT, derive_name_key, NameKeyUnsluggable
from ..naming_grammar import NAMING_GRAMMAR_RULES
from ....tooling import run_tool
from ....workspace_roots import forge_root, RootNotFound


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
    """The validator project, found by walking up from `root` and then by ASKING the resolver.

    The walk alone is a pre-split shape. `ItemSeedValidator` lives in gk-forge
    (`tools/ItemSeedValidator`), while the corpus root this is called with is gk-data's
    (`data/seed/items` inside the content pack), and those two repositories are SIBLINGS: no number of
    `..` hops from one arrives at the other. The walk therefore exhausted every ancestor of the pack
    and returned None, and the callers turned that into
    `ItemSeedValidator project not found near <gk-data>/.../items` -- a refusal naming a directory
    the project was never under, for a project sitting present in a sibling repository.

    So the walk stays (it is what a legacy monorepo clone and a planted fixture both need, and it is
    the nearest-match rule) and `forge_root()` is consulted after it. `forge_root` RAISES when
    gk-forge is absent, which is the same absence the walk already reported, so it is caught and the
    None answer is preserved: every caller raises its own clear RuntimeError on None, and nothing here
    invents a path that does not exist.
    """
    for parent in [root, *root.parents]:
        candidate = parent / "tools" / "ItemSeedValidator" / "ItemSeedValidator.csproj"
        if candidate.exists():
            return candidate
    try:
        sibling = forge_root() / "tools" / "ItemSeedValidator" / "ItemSeedValidator.csproj"
    except RootNotFound:
        return None
    return sibling if sibling.exists() else None


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


# =============================================================================================
# DETERMINISTIC DERIVATION — no model, no endpoint, no authored answer
# =============================================================================================
#
# `brief` + `validate_answers` + `apply` above are the MODEL path: they ask for a name and check the
# answer. They cannot repair this corpus, because the whole defect is 84 rows whose names are
# duplicates of names that must NOT move, and a local model given "Abyssal Maw" as the keeper returns
# another abyssal-maw name and is refused (the `brief` docstring records that measured loop).
#
# The path below derives each losing row's replacement from the row's OWN fields, reproducibly:
# `scope`/`scopeKey`/`slot` (or `speciesId`), `tags`, `materialClass`, `runtimeId` — never external
# data, never a model, and never a re-implementation of the normalizer. Every uniqueness question is
# asked of the authority (`validator_keys`, `--normalize-names`) and every grammar question of
# `name_defects` (`--check-names`), so a derived name that would mint a fresh collision or a
# malformed name is REFUSED before a write instead of shipping.
#
# The rule, stated once:
#
#   Keep the row's own head noun — the concrete thing its old name was naming ("Lineage", "Seed",
#   "Crest") — and qualify it with the two facts that identify the row and nothing else: the
#   ORDINAL of its own `slot` and the word its own `scopeKey`/`speciesId` carries.
#
# Why that satisfies `naming.v1.json`'s grammar (`NamingCheck`'s own regexes):
#
#   * `<Ordinal> <Base>` and `<Base> of the <Ordinal> <Scope>` are both legal shapes for a pool-exempt
#     kind such as `material` (words.v1.json `poolAccess.kindsExemptFromPools`: "material — ten of its
#     ids ship already and are consumed by live code; the vocabulary is fixed, not drawn"), and every
#     row is additionally checked against `CandidateNameDefects` — the authority's own patterns — so
#     the claim is measured, not argued.
#   * for a kind that DOES follow the patterns (`set`), the ladder starts at
#     `<Base> of the <Species>`: `OfConstruct = ^Word of (?:the )?Word(?: Word)?$`, which a
#     two-token species key satisfies (`Extract Ten`) and which is NOT `GeneratedOnly`
#     (`^Word Word of …`, which needs TWO words before `of`).
#   * no apostrophe, no lowercase word other than `of`/`the`, no plural head noun, and no bare
#     single-word fusion — all four are the shapes `CandidateNameDefects` refuses, and none of them
#     is reachable from an ordinal word, a `scopeKey`/`speciesId` token or the row's own head noun.
#
# The ladder is walked in order and the first candidate whose AUTHORITATIVE key is free wins, so the
# result is a pure function of (corpus, row fields) — the same input always yields the same 84 names,
# which is the whole point: a repair that cannot be reproduced cannot be reviewed.

#: `slot` is the trophy's position in its own family, and the corpus already speaks in ordinals for
#: it ("The Seventh Lineage", "The Third Seedling", "Seventh Lineage Seal"), so the derived qualifier
#: is corpus vocabulary rather than an invention. Ordinals only — the corpus also uses a noun form
#: ("Second Bulb"), and picking one per row from two forms would make the name depend on a coin flip.
SLOT_ORDINALS: dict[int, str] = {1: "First", 2: "Second", 3: "Third", 4: "Fourth", 5: "Fifth",
                                 6: "Sixth", 7: "Seventh", 8: "Eighth"}

#: A `scopeKey` that is a plural category rather than one thing ("variants", "hybrids", "carriers").
#: Only reached when the plainer rungs are all taken, and a label is a worse thing to put on an item
#: than a noun is, so it goes last rather than first.
_PLURAL_SCOPE_WORDS = frozenset({"variants", "hybrids", "carriers", "specters", "wraiths"})

#: `of`/`the` are the ONLY lowercase words a name may contain (`naming.v1.json`
#: `pluralsPossessivesConnectives.invatedConnectives`), so they are dropped before a name is built.
_CONNECTIVES = frozenset({"of", "the", "a", "and"})

#: `NamingCheck.Word` = `[A-Z][a-z]+(?:-[A-Z]?[a-z]+)*`, i.e. a display word, and NOT `runtimeId`'s
#: own shape (`trophy.family.aquatic.6`, `set.superhypno-001`). A qualified key is the row's own
#: identity; putting it in the middle of a display name ("Maw of the Trophy-Family-Aquatic-6") is an
#: id in a name field, which is the defect the model brief forbids and a reader would read as one.
#: The `runtimeId` is what makes the DERIVATION possible; it is deliberately not what gets PRINTED.
_QUALIFIER_FORBIDDEN_SUBSTRINGS = ("-", ".", "/", ":")


@dataclass(frozen=True)
class DerivedName:
    """One losing row's derived replacement, with the evidence for why it is that name."""
    entry_id: str
    kind: str
    path: Path
    old_name: str
    new_name: str
    #: Which rung of `derived_name_candidates` won, and what own field carried the qualifier.
    rule: str
    old_name_key: str
    new_name_key: str

    def as_answer(self) -> dict[str, str]:
        """The `answers` shape `validate_answers`/`apply` already speak, so both paths share a writer."""
        return {"name": self.new_name}


def _content_words(name: str) -> tuple[str, ...]:
    """The name's own display words, minus the closed connective list, in order."""
    return tuple(word for word in re.findall(r"[A-Za-z][A-Za-z-]*", name)
                 if word.casefold() not in _CONNECTIVES)


def _word_before_of(name: str) -> str:
    """The word immediately before the `of` in an of-construct, or "" when there is none.

    `Spore of the Bloom` -> `Spore`, `Second Seal of Lineage` -> `Seal`. Reading the word BEFORE the
    connective (rather than the first word of the name) is what keeps an ordinal from being mistaken
    for the thing being named.
    """
    head = ""
    for word in re.findall(r"[A-Za-z][A-Za-z-]*", name):
        if word.casefold() == "of":
            return head
        if word.casefold() not in _CONNECTIVES:
            head = word
    return ""


def _title_from_key(key: str) -> str:
    """`vegetation` -> `Vegetation`; `extract_ten` -> `Extract Ten`; a `runtimeId`-shaped key -> "".

    A qualifier the grammar cannot accept is not worth repairing into a different grammar violation,
    so an unusable key returns "" and the ladder simply has one rung fewer to walk.
    """
    parts = [part for part in re.split(r"[^A-Za-z]+", str(key or "")) if part]
    if not parts:
        return ""
    words = [part[:1].upper() + part[1:] for part in parts]
    return " ".join(words) if all(re.fullmatch(r"[A-Z][a-z]+(?:-[A-Z]?[a-z]+)*", w) for w in words) else ""


def _slot_ordinal(row: dict) -> str:
    slot = row.get("slot")
    return SLOT_ORDINALS[slot] if isinstance(slot, int) and not isinstance(slot, bool) else ""


def _head_noun(name: str, *, avoid: str = "") -> str:
    """The name's head noun — the thing it names — with the redundancy rule applied.

    An of-construct's head is the word before its `of` ("Spore of the Bloom" is a spore, "Second Seal
    of Lineage" is a seal), a compound's is its last word ("Cherry Burst" is a burst), and a
    possessive's is the word after the apostrophe ("Sovereign's Fourth Crest" is a crest — the
    apostrophe is not even a content word here). When that word is already inside the qualifier the
    row is being named after, the other noun is the one that still says something
    (`Cabbage of the Mortar` + `ultimatecabbagecannon` -> `Mortar`, not `Cabbage of the
    Ultimatecabbagecannon`).
    """
    words = _content_words(name)
    if not words:
        return ""
    head = _word_before_of(name) or words[-1]
    if avoid and head.casefold() in avoid.casefold():
        for word in words:
            if word.casefold() not in avoid.casefold():
                return word
    return head


def derived_name_candidates(entry: dict, kind: str) -> list[tuple[str, str]]:
    """`(name, rule)` rungs for one row, in strict preference order. A pure function of the row.

    Material rungs keep the row's head noun and qualify it with its own slot ordinal and its own
    `scopeKey`; set rungs keep the head noun and qualify it with its own `speciesId`, because a set's
    theme IS its creature and `<Base> of the <Species>` is the of-construct the grammar already
    allows. Nothing here reads another row, the registry, or a model.
    """
    old = str(entry.get("name") or "").strip()
    rows: list[tuple[str, str]] = []
    if kind == "material":
        scope_key = entry.get("scopeKey") or _runtime_qualifier(entry.get("runtimeId"))
        qualifier = _title_from_key(scope_key)
        ordinal = _slot_ordinal(entry)
        head = _head_noun(old)
        plain = bool(qualifier) and not _is_plural_category(qualifier)
        # Readability first, then strength: the ordinal alone reads best ("Fifth Lineage") and is the
        # shape this corpus already uses for a family's trophies; the of-construct carries BOTH own
        # facts and is the shape this corpus already uses when the ordinal alone cannot tell two rows
        # apart ("Lineage of the Sixth"); a single qualifier alone is next; the row's own tags only
        # after that, and its class last.
        if ordinal:
            rows.append((f"{ordinal} {head}", f"slot ordinal only: {ordinal}"))
        if qualifier and ordinal:
            rows.append((f"{head} of the {ordinal} {qualifier}",
                         f"of-construct: slot ordinal + scopeKey: {ordinal} {qualifier}"))
        if plain:
            rows.append((f"{qualifier} {head}", f"scopeKey only: {qualifier}"))
        for tag in _own_tag_words(entry):
            rows.append((f"{tag} {head}", f"own tag: {tag}"))
            if ordinal:
                rows.append((f"{head} of the {ordinal} {tag}",
                             f"of-construct: slot ordinal + own tag: {ordinal} {tag}"))
        if ordinal:
            rows.append((f"{head} of the {ordinal}", f"of-construct: slot ordinal only: {ordinal}"))
        if qualifier:
            rows.append((f"{head} of the {qualifier}", f"of-construct: scopeKey only: {qualifier}"))
        if qualifier and _is_plural_category(qualifier):
            # A plural `scopeKey` is demoted out of the BARE compound rung only: "Variants Seal"
            # puts a category label where a noun belongs. It still qualifies inside an of-construct
            # ("Seal of the Third Variants"), which reads as a category being counted rather than
            # worn, and that is the shape the ladder reaches first anyway.
            rows.append((f"{qualifier} {head}", f"scopeKey only (plural category): {qualifier}"))
            if ordinal:
                rows.append((f"{ordinal} {qualifier} {head}",
                             f"slot ordinal + scopeKey (plural category): {ordinal} {qualifier}"))
        # The row's own class last: "Trophy Lineage" is thin, but a thin legal name beats a
        # collision, and it is reached only when every richer qualifier was already taken.
        if entry.get("materialClass"):
            rows.append((f"{_title_from_key(str(entry['materialClass']))} {head}",
                         f"materialClass: {entry['materialClass']}"))
    elif kind == "set":
        species = entry.get("speciesId") or _runtime_qualifier(entry.get("themeKey"))
        qualifier = _title_from_key(species)
        head = _head_noun(old, avoid=qualifier)
        if qualifier:
            rows.append((f"{head} of the {qualifier}", f"of-construct: speciesId: {qualifier}"))
            rows.append((f"{head} of {qualifier}", f"of-construct: speciesId (no article): {qualifier}"))
            if " " not in qualifier:
                rows.append((f"{qualifier} {head}", f"compound: speciesId: {qualifier}"))
        if entry.get("setClass"):
            klass = _title_from_key(str(entry["setClass"]))
            if klass and qualifier:
                rows.append((f"{head} of the {qualifier} {klass}",
                             f"of-construct: speciesId + setClass: {qualifier} {klass}"))
    else:
        # Any other kind gets the two grammar-legal shapes built from its own distinguishing fields,
        # so the path stays usable when a new colliding population ships.
        qualifier = _title_from_key(str(entry.get("runtimeId") or entry.get("themeKey") or ""))
        head = _head_noun(old, avoid=qualifier)
        ordinal = _slot_ordinal(entry)
        if qualifier and ordinal:
            rows.append((f"{head} of the {ordinal} {qualifier}", f"of-construct: slot ordinal + key: {ordinal} {qualifier}"))
        if qualifier:
            rows.append((f"{head} of the {qualifier}", f"of-construct: own key: {qualifier}"))
        if ordinal:
            rows.append((f"{ordinal} {head}", f"slot ordinal only: {ordinal}"))
    return [(name, rule) for name, rule in rows if _acceptable_candidate(name) and name != old]


def _own_tag_words(entry: dict) -> tuple[str, ...]:
    """The row's own `tags`, in the order the corpus stores them (sorted, deduplicated).

    A tag is a property the row already declares about itself, so it is the row's own data in the
    strictest sense; the sort is what makes it reproducible when two tags both qualify.
    """
    tags = entry.get("tags")
    if not isinstance(tags, list):
        return ()
    words = {word for tag in tags if isinstance(tag, str)
             for word in [_title_from_key(tag)] if word}
    return tuple(sorted(words))


def _is_plural_category(qualifier: str) -> bool:
    """True when the qualifier names a CATEGORY of things rather than one thing."""
    first = qualifier.split(" ")[0].casefold()
    return first in _PLURAL_SCOPE_WORDS or (first.endswith("s") and not first.endswith("ss"))


def _runtime_qualifier(runtime_id: object) -> str:
    """`trophy.family.aquatic.6` -> `aquatic`: the middle token of a dotted runtimeId.

    `runtimeId` is unique by construction (`trophy.family.aquatic.5` vs `.6`), which is exactly what
    makes a derivation possible; its trailing sequence is dropped because a name carrying a number is
    a mechanic label, not a thing.
    """
    parts = [part for part in re.split(r"[^A-Za-z]+", str(runtime_id or "")) if part]
    return parts[1] if len(parts) >= 2 else ""


def _acceptable_candidate(name: str) -> bool:
    """The shapes `CandidateNameDefects` refuses, checked before the authority is asked.

    Cheaper than a `--check-names` round trip and it never lets a rung that is malformed by
    construction reach the write. The authority still checks every candidate that survives this.
    """
    if not name or name != name.strip():
        return False
    if "'" in name:
        return False
    if any(char in name for char in _QUALIFIER_FORBIDDEN_SUBSTRINGS):
        return False
    for word in re.findall(r"(?<![-\w])[a-z]+(?![-\w])", name):
        if word not in ("of", "the"):
            return False
    words = _content_words(name)
    # A single word is read as a fusion and must decompose into exactly two pool words; a derived
    # name is never one, so a one-word candidate is refused here rather than at the write.
    return len(words) >= 2


def _entry_index(root: Path) -> dict[str, tuple[Path, str, dict]]:
    """Every real entry under `root` as `id -> (path, kind, row)`. Skips registries, exemplars, runs."""
    index: dict[str, tuple[Path, str, dict]] = {}
    for path in sorted(root.glob("**/*.json")):
        if path.name.startswith("_") or "_exemplars" in path.parts or "_runs" in path.parts:
            continue
        document = _load(path)
        if document is None:
            continue
        kind = str(document.get("kind") or "")
        for row in document.get("entries") or ():
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                index[row["id"]] = (path, kind, row)
    return index


def derive_names(repairs: "tuple[NameRepair, ...] | list[NameRepair]", *,
                 items_root: Path | None = None, kind: str = "",
                 key_of: "Callable[[list[str]], dict[str, str]] | None" = None,
                 defects_of: "Callable[[list[str]], dict[str, list[str]]] | None" = None
                 ) -> tuple[DerivedName, ...]:
    """Every planned losing row's replacement, derived from the row's own fields. No model.

    Uniqueness is decided by the AUTHORITY (`validator_keys`), never by a Python copy of the
    normalizer: every candidate name and every still-current corpus name goes through
    `--normalize-names` in one batch, and a rung whose key is already spoken for is skipped. A row
    whose whole ladder is taken RAISES rather than writing a name that collides — a refusal naming the
    row is the only honest answer there.
    """
    root = Path(items_root or ITEM_SEED_ROOT)
    rows = [r for r in repairs if not kind or r.kind == kind]
    index = _entry_index(root)
    resolve_keys = key_of or (lambda names: validator_keys(names, items_root=root))
    resolve_defects = defects_of or (lambda names: name_defects(names, items_root=root))

    # Names still taken once the losing rows' OWN names go away: every other row's name, and
    # therefore the keeper's (a keeper is never renamed, so its key stays reserved). Keys come from
    # the authority, never from a Python mirror of the normalizer.
    renaming = {r.entry_id for r in rows}
    taken_names = sorted({str(row.get("name")).strip() for entry_id, (_p, _k, row) in index.items()
                          if entry_id not in renaming and isinstance(row.get("name"), str)
                          and str(row.get("name")).strip()})

    ladders: list[tuple[NameRepair, Path, str, dict, list[tuple[str, str]]]] = []
    for repair in sorted(rows, key=lambda r: r.entry_id):
        located = index.get(repair.entry_id)
        if located is None:
            raise RuntimeError(f"{repair.entry_id}: planned for repair but not found under {root}")
        path, row_kind, row = located
        ladders.append((repair, path, row_kind, row, derived_name_candidates(row, row_kind)))
    if not ladders:
        return ()

    wanted = sorted({name for *_rest, ladder in ladders for name, _rule in ladder}
                    | {str(row.get("name")).strip() for _r, _p, _k, row, _l in ladders
                       if isinstance(row.get("name"), str)}
                    | set(taken_names))
    keys = resolve_keys(wanted)
    taken_keys = {keys[name] for name in taken_names if keys.get(name)}

    derived: list[DerivedName] = []
    for repair, path, row_kind, row, ladder in ladders:
        old = str(row.get("name") or "").strip()
        old_key = keys.get(old, "")
        chosen: tuple[str, str, str] | None = None
        refusals: list[str] = []
        for candidate, rule in ladder:
            key = keys.get(candidate, "")
            if not key:
                refusals.append(f"{candidate!r} normalizes to an empty key")
            elif key == old_key:
                refusals.append(f"{candidate!r} is the old name's own idea")
            elif key in taken_keys:
                refusals.append(f"{candidate!r} reuses key {key!r}")
            else:
                chosen = (candidate, rule, key)
                break
        if chosen is None:
            raise RuntimeError(
                f"{repair.entry_id}: every derived candidate is taken under the authority's own "
                f"normalizer ({'; '.join(refusals) or 'the row carries no usable own field'}); "
                f"refusing to write a colliding name")
        name, rule, key = chosen
        derived.append(DerivedName(
            entry_id=repair.entry_id, kind=row_kind, path=path, old_name=old, new_name=name,
            rule=rule, old_name_key=old_key, new_name_key=key))
        taken_keys.add(key)

    # The authority's own grammar on the names actually chosen. A derived name that trades a
    # collision for a malformed answer is a worse defect, so this is a refusal, not a warning.
    defects = resolve_defects([entry.new_name for entry in derived])
    broken = {name: found for name, found in defects.items() if found}
    if broken:
        raise RuntimeError(f"derived names rejected by the authority's own grammar: {broken}")
    return tuple(derived)


def apply_derived(derived: "tuple[DerivedName, ...] | list[DerivedName]", *, write: bool,
                  items_root: Path | None = None) -> tuple[tuple[Path, dict[str, dict]], ...]:
    """Write the derived names, touching ONLY `name` and a `nameKey` that is provably the name's slug.

    ⛔ `nameKey` is deliberately NOT re-derived unconditionally, the way the model path's `apply`
    does. A `material` row's key is derived from its `runtimeId`, not its name
    (`material.trophy-family-aquatic-6` beside the name `Abyssal Sediment`), and its `iconKey` is
    `icon.<nameKey>`; re-deriving the key from a renamed display string would repoint the icon at an
    identity the row no longer has and would break the runtimeId convention 3,633 material rows
    follow. So a key moves only when it is EXACTLY the slug of the row's own old name — proven, not
    assumed — and `iconKey` moves with it only when it is exactly `icon.<that key>`. Every other
    field is written back byte-identical, which is what makes the diff reviewable.
    """
    root = Path(items_root or ITEM_SEED_ROOT)
    by_path: dict[Path, list[DerivedName]] = {}
    for entry in derived:
        by_path.setdefault(entry.path, []).append(entry)
    changed: list[tuple[Path, dict[str, dict]]] = []
    for path, entries in by_path.items():
        document = _load(path)
        if document is None:
            raise RuntimeError(f"{path}: unreadable while applying derived names")
        kind = str(document.get("kind") or "")
        touched: dict[str, dict] = {}
        for row in document.get("entries") or ():
            if not isinstance(row, dict):
                continue
            for entry in entries:
                if row.get("id") != entry.entry_id:
                    continue
                fields: dict[str, Any] = {"name": entry.new_name}
                row["name"] = entry.new_name
                old_name, old_key = entry.old_name, str(row.get("nameKey") or "")
                if kind == "combination":
                    # A combination's key is PLANNED from its grid cell, never from the display name
                    # (`apply`'s own note; `fae533a519` finding 1). Leave it.
                    pass
                else:
                    try:
                        pure = derive_name_key(kind, old_name) == old_key
                    except NameKeyUnsluggable:
                        pure = False
                    if pure:
                        row["nameKey"] = derive_name_key(kind, entry.new_name)
                        fields["nameKey"] = row["nameKey"]
                        if row.get("iconKey") == f"icon.{old_key}":
                            row["iconKey"] = f"icon.{row['nameKey']}"
                            fields["iconKey"] = row["iconKey"]
                touched[row["id"]] = fields
        changed.append((path, touched))
        if write:
            _atomic_json(path, document)
    return tuple(changed)


def repair_names_deterministically(*, items_root: Path | None = None, kind: str = "",
                                   write: bool = False,
                                   groups: "list[dict] | None" = None
                                   ) -> dict[str, Any]:
    """Plan -> derive -> apply, with no model and no endpoint anywhere in the path.

    Returns the derived table (entry id, old name, new name, which rung won) so a reviewer can read
    every rename before it lands, plus the paths written. `write=False` is the default: a repair that
    changes 84 shipped rows should be read before it is believed.
    """
    root = Path(items_root or ITEM_SEED_ROOT)
    repairs = plan(root, groups=groups)
    if kind:
        repairs = tuple(r for r in repairs if r.kind == kind)
    derived = derive_names(repairs, items_root=root, kind=kind)
    changed = apply_derived(derived, write=write, items_root=root)
    return {
        "write": bool(write),
        "kind": kind,
        "derived": [{"entryId": d.entry_id, "kind": d.kind, "file": str(d.path),
                     "oldName": d.old_name, "newName": d.new_name, "rule": d.rule,
                     "oldKey": d.old_name_key, "newKey": d.new_name_key} for d in derived],
        "changed": [str(path) for path, _touched in changed],
    }


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
