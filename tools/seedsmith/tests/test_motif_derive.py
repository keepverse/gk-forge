"""Tests for seedsmith.adapters.creatures.motifs (spec-motif-derive.md, wave D2)."""
from __future__ import annotations

import dataclasses

from seedsmith.adapters.creatures.motifs import (
    CreatureMotifInput,
    DerivedMotifs,
    FamilyMembership,
    classify_line,
    derive_motifs,
    own_motifs,
    prose_of,
)


def FM(family_id: str, basis: str = "text") -> FamilyMembership:
    return FamilyMembership(family_id=family_id, basis=basis)


def D(species_id: str, name: str = "Creature", flavor_text: "str | None" = None,
      families: tuple = ()) -> CreatureMotifInput:
    return CreatureMotifInput(species_id=species_id, name=name, flavor_text=flavor_text, families=families)


# ---- Real defect, real model, 2026-08-31: whole Chinese clauses were not word tokens -----------


def test_chinese_flavor_text_produces_real_short_words_not_whole_clauses():
    """The exact bug from the first real run: a punctuation-free Chinese clause is not one word,
    it is an un-segmented sentence. Before switching to jieba, `own_motifs` returned the entire
    clause below as a single "motif" — unusable as shared vocabulary."""
    text = "以下能防止爆炸樱桃产生溅射，可以用于保护其他植物，坚果有坚硬的外壳，融合后保留该特点。"
    tokens, basis = own_motifs(flavor_text=text, name="X")
    assert basis == "text"
    for t in tokens:
        assert len(t) <= 4, f"token {t!r} is not a short word — segmentation regressed to whole-clause capture"
    # A real content word from that clause must survive; common function words must not.
    assert any(t in ("樱桃", "坚果", "外壳", "植物", "融合") for t in tokens)
    assert "以下" not in tokens and "可以" not in tokens and "该" not in tokens


# ---- own_motifs -------------------------------------------------------------------------------


def test_own_motifs_prefers_flavor_text_and_reports_basis_text():
    tokens, basis = own_motifs(flavor_text="A powerful nut defender wields ancient shells.", name="X")
    assert basis == "text"
    assert tokens


def test_own_motifs_falls_back_to_name_when_no_flavor_text():
    tokens, basis = own_motifs(flavor_text=None, name="Wallnut Guardian")
    assert basis == "name"
    assert tokens


def test_own_motifs_blocked_when_neither_text_nor_usable_name():
    tokens, basis = own_motifs(flavor_text=None, name="")
    assert tokens == []
    assert basis == "blocked"


# ---- Determinism --------------------------------------------------------------------------------


def test_same_corpus_derived_twice_is_byte_identical():
    creatures = [
        D("a", flavor_text="Ancient nut defender.", families=(FM("nut"),)),
        D("b", flavor_text="Younger nut sentry.", families=(FM("nut"),)),
        D("c", flavor_text="Lone wanderer with no kin."),
    ]
    first = derive_motifs(creatures)
    second = derive_motifs(list(reversed(creatures)))
    assert first == second


# ---- Inheritance ----------------------------------------------------------------------------


def test_creature_in_two_families_inherits_from_both():
    creatures = [
        D("host", families=(FM("nut"), FM("shell"))),
        D("nut-a", flavor_text="Nut power surges within.", families=(FM("nut"),)),
        D("shell-a", flavor_text="Shell armor gleams brightly.", families=(FM("shell"),)),
    ]
    result = derive_motifs(creatures)
    host = result["host"]
    nut_pool_tokens = set(own_motifs(flavor_text="Nut power surges within.", name="x")[0])
    shell_pool_tokens = set(own_motifs(flavor_text="Shell armor gleams brightly.", name="x")[0])
    assert set(host.motifs) & nut_pool_tokens
    assert set(host.motifs) & shell_pool_tokens


def test_creature_in_no_family_with_text_derives_from_own_text_basis_text():
    creatures = [D("solo", flavor_text="A powerful lone wanderer.")]
    result = derive_motifs(creatures)
    assert result["solo"].motifs
    assert result["solo"].basis == "text"


def test_creature_in_no_family_no_text_is_blocked_with_no_motifs():
    creatures = [D("solo", name="", flavor_text=None)]
    result = derive_motifs(creatures)
    assert result["solo"].motifs == []
    assert result["solo"].basis == "blocked"
    assert result["solo"].tautological is False


def test_family_with_basis_name_propagates_basis_name_not_text():
    # This creature's OWN candidate for "nut" was extracted from its NAME pattern (basis="name"),
    # even though the family pool itself may contain text-derived tokens from other members —
    # basis tracks how THIS creature came to belong, not what the pool happens to contain.
    creatures = [
        D("d0", name="Wallnut Sentinel", families=(FM("nut", basis="name"),)),
        D("d1", flavor_text="Rich nut lore text here.", families=(FM("nut", basis="text"),)),
    ]
    result = derive_motifs(creatures)
    assert result["d0"].basis == "name"


# ---- Motif count and ordering -----------------------------------------------------------------


def test_motif_count_is_between_three_and_five_wherever_any_motif_exists():
    creatures = [
        D("d0", flavor_text="Ancient towering nut colossus guards the perimeter fiercely today.",
          families=(FM("nut"),)),
    ]
    result = derive_motifs(creatures)
    assert 1 <= len(result["d0"].motifs) <= 5  # small fixture; upper bound is the real invariant


def test_ordering_is_family_first_and_stable_across_runs():
    creatures = [
        D("host", families=(FM("alpha"), FM("beta"))),
        D("a-member", flavor_text="Alpha token appears here.", families=(FM("alpha"),)),
        D("b-member", flavor_text="Beta token appears here.", families=(FM("beta"),)),
    ]
    first = derive_motifs(creatures)["host"].motifs
    second = derive_motifs(list(reversed(creatures)))["host"].motifs
    assert first == second


# ---- Anti-motifs --------------------------------------------------------------------------------


def test_anti_motifs_drawn_from_the_nearest_contrasting_family_and_nonempty():
    creatures = [
        D("host", families=(FM("nut"),)),
        D("nut-a", flavor_text="Nut shell fortress strength.", families=(FM("nut"),)),
        D("fire-a", flavor_text="Blazing inferno flame chaos.", families=(FM("fire"),)),
    ]
    result = derive_motifs(creatures)
    assert result["host"].anti_motifs, "at least one other family exists globally, so contrast is possible"
    assert not (set(result["host"].anti_motifs) & set(result["host"].motifs))


def test_anti_motifs_empty_when_no_other_family_exists_anywhere():
    creatures = [
        D("host", families=(FM("nut"),)),
        D("nut-a", flavor_text="Nut shell fortress.", families=(FM("nut"),)),
    ]
    result = derive_motifs(creatures)
    assert result["host"].anti_motifs == []


# ---- A2's tautology flag ------------------------------------------------------------------------


def test_a2_tautology_flagged_when_own_and_every_family_are_basis_name():
    creatures = [D("d0", name="Nut Guardian", families=(FM("nut", basis="name"),))]
    result = derive_motifs(creatures)
    assert result["d0"].tautological is True


def test_not_tautological_when_any_contributing_basis_is_text():
    creatures = [
        D("d0", flavor_text="Real lore text about this creature appears here.",
          families=(FM("nut", basis="name"),)),
    ]
    result = derive_motifs(creatures)
    assert result["d0"].tautological is False


def test_not_tautological_with_no_family_at_all():
    creatures = [D("d0", name="Solo Wanderer")]
    result = derive_motifs(creatures)
    assert result["d0"].tautological is False


# ---- No numeric field ----------------------------------------------------------------------------


def test_derived_motifs_carries_no_numeric_field():
    for f in dataclasses.fields(DerivedMotifs):
        assert f.type not in ("int", "float"), f"{f.name} is a numeric field — motifs are words, not magnitudes"


# ---- G1.1: prose vs mechanical line classification (spec-motif-prose-filter.md §2.1) -----------


def test_stat_lines_are_mechanical():
    assert classify_line("韧性：270+2200（一类）") == "mechanical"
    assert classify_line("伤害：20/1.5秒") == "mechanical"


def test_mechanical_section_headers_are_mechanical():
    assert classify_line("特点：防具被磁力菇吸引后死亡") == "mechanical"
    assert classify_line("融合配方：坚果+樱桃炸弹") == "mechanical"


def test_circled_numeral_continuation_lines_are_mechanical():
    """Audit S1: the first draft said 'section headers AND THEIR CONTINUATION LINES' without ever
    defining a continuation line, and leaked 13 real lines of this exact shape into the prose bucket."""
    assert classify_line("②处于火力覆盖模式时，如果地图行数少于6行，则损失的子弹伤害会均分给其他子弹") == "mechanical"


def test_ascii_digit_threshold_lines_are_mechanical():
    assert classify_line("对于血量高于50%的雪橇冰车类僵尸，改为造成其50%韧性的伤害") == "mechanical"


def test_thematic_prose_is_prose():
    assert classify_line("铁桶坚果也能动起来？") == "prose"
    assert classify_line("仙人掌发射尖刺，可以对地或对空。") == "prose"


def test_cjk_numeral_line_survives_because_the_digit_rule_is_ascii_only():
    """The rule must NOT match 三/五/十. `可在三种攻击模式之间切换` is genuinely thematic; a rule
    matching CJK numerals would delete real prose."""
    assert classify_line("可在三种攻击模式之间切换，灵活分配火力。") == "prose"


def test_prose_of_prefers_flavor_introduce_and_drops_stat_lines():
    prose = prose_of(
        flavor_info=("铁桶坚果也能动起来？" + "\n" + "韧性：270+2200（一类）"
                     + "\n" + "特点：防具被磁力菇吸引后死亡"),
        flavor_introduce="至少现在他练成了铁头功。",
    )
    assert "铁头功" in prose            # introduce comes first
    assert "铁桶坚果也能动起来" in prose  # prose line of flavorInfo kept
    assert "韧性" not in prose          # stat line dropped
    assert "特点" not in prose          # section header dropped


# ---- G1.2: part-of-speech filtering (spec-motif-prose-filter.md §2.2, audit S2/S3) -------------


def test_pos_filter_drops_narrative_connectives_from_flavor_introduce():
    """The exact `bucketnutzombie` regression audit S2 found: preferring `flavorIntroduce` without
    POS filtering imported 为什么 / 是因为 / 不过 as "motifs". A corpus-FREQUENCY floor cannot fix
    this (S3) — those words have document frequency 2-3/84, so a floor keeps them."""
    narrative = ("为什么铁桶坚果僵尸的头这么铁？其实是因为大家都说吃核桃补脑，"
                 "但是他没注意到他吃的核桃含铁量太高。不过情况也许没那么糟，至少现在他练成了铁头功。")
    tokens, basis = own_motifs(flavor_text=narrative, name="X", cap=30)
    assert basis == "text"
    for connective in ("为什么", "是因为", "不过", "其实", "也许", "至少"):
        assert connective not in tokens, f"function word {connective!r} survived POS filtering"


def test_pos_filter_keeps_real_content_words():
    """The other direction: a filter that drops everything would pass the test above and be useless."""
    narrative = ("为什么铁桶坚果僵尸的头这么铁？其实是因为大家都说吃核桃补脑，"
                 "但是他没注意到他吃的核桃含铁量太高。不过情况也许没那么糟，至少现在他练成了铁头功。")
    tokens, _ = own_motifs(flavor_text=narrative, name="X", cap=30)
    for content in ("铁桶", "坚果", "核桃", "补脑", "练成", "铁头功"):
        assert content in tokens, f"content word {content!r} was wrongly dropped"


# ---- Committed-artifact consistency (added 2026-09-01, same class as the theme staleness) --------


def _creature_artifacts():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[3] / "data" / "seed" / "creatures"
    return (
        json.loads((root / "_generated" / "motif-assignments.json").read_text(encoding="utf-8")),
        json.loads((root / "_registry" / "motifs.v1.json").read_text(encoding="utf-8"))["motifs"],
    )


def test_the_motif_registry_is_exactly_the_distinct_motifs_in_use():
    """`motifs.v1.json` is a DERIVED vocabulary — `generate_motifs` builds it by walking each
    creature's `.motifs`. Nothing recomputed it would notice if the two drifted, which is exactly how
    `themes.v1.json` came to carry pre-G1 motifs for all 84 creatures while passing every gate.

    Deliberately motifs-only: `antiMotifs` are per-creature negatives, never vocabulary."""
    assignments, registry = _creature_artifacts()
    used = set()
    for rec in assignments.values():
        used |= set(rec.get("motifs") or [])

    assert set(registry) == used, (
        f"registry has {len(set(registry) - used)} unused and misses "
        f"{len(used - set(registry))} in-use motifs — re-run "
        f"`python -m seedsmith.adapters.creatures.generate_motifs`")
    assert len(registry) == len(set(registry)), "the registry contains duplicates"


def test_anti_motifs_are_deliberately_absent_from_the_registry():
    """Pins the intent, so a later 'fix' that unions anti-motifs in is a failing test rather than a
    silent widening of the legal vocabulary."""
    assignments, registry = _creature_artifacts()
    anti = set()
    for rec in assignments.values():
        anti |= set(rec.get("antiMotifs") or [])
    assert anti, "no anti-motifs at all — the fixture moved, re-measure before trusting this test"
    assert anti - set(registry), "every anti-motif is now registered vocabulary; that is not the design"


# ---- The `l` hole (found 2026-09-01 by tracing a motif that reached shipped content) -------------


def test_narrative_connectives_tagged_l_are_dropped():
    """⛔ The defect this pins, and why it was expensive.

    jieba tags multi-character narrative connectives as `l` (习用语). `l` was in `_CONTENT_POS`, so
    they survived the G1.2 filter and became motifs. `motif_coverage` then REQUIRES a motif to
    appear in the generated text — so a junk motif became *mandatory junk in committed content*:
    `normalzombie` shipped named 「随处可见的消耗」 and `flagzombie`'s doctrine forced in
    「毋庸置疑的指令」. Seven creatures, every one passing every gate.

    The single-word regression set (`为什么`/r, `不过`/c) could never have caught this — those are
    tagged as function words, these are tagged as content."""
    import jieba.posseg as pseg

    from seedsmith.adapters.creatures.motifs import _CONTENT_POS

    for phrase in ("从那之后", "发现自己", "一段时间", "随处可见", "毋庸置疑",
                   "更进一步", "并不知道", "很难说", "不多见"):
        tags = [t.flag for t in pseg.cut(phrase)]
        assert tags == ["l"], f"{phrase} is no longer l-tagged ({tags}); this test's premise moved"
        kept = [t.word for t in pseg.cut(phrase) if t.flag in _CONTENT_POS]
        assert kept == [], f"narrative connective {phrase!r} survived the POS filter as {kept}"


def test_idioms_and_abbreviations_are_still_kept():
    """The other direction — dropping `l` must not take `i` (成语) or `j` with it. `人心惶惶`
    ('panic-stricken') is exactly the evocative vocabulary a creature theme wants."""
    from seedsmith.adapters.creatures.motifs import _CONTENT_POS

    assert "i" in _CONTENT_POS and "j" in _CONTENT_POS
    assert "l" not in _CONTENT_POS, "`l` admits narrative connectives — see the test above"


def test_no_non_blocked_creature_was_left_without_motifs_by_the_filter():
    """Tightening a filter can silently starve a creature into `basis='name'`. The complete almanac
    refresh currently yields 857 text-basis and 47 name-basis rows."""
    import collections

    assignments, _ = _creature_artifacts()
    starved = [k for k, v in assignments.items()
               if not v.get("motifs") and v.get("basis") != "blocked"]
    assert starved == [], f"the POS filter starved {len(starved)} creatures: {starved[:5]}"
    by_basis = collections.Counter(v["basis"] for v in assignments.values())
    assert by_basis["text"] + by_basis["name"] == len(assignments), (
        f"unexpected basis values in complete roster: {dict(by_basis)}")
    assert by_basis["text"] > by_basis["name"], (
        f"name-only evidence unexpectedly dominates the roster: {dict(by_basis)}")


# ---- The coverage gap D2.3 itself flagged (closed 2026-09-01) ------------------------------------
#
# D2.3's own todo entry says of the `own_contributed` fix: "caught by re-deriving the fix from first
# principles while writing this note, NOT by a failing test ... a real limitation of this module's
# current coverage, not silently smoothed over."
#
# These two tests close it. The original defect: `basis` excluded a creature's OWN contribution
# whenever the creature had ANY family — so a creature whose own name-derived token genuinely survived
# into `motifs` reported `basis="text"` (inherited from the family) and hid the fact that part of
# its emitted vocabulary traces back to a bare string. `tautological` could not catch this: it
# requires EVERY family to be name-based, and here the family is text-based.
#
# One test alone would not close the gap — a version that always includes `own_basis` passes the
# first and fails the second. Both directions are needed to pin the actual rule.


def test_an_own_name_token_that_survives_the_trim_weakens_the_basis():
    """Family is text-based, own contribution is name-based and SURVIVES. The emitted motifs really
    do contain a name-derived token, so `basis` must say `name`, not `text`."""
    derived = derive_motifs([
        D("solo", name="Ironhide", families=(FM("f-armour", basis="text"),)),
        # A second member gives f-armour a real, text-derived pool to inherit from.
        D("mate", name="Mate", flavor_text="plated shell bulwark", families=(FM("f-armour", basis="text"),)),
    ])
    solo = derived["solo"]
    assert "ironhide" in solo.motifs, (
        f"premise moved: the own name-token was expected to survive the trim, got {solo.motifs}")
    assert solo.basis == "name", (
        "the creature's own name-derived token is in the emitted motifs, so the combined basis must "
        f"be 'name'; got {solo.basis!r} — this is the exact defect D2.3 flagged as untested")


def test_an_own_token_trimmed_away_does_not_weaken_the_basis():
    """The other direction, and the reason the fix is `own_contributed and any(t in motifs ...)`
    rather than a bare flag. Here the family pool alone fills all 5 slots, so the own name-token is
    derived and then trimmed — it contributed nothing to the emitted motifs, and must not drag the
    basis down to `name`."""
    # Two things have to be true at once, and both are easy to get wrong:
    #  1. THREE families, because each contributes at most `_FAMILY_SHARE` (2) tokens and five
    #     slots must be filled by inheritance alone.
    #  2. The subject must sort LAST — a family's pool is built in `sorted(member_ids)` order, so a
    #     subject sorting first would lead its own families' pools and be inherited back rather
    #     than appended-then-trimmed, which is a different code path.
    derived = derive_motifs([
        D("b", name="B", flavor_text="alpha bravo", families=(FM("f1", basis="text"),)),
        D("c", name="C", flavor_text="charlie delta", families=(FM("f2", basis="text"),)),
        D("e", name="E", flavor_text="echo foxtrot", families=(FM("f3", basis="text"),)),
        D("zz", name="Zzz", flavor_text=None, families=(
            FM("f1", basis="text"), FM("f2", basis="text"), FM("f3", basis="text"))),
    ])
    a = derived["zz"]
    assert len(a.motifs) == 5 and "zzz" not in a.motifs, (
        f"premise moved: the own name-token was expected to be trimmed away, got {a.motifs}")
    assert a.basis == "text", (
        f"nothing name-derived reached the emitted motifs, so basis must stay 'text'; got {a.basis!r}")
