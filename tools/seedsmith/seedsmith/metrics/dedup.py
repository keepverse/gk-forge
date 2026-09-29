"""seedsmith.metrics.dedup — SemanticDedup: two entries, one idea (spec-analytics.md §6).

Three deterministic layers, no model:

6.1 Exact and canonical — already shipped in C# for the naming check; here it runs across the
    WHOLE corpus regardless of kind, which is what the historical incident needed (`gem.g1-015`
    and `consumable.k1-007` both literally named "Mending Pulse" — a same-kind naming check alone
    would never have compared them).
6.2 Lexical near-duplicates — character 5-gram shingles -> MinHash signatures -> Jaccard
    similarity, with LSH banding so 1,400+ names cost O(n) buckets, not O(n^2) pairs.

Conceptual clustering (spec-analytics.md §6.3) is a deliberate, documented gap: the word pools
group by WHERE a word may be used, not WHAT IDEA it expresses, and using them for this would score
its healthiest possible value in exactly the corpus's most repetitive state. It ships only once
`axis` is added to the 516 adjective canonical entries — a registry addition, not a metric this
task can implement correctly today.
"""
from __future__ import annotations

import re
import zlib
from dataclasses import dataclass

from .model import Ctx, Finding, Loop, Metric, Severity

_WORD_RE = re.compile(r"[a-z0-9]+")


def canonical_words(name: str) -> "frozenset[str]":
    return frozenset(_WORD_RE.findall(name.lower()))


def shingles(text: str, k: int = 5) -> "set[str]":
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    if len(normalized) < k:
        return {normalized} if normalized else set()
    return {normalized[i:i + k] for i in range(len(normalized) - k + 1)}


# 32 independent (a, b) hash coefficients over a fixed large prime — deterministic across runs
# (no `random`, which the workflow-authoring stdlib-only constraint and simple reproducibility
# both want), generated once from a fixed seed sequence rather than hand-typed.
_PRIME = 4_294_967_311
_NUM_HASHES = 32
_HASH_COEFFS = [(1 + 2 * i, 1 + 3 * i) for i in range(_NUM_HASHES)]


def _shingle_hash(s: str) -> int:
    # NOT builtin hash(): Python randomizes str hashing per-process (PYTHONHASHSEED) unless
    # disabled, which would make every MinHash signature — and every LSH bucket built from one —
    # different across runs and unreproducible in CI. zlib.crc32 is stable for the same input,
    # in this process or any other.
    return zlib.crc32(s.encode("utf-8"))


def minhash_signature(shingle_set: "set[str]") -> "tuple[int, ...]":
    if not shingle_set:
        return tuple([0] * _NUM_HASHES)
    hashes = [_shingle_hash(s) for s in shingle_set]
    return tuple(
        min((a * h + b) % _PRIME for h in hashes)
        for a, b in _HASH_COEFFS
    )


def jaccard_estimate(sig_a: "tuple[int, ...]", sig_b: "tuple[int, ...]") -> float:
    matches = sum(1 for x, y in zip(sig_a, sig_b) if x == y)
    return matches / len(sig_a)


def lsh_bands(signature: "tuple[int, ...]", bands: int = 8) -> "list[tuple]":
    rows_per_band = len(signature) // bands
    return [tuple(signature[i * rows_per_band:(i + 1) * rows_per_band]) for i in range(bands)]


@dataclass(frozen=True)
class _Named:
    entry_id: str
    kind: str
    name: str


def _named_entries(corpus) -> "list[_Named]":
    result = []
    for kind in corpus.kinds:
        if kind == "display-template":
            continue  # parameterized rendering patterns are not player-facing item identities
        for entry in corpus.by_kind(kind):
            name = entry.get("name")
            if name:
                result.append(_Named(entry.id, kind, name))
    return result


@dataclass(frozen=True)
class _Prosed:
    entry_id: str
    kind: str
    field: str
    text: str


def _prose_entries(corpus, adapter) -> "list[_Prosed]":
    # Additive: an adapter that declares no `dedup_fields` (every adapter before commander-effect)
    # produces an empty list here, so this check is a strict addition with nothing to migrate.
    if adapter is None:
        return []
    kind_specs = {k.kind: k for k in adapter.kinds()}
    result = []
    for kind in corpus.kinds:
        spec = kind_specs.get(kind)
        if spec is None or not spec.dedup_fields:
            continue
        for entry in corpus.by_kind(kind):
            for field_name in sorted(spec.dedup_fields):
                text = entry.get(field_name)
                if text:
                    result.append(_Prosed(entry.id, kind, field_name, text))
    return result


class SemanticDedup(Metric):
    id = "SemanticDedup/NearDuplicate"
    family = "SemanticDedup"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"corpus"})
    covers: tuple[str, ...] = ("appendix-a:16",)

    def __init__(self, near_duplicate_threshold: float = 0.6,
                 prose_near_duplicate_threshold: float = 0.5) -> None:
        self.near_duplicate_threshold = near_duplicate_threshold
        # Lower than the name threshold on purpose: calibrated 2026-09-06 against the real
        # 84-entry commander-effect corpus with production shingles (k=5) + 32-hash MinHash. The
        # clearest real pair (doublecherry/doubleshooter, near-identical sentences describing the
        # same split-shot mechanic) scores 0.56; the next two candidates (0.41, 0.34) share only a
        # verb ("发射", to fire) and are legitimate distinct doctrines, not near-copies. 0.5 catches
        # the first without the other two.
        self.prose_near_duplicate_threshold = prose_near_duplicate_threshold

    def run(self, ctx: Ctx) -> list[Finding]:
        entries = _named_entries(ctx.corpus)
        findings: list[Finding] = []

        # 6.1a exact — literal string match, across kinds
        by_exact_name: "dict[str, list[_Named]]" = {}
        for e in entries:
            by_exact_name.setdefault(e.name, []).append(e)
        for name, group in by_exact_name.items():
            if len(group) > 1:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=name,
                    message=f"'{name}' is used verbatim by {len(group)} entries across "
                            f"{sorted({g.kind for g in group})}: "
                            f"{[g.entry_id for g in group]}",
                    evidence={"code": "ExactDuplicateName",
                             "entryIds": [g.entry_id for g in group]}))

        # 6.1b canonical — same word SET, different order/case/punctuation
        by_canonical: "dict[frozenset, list[_Named]]" = {}
        for e in entries:
            words = canonical_words(e.name)
            if words:
                by_canonical.setdefault(words, []).append(e)
        for words, group in by_canonical.items():
            distinct_names = {g.name for g in group}
            if len(distinct_names) > 1:
                findings.append(Finding(
                    metric=self.id, severity=Severity.NOTE, subject="/".join(sorted(words)),
                    message=f"{sorted(distinct_names)} share the same canonical word set across "
                            f"{[g.entry_id for g in group]}",
                    evidence={"code": "CanonicalDuplicate",
                             "entryIds": [g.entry_id for g in group]}))

        # 6.2 lexical near-duplicate via MinHash + LSH banding (avoids O(n^2) all-pairs)
        signatures = {e.entry_id: minhash_signature(shingles(e.name)) for e in entries}
        buckets: "dict[tuple, list[str]]" = {}
        for entry_id, sig in signatures.items():
            for band in lsh_bands(sig):
                buckets.setdefault(band, []).append(entry_id)

        reported: "set[frozenset]" = set()
        by_id = {e.entry_id: e for e in entries}
        for candidates in buckets.values():
            if len(candidates) < 2:
                continue
            for i in range(len(candidates)):
                for j in range(i + 1, len(candidates)):
                    a_id, b_id = candidates[i], candidates[j]
                    if a_id == b_id:
                        continue
                    pair = frozenset({a_id, b_id})
                    if pair in reported or by_id[a_id].name == by_id[b_id].name:
                        continue  # exact duplicates already reported above
                    similarity = jaccard_estimate(signatures[a_id], signatures[b_id])
                    if similarity >= self.near_duplicate_threshold:
                        reported.add(pair)
                        findings.append(Finding(
                            metric=self.id, severity=Severity.NOTE,
                            subject=f"{a_id}~{b_id}",
                            message=f"'{by_id[a_id].name}' and '{by_id[b_id].name}' are lexically "
                                    f"near-duplicate names (Jaccard~{similarity:.2f})",
                            evidence={"code": "LexicalNearDuplicate", "jaccard": similarity,
                                     "names": [by_id[a_id].name, by_id[b_id].name]}))

        # 6.1c / 6.2b prose duplicate and near-duplicate — same pipeline as 6.1a/6.2, over each
        # kind's own declared free-text field(s) (KindSpec.dedup_fields) rather than `name`.
        # `commander-effect`'s `doctrine` is the first consumer; additive, so a kind that declares
        # nothing produces no prose entries and this block is a no-op for it (see _prose_entries).
        prosed = _prose_entries(ctx.corpus, ctx.adapter)

        by_exact_text: "dict[tuple[str, str], list[_Prosed]]" = {}
        for p in prosed:
            by_exact_text.setdefault((p.field, p.text), []).append(p)
        for (field_name, text), group in by_exact_text.items():
            if len(group) > 1:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=text,
                    message=f"'{field_name}' text is used verbatim by {len(group)} entries: "
                            f"{[g.entry_id for g in group]}",
                    evidence={"code": "ExactProseDuplicate", "field": field_name,
                             "entryIds": [g.entry_id for g in group]}))

        # DIRECT all-pairs Jaccard over the exact shingle sets, not MinHash+LSH. §6.2's LSH banding
        # exists to keep 1,400+ NAMES off O(n^2) — verified 2026-09-06 that at prose-scale
        # similarity (~0.5-0.6, sentences sharing a topic rather than near-identical short
        # strings), 8-band/4-row LSH has real recall loss: it missed the real corpus's clearest
        # pair (Jaccard 0.56) entirely on a live run. A kind with a prose dedup field is bounded in
        # the low thousands at worst (commander-effect's ceiling is ~900 creatures), where O(n^2)
        # exact-shingle comparison is cheap and has no recall problem to trade away.
        prose_shingle_sets = {(p.entry_id, p.field): shingles(p.text) for p in prosed}
        prose_by_key = {(p.entry_id, p.field): p for p in prosed}
        prose_keys = list(prose_shingle_sets.keys())
        for i in range(len(prose_keys)):
            for j in range(i + 1, len(prose_keys)):
                a_key, b_key = prose_keys[i], prose_keys[j]
                a_entry, b_entry = prose_by_key[a_key], prose_by_key[b_key]
                if a_entry.text == b_entry.text:
                    continue  # exact duplicates already reported above
                a_set, b_set = prose_shingle_sets[a_key], prose_shingle_sets[b_key]
                if not a_set or not b_set:
                    continue
                similarity = len(a_set & b_set) / len(a_set | b_set)
                if similarity >= self.prose_near_duplicate_threshold:
                    findings.append(Finding(
                        metric=self.id, severity=Severity.NOTE,
                        subject=f"{a_entry.entry_id}~{b_entry.entry_id}",
                        message=f"{a_entry.kind} entries '{a_entry.entry_id}' and "
                                f"'{b_entry.entry_id}' have near-duplicate '{a_entry.field}' "
                                f"text (Jaccard={similarity:.2f})",
                        evidence={"code": "ProseNearDuplicate", "jaccard": similarity,
                                 "field": a_entry.field,
                                 "entryIds": [a_entry.entry_id, b_entry.entry_id],
                                 "texts": [a_entry.text, b_entry.text]}))
        return findings
