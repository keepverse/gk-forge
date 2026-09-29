"""seedsmith.adapters.items.setgen.seedfile — a priced draft becomes a seed row, and the row goes
somewhere it was asked to go.

⛔ **The output directory is never defaulted.** A generator whose write target has a default writes
into the shipped corpus the first time someone forgets a flag, and the shipped corpus is what every
metric baseline in this program is measured against. `resolve_out_dir` refuses the two production
kind directories unless the caller says so in as many words.

⚠ **Two shapes, read off the corpus rather than invented.** A threshold's element-generated pick is
written `{"family": …, "powerBand": …, "params": {"element": …}}` — measured on
`set.frostbitten-vanguard-002` and `charm.off-ctrl-015`, both shipped — never as a `variant` key,
which is the generator's own internal spelling and appears nowhere in the corpus.

⚠ **Member identity is resolved by lookup, never by the model.** The model chooses a `(role, frame)`
pair; this module selects one existing base-type id from that pair's closed corpus vocabulary. It
never invents an item id or copies a unique's base type.

⛔ **Corrected 2026-09-09.** The previous implementation stopped after emitting the pair and left
the lookup unwired, even though the module's own emit table already assigned that lookup to this
stage. The resolver below closes that stale-code gap without asking the model to invent identity.

The row carries both the pair the model chose and the concrete id selected by the deterministic
lookup. A missing pair is a hard refusal before the file is written.
"""
from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import topology as topology_mod
from .distribute import SetPlan
from .topology import SetTopologyTuning
from .vocab import FamilyPick, Vocabulary
from ..charmgen.rules import CharmPlan

REPO_ROOT = Path(__file__).resolve().parents[6]
NAMING_REGISTRY = REPO_ROOT / "data" / "seed" / "items" / "_registry" / "naming.v1.json"
ITEM_SEED_ROOT = REPO_ROOT / "data" / "seed" / "items"

#: The two directories a generated set / charm eventually ships in. Writing here is the production
#: run; everything else is a sample, and the two must never be confusable on disk.
PRODUCTION_KIND_DIRS: "dict[str, Path]" = {
    "set": ITEM_SEED_ROOT / "sets",
    "charm": ITEM_SEED_ROOT / "charms",
}


class OutDirRefused(ValueError):
    """The requested write target is the shipped corpus and the caller did not say so."""


class NameKeyUnsluggable(ValueError):
    """A display name produced no ASCII slug, so no legal `nameKey` can be derived from it.

    ⛔ 2026-09-12: `_slugify` used to fall back to the literal `"item"`, which turned every
    non-Latin name into the SAME key — six shipped sets (Chinese display names, `set.item`) proved
    it: `^[a-z0-9.-]+$` is satisfied, uniqueness is silently destroyed, and a whole-corpus
    NameKeyDuplicate finding is the only visible symptom. A name the grammar cannot slug is a
    content defect, so it is refused by name rather than masked with a placeholder key. The
    registry's own rule (`seed-contract.md` §6) is that the string may be free text but the KEY
    must be `^[a-z0-9.-]+$`; a free-text name therefore still needs an ASCII identity, and this
    class is how the emitter says so."""


_NAME_KEY_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """`name` -> a `[a-z0-9-]+` slug: lowercase, every run of non-alphanumeric characters becomes
    one hyphen, no leading/trailing hyphen. Mirrors `trees.nodegen.run._slugify` exactly (same
    real 2026-09-06 finding that motivated it there: never trust the model to derive its own
    `nameKey` from its own `name` — see `derive_name_key`'s own docstring for this module's own,
    worse incident on the same field).

    Returns `""` for a name with no ASCII alphanumeric content (e.g. a pure-CJK or
    pure-punctuation name). The caller decides whether that is fatal — it is, for a shipped key;
    see `NameKeyUnsluggable`."""
    return _NAME_KEY_SLUG_RE.sub("-", name.strip().lower()).strip("-")


def derive_name_key(kind: str, name: str) -> str:
    """`set.<slug>` / `charm.<slug>` — computed deterministically from the model's own `name`
    choice, never asked of the model itself.

    ⛔ **Real incident, 2026-09-08.** `nameKey` used to be a field the model filled in directly
    (constrained by a `pattern` regex `set_schema`/`charm_schema` sent it). Two independent
    findings converge on removing it from the schema entirely rather than continuing to ask:
    `trees.nodegen`'s own 2026-09-06 finding (`_derive_unique_name_key`'s docstring) — a real local
    model repeatedly fell back to a generic templated key decoupled from its own `name` choice,
    twice, even after a wording fix — and this program's own incident the same day: a quantized
    model (reproduced on two different local models) degenerated into a repeated-token loop inside
    this exact field, burning the full `max_tokens` budget on garbage, with `maxLength`/`pattern`
    both confirmed unenforced by LM Studio's grammar sampler. There is no information `nameKey`
    could carry beyond a mechanical transform of `name`, so it is derived here instead — the
    failure mode does not exist if the field is never generated at all.

    **Scope, named rather than silently assumed:** this does not check the derived key against the
    already-shipped corpus for a collision — `set_entry`/`charm_entry` never did that when the
    model supplied `nameKey` directly either, so this is unchanged collision safety, not a
    regression. A corpus-wide dedup pass is a real, separate feature (`trees.nodegen`'s own
    `_derive_unique_name_key` shows the shape one would take) — out of scope for this fix, which
    exists to close the degenerate-generation incident, not to add a capability this module never
    had.

    ⛔ **2026-09-12:** the empty-slug fallback is gone (see `NameKeyUnsluggable`). A name with no
    ASCII content raises rather than minting the shared placeholder `"item"` key that shipped six
    `set.item` duplicates.
    """
    slug = _slugify(name)
    if not slug:
        raise NameKeyUnsluggable(
            f"name {name!r} produced no ASCII slug, so no legal `{kind}.<slug>` nameKey exists; "
            "the display string may be free text but its key must match ^[a-z0-9.-]+$")
    return f"{kind}.{slug}"


def resolve_out_dir(out_dir: "str | Path", *, allow_production_tree: bool = False) -> Path:
    """Where rows land. Refuses the production kind directories unless explicitly authorised.

    ⚠ Refuses anything under `gk-data/packs/fusion/data/seed/items/` outright when not authorised, not just the two kind
    directories: every metric in this program globs that tree recursively
    (`corpus/model.py`'s `rglob("*.json")`, `ItemSeedValidator`'s `SearchOption.AllDirectories`), so
    a sample dropped anywhere inside it moves finding counts another stream uses as a baseline.
    An underscore prefix does not help — only `_exemplars/` is special-cased, and only there.
    """
    path = Path(out_dir).resolve()
    if allow_production_tree:
        return path
    try:
        path.relative_to(ITEM_SEED_ROOT.resolve())
    except ValueError:
        return path
    raise OutDirRefused(
        f"{path} is inside {ITEM_SEED_ROOT} — every items metric globs that tree recursively, so a "
        f"sample written there changes finding counts other streams baseline against. Write "
        f"outside it, or pass --allow-production-tree if this really is the production run.")


# --------------------------------------------------------------------------------------------
# Resolving what the model named back onto the vocabulary it was offered.
# --------------------------------------------------------------------------------------------

def resolve_pick(picks: "tuple[FamilyPick, ...]", token: str) -> "FamilyPick | None":
    """Map one family string from an answer onto the pick it names.

    ⚠ **Two spellings are accepted because the brief and the schema disagree about which one to
    ask for, and that disagreement is module 13's, not this module's.** `brief._pick_lines` prints
    `pick_id` (`atom.searing-strike.fire`); `schema.set_schema` describes the same field as *"a
    stat.modify / stat.derived family id"* (`atom.searing-strike`). Accepting both here keeps a
    well-meant answer out of the reject pile; the disagreement itself is filed as a defect rather
    than papered over.
    """
    for pick in picks:
        if pick.pick_id == token:
            return pick
    for pick in picks:
        if pick.family == token and pick.variant is None:
            return pick
    return None


def resolve_capability(vocabulary: Vocabulary, node: "dict[str, Any]") -> "FamilyPick | None":
    """`{"family": …, "variant": …}` -> the capability pick, or `None` if it names nothing.

    ⛔ Real incident, 2026-09-08: AFTER the brief-truncation fix (`brief._pick_lines` — the run
    could finally see every pick), a live 53-subject run still escalated on this exact field,
    for a different reason. Every stat/charm family in this whole program is named by copying
    ONE plain string (`resolve_pick`'s own two-spelling tolerance), but `capability` alone asks
    for a split `{family, variant}` object — a shape found nowhere else in the brief the model
    reads. Two live shapes came back wrong because of it: an elemental pick's full printed id
    echoed into BOTH fields (`{"family": "atom.deathblast.fire", "variant":
    "atom.deathblast.fire"}` instead of the split `{"family": "atom.deathblast", "variant":
    "fire"}`), and a flat (variant-less) pick given a placeholder instead of an omitted variant
    (`{"family": "atom.freezing", "variant": "none"}`). Both are legal, unambiguous picks a
    human reading the printed list would recognize instantly, so `family` is tried as a plain
    pick_id FIRST — the same tolerant lookup every stat/charm family already goes through —
    before falling back to the family+variant combination the schema actually documents.
    """
    family = node.get("family")
    if not isinstance(family, str):
        return None
    direct = resolve_pick(vocabulary.capability, family)
    if direct is not None:
        return direct
    variant = node.get("variant")
    if isinstance(variant, str) and variant:
        for pick in vocabulary.capability:
            if pick.family == family and pick.variant == variant:
                return pick
    return None


# --------------------------------------------------------------------------------------------
# Ids.
# --------------------------------------------------------------------------------------------

def axis_group_map(path: "Path | None" = None) -> "dict[str, str]":
    """`axis -> axisGroupId`, read fresh from `naming.v1.json` rather than transcribed.

    The 5-into-3 fold (`offense`/`control` -> `off-ctrl`, `survivability`/`utility` -> `surv-util`,
    `economy` -> `econ`) is the registry's own decision and is exactly the kind of fact
    `registries.py`'s header rule says to read, never copy.
    """
    doc = json.loads((path or NAMING_REGISTRY).read_text(encoding="utf-8"))
    groups = doc["idNamespaces"]["charms"]["axisGroups"]
    return {axis: row["axisGroupId"] for row in groups for axis in row["axes"]}


def next_charm_seq(axis_group_id: str, *, corpus_root: "Path | None" = None) -> int:
    """The first sequence number free in this axis-group partition, measured off the live corpus.

    Ids are never reused (`naming.v1.json`'s own rule), so a generated charm continues the shipped
    partition rather than restarting it. Read, not assumed: the shipped counts move.
    """
    root = corpus_root or (ITEM_SEED_ROOT / "charms")
    pattern = re.compile(rf"^charm\.{re.escape(axis_group_id)}-(\d{{3}})$")
    highest = 0
    if root.exists():
        for file in sorted(root.glob("*.json")):
            doc = json.loads(file.read_text(encoding="utf-8"))
            for entry in doc.get("entries") or []:
                match = pattern.match(str(entry.get("id", "")))
                if match:
                    highest = max(highest, int(match.group(1)))
    return highest + 1


def _base_types_dir(corpus_root: "Path | None") -> Path:
    """Resolve the base-type corpus root used by a set run.

    ``corpus_root`` is primarily a test/sample override. Accept both the item root and the
    repository's ``gk-data/packs/fusion/data/seed`` root so callers cannot accidentally point the resolver at a sibling
    kind and get an empty vocabulary.
    """
    if corpus_root is None:
        return ITEM_SEED_ROOT / "base-types"
    root = Path(corpus_root)
    for candidate in (root / "base-types", root / "items" / "base-types", root):
        if candidate.is_dir() and any(candidate.glob("*.json")):
            return candidate
    return root / "base-types"


def load_base_type_candidates(*, corpus_root: "Path | None" = None,
                              include_unique: bool = False
                              ) -> "dict[tuple[str, str], tuple[str, ...]]":
    """Read the concrete base-type ids available for each ``(frame, role)`` pair.

    The lookup is intentionally built from the live base-type files, not a copied registry list.
    Unique items are excluded because ``ssot-sets.md §3.8`` forbids paying for one base type as
    both a unique and a set piece. Malformed files are not swallowed: a production run must stop
    before writing a set against an unreadable vocabulary.
    """
    directory = _base_types_dir(corpus_root)
    candidates: "dict[tuple[str, str], set[str]]" = {}
    for path in sorted(directory.rglob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("kind") != "base-type":
            continue
        for entry in document.get("entries") or ():
            frame, role, entry_id = entry.get("frame"), entry.get("role"), entry.get("id")
            if all(isinstance(value, str) and value for value in (frame, role, entry_id)):
                candidates.setdefault((frame, role), set()).add(entry_id)

    unique_ids: set[str] = set()
    unique_dir = directory.parent / "uniques"
    if unique_dir.is_dir():
        for path in sorted(unique_dir.rglob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            if document.get("kind") != "unique":
                continue
            for entry in document.get("entries") or ():
                base_type = entry.get("baseType")
                if isinstance(base_type, str) and base_type:
                    unique_ids.add(base_type)

    return {
        key: tuple(sorted(ids if include_unique else ids - unique_ids))
        for key, ids in sorted(candidates.items())
        if (ids if include_unique else ids - unique_ids)
    }


def bind_member_base_types(entry_id: str, members: "list[dict] | tuple[dict, ...]",
                           candidates: "dict[tuple[str, str], tuple[str, ...]]",
                           *, existing_candidates: "dict[tuple[str, str], tuple[str, ...]] | None" = None,
                           ) -> "list[dict]":
    """Bind model-selected member pairs to existing base types deterministically.

    A stable hash spreads independent sets over the available ids while remaining byte-identical
    across runs. Existing bindings are validated and preserved; they are never silently replaced.
    """
    bound: "list[dict]" = []
    for index, member in enumerate(members):
        if not isinstance(member, dict):
            raise ValueError(f"{entry_id}: member {index} is not an object")
        role, frame = member.get("role"), member.get("frame")
        if not isinstance(role, str) or not isinstance(frame, str):
            raise ValueError(f"{entry_id}: member {index} needs string role and frame")
        choices = candidates.get((frame, role), ())
        if not choices:
            raise ValueError(f"{entry_id}: no non-unique base type exists for ({role}, {frame})")
        existing = member.get("baseType")
        if existing is not None:
            valid_existing = isinstance(existing, str) and (existing in choices or (
                existing_candidates is not None and existing in existing_candidates.get((frame, role), ())))
            if not valid_existing:
                raise ValueError(f"{entry_id}: member ({role}, {frame}) names unavailable baseType "
                                 f"{existing!r}")
            chosen = existing
        else:
            digest = hashlib.sha256(f"{entry_id}\0{role}\0{frame}".encode("utf-8")).digest()
            chosen = choices[int.from_bytes(digest[:8], "big") % len(choices)]
        bound.append({"role": role, "frame": frame, "baseType": chosen})
    return bound


# --------------------------------------------------------------------------------------------
# Rows.
# --------------------------------------------------------------------------------------------

def _atom_row(pick: FamilyPick, power_band: str, *, negative: bool = False) -> "dict[str, Any]":
    """One atom row in the corpus's own shape.

    ⚠ `params.sign = "negative"` is how the shipped corpus marks a signet's drawback
    (`charm.econ-019`, read 2026-09-06) — NOT a separate `drawback` field. Emitting the drawback as
    an ordinary fixed atom would turn a cost into a bonus, silently.
    """
    row: "dict[str, Any]" = {"family": pick.family, "powerBand": power_band}
    params: "dict[str, Any]" = {}
    if pick.variant:
        params["element"] = pick.variant
    if negative:
        params["sign"] = "negative"
    if params:
        row["params"] = params
    return row


def set_entry(*, entry_id: str, theme_key: str, draft: "dict[str, Any]", plan: SetPlan,
              base_type_candidates: "dict[tuple[str, str], tuple[str, ...]] | None" = None,
              species_id: "str | None" = None,
              topology_tuning: "SetTopologyTuning | None" = None,
              ) -> "dict[str, Any]":
    """One `set` row. `kinds.py` requires `id`/`nameKey`/`name` plus `themeKey`/`members`/`thresholds`;
    everything else here is in that kind's optional set.

    species-gear-chain T27 (`set-species-binding` a, spec-set-species-binding.md): `speciesId` is a
    JOIN, never a judgement — it is threaded here from the theme's OWN `speciesId` field (already
    lower-case, the runtime catalog's spelling, per Open question 2a), never derived from `name` or
    asked of the model. `species_id=None` (a `build.*`/`theme.*` theme) omits the key entirely —
    explicit absence, distinguishable from a `creature.*` theme that failed to resolve (which the
    caller must refuse rather than reach this function at all, per the spec's own boundary).

    `setClass` **is** emitted here (spec rev 2, the owner's 2026-09-21 ruling): resolved from the
    entry's OWN declared topology — the distinct member roles and the threshold list it just built —
    through `topology.stamp_class`, the same function the backward repair calls. So the class of a
    generated entry is never a second opinion about its shape, and a shape the ladder cannot classify
    raises `SetTopologyError` here rather than shipping an unclassifiable set. `topology_tuning` is
    passable so a batch resolves against one loaded tuning; omitted, it is loaded once per call.
    """
    thresholds: "list[dict[str, Any]]" = []
    for threshold in plan.thresholds:
        row: "dict[str, Any]" = {"pieces": threshold.pieces}
        if threshold.capability is not None:
            row["capability"] = _atom_row(threshold.capability, threshold.power_band)
        else:
            row["atoms"] = [_atom_row(p, threshold.power_band) for p in threshold.stats]
        thresholds.append(row)

    candidates = base_type_candidates if base_type_candidates is not None else load_base_type_candidates()
    members = bind_member_base_types(entry_id, list(draft.get("members") or ()), candidates)

    entry: "dict[str, Any]" = {
        "id": entry_id,
        "nameKey": derive_name_key("set", draft["name"]),
        "name": draft["name"],
        "themeKey": theme_key,
    }
    if species_id:
        entry["speciesId"] = species_id
    entry.update({
        "members": members,
        "thresholds": thresholds,
        "flavor": draft.get("flavor", ""),
        "tags": [],
        "notes": ("Generated from an authored answer against promptVersion set-charm-gen/1. "
                  "Member baseType ids are deterministic lookups over the existing base-type "
                  "corpus; the model supplies only role/frame pairs."),
    })
    topology_mod.stamp_class(entry, topology_tuning or topology_mod.load())
    return entry


def _frame_hint(value: Any) -> str:
    """§3.7's frame_hint vocabulary: any/humanoid/plant. Absent, explicit null, or blank all resolve to
    the author-neutral default `any`; a non-blank value is preserved for the carry gate to judge (an
    out-of-vocabulary string is the gate's refusal to report, not this emitter's to silently rewrite)."""
    if value is None:
        return "any"
    text = str(value).strip()
    return text or "any"


def charm_entry(*, entry_id: str, theme_key: str, draft: "dict[str, Any]", plan: CharmPlan,
                ) -> "dict[str, Any]":
    """One `charm` row. `apCost`, `prefixRolls` and `suffixRolls` come from the CLASS, never from
    the answer — deterministic planning assigns `charmClass` and the tuning file prices it
    (ssot-charms §3.4)."""
    fixed = [_atom_row(pick, pick.power_band or "low") for pick in plan.families]
    row: "dict[str, Any]" = {
        "id": entry_id,
        "nameKey": derive_name_key("charm", draft["name"]),
        "name": draft["name"],
        "charmClass": plan.charm_class,
        "apCost": plan.ap_cost,
        "axis": plan.axis,
        # §3.7's frame_hint has exactly three legal values (any/humanoid/plant). `draft.get(k, "any")`
        # returns the model's EXPLICIT null when it emits `"frameHint": null`, which is not the same as
        # the key being absent -- two shipped charms (charm.econ-028, charm.econ-151) carried a literal
        # null that way. Normalise null/blank to the default rather than let a null reach the corpus.
        "frameHint": _frame_hint(draft.get("frameHint")),
        "fixedAtoms": fixed,
        "prefixRolls": plan.prefix_rolls,
        "suffixRolls": plan.suffix_rolls,
        "tags": [],
        "flavor": draft.get("flavor", ""),
        "notes": f"themeKey: {theme_key}",
    }
    if plan.unique_carry:
        row["uniqueCarry"] = True
    if plan.drawback is not None:
        row["fixedAtoms"] = fixed + [
            _atom_row(plan.drawback, plan.drawback.power_band or "low", negative=True)]
    return row


# --------------------------------------------------------------------------------------------
# Files.
# --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SeedFileMeta:
    """The `_meta` block every shipped seed file carries. The clock is injected for
    `provenance.py`'s stated reason — a timestamp is the one field that would otherwise make a
    generated file non-reproducible."""

    batch: str
    partition: str
    prompt_version: str
    model: str
    authored_utc: str
    source_ref: str
    registry_versions: "dict[str, int]"

    def to_dict(self) -> "dict[str, Any]":
        return {
            "batch": self.batch,
            "partition": self.partition,
            "contractVersion": 1,
            "registryVersions": dict(self.registry_versions),
            "exemplarVersion": 1,
            "promptVersion": self.prompt_version,
            "model": self.model,
            "authoredUtc": self.authored_utc,
            "sourceRef": self.source_ref,
        }


def seed_document(kind: str, entries: "list[dict[str, Any]]", meta: SeedFileMeta) -> "dict[str, Any]":
    return {"schemaVersion": 1, "kind": kind, "_meta": meta.to_dict(), "entries": entries}


def write_seed_file(out_dir: Path, filename: str, document: "dict[str, Any]") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    # ⛔ `newline="\n"` is load-bearing on Windows, 2026-09-28. `Path.write_text` opens in TEXT mode with
    # universal newlines, so every `\n` in the JSON becomes `\r\n` on disk. Measured on the real tree: 61 of
    # 945 set partitions carried CRLF in the WORKING TREE while carrying none in the committed blob - and
    # because `.gitattributes` says `* text=auto eol=lf`, git normalises them away, so `git status` reports
    # them CLEAN. The corruption is therefore invisible to every git-level check and only a test that reads
    # raw bytes can see it, which is what `test_topology_repair::test_written_partitions_are_lf_only` does.
    # `species_repair.py` and `name_repair.py` already pass this; the writers that lacked it are the defect.
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path
