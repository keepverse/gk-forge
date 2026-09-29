"""G4 — commander-effect generator (spec-commander-effect.md). Zero real model calls."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from seedsmith.adapters.creatures.commander_effect import (
    COMMANDER_EFFECT_SCHEMA,
    ID_PREFIX,
    build_brief,
    build_context,
    entry_for,
    load_subjects,
)
from seedsmith.briefkit.render import CITATION_PATTERNS
from seedsmith.pipeline.model import audit_schema
from seedsmith.pipeline.open_loop import audit_open_loop_schema

CREATURES_ROOT = Path(__file__).resolve().parents[3] / "data" / "seed" / "creatures"

SUBJ = {
    "speciesId": "wallnut",
    "displayName": "坚果",
    "motifs": ["坚果", "外壳"],
    "antiMotifs": ["脆弱"],
    "basis": "text",
}


# ---- Brief and schema ---------------------------------------------------------------------------


def test_brief_inlines_motifs_anti_motifs_and_the_expression_rule():
    brief = build_brief(build_context(SUBJ))
    assert "坚果" in brief and "外壳" in brief
    assert "脆弱" in brief
    assert "doctrine" in brief.lower()


def test_brief_cites_nothing():
    """A brief saying 'motifs come from motifs.v1.json' invites invention — 51 invented tags,
    historically. The vocabulary is inlined literally instead."""
    brief = build_brief(build_context(SUBJ))
    for pattern in CITATION_PATTERNS:
        assert pattern.search(brief) is None, f"brief looks like a citation: {pattern.pattern}"


def test_schema_has_no_numeric_field():
    numeric = [d for d in audit_schema(COMMANDER_EFFECT_SCHEMA) if "numeric" in d.reason]
    assert numeric == []


def test_schema_has_no_verdict_field():
    assert audit_open_loop_schema(COMMANDER_EFFECT_SCHEMA) == []


# ---- The id collision that would fail corpus load ------------------------------------------------


def test_entry_id_is_namespaced():
    entry = entry_for("wallnut", {"name": "n", "doctrine": "d"}, basis="text")
    assert entry["id"] == "commander-effect.wallnut"
    assert entry["creatureId"] == "wallnut"


def test_an_unprefixed_id_collides_with_the_creature_and_fails_corpus_load():
    """`Corpus.add` raises on a duplicate id ACROSS ALL KINDS — `entries` is one global dict and
    only `by_kind` is partitioned. Asserted so a later refactor cannot lose the prefix."""
    from seedsmith.corpus.model import Corpus, CorpusLoadError, Entry

    c = Corpus()
    c.add(Entry(id="wallnut", kind="creature", partition="p", path="d.json", data={"id": "wallnut"}))
    with pytest.raises(CorpusLoadError):
        c.add(Entry(id="wallnut", kind="commander-effect", partition="p", path="c.json",
                    data={"id": "wallnut"}))
    c.add(Entry(id=ID_PREFIX + "wallnut", kind="commander-effect", partition="p", path="c.json",
                data={"id": ID_PREFIX + "wallnut"}))


# ---- Subject selection: a blocked creature generates nothing -----------------------------------------


def test_a_blocked_creature_is_not_a_subject(tmp_path):
    root = tmp_path / "creatures"
    (root / "_generated").mkdir(parents=True)
    (root / "creature").mkdir()
    (root / "creature" / "a.json").write_text(json.dumps(
        {"kind": "creature", "entries": [{"id": "ok", "name": "OK"}, {"id": "blk", "name": "B"}]}),
        encoding="utf-8")
    (root / "_generated" / "motif-assignments.json").write_text(json.dumps({
        "ok": {"motifs": ["m"], "antiMotifs": [], "basis": "text"},
        "blk": {"motifs": [], "antiMotifs": [], "basis": "blocked"},
    }), encoding="utf-8")

    ids = [s["speciesId"] for s in load_subjects(root)]
    assert ids == ["ok"], "a blocked creature must produce nothing — an answer, not a failure"


def test_real_corpus_subjects_all_carry_motifs():
    for s in load_subjects(CREATURES_ROOT):
        assert s["motifs"], f"{s['speciesId']} became a subject with no motifs"


def test_post_g1_subjects_do_not_carry_stat_vocabulary():
    """G1 must land before G4 runs: generating from 一类 ('armour-class one') or 优先 ('priority')
    would bake stat vocabulary into committed, append-only content."""
    banned = {"一类", "优先"}
    for s in load_subjects(CREATURES_ROOT):
        assert not (banned & set(s["motifs"])), f"{s['speciesId']} still carries stat vocabulary"


# ---- End to end against a fake model --------------------------------------------------------------


def _run(call, persisted):
    from seedsmith.workflow.graphs.commander_effect import build_commander_effect_graph
    from seedsmith.workflow.runner import run_one
    from seedsmith.workflow.state import new_state

    app = build_commander_effect_graph(
        on_persist=lambda k, v: persisted.__setitem__(k, v), call=call)
    ctx = build_context(SUBJ)
    return run_one(app, new_state("wallnut", brief=build_brief(ctx), context=ctx))


def test_generation_persists_a_clean_draft():
    pytest.importorskip("langgraph.graph")
    persisted = {}
    reply = json.dumps({"name": "坚果阵", "doctrine": "以外壳为盾，以坚果护位。"}, ensure_ascii=False)
    out = _run(lambda *a, **k: reply, persisted)
    assert out["outcome"] == "persisted"
    assert persisted["wallnut"]["name"] == "坚果阵"


def test_a_draft_using_an_anti_motif_is_rejected_then_repaired():
    pytest.importorskip("langgraph.graph")
    replies = [
        json.dumps({"name": "x", "doctrine": "这支部队很脆弱。"}, ensure_ascii=False),
        json.dumps({"name": "y", "doctrine": "以坚果为盾。"}, ensure_ascii=False),
    ]
    seen, persisted = [], {}

    def call(system, user, *, config=None, schema=None):
        seen.append(user)
        return replies[min(len(seen) - 1, len(replies) - 1)]

    out = _run(call, persisted)
    assert out["outcome"] == "persisted"
    assert out["attempts"] == 2
    assert "anti-motif" in seen[1], "the repair prompt must name the exact defect"


def test_a_field_echo_draft_is_rejected_and_never_persisted():
    pytest.importorskip("langgraph.graph")
    persisted = {}
    bad = json.dumps({"name": "x", "doctrine": "DOCTRINE: 以坚果为盾"}, ensure_ascii=False)
    out = _run(lambda *a, **k: bad, persisted)
    assert out["outcome"] == "escalated"
    assert persisted == {}, "the 7-of-8 'DOCTRINE:' defect must never reach the corpus"


# ---- Idempotency and staleness (plan CP-G4: "re-run produces zero new writes") -------------------


def test_entry_records_the_motifs_it_was_generated_from():
    e = entry_for("wallnut", {"name": "n", "doctrine": "d"}, basis="text", motifs=["坚果", "外壳"])
    assert e["_provenance"]["motifs"] == ["坚果", "外壳"]


def test_an_entry_whose_motifs_still_match_is_not_stale():
    from seedsmith.adapters.creatures.commander_effect import stale_ids

    entries = [entry_for("w", {"name": "n", "doctrine": "d"}, basis="text", motifs=["a", "b"])]
    subjects = [{"speciesId": "w", "motifs": ["a", "b"]}]
    assert stale_ids(entries, subjects) == []


def test_an_entry_generated_from_different_motifs_is_stale():
    """The real case: G1's `l`-tag fix changed 9 creatures' motifs, so their committed effects were
    generated from vocabulary that no longer exists."""
    from seedsmith.adapters.creatures.commander_effect import stale_ids

    entries = [entry_for("w", {"name": "n", "doctrine": "d"}, basis="text",
                         motifs=["从那之后", "僵尸"])]
    subjects = [{"speciesId": "w", "motifs": ["塔罗牌", "僵尸"]}]
    assert stale_ids(entries, subjects) == ["w"]


def test_an_entry_with_no_recorded_motifs_is_reported_stale():
    """It cannot be proven current. Silently assuming it is current is exactly how the theme
    registry rotted through four phases without a single gate noticing."""
    from seedsmith.adapters.creatures.commander_effect import stale_ids

    entries = [entry_for("w", {"name": "n", "doctrine": "d"}, basis="text")]
    assert stale_ids(entries, [{"speciesId": "w", "motifs": ["a"]}]) == ["w"]


def test_every_committed_entry_is_current_against_the_live_corpus():
    """The end-to-end invariant. Fails the moment motifs change without the effects being
    regenerated — the gap that let 7 creatures ship with narrative connectives forced into their
    doctrine by `motif_coverage`."""
    import json

    from seedsmith.adapters.creatures.commander_effect import stale_ids

    entries = json.loads(
        (CREATURES_ROOT / "commander-effect" / "all.json").read_text(encoding="utf-8"))["entries"]
    stale = stale_ids(entries, load_subjects(CREATURES_ROOT))
    assert stale == [], (
        f"{len(stale)} committed effect(s) were generated from outdated motifs — re-run "
        f"`python -m seedsmith.adapters.creatures.generate_commander_effects --stale`: {stale[:5]}")


def test_no_committed_effect_contains_a_narrative_connective():
    """Content-level guard, independent of the POS filter. If `l` ever creeps back into
    `_CONTENT_POS`, this fails on the shipped text rather than on a unit fixture."""
    import json

    entries = json.loads(
        (CREATURES_ROOT / "commander-effect" / "all.json").read_text(encoding="utf-8"))["entries"]
    banned = ("从那之后", "发现自己", "一段时间", "随处可见", "毋庸置疑",
              "更进一步", "并不知道", "很难说", "不多见")
    hits = [(e["creatureId"], t) for e in entries for t in banned
            if t in e["name"] or t in e["doctrine"]]
    assert hits == [], f"narrative connectives reached committed content: {hits}"
