"""`names-registry` (NS26, spec-names-registry.md) — the lead rows and the union with character seeds.

    python -m pytest gk-forge/tools/seedsmith/tests/test_narrative_names_registry.py -q -s

Fixture lead displays are invented (`Examplar Vane`, `Quietlark`) so a character-seed fixture never has
to carry a real name to prove the collision rule; only `lead_display_strings_follow_R11` reads the
committed file, because that row IS the owner's ruling. The committed file's row count is printed, never
asserted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.narrative.names import (  # noqa: E402
    Article,
    Gender,
    NameMissing,
    Number,
    load_names,
    normalise_display,
)
from seedsmith.adapters.narrative.token_grammar import GrammarRefusal, load_grammar  # noqa: E402
from seedsmith.briefkit.render import render_brief  # noqa: E402
from seedsmith.planner.schedule import Job  # noqa: E402

#: Invented fixture displays — one per lead token, with its tags.
FIXTURE_DISPLAYS = {
    "lead_summoner": ("Examplar Vane", "definite", "male"),
    "lead_companion": ("Quietlark", "none", "neuter"),
    "lead_antagonist": ("Vane", "definite", "male"),
}
LEADS = ("lead_summoner", "lead_companion", "lead_antagonist")


def _names_doc(displays: "dict | None" = None, locale: str = "en", **overrides) -> dict:
    rows = displays if displays is not None else FIXTURE_DISPLAYS
    doc = {
        "schemaVersion": 1,
        "registryVersion": 1,
        "locale": locale,
        "names": {
            token: {"display": display, "article": article, "gender": gender, "number": "singular",
                    "ruling": "R11"}
            for token, (display, article, gender) in rows.items()
        },
    }
    doc.update(overrides)
    return doc


def _write_names(tmp_path: Path, doc: "dict | None" = None, locale: str = "en") -> Path:
    path = tmp_path / f"names.{locale}.v1.json"
    path.write_text(json.dumps(doc if doc is not None else _names_doc(locale=locale)),
                    encoding="utf-8")
    return path


def _seed(tmp_path: Path, *, identifier: str = "character.marrow-fern", display: str = "Marrow Fern",
          epithet: str = "Quiet Root", status: str = "live", **grammar) -> Path:
    corpus = tmp_path / "characters" / "fixture"
    corpus.mkdir(parents=True, exist_ok=True)
    tags = {"gender": "female", "number": "singular", "article": "none", "epithetArticle": "definite"}
    tags.update(grammar)
    document = {
        "schemaVersion": 1,
        "kind": "character",
        "_meta": {"contractVersion": 1, "partition": "fixture"},
        "entries": [{
            "id": identifier,
            "status": status,
            "name": {"key": "ns.character.fixture.name.0", "text": display},
            "epithet": {"key": "ns.character.fixture.epithet.0", "text": epithet},
            "grammar": tags,
        }],
    }
    path = corpus / f"{identifier}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _load(tmp_path: Path, *, path: "Path | None" = None, corpus_root: "Path | None" = None,
          **overrides):
    return load_names("en", path=path if path is not None else _write_names(tmp_path),
                      corpus_root=corpus_root if corpus_root is not None else tmp_path / "characters",
                      **overrides)


def _load_written(tmp_path: Path):
    """Load whatever names file is already on disk, WITHOUT writing the default over it."""
    return load_names("en", path=tmp_path / "names.en.v1.json", corpus_root=tmp_path / "characters")


# --- the authored file ----------------------------------------------------------------------------

def test_lead_rows_are_exactly_the_three_leads(capsys) -> None:
    names = load_names()
    authored = {token: row for token, row in names.rows.items() if row.source == "registry"}
    # A declaration, with its reason: the grammar's lead family is closed (owner ruling R11), so a
    # fourth lead is a token-grammar change, never a row added here.
    assert set(authored) == set(LEADS)
    assert len(authored) == 3
    assert set(load_grammar().leads) == set(LEADS)
    print(f"reading: committed registry rows={len(names.rows)} authored={len(authored)} "
          f"locale={names.locale} registryVersion={names.registry_version}")


def test_lead_display_strings_follow_R11() -> None:
    names = load_names()
    summoner = names.row("lead_summoner")
    assert (summoner.display, summoner.article, summoner.gender) == ("Garden Keeper", Article.DEFINITE,
                                                                     Gender.MALE)
    companion = names.row("lead_companion")
    assert (companion.display, companion.article, companion.gender) == ("Hourbloom", Article.NONE,
                                                                        Gender.NEUTER)
    antagonist = names.row("lead_antagonist")
    assert (antagonist.display, antagonist.article, antagonist.gender) == ("Rotwright", Article.DEFINITE,
                                                                           Gender.MALE)
    with pytest.raises(NameMissing):
        names.row("c_nobody")


def test_feature_enums_match_the_grammar() -> None:
    features = load_grammar().features
    assert tuple(member.value for member in Article) == tuple(features["article"])
    assert tuple(member.value for member in Gender) == tuple(features["gender"])
    assert tuple(member.value for member in Number) == tuple(features["number"])


@pytest.mark.parametrize("display, reason", [
    ("The Examplar", "display_article"),
    ("Examplar2", "display_digit"),
    ("{lead_summoner}", "display_brace"),
    ("<em>Examplar</em>", "display_markup"),
    ("Examplar \u9f99", "display_script"),
    ("", "display_missing"),
    (" Examplar", "display_whitespace"),
])
def test_display_has_no_article_digit_brace_or_markup(tmp_path: Path, display: str, reason: str) -> None:
    doc = _names_doc()
    doc["names"]["lead_summoner"]["display"] = display
    with pytest.raises(GrammarRefusal) as raised:
        _load(tmp_path, path=_write_names(tmp_path, doc))
    assert raised.value.reason == reason


@pytest.mark.parametrize("field, value", [
    ("article", "indefinite"),
    ("gender", "other"),
    ("number", "dual"),
])
def test_tags_are_closed(tmp_path: Path, field: str, value: str) -> None:
    doc = _names_doc()
    doc["names"]["lead_summoner"][field] = value
    with pytest.raises(GrammarRefusal) as raised:
        _load(tmp_path, path=_write_names(tmp_path, doc))
    assert raised.value.reason == "unknown_tag"


def test_english_rows_are_singular(tmp_path: Path) -> None:
    doc = _names_doc()
    doc["names"]["lead_companion"]["number"] = "plural"
    with pytest.raises(GrammarRefusal) as raised:
        _load(tmp_path, path=_write_names(tmp_path, doc))
    assert raised.value.reason == "plural_in_english"


def test_non_lead_token_in_the_authored_file_is_refused(tmp_path: Path) -> None:
    doc = _names_doc()
    doc["names"]["c_marrow_fern"] = {"display": "Marrow Fern", "article": "none", "gender": "female",
                                     "number": "singular", "ruling": "none"}
    with pytest.raises(GrammarRefusal) as raised:
        _load(tmp_path, path=_write_names(tmp_path, doc))
    assert raised.value.reason == "non_lead_in_registry"


# --- the union with character seeds ---------------------------------------------------------------

def test_union_includes_character_seeds(tmp_path: Path) -> None:
    _seed(tmp_path)
    names = _load(tmp_path)
    assert set(names.tokens()) == set(LEADS) | {"c_marrow_fern", "c_marrow_fern_epithet"}
    name = names.row("c_marrow_fern")
    assert (name.display, name.article, name.gender, name.source) == ("Marrow Fern", Article.NONE,
                                                                      Gender.FEMALE, "character-seed")
    epithet = names.row("c_marrow_fern_epithet")
    assert (epithet.display, epithet.article) == ("Quiet Root", Article.DEFINITE)


def test_character_fixtures_are_invented() -> None:
    committed = {row.display for row in load_names().rows.values()}
    for _token, (display, _article, _gender) in FIXTURE_DISPLAYS.items():
        assert display not in committed
    assert "Marrow Fern" not in committed


def test_normalised_collision_is_refused(tmp_path: Path) -> None:
    # §5 sorts the remaining tokens, so word order does not save a collision.
    assert normalise_display("Vane Examplar") == normalise_display("Examplar Vane") == "examplar vane"
    _seed(tmp_path, display="Vane Examplar")
    with pytest.raises(GrammarRefusal) as raised:
        _load(tmp_path)
    assert raised.value.reason == "normalised_collision"
    assert "lead_summoner" in str(raised.value)


def test_tombstoned_character_contributes_nothing(tmp_path: Path) -> None:
    _seed(tmp_path, status="tombstone")
    names = _load(tmp_path)
    assert set(names.tokens()) == set(LEADS)


def test_missing_corpus_is_an_empty_source(tmp_path: Path) -> None:
    names = _load(tmp_path)
    assert set(names.tokens()) == set(LEADS)
    assert all(row.source == "registry" for row in names.rows.values())


def test_second_locale_must_match_token_set(tmp_path: Path) -> None:
    french = _names_doc(locale="fr")
    del french["names"]["lead_antagonist"]
    _write_names(tmp_path, french, locale="fr")
    with pytest.raises(GrammarRefusal) as raised:
        _load(tmp_path)
    assert raised.value.reason == "locale_parity"


# --- a rename touches no seed ---------------------------------------------------------------------

def test_rename_changes_no_brief_hash(tmp_path: Path) -> None:
    job = Job(partition="fixture", kind="storylet", entries=1, brief="fixture",
              model="fixture-model", constraints={}, closes=())
    before = _load(tmp_path)
    first = render_brief(job, vocabularies={"tokens": before.tokens()})

    renamed = dict(FIXTURE_DISPLAYS)
    renamed["lead_summoner"] = ("Renamed Keeper", "definite", "male")
    _write_names(tmp_path, _names_doc(displays=renamed))
    after = _load_written(tmp_path)
    second = render_brief(job, vocabularies={"tokens": after.tokens()})

    assert after.row("lead_summoner").display == "Renamed Keeper"
    assert first.content_hash == second.content_hash
    for display in before.displays():
        assert display not in first.text, "a brief must never carry a display string"
