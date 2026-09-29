"""The names registry and the one loader every consumer reads (spec-names-registry.md, NS26).

Publish the one file that maps story tokens to display strings in a locale, with closed grammatical
feature tags: `gk-data/packs/fusion/data/seed/narrative/_registry/names.en.v1.json`, whose first rows are the three leads
(owner ruling R11). This is the file other programs consume directly — `identity-rename` points the
shipped surfaces at it, `ip-censor` scans it before a release, the runtime's `narrative-text` renders
from it, and `narrative-validators` reads it to refuse any literal name in generated text.

**A rename touches no seed.** No seed brief contains a display string (a brief carries tokens and tags
only), so changing `display` changes no brief hash and stales no seed. The loader never copies a
generated name into the authored file: character seeds are a second source, unioned at read time.

Read fresh on every call, never transcribed. The three feature enums are declared here AND in
`tokens.v1.json`; `load_names` refuses a tag the grammar does not own, so the two cannot drift.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from ...workspace_roots import content_root
from .token_grammar import Grammar, GrammarRefusal, load_grammar, slug_for

__all__ = [
    "DEFAULT_LOCALE",
    "SOURCES",
    "Article",
    "Gender",
    "Number",
    "NameMissing",
    "NameRow",
    "NameSet",
    "load_names",
    "normalise_display",
]

DEFAULT_LOCALE = "en"
#: Where a row came from. `registry` is the authored lead file; `character-seed` is generated output,
#: unioned at read time and never copied into the authored file.
SOURCES: "tuple[str, ...]" = ("registry", "character-seed")

_REGISTRY_DIR_REL = "data/seed/narrative/_registry"
_REGISTRY_NAME = "names.{locale}.v1.json"
_CHARACTERS_REL = "data/seed/narrative/characters"
_FILE_NAME = re.compile(r"^names\.([a-z]{2,3})\.v\d+\.json$")
_TOP_KEYS = frozenset({"schemaVersion", "registryVersion", "locale", "names"})
_ROW_KEYS = frozenset({"display", "article", "gender", "number", "ruling"})
_SEED_KEYS = frozenset({"schemaVersion", "kind", "_meta", "entries"})
_ENTRY_KEYS = frozenset({"id", "status", "name", "epithet", "grammar"})
_GRAMMAR_KEYS = frozenset({"gender", "number", "article", "epithetArticle"})
#: A display is Latin letters plus the three joiners. A strict allow-list until `script-check`'s
#: `latin` policy lands (spec §3 rule 3).
_DISPLAY_RE = re.compile(r"^[A-Za-z][A-Za-z '\-]*$")
#: `item/seed-contract.md` §5's connectives — dropped before a collision comparison.
_CONNECTIVES = frozenset({"of", "the", "a", "and"})
#: An article belongs in the tag, never at the head of the string.
_ARTICLE_WORDS = frozenset({"the", "a", "an"})


class Article(Enum):
    """Whether the name reads with "the". The registry never stores an article-bearing string: a
    message selects on this tag, so `_start` and the vocative `_bare` both come out of one row."""

    DEFINITE = "definite"
    NONE = "none"


class Gender(Enum):
    """What pronouns agree with. Grammar only, never a statement about the creature."""

    MALE = "male"
    FEMALE = "female"
    NEUTER = "neuter"
    NONE = "none"


class Number(Enum):
    """Verb and pronoun agreement. English v1 rows are `singular`; `plural` is reserved for group
    tokens, because `expand`'s pronoun forms assume the singular."""

    SINGULAR = "singular"
    PLURAL = "plural"
    NONE = "none"


class NameMissing(KeyError):
    """No row for a token. Named rather than a bare `KeyError`, and the message names the token."""

    def __init__(self, token: str) -> None:
        self.token = token
        super().__init__(f"names: no row for token {token!r}")


@dataclass(frozen=True)
class NameRow:
    """One name, from either source. `display` is the bare name; the three tags are closed enums."""

    token: str
    display: str
    article: Article
    gender: Gender
    number: Number
    source: str


@dataclass(frozen=True)
class NameSet:
    """The union a consumer reads: the authored lead rows plus every live character seed."""

    locale: str
    registry_version: int
    rows: "Mapping[str, NameRow]"

    def row(self, token: str) -> NameRow:
        try:
            return self.rows[token]
        except KeyError:
            raise NameMissing(token) from None

    def tokens(self) -> "tuple[str, ...]":
        return tuple(sorted(self.rows))

    def displays(self) -> "tuple[str, ...]":
        """Every display string in the union — what the no-literal-name rule inspects."""
        return tuple(sorted({row.display for row in self.rows.values()}))


def _refuse(reason: str, message: str) -> "GrammarRefusal":
    return GrammarRefusal(reason, message)


def normalise_display(display: str) -> str:
    """`item/seed-contract.md` §5's collision normalisation: lowercase, strip punctuation, drop the
    connectives, sort the remaining tokens. So `Ashen Fang` and `Fang of Ash` both read `ash fang`."""
    words = re.findall(r"[a-z0-9']+", display.lower())
    return " ".join(sorted(word for word in words if word not in _CONNECTIVES))


def _read_json(path: Path, label: str) -> "dict[str, Any]":
    if not path.exists():
        raise _refuse("registry_missing", f"{label} does not exist: {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise _refuse("registry_malformed", f"{label} must be a JSON object")
    return document


def _check_keys(document: "Mapping[str, Any]", allowed: "frozenset[str]", label: str) -> None:
    unknown = sorted(set(document) - allowed)
    if unknown:
        raise _refuse("registry_malformed", f"{label} has unknown key(s) {unknown} — allowed: "
                                            f"{sorted(allowed)}")
    missing = sorted(allowed - set(document))
    if missing:
        raise _refuse("registry_malformed", f"{label} is missing required key(s) {missing}")


def _tag(enum: "type[Enum]", value: Any, feature: str, grammar: Grammar, label: str) -> Any:
    """A tag member, refused unless the token grammar's own feature list owns the value — so a
    widened enum has to be a reviewed change in `tokens.v1.json` too."""
    if not isinstance(value, str) or value not in grammar.features[feature]:
        raise _refuse("unknown_tag",
                      f"{label}: {feature} {value!r} is outside the grammar's closed list "
                      f"{list(grammar.features[feature])}")
    return enum(value)


def _display(value: Any, label: str) -> str:
    """The five display refusals: empty, a digit, a brace, markup, an article word at the head, and
    any character outside Latin letters plus the three joiners."""
    if not isinstance(value, str) or not value.strip():
        raise _refuse("display_missing", f"{label}: display is empty")
    if value != value.strip():
        raise _refuse("display_whitespace", f"{label}: display {value!r} has leading/trailing whitespace")
    digit = next((char for char in value if char.isdigit()), None)
    if digit is not None:
        raise _refuse("display_digit", f"{label}: display {value!r} contains the digit {digit!r}")
    brace = next((char for char in value if char in "{}"), None)
    if brace is not None:
        raise _refuse("display_brace", f"{label}: display {value!r} contains {brace!r} — a display is "
                                       f"never a token")
    markup = next((char for char in value if char in "<>"), None)
    if markup is not None:
        raise _refuse("display_markup", f"{label}: display {value!r} contains {markup!r} — markup "
                                        f"belongs to the presentation layer")
    if not _DISPLAY_RE.match(value):
        raise _refuse("display_script", f"{label}: display {value!r} is outside Latin letters, space, "
                                        f"hyphen and apostrophe")
    head = value.split()[0].lower()
    if head in _ARTICLE_WORDS:
        raise _refuse("display_article", f"{label}: display {value!r} begins with the article word "
                                         f"{head!r} — the article is a tag")
    return value


def _check_unique(rows: "Mapping[str, NameRow]", label: str) -> None:
    """Uniqueness across the union, after §5 normalisation. A character that normalises onto a lead is
    refused; the loader is the backstop, generation-time `name_collision` is the first catch."""
    seen: "dict[str, str]" = {}
    for token in sorted(rows):
        key = normalise_display(rows[token].display)
        if key in seen:
            raise _refuse("normalised_collision",
                          f"{label}: {token!r} ({rows[token].display!r}) and {seen[key]!r} "
                          f"({rows[seen[key]].display!r}) both normalise to {key!r}")
        seen[key] = token


def _seed_rows(corpus_root: "Path | None", grammar: Grammar) -> "list[NameRow]":
    """Every live character seed as `c_<slug>` and `c_<slug>_epithet` rows. A missing corpus directory
    is an EMPTY SOURCE, not an error: until `character-pipeline` has run there are no seeds."""
    root = Path(corpus_root) if corpus_root is not None else content_root() / _CHARACTERS_REL
    if not root.is_dir():
        return []
    files = sorted(path for path in root.rglob("*.json") if path.is_file())
    entries: "list[tuple[Path, dict]]" = []
    for path in files:
        document = _read_json(path, str(path))
        _check_keys(document, _SEED_KEYS, str(path))
        if document["kind"] != "character":
            raise _refuse("character_seed_malformed",
                          f"{path}: kind must be 'character', got {document['kind']!r}")
        rows = document["entries"]
        if not isinstance(rows, list):
            raise _refuse("character_seed_malformed", f"{path}: entries must be a list")
        for entry in rows:
            if not isinstance(entry, dict):
                raise _refuse("character_seed_malformed", f"{path}: every entry must be an object")
            entries.append((path, entry))

    ids = [str(entry["id"]) for _path, entry in entries if isinstance(entry.get("id"), str)]
    rows: "list[NameRow]" = []
    for path, entry in entries:
        _check_keys(entry, _ENTRY_KEYS, f"{path}: entry {entry.get('id')!r}")
        identifier = str(entry["id"])
        if entry["status"] not in ("live", "tombstone"):
            raise _refuse("character_seed_malformed",
                          f"{path}: {identifier!r} status {entry['status']!r} is outside "
                          f"('live', 'tombstone')")
        if entry["status"] == "tombstone":
            continue
        if not identifier.startswith("character."):
            raise _refuse("character_seed_malformed",
                          f"{path}: {identifier!r} is not a character id (namespace 'character')")
        slug = slug_for(identifier, corpus=ids)
        tags = entry["grammar"]
        if not isinstance(tags, dict):
            raise _refuse("character_seed_malformed", f"{path}: {identifier!r} grammar must be an object")
        _check_keys(tags, _GRAMMAR_KEYS, f"{path}: {identifier!r} grammar")
        label = f"{path}: {identifier!r}"
        name = _keyed_text(entry["name"], f"{label} name")
        epithet = _keyed_text(entry["epithet"], f"{label} epithet")
        rows.append(NameRow(token=f"c_{slug}", display=_display(name, f"{label} name"),
                            article=_tag(Article, tags["article"], "article", grammar, label),
                            gender=_tag(Gender, tags["gender"], "gender", grammar, label),
                            number=_tag(Number, tags["number"], "number", grammar, label),
                            source="character-seed"))
        rows.append(NameRow(token=f"c_{slug}_epithet", display=_display(epithet, f"{label} epithet"),
                            article=_tag(Article, tags["epithetArticle"], "article", grammar, label),
                            gender=_tag(Gender, tags["gender"], "gender", grammar, label),
                            number=_tag(Number, tags["number"], "number", grammar, label),
                            source="character-seed"))
    return rows


def _keyed_text(value: Any, label: str) -> str:
    """Keyed text (`{key, text}`, contract §4) — the loader reads the string, never the key."""
    if not isinstance(value, dict) or not isinstance(value.get("text"), str):
        raise _refuse("character_seed_malformed", f"{label} must be keyed text with a string `text`")
    if not isinstance(value.get("key"), str) or not value["key"].strip():
        raise _refuse("character_seed_malformed", f"{label} carries no `key` (contract §4)")
    return value["text"]


def _lead_tokens(registry_path: Path) -> "dict[str, set[str]]":
    """The lead token set of every locale file beside the one being loaded. Locale parity: when a
    second locale file exists, its token set equals the first's."""
    siblings: "dict[str, set[str]]" = {}
    for path in sorted(registry_path.parent.glob("names.*.json")):
        match = _FILE_NAME.match(path.name)
        if match is None:
            continue
        document = _read_json(path, str(path))
        names = document.get("names")
        if not isinstance(names, dict):
            raise _refuse("registry_malformed", f"{path}: names must be an object")
        siblings[match.group(1)] = set(names)
    return siblings


def load_names(locale: str = DEFAULT_LOCALE, *, path: "Path | str | None" = None,
               corpus_root: "Path | str | None" = None, grammar: "Grammar | None" = None) -> NameSet:
    """Load and validate the names registry for `locale`, unioned with every live character seed.

    Refuses, naming the token and the value: an unknown or missing key; a `locale` that differs from
    the requested one or the file name's own code; a non-lead token in the file; a lead row that is
    missing (the grammar's lead family is closed); an empty, digit-bearing, brace-bearing,
    markup-bearing, article-headed or non-Latin display; a tag outside the grammar's closed feature
    list; a `plural` row in `en` v1; a malformed or tombstoned character seed; a display that
    normalises onto another row; and a locale file whose lead token set differs from the others'.
    """
    grammar = grammar if grammar is not None else load_grammar()
    registry_path = (Path(path) if path is not None
                     else content_root() / _REGISTRY_DIR_REL / _REGISTRY_NAME.format(locale=locale))
    document = _read_json(registry_path, "names registry")
    label = str(registry_path)
    _check_keys(document, _TOP_KEYS, label)
    if document["schemaVersion"] != 1:
        raise _refuse("registry_malformed", f"{label}: schemaVersion must be 1")
    if not isinstance(document["registryVersion"], int) or isinstance(document["registryVersion"], bool):
        raise _refuse("registry_malformed", f"{label}: registryVersion must be an integer")
    declared = document["locale"]
    if declared != locale:
        raise _refuse("locale_mismatch",
                      f"{label}: locale {declared!r} does not match the requested locale {locale!r}")
    match = _FILE_NAME.match(registry_path.name)
    if match and match.group(1) != declared:
        raise _refuse("locale_mismatch",
                      f"{label}: file name says locale {match.group(1)!r} but the document says "
                      f"{declared!r}")

    names = document["names"]
    if not isinstance(names, dict) or not names:
        raise _refuse("registry_malformed", f"{label}: names must be a non-empty object")

    rows: "dict[str, NameRow]" = {}
    for token, row in names.items():
        row_label = f"{label}: row {token!r}"
        if not isinstance(row, dict):
            raise _refuse("registry_malformed", f"{row_label} must be an object")
        _check_keys(row, _ROW_KEYS, row_label)
        if token not in grammar.leads:
            raise _refuse("non_lead_in_registry",
                          f"{row_label}: the authored file holds lead tokens only — a character name "
                          f"comes from its own seed")
        number = _tag(Number, row["number"], "number", grammar, row_label)
        if locale == "en" and number is not Number.SINGULAR:
            raise _refuse("plural_in_english",
                          f"{row_label}: number {number.value!r} — English v1 rows are singular, because "
                          f"`expand`'s pronoun forms assume it")
        if not isinstance(row["ruling"], str) or not row["ruling"].strip():
            raise _refuse("registry_malformed", f"{row_label}: ruling must name the owner ruling or "
                                                 f"'none'")
        rows[str(token)] = NameRow(token=str(token), display=_display(row["display"], row_label),
                                   article=_tag(Article, row["article"], "article", grammar, row_label),
                                   gender=_tag(Gender, row["gender"], "gender", grammar, row_label),
                                   number=number, source="registry")

    if set(rows) != set(grammar.leads):
        raise _refuse("lead_rows_incomplete",
                      f"{label}: the lead family is closed, so every locale file holds exactly "
                      f"{sorted(grammar.leads)}; got {sorted(rows)}")

    for row in _seed_rows(corpus_root, grammar):
        if row.token in rows:
            raise _refuse("duplicate_token",
                          f"{label}: {row.token!r} comes from both the authored file and a character seed")
        rows[row.token] = row

    _check_unique(rows, label)

    siblings = _lead_tokens(registry_path)
    expected = set(grammar.leads)
    for code, tokens in siblings.items():
        if tokens != expected:
            raise _refuse("locale_parity",
                          f"{label}: locale {code!r} declares lead tokens {sorted(tokens)}, not "
                          f"{sorted(expected)}")

    return NameSet(locale=declared, registry_version=int(document["registryVersion"]), rows=rows)
