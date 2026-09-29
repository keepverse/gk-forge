"""Tests for the character vocabulary registries and their readers (NS23, spec-character-vocab.md §3-§6).

    python -m pytest gk-forge/tools/seedsmith/tests/test_narrative_character_vocab.py -q

The committed registries are authored vocabularies: the assertions here are the CONTRACT (the runtime role
list, the disposition-band join, the R13 rules, the lead-token declaration) — never a row count.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from seedsmith.adapters.narrative.character_vocab import (  # noqa: E402
    CONTEXT_IDS,
    LEAD_TOKENS,
    PERSONAL_HISTORY_CONTEXTS,
    ROLE_IDS,
    VOICE_IDS,
    all_defects,
    disposition_bands,
    load_line_contexts,
    load_line_pairs,
    load_roles,
    load_voices,
    required_pairs,
    validate_line_pairs,
    validate_roles,
    validate_voice_exemplars,
    VOICE_REGISTERS,
    avoid_terms,
    exemplar_line_bounds,
    load_voice_exemplar,
)


def test_every_value_has_description_and_negative():
    rows = load_roles() + load_voices() + load_line_contexts() + load_line_pairs()["linePairs"]
    assert rows
    for row in rows:
        assert row["description"].strip(), row["id"]
        assert row["negative"].strip(), row["id"]


def test_the_committed_registries_are_clean():
    assert all_defects() == []


def test_voted_lists_have_none():
    assert "none" in ROLE_IDS and "none" in VOICE_IDS and "none" in CONTEXT_IDS
    assert {row["id"] for row in load_roles() if row["id"] == "none"}
    assert {row["id"] for row in load_voices() if row["id"] == "none"}
    assert {row["id"] for row in load_line_contexts() if row["id"] == "none"}


def test_roles_match_the_runtime_list():
    # The nine members pinned with the reason: the runtime's closed role list (§6.3); a change is reviewed
    # in both programs.
    assert ROLE_IDS == ("wanderer", "trader", "hermit", "chronicler", "clan-elder", "warlord", "captive",
                        "envoy", "companion", "none")
    assert [row["id"] for row in load_roles()] == list(ROLE_IDS)
    # A planted rogue role is reported by name.
    planted = [dict(row) for row in load_roles()]
    planted.append({"id": "bandit", "allegiance": "independent", "description": "d", "negative": "n"})
    assert any("runtime's nine" in d for d in validate_roles(planted))


def test_bands_are_the_disposition_file():
    bands = disposition_bands()
    assert bands == ("eager", "open", "wary", "hostile")
    for row in load_line_pairs()["linePairs"]:
        for pair in row["pairs"]:
            for band in pair["bands"]:
                assert band in bands, (row["id"], pair["context"], band)
    assert load_line_pairs()["bandsFrom"].endswith("disposition.v1.json")


def test_every_pair_names_known_context_and_band():
    document = load_line_pairs()
    known = {row["id"] for row in load_line_contexts() if row["id"] != "none"}
    for row in document["linePairs"]:
        for pair in row["pairs"]:
            assert pair["context"] in known, (row["id"], pair["context"])
            assert pair["bands"], (row["id"], pair["context"])
    # A planted unknown context and a planted unknown band are both reported.
    planted = json.loads(json.dumps(document))
    planted["linePairs"][0]["pairs"].append({"context": "smalltalk", "bands": ["warm"]})
    defects = validate_line_pairs(planted, load_line_contexts(), disposition_bands())
    assert any("no known line context" in d for d in defects)
    assert any("not a disposition band" in d for d in defects)


def test_antagonist_pairs_have_no_personal_history():
    antagonist = [row for row in load_line_pairs()["linePairs"] if row["id"] == "antagonist"][0]
    contexts = {pair["context"] for pair in antagonist["pairs"]}
    assert contexts == {"greet", "farewell", "taunt", "doctrine"}
    assert not (contexts & set(PERSONAL_HISTORY_CONTEXTS))
    # A planted personal-history pair on the antagonist is reported.
    planted = json.loads(json.dumps(load_line_pairs()))
    antagonist_row = [r for r in planted["linePairs"] if r["id"] == "antagonist"][0]
    antagonist_row["pairs"].append({"context": "thanks", "bands": ["eager"]})
    defects = validate_line_pairs(planted, load_line_contexts(), disposition_bands())
    assert any("R13 rule 3" in d for d in defects)


def test_joins_is_never_an_antagonist_pair():
    for row in load_line_pairs()["linePairs"]:
        if row["id"] == "antagonist":
            assert "joins" not in {pair["context"] for pair in row["pairs"]}
    planted = json.loads(json.dumps(load_line_pairs()))
    antagonist_row = [r for r in planted["linePairs"] if r["id"] == "antagonist"][0]
    antagonist_row["pairs"].append({"context": "joins", "bands": ["eager"]})
    defects = validate_line_pairs(planted, load_line_contexts(), disposition_bands())
    assert any("never an antagonist pair" in d for d in defects)


def test_leads_block_matches_the_three_lead_tokens():
    assert LEAD_TOKENS == ("lead_summoner", "lead_companion", "lead_antagonist")
    assert list(load_line_pairs()["leads"]) == list(LEAD_TOKENS)
    planted = json.loads(json.dumps(load_line_pairs()))
    planted["leads"] = ["lead_summoner", "lead_companion"]
    defects = validate_line_pairs(planted, load_line_contexts(), disposition_bands())
    assert any("R11" in d for d in defects)


def test_required_pairs_is_a_pure_function():
    document = load_line_pairs()
    first = required_pairs(document, "independent")
    second = required_pairs(document, "independent")
    assert first == second
    assert ("greet", "eager") in first and ("greet", "hostile") in first
    assert ("thanks", "hostile") not in first          # thanks is {eager, open} only
    assert required_pairs(document, "player") == frozenset()
    with pytest.raises(ValueError):
        required_pairs(document, "bandit")


def test_an_unknown_key_is_refused(tmp_path):
    doc = json.loads(json.dumps({"schemaVersion": 1, "registryVersion": 1, "voices": [
        {"id": "formal", "description": "d", "negative": "n", "extra": 1}]}))
    path = tmp_path / "voices.v1.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown key"):
        load_voices(path)


# ---------------------------------------------------------------------------------------------
# NS24 — voice exemplars (spec-character-vocab.md §4)
# ---------------------------------------------------------------------------------------------


def test_every_register_has_an_exemplar_that_loads():
    bounds = exemplar_line_bounds()
    assert bounds == (4, 8)                       # the budget block, not a code constant
    assert validate_voice_exemplars() == []
    for register in VOICE_REGISTERS:
        document = load_voice_exemplar(register)
        assert bounds[0] <= len(document["lines"]) <= bounds[1], register
        assert document["lexicon"]["signature"] and document["lexicon"]["forbidden"], register
    assert "none" not in VOICE_REGISTERS          # `none` is a refusal, not a register
    # The bound comes from the budget: a stricter bound reports every register, never a crash.
    assert all("outside the budget" in d for d in validate_voice_exemplars(bounds=(9, 12)))


def test_exemplar_lines_cite_no_other_franchise():
    # IC-3: the mark list is ip-censor's, never a private list here; an absent helper SKIPS with a
    # printed note rather than failing (the scan is a release gate, not a blocker).
    terms = avoid_terms()
    if not terms:
        print("voice exemplars: ip-censor's load_avoid_terms helper is absent in this tree -- "
              "skipping the mark check (IC-3)")
        return
    for register in VOICE_REGISTERS:
        for line in load_voice_exemplar(register)["lines"]:
            for term in terms:
                assert str(term).lower() not in line.lower(), (register, term)
