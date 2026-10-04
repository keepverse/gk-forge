"""The rule a family label has to satisfy, and the predicate that decides it.

**THE RULE — "a family label must group something, because it becomes a namespace key."**

A derived family id is not prose. `consolidate.canonical_key` turns an authored label into a
kebab id, and the actions characteristic-pool consumers use that id as an *action namespace key*:
two species in one family share the action namespace. A label that names one thing, or a fragment
of the author's sentence rather than a category, therefore cannot be a namespace key — it is a
private key with a public name. Measured on the committed corpus (904 species,
`gk-data/packs/fusion/data/seed/creatures/species`, re-derived 2026-10-04): **509 distinct family
ids, 277 of them held by exactly one species.**

This module turns that one rule into a decidable, deterministic classification, so the defect can
be stopped where the labels are *authored and derived* rather than scrubbed from an emitted file
afterwards. It is the reusable predicate: `classify_vocabulary` is what
`characteristic_pool/catalog.derive_live_family_assignments` consults before it returns an
assignment, and `census` is what reports the per-class counts.

**The five classes.** The class is the *reason* a family id failed the rule; it is not a severity
ranking, and D/E are not defects.

| Class | Name | Decidable test |
|---|---|---|
| **A** | `placeholder` | every authored label feeding the id carries a fill-in token (`placeholder`, `unnamed`, …) |
| **B** | `identity_echo` | the id is a fragment of the species' own identity — a name-initial, or a token-run of the `speciesId` — and holds one species |
| **C** | `walk_back_artefact` | `head_noun` reached the id by skipping a generic suffix, and the id holds one species |
| **D** | `singleton_role_tag` | holds one species and is none of the above: a real-looking category word with no second member *yet* |
| **E** | `legitimate` | holds two or more species and is none of A–C |

**A, B and C are rejected.** D is deliberately NOT rejected: a singleton like `bamboo` (from
`bamboo-shooter`) or `cattail` is a real category that is merely under-populated, which is a
content decision for the corpus, not a labelling defect, and silently deleting it would destroy a
category the next species belongs to.

**Class C is an upper bound, and this is deliberate.** It is *not* an exact partition of "the head
noun is a participle". That narrower test was measured and rejected: an English-morphology test on
the derived id flags `plant` (391 species), `ranged` (23), `gatling`, `weed`, `seaweed`, `reed`,
`spikeweed`, `artillery`, `economy` and 30-odd other real families, so it is a broken detector and
this module will not ship one. C therefore rejects every *forced walk-back that groups nothing*,
which is a superset of the true parse fragments (`headed` from `two-headed-shooter`, `armour` from
`stacked-armour-shooter`) and also takes the under-populated walk-backs (`bamboo`, `flying`,
`homing`, `coin`). Every one of those groups nothing, so the rule rejects them for the same
reason; the class name describes the common *shape*, not a verified part of speech. A caller that
needs the exact linguistic judgement has to supply a lexicon, and this module deliberately does
not fake one.

**Class B reads only the `speciesId`.** It once also read the species file stem, which looks like
the name — and is in fact the slugified *first family label* the pipeline itself wrote
(`Runner._family_for` → `_slugify_family`, measured: **904 of 904** species files are named
`slug(first family label)`, zero exceptions). Testing "is this label part of the species' name"
against the stem therefore compares the pipeline's output with itself and reports an echo for
almost every first label. `speciesId` is the one identity string the corpus carries independently
of what the family pipeline decided.

**No model call, no network, no file IO.** Same inputs -> same classification, always: the class of
a family id is a pure function of the candidate set, so `consolidate` over unchanged candidates is
unchanged. See `docs/architecture/validation-ssot.md` §1 — this module's tests assert the shape of
the partition and its invariants, never a count, because the corpus grows whenever a species ships.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from seedsmith.ladders import normalize_family_key

from .consolidate import (
    FamilyCandidateInput,
    consolidate,
    head_noun,
    load_synonyms,
    normalize,
)

__all__ = [
    "PLACEHOLDER_TOKENS",
    "FALLBACK_FIELD",
    "CLASS_A", "CLASS_B", "CLASS_C", "CLASS_D", "CLASS_E",
    "CLASS_NAMES",
    "REJECTED_CLASSES",
    "FamilyLabelVerdict",
    "DerivationReport",
    "camel_tokens",
    "is_placeholder_label",
    "identity_echo_of",
    "walk_back_head",
    "classify_family",
    "classify_vocabulary",
    "census",
    "rejected_labels",
    "fallback_family",
    "iter_family_labels",
    "derive_vetted_assignments",
]

# =================================================================================================
# Class A — placeholder-derived
# =================================================================================================
#
# A fill-in token standing in for content the author did not have. The corpus's own seed for this:
# `gk-data/.../species/unnamed-plant.json` is a species whose display name was never captured, so
# `prompts._lore_block` renders `Name: (unnamed)` into the identity brief (prompts.py:43) and the
# identity pipeline answered with `["unnamed plant", "placeholder entry"]`. `unnamed plant` reduces
# to the corpus's largest real family (`plant`) and is harmless; `placeholder entry` reduces to
# `entry`, which then holds exactly one species.
#
# The test is per *label* and the class is per *family*: the family is A only when EVERY authored
# label that feeds it is a placeholder. Testing the family rather than the label is what keeps
# `plant` and `zombie` — which are fed by ~200 real labels each plus a handful of placeholder ones
# — out of class A.
PLACEHOLDER_TOKENS = frozenset({
    "placeholder", "unnamed", "unclassified", "unknown", "unspecified",
    "tbd", "todo", "nil", "n-a",
})


def is_placeholder_label(raw_label: str) -> bool:
    """True when a token of `raw_label` is a fill-in token rather than content."""
    return any(tok in PLACEHOLDER_TOKENS for tok in normalize(raw_label).split("-") if tok)


# =================================================================================================
# Class B — identity echo
# =================================================================================================
#
# The two shapes a proper name leaves behind when it is run through `head_noun`:
#
#   * a name-INITIAL — `ultimate Professor Z` reduces to `z`. A single character (or two) is never a
#     category word, and there is no corpus in which `z` groups anything;
#   * an id-ECHO — the id's token-run occurs, at token boundaries, inside the speciesId's own
#     camel-case word split. `CattailGirl` -> `cattail girl`, so `cattail` is that creature's name
#     rather than a family it belongs to.
#
# Both are only defects when the id holds ONE species: `squash` and `cactus` are name echoes and
# are also perfectly good seven- and eight-member families, and the rule the module enforces is
# about grouping, not about where a word came from.
NAME_INITIAL_MAX_LEN = 2

#: Camel-case / Pascal-case / digit split. An all-caps run is one token (`GnomeZombie` -> `gnome
#: zombie`), a capitalised word is one token, and digits are their own token.
_CAMEL_TOKEN_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|[0-9]+")


def camel_tokens(text: str) -> "list[str]":
    """`CattailGirl` -> `['cattail', 'girl']`; `GnomeZombie2` -> `['gnome', 'zombie', '2']`."""
    return [m.group(0).lower() for m in _CAMEL_TOKEN_RE.finditer(text)]


def identity_echo_of(family_id: str, species_name: str) -> "str | None":
    """The reason `family_id` is a fragment of `species_name`'s own name, or None.

    `species_name` must be the name AS COMMITTED, with its capitals intact: `HypnoCattailGirl`
    splits into three words and `hypnocattailgirl` is one, so a lower-cased id silently answers None
    for every id-echo and class B can then only ever catch a name-initial. Every consumer
    canonicalises `speciesId` to lower case for its own key — correct for the key, fatal for this —
    so the committed casing is carried alongside as `names` (`derive_vetted_assignments`).
    """
    if len(family_id) <= NAME_INITIAL_MAX_LEN:
        return "name-initial"
    want = family_id.split("-")
    tokens = camel_tokens(species_name)
    span = len(want)
    for start in range(len(tokens) - span + 1):
        if tokens[start:start + span] == want:
            return "id-echo"
    return None


# =================================================================================================
# Class C — walk-back artefact
# =================================================================================================
#
# `consolidate.head_noun` walks a label's tokens from the right and returns the first one that is not
# in `_GENERIC_SUFFIXES`. When the label ENDS in a generic suffix, that walk promotes a modifier to
# head — which is right when the modifier is the category (`nut-shooter` -> `nut`, 36 species) and
# wrong when it is not (`two-headed-shooter` -> `headed`, one species). The class is decided on the
# DERIVATION EVENT, not on the resulting string: comparing the derived id's morphology against
# English suffixes was measured and flags `plant`, `ranged`, `gatling`, `weed` and `seaweed`, so it
# is not a test. This one is exact about what it claims — `head_noun` skipped a suffix — and the
# one-species condition is what makes the skip a defect.
def walk_back_head(raw_label: str) -> "str | None":
    """The head token `head_noun` PROMOTED past a generic suffix, or None if it read the last token."""
    tokens = [t for t in normalize(raw_label).split("-") if t]
    if not tokens:
        return None
    head = head_noun(normalize(raw_label))
    return None if head == tokens[-1] else head


# =================================================================================================
# The classification
# =================================================================================================

CLASS_A = "A"
CLASS_B = "B"
CLASS_C = "C"
CLASS_D = "D"
CLASS_E = "E"

CLASS_NAMES: "Mapping[str, str]" = {
    CLASS_A: "placeholder",
    CLASS_B: "identity_echo",
    CLASS_C: "walk_back_artefact",
    CLASS_D: "singleton_role_tag",
    CLASS_E: "legitimate",
}

#: The three classes this module refuses to let a label be authored as. D and E are not defects —
#: D is an under-populated real category, E is a family that groups. See the module docstring.
REJECTED_CLASSES = frozenset({CLASS_A, CLASS_B, CLASS_C})


@dataclass(frozen=True)
class FamilyLabelVerdict:
    """One family id's class and the reason for it — the reusable per-family report."""

    family_id: str
    klass: str
    reason: str
    raw_labels: "tuple[str, ...]"
    species: "tuple[str, ...]"
    group_size: int

    @property
    def rejected(self) -> bool:
        return self.klass in REJECTED_CLASSES

    @property
    def class_name(self) -> str:
        return CLASS_NAMES[self.klass]


def classify_family(
    family_id: str,
    *,
    raw_labels: Sequence[str],
    species: Sequence[str],
    group_size: int,
) -> FamilyLabelVerdict:
    """Class one family id. A pure function of its arguments — no IO, no order dependence."""
    raws = tuple(raw_labels)
    members = tuple(species)
    one = group_size == 1

    if all(is_placeholder_label(r) for r in raws):
        return FamilyLabelVerdict(family_id, CLASS_A, "fed only by placeholder labels", raws,
                                  members, group_size)

    if one:
        for member in members:
            why = identity_echo_of(family_id, member)
            if why is not None:
                return FamilyLabelVerdict(
                    family_id, CLASS_B, f"{why} of {member!r} and holds one species",
                    raws, members, group_size)

    if one:
        for raw in raws:
            head = walk_back_head(raw)
            if head is not None:
                return FamilyLabelVerdict(
                    family_id, CLASS_C,
                    f"head_noun promoted {head!r} past a generic suffix in {raw!r} "
                    f"and the id holds one species",
                    raws, members, group_size)

    if one:
        return FamilyLabelVerdict(
            family_id, CLASS_D, "holds one species and is a real-looking category word",
            raws, members, group_size)

    return FamilyLabelVerdict(
        family_id, CLASS_E, f"holds {group_size} species", raws, members, group_size)


def classify_vocabulary(
    candidates: Sequence[FamilyCandidateInput],
    *,
    synonyms: "Mapping[str, str] | None" = None,
    names: "Mapping[str, str] | None" = None,
) -> "dict[str, FamilyLabelVerdict]":
    """Class every family id the candidate set produces, keyed by that id.

    Group sizes are read from `consolidate` over the candidate set AS AUTHORED — the whole set, not
    a filtered one. That is deliberate and it is what makes the classification non-circular: if the
    grouping were computed after dropping the rejected labels, a family's size would depend on
    whether it was dropped, and the rule could not be stated as "must group something". Rejecting
    only ever REMOVES candidates, so the vocabulary this returns is a superset of the one the
    caller goes on to derive, and a surviving id can never be one this call did not classify.

    **The ids come from `consolidate`'s own output, never from re-deriving them here.** Recomputing
    a candidate's id with `canonical_key` looks equivalent and is not: `consolidate` may fold a head
    away that `canonical_key` keeps (it accepts extra corroborating terms), so a second
    implementation of "which id does this label produce" silently disagrees with the one that
    produced the assignments — and did, in this repo, as a `KeyError` on the first real corpus run.
    `families[id]["nativeLabels"]` and `assignments` are the two authoritative mappings, and this
    function reads nothing else.
    """
    syn = dict(synonyms) if synonyms is not None else load_synonyms()
    consolidated = consolidate(candidates, synonyms=syn)
    assignments = consolidated.assignments
    committed = dict(names) if names else {}

    raw_by: "dict[str, list[str]]" = {
        family_id: list(record.get("nativeLabels") or [])
        for family_id, record in consolidated.families.items()
    }
    species_by: "dict[str, set[str]]" = {}
    sizes: "dict[str, int]" = {}
    for species_id, families in assignments.items():
        for family_id in families:
            species_by.setdefault(family_id, set()).add(committed.get(species_id, species_id))
            sizes[family_id] = sizes.get(family_id, 0) + 1

    return {
        family_id: classify_family(
            family_id,
            raw_labels=sorted({str(v) for v in raw_by.get(family_id, [])}),
            species=sorted(species_by.get(family_id, set())),
            group_size=sizes.get(family_id, 0),
        )
        for family_id in sorted(sizes)
    }


def census(verdicts: "Mapping[str, FamilyLabelVerdict]") -> "dict[str, int]":
    """Per-class counts. A READING of the corpus, never a constant to assert on (validation-ssot §1)."""
    out = {k: 0 for k in (CLASS_A, CLASS_B, CLASS_C, CLASS_D, CLASS_E)}
    for verdict in verdicts.values():
        out[verdict.klass] += 1
    return out


def rejected_labels(
    candidates: Sequence[FamilyCandidateInput],
    verdicts: "Mapping[str, FamilyLabelVerdict]",
) -> "tuple[list[FamilyCandidateInput], dict[str, list[str]]]":
    """Split `candidates` into the ones that survive and the ones refused, with the reasons.

    Returns `(kept, refused)` where `refused` maps a rejected family id to the labels that produced
    it, so a caller can report why a species lost a label instead of silently dropping it.

    A candidate is matched to its family through the verdict's OWN `raw_labels` — the labels
    `consolidate` recorded as having folded into that id — rather than by re-deriving the id. One
    label consolidates into exactly one id, so the mapping is unambiguous, and it stays correct when
    `consolidate` folds a head away that a bare `canonical_key` would have kept (see
    `classify_vocabulary`).
    """
    refused: "dict[str, list[str]]" = {}
    rejected_labels_flat: "set[str]" = set()
    for verdict in verdicts.values():
        if not verdict.rejected:
            continue
        labels = {str(v) for v in verdict.raw_labels}
        refused[verdict.family_id] = sorted(labels)
        rejected_labels_flat |= labels

    kept = [c for c in candidates if c.label not in rejected_labels_flat]
    return kept, refused


# =================================================================================================
# The deterministic fallback — a species whose family set would otherwise be EMPTY
# =================================================================================================
#
# Filtering is not allowed to trade "ugly labels" for "the corpus will not load". The loader's
# `has no family` raise turned an emptied family set into a hard failure of the WHOLE corpus, so an
# empty set must never survive the filter in the first place: it resolves to a family drawn from
# committed vocabulary instead.
#
# The fallback is the species' own `side`, normalised through the consumer's own key rule. It is
# deterministic because `side` is a committed field the identity pipeline never authors per species
# — it is the corpus's coarse taxonomy — and because it is read through `normalize_family_key`, the
# single definition every other consumer already uses, so the result is a legal action namespace key
# by construction. Measured on the committed corpus it is a closed two-value vocabulary
# (`plant` 677 species, `zombie` 227), and both values are already the two largest families in the
# derived vocabulary (`plant` 391, `zombie` 149), so the fallback adds no new id to the namespace.
#
# A record with no usable `side` is a DIFFERENT defect — a species record missing its taxonomy — and
# it raises, by name. This fallback covers the empty-family-set path only.
FALLBACK_FIELD = "side"


def fallback_family(record: Mapping[str, object]) -> str:
    """The family a species with no surviving family label resolves to. Never returns an empty id."""
    raw = record.get(FALLBACK_FIELD)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(
            f"species {record.get('speciesId')!r} has no usable {FALLBACK_FIELD!r} to fall back to "
            f"— an empty family set cannot be resolved deterministically without it")
    # normalize_family_key RAISES rather than returning an empty key, which is the contract every
    # other consumer already depends on; reusing it keeps ONE normalisation in the tree.
    return normalize_family_key(raw)


def iter_family_labels(raw: object) -> "list[str]":
    """A species record's authored family labels, whether the field is a list or one bare string."""
    if isinstance(raw, str):
        raw = [raw]
    return [str(label).strip() for label in (raw or []) if str(label).strip()]


# =================================================================================================
# The derivation — filter, then resolve, so no species can end up with an EMPTY family set
# =================================================================================================
#
# This is the whole mechanism, in one pure function, so it can be tested over the committed corpus
# without a filesystem write and without depending on any consumer's load path. The consumer calls it
# (see `characteristic_pool/catalog.derive_live_family_assignments`); nothing else may.
#
# Order matters and is load-bearing:
#   1. build candidates from the records as authored;
#   2. CLASSIFY the whole vocabulary, unfiltered — so "does this id group anything" is answered
#      against what the corpus actually says, not against what survived;
#   3. drop the candidates whose id is class A, B or C;
#   4. re-consolidate the survivors;
#   5. for any species left empty, resolve the deterministic fallback.
#
# Step 4 cannot invent an id that step 2 did not classify: the canonical-key function is unchanged
# between the two calls and removing candidates only removes keys, never adds one.
@dataclass(frozen=True)
class DerivationReport:
    """Everything a caller needs to report the derivation honestly."""

    assignments: "dict[str, list[str]]"
    verdicts: "dict[str, FamilyLabelVerdict]"
    #: family id -> the authored labels that were refused, for every class A/B/C id
    refused: "dict[str, list[str]]"
    #: species ids that took the deterministic fallback rather than carrying an authored label
    fell_back: "tuple[str, ...]"

    @property
    def census(self) -> "dict[str, int]":
        return census(self.verdicts)


def derive_vetted_assignments(
    records: Iterable[Mapping[str, object]],
    *,
    synonyms: "Mapping[str, str] | None" = None,
) -> DerivationReport:
    """Species -> family ids, with the artefact classes refused and no species left empty."""
    syn = dict(synonyms) if synonyms is not None else load_synonyms()

    candidates: "list[FamilyCandidateInput]" = []
    by_species: "dict[str, dict[str, object]]" = {}
    names: "dict[str, str]" = {}
    for record in records:
        species_id = str(record["speciesId"]).strip().lower()
        # The name as committed, capitals intact, keyed by the canonical id. `speciesId` is
        # lower-cased for the key, and the lower-cased form collapses `HypnoCattailGirl` into one
        # token, which is the signal class B reads. The game's own humps are the record of where one
        # creature word ends and the next begins; the canonical id is not.
        names[species_id] = str(record["speciesId"]).strip()
        raw = record.get("family", [])
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            raise ValueError(f"species {species_id!r}: family must be a list")
        by_species[species_id] = record
        for label in sorted({str(v).strip() for v in raw if str(v).strip()}):
            candidates.append(FamilyCandidateInput(
                species_id=species_id, label=label, native_label=label, basis="text"))

    verdicts = classify_vocabulary(candidates, synonyms=syn, names=names)
    kept, refused = rejected_labels(candidates, verdicts)
    assignments = consolidate(kept, synonyms=syn).assignments

    fell_back: "list[str]" = []
    for species_id in sorted(by_species):
        if assignments.get(species_id):
            continue
        assignments[species_id] = [fallback_family(by_species[species_id])]
        fell_back.append(species_id)

    return DerivationReport(
        assignments={sid: sorted(set(fams)) for sid, fams in sorted(assignments.items())},
        verdicts=verdicts,
        refused={fid: sorted(set(labels)) for fid, labels in sorted(refused.items())},
        fell_back=tuple(fell_back),
    )
