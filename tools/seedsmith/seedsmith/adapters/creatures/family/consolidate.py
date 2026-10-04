"""seedsmith.adapters.creatures.family.consolidate — candidate labels -> the family vocabulary
(spec-family-consolidate.md).

Runs over `family-extract`'s COMMITTED output only, never live extraction (§2.0/§7 boundaries) —
the input to this module is a fixed, already-recorded set of candidates, which is what makes
"same inputs -> byte-identical vocabulary, forever" (§2.1) a provable claim rather than a hope.

Merging reads `label` (English) only; `nativeLabel` is carried into the family record for display
and `lore-enrich`, and never participates in grouping (§2.0, resolving audit S7).

**The head-noun merge carries ONE narrow refusal (2026-10-04).** §2.1 rule 2 reduces a label to its
last non-generic token, and it was right to exist — `wall-nut`, `tall-nut`, `defensive-nut` and
`nut-type` must all reduce to `nut`, or the same family splits four ways. What it did not know is
whether the token it lands on is worth keeping when the label had better information to give. So:

> the merge is refused when the label's own LEADING token is a term the corpus already groups by and
> the head it would emit is not, because the merge then provably throws away information the corpus
> asserted. `undead fauna` reduces to `fauna`, discarding `undead` — and `undead` is a family 30+
> species land on while `fauna` is a category noun nothing else uses.

That is the whole rule, and its narrowness is measured rather than cautious: the wider version —
"refuse every head the corpus has not itself corroborated" — was built, broke four pre-existing
`test_family_consolidate.py` cases, and did not even fix what it was built for. `merge_corroborated`
carries that account and `tests/test_family_source_repairs.py` pins both directions.

The **corroborated** set is two committed sources and no hand-written vocabulary: a token some
candidate in this same run authored as its WHOLE label, plus the curated `families.v1.json` registry
ids the caller passes in. `attested_grouping_terms` is the first; the second is why `wall-nut` still
reduces to `nut` when `nut` is a curated family that no species ever authored bare.

`head_noun` and `canonical_key` keep their signatures and their original behaviour for a caller that
has no corpus in hand; the gate lives in `merge_corroborated`, which is the only function that can
see the whole candidate set. Determinism is untouched — §2.1's claim is "same inputs ->
byte-identical vocabulary", and the corroboration set is itself a pure function of those same
inputs.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

__all__ = [
    "FamilyCandidateInput",
    "ConsolidatedFamilies",
    "normalize",
    "head_noun",
    "canonical_key",
    "attested_grouping_terms",
    "merge_corroborated",
    "consolidate",
    "load_synonyms",
]

SYNONYMS_PATH = Path(__file__).resolve().parent / "synonyms.json"

# §2.1 rule 2 — a documented suffix set. A token here means "this word describes the SHAPE of the
# label, not what the thing IS" — stripping it is what makes `nut-type` reduce to the same head as
# `wall-nut`.
#
# Expanded 2026-08-31 after the FIRST REAL model run exposed the original 5-word set as too narrow.
# `google/gemma-4-26b-a4b-qat`, unprompted, produced labels like `fire-based`, `light-based`,
# `chomper-kin`, `nut-kin`, `pea-kin`, `ice-attackers`, `bucket-users`, `sun-producers` — every one
# a "<theme>-<generic relational noun>" shape the original 5 words did not cover. Left unfixed, this
# produced BOTH failure directions at once on the same 53-candidate batch: semantically IDENTICAL
# groups split apart (`ice-attackers` and `ice-family` became two separate families instead of one),
# and semantically UNRELATED groups incorrectly merged (`fire-based`+`light-based` -> one false
# "based" family; `chomper-kin`+`nut-kin`+`pea-kin` -> one false "kin" family). The false-merge
# direction is the more dangerous of the two — it silently combines things that are not kin, which
# is exactly what audit A6 named this module to prevent.
_GENERIC_SUFFIXES = frozenset({
    "type", "class", "kind", "kins", "kin", "variant", "family", "families", "themed", "theme",
    "based", "users", "user", "attacker", "attackers", "producer", "producers", "vessel", "vessels",
    "shooter", "shooters", "related", "affiliated", "linked", "associated", "group", "style",
})

_PUNCT = re.compile(r"[^a-z0-9]+")


def normalize(label: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace, kebab-case (§2.1 rule 1)."""
    return _PUNCT.sub("-", label.strip().lower()).strip("-")


def head_noun(normalized_label: str) -> str:
    """The last token that is not a generic suffix (§2.1 rule 2) — `wall-nut`, `defensive-nut` and
    `nut-type` all reduce to `nut`. If every token is a generic suffix, the last token is used
    anyway rather than returning an empty head."""
    tokens = [t for t in normalized_label.split("-") if t]
    if not tokens:
        return normalized_label
    for token in reversed(tokens):
        if token not in _GENERIC_SUFFIXES:
            return token
    return tokens[-1]


def load_synonyms(path: Path = SYNONYMS_PATH) -> "dict[str, str]":
    """Read fresh, never transcribed — a human edits this file, the algorithm only reads it."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    return dict(doc.get("aliases") or {})


def canonical_key(label: str, synonyms: Mapping[str, str]) -> str:
    """§2.1 rules 2-3, composed: an exact synonym match wins over head-noun merging (it exists
    precisely for the labels head-noun merging cannot reach), otherwise fall back to the head."""
    norm = normalize(label)
    if norm in synonyms:
        return normalize(synonyms[norm])
    return head_noun(norm)


def attested_grouping_terms(candidates: Sequence[FamilyCandidateInput]) -> "frozenset[str]":
    """Every token the corpus itself uses as a WHOLE family label — one of the two committed sources
    `merge_corroborated`'s refusal consults.

    A single-token label is a species stating "this word is my family", which is the only in-corpus
    evidence that the word names a group rather than describing one. Multi-token labels contribute
    nothing: `wall-nut` says `nut` is worth keeping `wall` beside, not that `nut` stands alone.
    Measured over the live corpus, 2026-10-04: 170 of them.
    """
    out: "set[str]" = set()
    for c in candidates:
        norm = normalize(c.label)
        if norm and "-" not in norm:
            out.add(norm)
    return frozenset(out)


def merge_corroborated(
    label: str, synonyms: Mapping[str, str], corroborated: "frozenset[str]",
) -> str:
    """`canonical_key`, with ONE narrow refusal added on top of §2.1 rule 2.

    **The refusal, stated as the loss it prevents:** the head-noun merge is NOT applied when the
    label's own LEADING token is a term the corpus already groups by and the head it would emit is
    not — because in that case the merge provably throws away information the corpus asserted.
    `undead fauna` reduces to `fauna`, discarding `undead`, and `undead` is a family 30+ species
    land on while `fauna` is a category noun nothing else uses. The label keeps both words.

    **What this rule deliberately does NOT do, and why the scope is this narrow.** The tempting
    version — refuse every head the corpus has not itself corroborated — was built and measured on
    2026-10-04, and it destroys §2.1 rule 2. On a candidate set of three (`wall-nut`,
    `defensive-nut`, `nut-type`) nothing is corroborated, so all three stop merging and a family
    that has been one family since 2026-08-31 splits three ways. Worse, it does not even fix the
    cases it was built for: `botanical` is reached by stripping from four labels, so it WOULD be
    refused, and so would every legitimately small corpus. Four pre-existing tests
    (`test_family_consolidate.py`) caught exactly this, which is what a guard is for.

    So the rule refuses only a PROVABLE loss and leaves every undecidable case exactly as §2.1 rule 2
    left it. Deciding `fragile-body` -> `body` or `two-headed-shooter` -> `headed` needs to know
    that `body` and `headed` are not family terms, and nothing in this tree knows what a word means.
    Adding a curated non-noun lexicon would be inventing a taxonomy, which is the one thing the
    owner ruling for this work forbids. Those labels are the unresolved remainder, and the sibling
    `fallback.py` is what catches the species they strand.

    A synonym match still wins outright — rule 3 is an explicit human override and must not be
    second-guessed. Never raises and never returns empty: this module places the candidate
    somewhere, and dropping it is `fallback.py`'s decision, not this one's.
    """
    norm = normalize(label)
    if norm in synonyms:
        return normalize(synonyms[norm])
    head = head_noun(norm)
    if head == norm:
        return head                      # a single token is its own head; nothing was merged away
    leading = next((t for t in norm.split("-") if t), head)
    if leading in corroborated and head not in corroborated:
        return norm                      # the merge would discard a family term the corpus asserts
    return head


@dataclass(frozen=True)
class FamilyCandidateInput:
    species_id: str
    label: str
    native_label: str
    basis: str  # "text" | "name" — a `blocked` creature contributes no candidate at all


@dataclass(frozen=True)
class ConsolidatedFamilies:
    # familyId -> {nativeLabels: [...], basis-per-nativeLabel is not tracked here; a family is a
    # merged vocabulary entry, not a per-candidate ledger}
    families: "dict[str, dict]"
    # speciesId -> [familyId], sorted, deduplicated — multi-membership (§2.4)
    assignments: "dict[str, list[str]]"


def consolidate(
    candidates: Sequence[FamilyCandidateInput],
    *,
    synonyms: "Mapping[str, str] | None" = None,
    existing_registry: "Mapping[str, dict] | None" = None,
    established_terms: "Mapping[str, str] | None" = None,
) -> ConsolidatedFamilies:
    """Mechanical merge: normalize -> head-noun/synonym -> canonical key -> family id.

    `established_terms` is an OPTIONAL extra corroboration set of family terms the corpus cannot
    state about itself — today the caller passes the curated `families.v1.json` registry ids. It is
    a parameter rather than a path this module resolves because a leaf that resolves paths is a
    leaf that can join an import cycle (`seedsmith.ladders` says so about itself), and because the
    registry is owned by the seed root the caller already owns. `None` means "corroboration from
    this run's own labels only", which is the weaker but still-correct behaviour.

    `existing_registry` is `families.v1.json`'s own content from a PRIOR run, if any — append-only
    (§2.3): every id already in it keeps its exact identity and position; only a canonical key with
    no prior id gets a new one, appended in order of first appearance across `candidates` sorted by
    `speciesId` (§2.1 rule 4). Passing `None` means "first run ever", not "ignore history".
    """
    syn = dict(synonyms) if synonyms is not None else load_synonyms()
    ordered = sorted(candidates, key=lambda c: c.species_id)

    # The corroboration set is a pure function of the SAME candidate set this run consumes, so §2.1's
    # "same inputs -> byte-identical vocabulary" is preserved: two runs over the same corpus reach
    # the same set and therefore the same keys, in the same order.
    corroborated = attested_grouping_terms(ordered) | frozenset(
        normalize(str(term)) for term in (established_terms or ()))

    key_to_id: "dict[str, str]" = {}
    order: "list[str]" = []
    if existing_registry:
        for family_id, record in existing_registry.items():
            key_to_id[record.get("canonicalKey", family_id)] = family_id
            order.append(family_id)

    families: "dict[str, dict]" = (
        {fid: dict(rec) for fid, rec in existing_registry.items()} if existing_registry else {}
    )
    assignments: "dict[str, set[str]]" = {}

    for c in ordered:
        key = merge_corroborated(c.label, syn, corroborated)
        family_id = key_to_id.get(key)
        if family_id is None:
            # A canonical key with no matching id in the existing registry is a NEW family — its
            # id IS the canonical key text (§2.1: the head/synonym target, kebab already).
            family_id = key
            key_to_id[key] = family_id
            order.append(family_id)
            families[family_id] = {"canonicalKey": key, "nativeLabels": []}
        native_labels = families[family_id].setdefault("nativeLabels", [])
        if c.native_label not in native_labels:
            native_labels.append(c.native_label)
        assignments.setdefault(c.species_id, set()).add(family_id)

    # Append-only ordering preserved: rebuild `families` in `order`'s sequence so the emitted file
    # never silently reorders an id that was already present.
    ordered_families = {fid: families[fid] for fid in order}
    ordered_assignments = {sid: sorted(fams) for sid, fams in sorted(assignments.items())}

    return ConsolidatedFamilies(families=ordered_families, assignments=ordered_assignments)
