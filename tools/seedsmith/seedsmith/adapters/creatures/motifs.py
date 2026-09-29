"""seedsmith.adapters.creatures.motifs — motifs and anti-motifs per creature (spec-motif-derive.md).

Pure derivation, no model call, no human pass (owner, Q1) — the point is not sophistication, it is
a mechanism a family member can inherit from and a later pass (`lore-enrich`) can improve without
anyone re-authoring by hand. §2.5's own words: "first-pass motifs... are supposed to be visibly
weak" — this module is deliberately naive, not accidentally so.

Two passes, because a family's own motif pool does not exist until its MEMBERS' own-text motifs
have been derived once:
  pass 1 — `own_motifs(text_or_name)` per creature, independent of family
  pass 2 — aggregate each family's pool from its members' pass-1 motifs
  pass 3 — each creature's final motifs = its families' pools (family-first) + its own, trimmed 3-5

⚠️ **`jieba` dependency, owner-approved 2026-08-31, scoped to this module's tokenizer only.** The
program's standing rule is "stdlib only outside `pipeline`" — this is the one exception, and here is
why a regex genuinely cannot do the job it is standing in for: Chinese has no spaces between words,
so a punctuation-free run of characters is not "one token", it is an un-segmented CLAUSE. Confirmed
on the first real 84-creature run: the original regex tokenizer (`[一-鿿]+`, "maximal CJK run") returned
whole sentences as "motifs" — e.g. `以下能防止爆炸樱桃产生溅射` (an entire clause) — which is unusable
as shared vocabulary. `jieba` performs real dictionary/statistical word segmentation; no
regex-based heuristic can approximate that without linguistic knowledge a regex does not have.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import jieba
import jieba.posseg as pseg

__all__ = [
    "classify_line",
    "prose_of",
    "FamilyMembership",
    "CreatureMotifInput",
    "DerivedMotifs",
    "own_motifs",
    "derive_motifs",
]

# Family-first default split (owner-decided starting point, spec §9 Q1 — revisit against the real
# roster, not chosen by feel): a creature with enough inherited motifs takes 2 from its families and
# 1 of its own; family-first ordering is what makes a family read as a family rather than a list
# of individually-flavoured creatures.
_FAMILY_SHARE = 2
_OWN_SHARE = 1
_MIN_MOTIFS = 3
_MAX_MOTIFS = 5

_ASCII_TOKEN = re.compile(r"[A-Za-z0-9]+")
_HAS_CJK = re.compile(r"[一-鿿]")

# jieba segments; it does not remove function words. This is a small, documented particle/pronoun/
# common-verb list for THIS game's flavour-text register — measured against the real corpus while
# fixing the whole-clause defect, not exhaustive Chinese NLP stopword research. A motif that is a
# real content word (a noun, a distinctive verb) survives; a grammatical scaffold word does not.
_CJK_STOPWORDS = frozenset({
    "的", "了", "是", "在", "和", "或", "与", "及", "其", "这", "那", "每", "当", "将", "被", "对",
    "向", "从", "上", "下", "内", "外", "次", "个", "以", "以下", "以上", "如果", "则", "后", "前",
    "能", "可以", "会", "都", "也", "还", "并", "且", "为", "使", "让", "给", "但", "而", "此",
    "该", "本", "又", "再", "更", "最", "很", "非常", "一个", "一种", "所有", "任何", "没有", "不会",
    "不能", "只", "只能", "只有", "自己", "拥有", "具有", "进行", "获得", "产生", "造成", "发生",
    "出现", "变成", "成为", "开始", "结束", "之后", "之前", "同时", "时候", "情况", "状态", "效果",
})


# ---- G1.1: prose vs mechanical line classification (spec-motif-prose-filter.md §2.1) ----------
#
# Measured over the real 84-creature corpus: 70% of `flavorInfo` is a STAT TABLE, only 29% prose. The
# derivation was therefore reading `韧性：270+2200（一类）` and emitting `一类` ("armour-class one")
# as a "motif". Four rules, all structural — a balance pass would never touch them.
#
# Rules 3 and 4 were added by audit S1: the first draft said "section headers and their continuation
# lines" WITHOUT DEFINING a continuation line, and leaked 15 of 99 supposedly-prose lines.

#: Rule 1 — `label：value`. The <=12-char bound separates a field label from a sentence that merely
#: contains a colon; structural, not tunable.
_STAT_LINE = re.compile(r"^\s*[^：:]{1,12}[：:]")

#: Rule 2 — mechanical section headers.
_MECHANICAL_HEADERS = ("特点", "特性", "弱点", "使用条件", "融合配方")

#: Rule 3 — a circled numeral opens the CONTINUATION of a 特点 list. This is the definition the
#: first draft hand-waved (13 real lines leaked through without it).
_CIRCLED_NUMERALS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫"

#: Rule 4 — an ASCII digit means threshold/stat text. DELIBERATELY ASCII-only: `可在三种攻击模式之间切换`
#: uses the CJK numeral 三, is genuinely thematic, and must survive. A rule matching CJK numerals
#: would delete real prose.
_ASCII_DIGIT = re.compile(r"\d")


def classify_line(line: str) -> str:
    """`"mechanical"` or `"prose"` (spec-motif-prose-filter.md §2.1). Pure, and exported so each
    rule is testable alone rather than only through `own_motifs`."""
    s = line.strip()
    if not s:
        return "mechanical"
    if _STAT_LINE.match(s):
        return "mechanical"
    if s.startswith(_MECHANICAL_HEADERS):
        return "mechanical"
    if s[0] in _CIRCLED_NUMERALS:
        return "mechanical"
    if _ASCII_DIGIT.search(s):
        return "mechanical"
    return "prose"


def prose_of(*, flavor_info: "str | None", flavor_introduce: "str | None") -> str:
    """The text motifs may be derived from. `flavorIntroduce` is preferred where present (18/84
    creatures carry it; it is pure lore with zero stat content), then the prose lines of `flavorInfo`.

    ⚠️ Preferring `flavorIntroduce` is only safe BECAUSE of the POS filter below — measured, it is
    often a joke narrative ("Why is the bucket-nut's head so iron? Actually it's because...") and
    without POS filtering it imports `为什么`/`是因为`/`不过` as "motifs" (audit S2)."""
    parts: "list[str]" = []
    intro = (flavor_introduce or "").strip()
    if intro:
        parts.append(intro)
    for line in (flavor_info or "").split("\n"):
        if classify_line(line) == "prose":
            parts.append(line.strip())
    return "\n".join(p for p in parts if p)


# ---- G1.2: part-of-speech filtering (spec-motif-prose-filter.md §2.2) -------------------------
#
# Audit S3 measured that a corpus-FREQUENCY floor is the wrong instrument and fails in BOTH
# directions: `为什么` ("why") has document frequency 3/84 so a floor KEEPS it, while `樱桃`
# ("cherry", 9/84) and `坚果` ("nut", 7/84) are real family motifs a floor would risk DROPPING.
# Connectives are rare-but-meaningless; family words are common-but-meaningful.
#
# Part of speech separates them cleanly, verified on the exact failing narrative:
#   KEEP  铁桶/n 坚果/n 核桃/n 补脑/n 含铁/n 练成/v 铁头功/n
#   DROP  为什么/r 其实/d 是因为/c 但是/c 不过/c 也许/d 至少/d 现在/t
# ⛔ `l` (习用语, colloquial set phrase) is DELIBERATELY ABSENT — measured 2026-09-01, it was the
# single remaining hole in this filter. jieba tags multi-character narrative connectives as `l`, so
# they survived POS filtering and became motifs: `从那之后` ("from then on"), `发现自己`
# ("discovered oneself"), `一段时间` ("a period of time"), `随处可见` ("seen everywhere"),
# `毋庸置疑` ("undoubtedly"), `更进一步`, `并不知道`, `很难说`, `不多见` — 9 of the 11
# `l`-tagged motifs in the corpus were pure scaffolding.
#
# This is not cosmetic. `motif_coverage` REQUIRES a motif to appear in the generated text, so a junk
# motif becomes MANDATORY junk in committed content: `normalzombie` shipped named 「随处可见的消耗」
# ("Ubiquitous Attrition") and `flagzombie`'s doctrine forced in 「毋庸置疑的指令」. All 7 passed
# every gate — the same "a pass rate is not quality" failure this program keeps re-learning.
#
# The cost is 2 real motifs (`无人机` "drone", `绕道而行` "detour around"), accepted because a motif is
# a MANDATORY creative seed: a bad one corrupts output, a missing one costs nothing when the creature
# still has others. `i` (成语) is kept — idioms like `人心惶惶` are evocative, not scaffolding.
#: Content classes: nouns, verbs, adjectives, idioms. Everything else is scaffolding.
_CONTENT_POS = frozenset({
    "n", "nr", "ns", "nt", "nz", "ng", "nrt", "nrfg",
    "v", "vn", "vd", "vg", "vi", "vq",
    "a", "an", "ad", "ag",
    "i", "j", "s",
})


def _tokenize(text: str) -> list[str]:
    if _HAS_CJK.search(text):
        # POS-tagged segmentation (G1.2). `_CJK_STOPWORDS` survives as a small OVERRIDE for words
        # jieba mis-tags as content — it is no longer the primary mechanism.
        return [w for w, flag in pseg.cut(text)
                if _HAS_CJK.search(w) and flag in _CONTENT_POS and w not in _CJK_STOPWORDS]
    return [t.lower() for t in _ASCII_TOKEN.findall(text)]


def own_motifs(*, flavor_text: "str | None", name: str, cap: int = _MAX_MOTIFS) -> "tuple[list[str], str]":
    """A creature's own contribution before any family inheritance. Prefers flavour text (`basis =
    "text"`); falls back to the name (`basis = "name"`) when no text exists — §2.5's expected
    common case, since B3 measured most of the roster this thin. Longer tokens are treated as more
    distinctive than short ones (a real heuristic choice, documented rather than hidden): a
    4-character compound says more about a creature than a 1-character particle.
    """
    source, basis = (flavor_text, "text") if flavor_text else (name, "name")
    if not source:
        return [], "blocked"
    tokens = sorted(set(_tokenize(source)), key=lambda t: (-len(t), t))
    if not tokens:
        return [], "blocked"
    return tokens[:cap], basis


@dataclass(frozen=True)
class FamilyMembership:
    family_id: str
    basis: str  # the (creature, family) candidate's own basis from family-extract: "text" | "name"


@dataclass(frozen=True)
class CreatureMotifInput:
    species_id: str
    name: str
    flavor_text: "str | None"
    families: "tuple[FamilyMembership, ...]" = ()  # family-first order = membership order given


@dataclass(frozen=True)
class DerivedMotifs:
    motifs: "list[str]"
    anti_motifs: "list[str]"
    basis: str  # "text" | "name" | "blocked" — the WEAKEST basis among everything that contributed
    tautological: bool  # A2: this creature's OWN motifs and EVERY family it belongs to are basis="name"


_BASIS_RANK = {"text": 0, "name": 1, "blocked": 2}  # lower = stronger; combined basis is the weakest


def _weakest(bases: Sequence[str]) -> str:
    return max(bases, key=lambda b: _BASIS_RANK[b]) if bases else "blocked"


def derive_motifs(
    creatures: Sequence[CreatureMotifInput],
) -> "dict[str, DerivedMotifs]":
    """§2.2-§2.4, all three passes. Deterministic: sorted iteration everywhere ties could occur."""
    ordered = sorted(creatures, key=lambda d: d.species_id)

    # Pass 1 — own motifs, independent of family.
    own: "dict[str, tuple[list[str], str]]" = {
        d.species_id: own_motifs(flavor_text=d.flavor_text, name=d.name) for d in ordered
    }

    # Pass 2 — aggregate each family's pool from its members' own motifs, in speciesId order so
    # the pool itself is deterministic regardless of dict iteration order.
    family_members: "dict[str, list[str]]" = {}
    for d in ordered:
        for fm in d.families:
            family_members.setdefault(fm.family_id, []).append(d.species_id)

    family_pool: "dict[str, list[str]]" = {}
    for family_id, member_ids in family_members.items():
        pool: "list[str]" = []
        for sid in sorted(member_ids):
            for token in own[sid][0]:
                if token not in pool:
                    pool.append(token)
        family_pool[family_id] = pool

    # Pass 3 — per creature, family-first union then trim; anti-motifs from the nearest contrasting
    # family (fewest shared motifs among this creature's OWN family pools); basis is the weakest of
    # everything that actually contributed.
    result: "dict[str, DerivedMotifs]" = {}
    all_families_by_pool_overlap = family_pool  # for contrast lookup below

    for d in ordered:
        own_tokens, own_basis = own[d.species_id]
        family_bases = [fm.basis for fm in d.families]

        if not d.families and own_basis == "blocked":
            result[d.species_id] = DerivedMotifs(motifs=[], anti_motifs=[], basis="blocked", tautological=False)
            continue

        combined: "list[str]" = []
        for fm in d.families:  # family-first, membership order preserved
            for token in family_pool.get(fm.family_id, [])[:_FAMILY_SHARE]:
                if token not in combined:
                    combined.append(token)
        own_slice = own_tokens[:_OWN_SHARE if d.families else _MAX_MOTIFS]
        own_contributed = False
        for token in own_slice:
            if token not in combined:
                combined.append(token)
                own_contributed = True
        motifs = combined[:_MAX_MOTIFS]
        # A token dropped by the final [:​_MAX_MOTIFS] trim never really "contributed" — recompute
        # against what actually survived, so `basis` reflects the emitted motifs, not the scratch list.
        own_contributed = own_contributed and any(t in motifs for t in own_slice)

        # Anti-motifs: the family (among ALL families that exist, not just this creature's own) whose
        # pool shares the FEWEST tokens with this creature's own family pools — "the nearest OTHER
        # family" (§2.3). Only meaningful with >=1 family to contrast against another family.
        anti: "list[str]" = []
        own_family_ids = {fm.family_id for fm in d.families}
        candidate_others = {fid: pool for fid, pool in all_families_by_pool_overlap.items()
                            if fid not in own_family_ids}
        if own_family_ids and candidate_others:
            own_pool_tokens = set(motifs)
            nearest_other = min(
                sorted(candidate_others),  # deterministic tie-break, alphabetic
                key=lambda fid: len(own_pool_tokens & set(candidate_others[fid])),
            )
            anti = [t for t in candidate_others[nearest_other] if t not in own_pool_tokens][:_MAX_MOTIFS]

        # Weakest basis among everything that actually ended up in `motifs` — never among tokens
        # that were derived but then trimmed away, and never "blocked" poisoning a creature whose
        # family motifs did the real work (own_basis="blocked" only when own_tokens is empty, in
        # which case own_contributed is already False).
        contributing_bases = family_bases + ([own_basis] if own_contributed else [])
        basis = _weakest(contributing_bases) if contributing_bases else "blocked"
        # A2: tautological iff this creature's own motifs AND every family it belongs to are all
        # basis="name" — the case where motifs and family both trace back to the same bare string.
        tautological = own_basis == "name" and bool(d.families) and all(b == "name" for b in family_bases)

        result[d.species_id] = DerivedMotifs(
            motifs=motifs, anti_motifs=anti, basis=basis, tautological=tautological,
        )

    return result
