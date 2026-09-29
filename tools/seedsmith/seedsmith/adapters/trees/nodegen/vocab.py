"""seedsmith.adapters.trees.nodegen.vocab — the affix pick vocabulary, COUNTED fresh (task H1,
spec-tree-language.md §3 rows 11-12, §5.1); `permitted_for_branch` is task H3's own addition.

⛔ Same standing rule `items/setgen/vocab.py` states for its own vocabulary: **never derive a
design proportion from a snapshot of a generated corpus — count it, or don't quote it.** D22 (§3):
"Every effect is an affix from the shipped catalog. No passive-specific effect vocabulary exists in
this module" — so this module reads the SAME `gk-data/packs/fusion/data/seed/items/affix-families/*.json` the item
program already ships, rather than authoring a tree-specific effect library.

Counted 2026-09-12 (§3 row 11-12, §5.1): **125 families**, **seven** distinct `tags` values —
`offensive` 58, `defensive` 47, `utility` 19, `sturdy` 5, `arcane` 4, `mechanical` 3, `metal` 2
(112 families carry one tag, 13 carry more than one). Only the first three are branch-shaped; the
other four are category tags, which is the honest finding §5.1 records: the tag vocabulary is not
enough to key an exclusion predicate on by itself, which is why `exclusion.py` keys on the plan's own
`propertyVocabulary` instead of these tags.

⭐ Re-counted 2026-09-22: still **125 families** and **seven** tags, but `utility` is **17** and the
single-tag/multi-tag split is **114/11** — the tag-axis exclusivity repair (`e1d9103ee`, 2026-09-20)
took the tag off two `g-evade.json` entries that also carried a same-axis tag. Both readings are
readings: a per-tag count moves whenever the corpus does, which is why `tests/adapters/trees/
test_nodegen_vocab.py` now asserts the contract (closed tag vocabulary, at least one tag per family,
the generators' own exclusivity rule, both branches non-empty) instead of these numbers.

**`permitted_for_branch` is the narrowest cut this stage can honestly make today.** A node's
`QuotaCell` (`quota.py`, task H3) allocates a `trigger`/`element`/`status`/`channelFamily` — the
full §4.2 design narrows `affixIds`'s own enum to the affixes whose OWN bound atoms match that
cell on every axis. That cross-reference needs a per-affix atom-tag registry which does not exist
yet (§5.1's own "Blocked on other work" finding: "until [it] lands... a predicate can key on
`posture` and nothing else" — the same blocker, one level up, on affix selection rather than
exclusion). `permitted_for_branch` uses the ONE real, unblocked signal this vocabulary carries
today — `offensive`/`defensive`/`utility` tags, matched against the node's own branch — so the
brief's `affixIds` enum is never empty while the finer six-axis cut waits on that registry. This is
named here as a wiring gap, not an architectural wall (`AGENTS.md`'s own rule): the day the
registry lands, this function's body is the one place that gets narrower, its signature unchanged.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[6]
AFFIX_FAMILY_DIR = REPO_ROOT / "data" / "seed" / "items" / "affix-families"


class AffixVocabularyError(ValueError):
    """The affix corpus is structurally unusable — refused, never silently narrowed."""


@dataclass(frozen=True)
class AffixOption:
    """One `affixIds` choice a node's brief may offer. `one_line` is the brief's own no-numbers
    identity line — the affix's shipped `name`, never its `displayTemplate` (that field embeds a
    `{value}%`-shaped magnitude placeholder, which has no business in a schema-adjacent brief).
    `op` is the family's own authored op (may be empty): structural ops are excluded from
    `permitted_for_branch` by the ladder principle (EX-1), never offered to the picker.
    `resolvable` is computed by `build()` from the generated atom rows, never defaulted by a
    caller: True means at least one emitted row carries a concrete string channel (the binder
    prices and checks it downstream — permitted is not-doomed, never guaranteed) or a
    `status.apply` row with a status (carried as StatusAtoms). Default True exists for synthetic
    test options only."""

    affix_id: str
    name: str
    tags: "tuple[str, ...]"
    kind_id: str
    op: str = ""
    resolvable: bool = True

    @property
    def one_line(self) -> str:
        return f"{self.affix_id} — {self.name}"


@dataclass(frozen=True)
class AffixVocabulary:
    options: "tuple[AffixOption, ...]"

    @property
    def count(self) -> int:
        return len(self.options)

    def ids(self) -> "tuple[str, ...]":
        return tuple(o.affix_id for o in self.options)

    def by_tag(self, tag: str) -> "tuple[AffixOption, ...]":
        return tuple(o for o in self.options if tag in o.tags)

    def tag_counts(self) -> "dict[str, int]":
        counts: "dict[str, int]" = {}
        for o in self.options:
            for t in o.tags:
                counts[t] = counts.get(t, 0) + 1
        return counts

    def get(self, affix_id: str) -> AffixOption:
        for o in self.options:
            if o.affix_id == affix_id:
                return o
        raise AffixVocabularyError(f"unknown affix id {affix_id!r} — not in the loaded corpus")

    def permitted_for_branch(self, branch: str) -> "tuple[AffixOption, ...]":
        """§4.2 step 6's affix-side cut, at the ONE granularity today's tag vocabulary supports:
        `branch`'s own tag (`offensive` or `defensive`) plus `utility` (fits either branch) —
        never the finer six-axis `QuotaCell` cut, which needs the not-yet-built atom-tag registry
        (this module's own docstring). Held, never widened, if nothing matches: an empty result
        means the corpus has no affix tagged for this branch at all, which is a vocabulary defect
        to surface, not paper over with the whole 125-family list.
        EX-1 (ladder principle, passive-tree-repair): structural ops (`Replace`/`Flag`) are
        excluded — they substitute a constant where the power ladder requires f(Theta)
        (ssot-power-scale.md sections 2/5.1, PS-3), so no tree node may offer them. Re-authoring
        one as Flat re-admits it here with no code change (the filter reads the authored op).
        P5.1 (same program): only binder-resolvable families are offered — `resolvable`, computed
        by `build()` from the generated atom rows. A family with no emitted row, a pool-dict
        channel row only, or a bare stem row only cannot bind today (P4.1 refuse stands; pools
        await effect-pipeline module 2), so offering it manufactures a refusal. Permitted is
        not-doomed, never guaranteed: the binder's own checks (registration, anchor, coeff)
        still refuse honestly downstream."""
        if branch not in ("offensive", "defensive"):
            raise ValueError(f"permitted_for_branch: branch must be 'offensive' or 'defensive', "
                             f"got {branch!r}")
        return tuple(o for o in self.options
                     if (branch in o.tags or "utility" in o.tags)
                     and o.op not in ("Replace", "Flag")
                     and o.resolvable)


def load_affix_families(directory: "Path | None" = None) -> "list[dict]":
    """Every shipped affix-family entry, read fresh. Mirrors
    `items/setgen/vocab.py:load_families` exactly — same directory, same `kind` filter — because
    this is the SAME corpus, not a tree-specific copy of it."""
    entries: "list[dict]" = []
    for path in sorted((directory or AFFIX_FAMILY_DIR).glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("kind") != "affix-family":
            continue
        entries.extend(doc.get("entries", []))
    return entries


def load_generated_rows(generated_dir: "Path | None" = None) -> "dict[str, list[dict]]":
    """Emitted atom rows by family id, read fresh from `gk-data/packs/fusion/data/seed/atoms/generated/`. The P5.1
    resolvability ground truth: only families with at least one bindable row may be offered."""
    from pathlib import Path as _Path

    root = generated_dir or (AFFIX_FAMILY_DIR.parent.parent / "atoms" / "generated")
    rows: "dict[str, list[dict]]" = {}
    for path in sorted(root.glob("family-expand.*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for entry in doc.get("entries", []):
            rows.setdefault(str(entry.get("family", "")), []).append(entry)
    return rows


def _tuning_bases() -> "set[str]":
    """Channels E43's Flat path can price: v3 pins + the v2/shipped-curve channels
    (atk/defense/maxHp/hp) + channel-policy referenceMs. Read fresh from the tuning files —
    the same ground truth the generator reads, never restated here."""
    bases = {"atk", "defense", "maxHp", "hp"}
    seed = AFFIX_FAMILY_DIR.parent.parent  # .../data/seed
    v3 = seed.parent / "tuning" / "power-scale.v3.json"  # .../data/tuning
    if v3.exists():
        bases.update(json.loads(v3.read_text(encoding="utf-8")).get("channels", {}).keys())
    policy = seed / "channel-policy" / "defaults.json"
    if policy.exists():
        doc = json.loads(policy.read_text(encoding="utf-8"))
        bases.update(e["channel"] for e in doc.get("entries", []) if "referenceMs" in e)
    return bases


def is_resolvable(family_id: str, rows: "list[dict]", bases: "set[str] | None" = None) -> bool:
    """True when at least one emitted row binds today (P5.1). Precise per-op rules: a
    `{variant}`-templated channel always maps to a pool ref at emission (P4.1 refuse stands)
    no matter the op; bare `''`/bare-status stems are guard-refused; `status.apply` with a
    status binds as StatusAtoms (MC-1); Increased/More on a concrete channel use the identity
    ratio (no base needed); Flat needs a priced base (v3/v2/policy). Permitted is not-doomed,
    never guaranteed: registration/anchor/coeff checks still refuse honestly downstream."""
    return exclusion_reason(family_id, rows, bases) is None


def exclusion_reason(
    family_id: str, rows: "list[dict]", bases: "set[str] | None" = None
) -> "str | None":
    """P5.2: WHY a family is not offered, as data — None means resolvable. The residue's
    machine-readable classification (every unresolvable family id carries one of these
    closed reasons; an unclassified family is the defect this function exists to catch):
    `structural-op` (ladder principle — decided in the family entry, read from its op),
    `no-emitted-rows` (unexpanded: verbs, templates, unauthored), `pool-channels-only`
    (effect-pipeline module 2 territory), `bare-stem-only` (content gap: `''`/bare-status
    channels, no concrete channel authored), `unbased-channel` (concrete channel no program
    has priced — pierce/overflow unregistered per P3.3, zombieSpeed battle-tempo's: the
    refusal names the tuning gap, and the owning program is named in the residue consumer,
    never guessed here). Priority on mixed rows: pool dominates bare (module-2 territory is
    the deeper program)."""
    if not rows:
        return "no-emitted-rows"
    if bases is None:
        bases = _tuning_bases()
    saw_pool = False
    saw_bare = False
    saw_unbased = False
    for row in rows:
        if row.get("kind") == "status.apply":
            if (row.get("params") or {}).get("status"):
                return None
            continue
        channel = (row.get("params") or {}).get("channel")
        op = str((row.get("params") or {}).get("op") or "").lower()
        if not isinstance(channel, str) or not channel or "{" in channel:
            if isinstance(channel, dict) and "pool" in channel:
                saw_pool = True
            else:
                saw_bare = True
            continue
        if op in ("increased", "more"):
            return None
        if op == "flat" and channel in bases:
            return None
        if op == "flat":
            saw_unbased = True
        else:
            saw_bare = True
    if saw_pool:
        return "pool-channels-only"
    if saw_unbased:
        return "unbased-channel"
    if saw_bare:
        return "bare-stem-only"
    return "no-emitted-rows"


def classify_residue(entries: "list[dict]", generated: "dict[str, list[dict]]") -> "dict[str, str]":
    """P5.2: every unresolvable family id mapped to its closed exclusion reason — the residue
    classification as data, not prose. Structural-op comes from the entry's own op (ladder
    principle); the rest from the emitted rows. A family id with no reason is a taxonomy hole
    (the test below fails naming it); a resolvable family never appears here."""
    residue: "dict[str, str]" = {}
    for entry in entries:
        fid = entry["id"]
        op = str((entry.get("params") or {}).get("op") or "")
        if op in ("Replace", "Flag"):
            residue[fid] = "structural-op"
            continue
        reason = exclusion_reason(fid, generated.get(fid, []))
        if reason is not None:
            residue[fid] = reason
    return residue


def build(directory: "Path | None" = None) -> AffixVocabulary:
    generated = load_generated_rows()
    if not generated:
        raise AffixVocabularyError(
            "no generated atom rows under data/seed/atoms/generated — resolvability "
            "cannot be computed; held, never defaulted to all-resolvable")
    bases = _tuning_bases()
    options = tuple(
        AffixOption(
            affix_id=entry["id"],
            name=str(entry["name"]),
            tags=tuple(entry.get("tags") or ()),
            kind_id=str(entry["kindId"]),
            op=str((entry.get("params") or {}).get("op") or ""),
            resolvable=is_resolvable(entry["id"], generated.get(entry["id"], []), bases),
        )
        for entry in load_affix_families(directory)
    )
    if not options:
        raise AffixVocabularyError(
            f"no affix-family entries found under {(directory or AFFIX_FAMILY_DIR)} — "
            f"held, never widened to an empty-but-legal vocabulary")
    return AffixVocabulary(options=options)
