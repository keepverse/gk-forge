"""`token-grammar` (NS25, spec-token-grammar.md) — the registry, `parse`, `expand` and the helpers.

    python -m pytest gk-forge/tools/seedsmith/tests/test_narrative_token_grammar.py -q -s

Fixtures are invented (`lead_example`, `c_examplar_vane`) and `test_fixtures_contain_no_real_name` proves
they stay that way: a real lead name may never appear in this module or its fixtures. The one test that
reads the committed registry prints its reading — a population is a reading, never a constant.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.narrative.token_grammar import (  # noqa: E402
    ARTICLE,
    FEATURES,
    FORMS,
    GENDER,
    NUMBER,
    PRONOUNS,
    RESERVED_SUFFIXES,
    SLOTS,
    Grammar,
    GrammarRefusal,
    Literal,
    Markup,
    Token,
    expand,
    literal_text,
    load_grammar,
    parse,
    render_for_brief,
    slug_for,
    tokens_used,
)
from seedsmith.workspace_roots import content_root  # noqa: E402

#: Invented fixture tokens. `lead_example` is not a real lead; `examplar-vane` is not a real character.
LEAD = "lead_example"
CHARACTER = "c_examplar_vane"

#: Every fixture string this module builds, so the no-real-name test can scan them all.
FIXTURE_STRINGS: "list[str]" = []


def _s(text: str) -> str:
    FIXTURE_STRINGS.append(text)
    return text


def _registry_doc(**overrides) -> dict:
    doc = {
        "schemaVersion": 1,
        "registryVersion": 1,
        "entityFamilies": {
            "lead": {"pattern": "^lead_[a-z][a-z0-9_]*$", "description": "the fixture lead family",
                     "negative": "not a fixture character"},
            "character": {"pattern": "^c_[a-z][a-z0-9_]*$", "description": "a fixture character",
                          "negative": "not a fixture lead"},
            "role": {"pattern": "^role_[a-z][a-z_]*$", "description": "a fixture role",
                     "negative": "not a fixture lead"},
        },
        "leads": {LEAD: {"description": "the fixture lead", "negative": "not a real lead"}},
        "forms": {name: {"description": f"fixture form {name}", "negative": f"not another form {name}"}
                  for name in FORMS},
        "pronouns": {name: {"description": f"fixture pronoun {name}",
                            "negative": f"not a chosen pronoun {name}"} for name in PRONOUNS},
        "slots": {name: {"description": f"fixture slot {name}", "negative": f"never write {name}"}
                  for name in SLOTS},
        "features": {name: list(values) for name, values in FEATURES.items()},
        "markup": {
            "em": {"shape": "paired", "description": "fixture stress", "negative": "not colour"},
            "whisper": {"shape": "paired", "description": "fixture quiet", "negative": "not a secret"},
            "shout": {"shape": "paired", "description": "fixture loud", "negative": "not capitals"},
            "pause": {"shape": "empty", "description": "fixture beat", "negative": "not a line break"},
        },
    }
    doc.update(overrides)
    return doc


def _grammar(tmp_path: Path, **overrides) -> Grammar:
    path = tmp_path / "tokens.v1.json"
    path.write_text(json.dumps(_registry_doc(**overrides)), encoding="utf-8")
    return load_grammar(path)


def _all_forms(grammar: Grammar) -> "list[tuple[str, str, str]]":
    """(text, family, form) for every family x form x pronoun, plus every slot and every tag."""
    cases: "list[tuple[str, str, str]]" = []
    for name, family in ((LEAD, "lead"), (CHARACTER, "character")):
        cases.append((f"{{{name}}}", family, "running"))
    for form in FORMS:
        if form == "epithet":
            cases.append((f"{{{CHARACTER}_{form}}}", "character", form))
        else:
            cases.append((f"{{{LEAD}_{form}}}", "lead", form))
            cases.append((f"{{{CHARACTER}_{form}}}", "character", form))
    for pronoun in PRONOUNS:
        cases.append((f"{{{LEAD}_{pronoun}}}", "lead", pronoun))
        cases.append((f"{{{CHARACTER}_{pronoun}}}", "character", pronoun))
    return cases


# --- the registry ---------------------------------------------------------------------------------

def test_every_token_family_form_slot_and_tag_has_description_and_negative(capsys) -> None:
    grammar = load_grammar()
    rows: "list[tuple[str, dict]]" = []
    for label, block in (("family", grammar.families), ("lead", grammar.leads), ("form", grammar.forms),
                         ("pronoun", grammar.pronouns), ("slot", grammar.slots),
                         ("markup", grammar.markup)):
        rows.extend((f"{label} {name!r}", row) for name, row in block.items())
    for label, row in rows:
        assert row["description"].strip(), f"{label} has no description"
        assert row["negative"].strip(), f"{label} has no negative clause"
    print(f"reading: registryVersion={grammar.registry_version} families={len(grammar.families)} "
          f"leads={len(grammar.leads)} forms={len(grammar.forms)} pronouns={len(grammar.pronouns)} "
          f"slots={len(grammar.slots)} tags={len(grammar.markup)} rows-with-clauses={len(rows)}")
    assert grammar.leads, "the grammar's lead family is closed but must not be empty"


def test_features_are_closed(tmp_path: Path) -> None:
    grammar = load_grammar()
    assert grammar.features == FEATURES
    assert tuple(grammar.features["gender"]) == GENDER
    assert tuple(grammar.features["number"]) == NUMBER
    assert tuple(grammar.features["article"]) == ARTICLE
    widened = _registry_doc()
    widened["features"]["gender"] = [*GENDER, "other"]
    path = tmp_path / "tokens.v1.json"
    path.write_text(json.dumps(widened), encoding="utf-8")
    with pytest.raises(GrammarRefusal) as raised:
        load_grammar(path)
    assert raised.value.reason == "registry_malformed"


# --- parse ----------------------------------------------------------------------------------------

def test_parse_accepts_every_form(tmp_path: Path) -> None:
    grammar = _grammar(tmp_path)
    for text, family, form in _all_forms(grammar):
        _s(text)
        segments = parse(text, grammar)
        assert len(segments) == 1, text
        segment = segments[0]
        assert isinstance(segment, Token), text
        assert (segment.family, segment.form) == (family, form), text
        assert segment.name == (LEAD if family == "lead" else CHARACTER), text
    for slot in SLOTS:
        _s(f"{{{slot}}}")
        segment = parse(f"{{{slot}}}", grammar)[0]
        assert isinstance(segment, Token) and (segment.family, segment.form) == ("slot", "running")
    for tag, shape in (("em", "paired"), ("whisper", "paired"), ("shout", "paired"), ("pause", "empty")):
        if shape == "empty":
            text = f"<{tag}/>"
            _s(text)
            assert parse(text, grammar) == (Markup(tag=tag, kind="empty"),)
        else:
            text = f"<{tag}>words</{tag}>"
            _s(text)
            assert parse(text, grammar) == (Markup(tag=tag, kind="open"), Literal("words"),
                                            Markup(tag=tag, kind="close"))
    mixed = _s("You are too late, {c_examplar_vane_bare} — <em>{lead_example_start} "
               "{lead_example_poss} {place}</em><pause/>")
    segments = parse(mixed, grammar)
    assert [type(s).__name__ for s in segments] == ["Literal", "Token", "Literal", "Markup", "Token",
                                                    "Literal", "Token", "Literal", "Token", "Markup",
                                                    "Markup"]
    assert parse("{role_guide}", grammar) == (Token("role", "role_guide", "running"),)


@pytest.mark.parametrize("text, reason", [
    ("{bogus}", "unknown_family"),
    ("{lead_example_bogus}", "unknown_family"),
    ("{c_1bad}", "malformed_slug"),
    ("{c_vane_article}", "reserved_suffix"),
    ("{role_guide_start}", "suffix_on_role"),
    ("{role_Guide}", "malformed_role"),
    ("{place_start}", "suffix_on_slot"),
    ("{lead_example_epithet}", "suffix_on_lead"),
    ("{c_examplar_vane_epithet_subj}", "epithet_takes_no_form"),
    ("hello {", "unbalanced_brace"),
    ("hello }", "stray_brace"),
    ("{a{b}", "stray_brace"),
    ("{}", "empty_token"),
    ("{lead_example_start, select, definite {the}}", "icu_in_short_form"),
    ("{lead_example_gender, select, male {he}}", "icu_in_short_form"),
    ("{lead_example} #1", "ok-outside-token-is-literature"),
    ("<b>x</b>", "unknown_tag"),
    ("<em>x", "unbalanced_tag"),
    ("</em>", "unbalanced_tag"),
    ("<pause>x</pause>", "unbalanced_tag"),
    ("<pause>", "unbalanced_tag"),
    ("<em><em>x</em></em>", "nested_tag"),
    ("a > b", "stray_angle"),
    ("{lead_example<x>}", "stray_angle"),
])
def test_parse_refuses_outside_the_grammar(tmp_path: Path, text: str, reason: str) -> None:
    grammar = _grammar(tmp_path)
    _s(text)
    if reason == "ok-outside-token-is-literature":
        # `#` is ICU syntax only INSIDE a token; in literal text it is an ordinary character.
        assert parse(text, grammar) == (Token("lead", LEAD, "running"), Literal(" #1"))
        return
    with pytest.raises(GrammarRefusal) as raised:
        parse(text, grammar)
    assert raised.value.reason == reason, text


# --- expand ---------------------------------------------------------------------------------------

def _running(argument: str) -> str:
    return ("{" + argument + "_article, select, definite {the {" + argument + "}} other {{"
            + argument + "}}}")


def _start(argument: str) -> str:
    return ("{" + argument + "_article, select, definite {The {" + argument + "}} other {{"
            + argument + "}}}")


def _pronoun(argument: str, male: str, female: str, neuter: str, other: str) -> str:
    return ("{" + argument + "_gender, select, male {" + male + "} female {" + female + "} neuter {"
            + neuter + "} other {" + other + "}}")


@pytest.mark.parametrize("argument", [LEAD, CHARACTER])
def test_expand_matches_the_table(tmp_path: Path, argument: str) -> None:
    grammar = _grammar(tmp_path)
    table = {
        f"{{{argument}}}": _running(argument),
        f"{{{argument}_start}}": _start(argument),
        f"{{{argument}_bare}}": f"{{{argument}}}",
        f"{{{argument}_subj}}": _pronoun(argument, "he", "she", "it", _running(argument)),
        f"{{{argument}_obj}}": _pronoun(argument, "him", "her", "it", _running(argument)),
        f"{{{argument}_poss}}": _pronoun(argument, "his", "her", "its", _running(argument) + "'s"),
    }
    for short, icu in table.items():
        _s(short)
        assert expand(short, grammar) == icu, short
    # Beyond §5's table: an epithet and a slot pass through as their own ICU argument, and a role takes
    # the running form (it is replaced by what the role was cast to).
    assert expand("{c_examplar_vane_epithet}", grammar) == "{c_examplar_vane_epithet}"
    assert expand("{place}", grammar) == "{place}"
    assert expand("{role_guide}", grammar) == _running("role_guide")


def test_expand_is_idempotent(tmp_path: Path) -> None:
    grammar = _grammar(tmp_path)
    message = _s("It's {lead_example_poss} turn, <em>{c_examplar_vane_start} — "
                 "{lead_example_bare} at {place}.</em>")
    once = expand(message, grammar)
    assert expand(once, grammar) == once
    # Already-expanded text is copied verbatim: its spans are not grammar tokens.
    assert expand(once, grammar) == once
    assert expand(_running(LEAD), grammar) == _running(LEAD)
    # Boundary, proven not glossed (module docstring): §5 gives `{T_bare}` -> `{T}`, so a message that is
    # ONLY a bare form expands to textually the running short form, and a second call reads it as one.
    assert expand(f"{{{LEAD}_bare}}", grammar) == f"{{{LEAD}}}"
    assert expand(expand(f"{{{LEAD}_bare}}", grammar), grammar) == _running(LEAD)


def _icu_arguments(message: str) -> "set[str]":
    """The argument names an expanded message references. A select's variant body is delimited by its own
    braces (`male {he}` contributes the literal `he`), so branch bodies are recursed into, not read."""
    arguments: "set[str]" = set()
    index = 0
    while index < len(message):
        if message[index] != "{":
            index += 1
            continue
        depth, cursor, comma = 0, index, -1
        while cursor < len(message):
            if message[cursor] == "{":
                depth += 1
            elif message[cursor] == "}":
                depth -= 1
                if depth == 0:
                    break
            elif message[cursor] == "," and depth == 1 and comma < 0:
                comma = cursor
            cursor += 1
        inner = message[index + 1: cursor]
        if comma > 0:
            arguments.add(inner[:comma - index - 1].strip())
            arguments |= _select_body_arguments(inner)
        elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", inner):
            arguments.add(inner)
        index = cursor + 1
    return arguments


def _select_body_arguments(inner: str) -> "set[str]":
    """The arguments inside a `<arg>, select, <key> {body} ...` span's bodies."""
    parts = inner.split(",", 2)
    if len(parts) < 3 or parts[1].strip() != "select":
        return set()
    rest, index, arguments = parts[2], 0, set()
    while index < len(rest):
        if rest[index] != "{":
            index += 1
            continue
        depth, cursor = 0, index
        while cursor < len(rest):
            if rest[cursor] == "{":
                depth += 1
            elif rest[cursor] == "}":
                depth -= 1
                if depth == 0:
                    break
            cursor += 1
        arguments |= _icu_arguments(rest[index + 1: cursor])
        index = cursor + 1
    return arguments


@pytest.mark.parametrize("argument", [LEAD, CHARACTER])
def test_expanded_arguments_are_closed(tmp_path: Path, argument: str) -> None:
    grammar = _grammar(tmp_path)
    closed = {argument, f"{argument}_article", f"{argument}_gender", f"{argument}_number"}
    for suffix in ("", "_start", "_bare", "_subj", "_obj", "_poss"):
        text = _s(f"{{{argument}{suffix}}}")
        assert _icu_arguments(expand(text, grammar)) <= closed, text
    for suffix in ("_subj", "_obj", "_poss"):
        arguments = _icu_arguments(expand(f"{{{argument}{suffix}}}", grammar))
        assert f"{argument}_gender" in arguments, suffix
        assert arguments <= closed, suffix


def test_apostrophes_survive_expansion(tmp_path: Path) -> None:
    grammar = _grammar(tmp_path)
    text = _s("It's {lead_example_poss} turn")
    expanded = expand(text, grammar)
    assert "It's " in expanded
    assert expanded.endswith(" turn")
    # The literal contraction and the possessive `'s` both survive as single apostrophes.
    assert expanded.count("'") == 2
    # An apostrophe that WOULD open an ICU quoted span is doubled, so it still renders as one apostrophe.
    escaped = expand(_s("a '#' sign and {lead_example}"), grammar)
    assert "''#'" in escaped


def test_literal_text_excludes_tokens(tmp_path: Path) -> None:
    grammar = _grammar(tmp_path)
    assert literal_text(_s("A {c_examplar_vane} speaks"), grammar) == "A  speaks"
    # A digit inside a slug is not prose; a digit in literal words is.
    assert literal_text(_s("{c_vane2} strikes"), grammar) == " strikes"
    assert "7" in literal_text(_s("plain 7 words"), grammar)
    assert tokens_used(_s("{c_examplar_vane_epithet} and {lead_example_start} at {place}"),
                       grammar) == {"c_examplar_vane_epithet", LEAD, "place"}


# --- slug_for -------------------------------------------------------------------------------------

def test_slug_for_is_deterministic_and_refuses_collisions() -> None:
    assert slug_for("character.examplar-vane") == "examplar_vane"
    assert slug_for("character.examplar-vane") == slug_for("character.examplar-vane")
    assert slug_for("character.vane-2", corpus=["character.vane-2", "character.other"]) == "vane_2"
    with pytest.raises(GrammarRefusal) as collision:
        slug_for("character.vane-2", corpus=["character.vane.2"])
    assert collision.value.reason == "slug_collision"
    with pytest.raises(GrammarRefusal) as reserved:
        slug_for("character.vane-epithet")
    assert reserved.value.reason == "reserved_suffix"
    for suffix in RESERVED_SUFFIXES:
        with pytest.raises(GrammarRefusal) as each:
            slug_for(f"character.vane{suffix}")
        assert each.value.reason == "reserved_suffix", suffix
    with pytest.raises(GrammarRefusal) as malformed:
        slug_for("character.2vane")
    assert malformed.value.reason == "malformed_slug"


# --- render_for_brief -----------------------------------------------------------------------------

def test_render_for_brief_inlines_descriptions(tmp_path: Path) -> None:
    grammar = _grammar(tmp_path)
    text = render_for_brief([LEAD, CHARACTER, "role_guide", "place"], grammar)
    for name in (LEAD, CHARACTER, "role_guide", "place"):
        line = next(line for line in text.splitlines() if line.startswith(f"{{{name}}}"))
        assert "Negative:" in line
    assert "the fixture lead" in text and "not a real lead" in text
    assert "a fixture character" in text and "not a fixture lead" in text
    assert "a fixture role" in text
    assert "never write place" in text
    assert "{reward}" not in text, "an undeclared token must not appear in the brief"
    with pytest.raises(GrammarRefusal) as unknown:
        render_for_brief(["bogus"], grammar)
    assert unknown.value.reason == "unknown_token"


# --- the no-real-name rule ------------------------------------------------------------------------

def test_fixtures_contain_no_real_name() -> None:
    names = json.loads((content_root() / "data/seed/narrative/_registry/names.en.v1.json")
                       .read_text(encoding="utf-8"))
    displays = [row["display"] for row in names["names"].values()]
    assert displays, "the names registry declares no display string — the scan would prove nothing"
    for display in displays:
        for fixture in FIXTURE_STRINGS:
            assert display not in fixture, f"a fixture carries the real name {display!r}"
