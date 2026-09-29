"""The story-text token grammar: the registry, `parse`, `expand` and the helpers (spec-token-grammar.md, NS25).

A story string has three parts and only one of them is words: literal text, **entity tokens** resolved
from the names registry and the runtime cast, and **semantic markup** the presentation layer renders. The
model writes the short forms below; `expand` rewrites them into the ICU MessageFormat lingui renders, so
the model never sees a real name and cannot leak one, and renaming a lead is one registry edit.

    {lead_summoner}   {c_<slug>}   {c_<slug>_epithet}   {role_<roleId>}   {place} {supply} {reward} {cost}

`parse` is the closure every validator uses: it is total over the grammar and refuses everything else with
a named reason. `expand` is the only writer of ICU; `literal_text` is the only part the prose rules
(digit-free, no-literal-name) inspect, so a digit inside a slug is not prose.

**The `_bare` boundary in `expand` (read before changing this module).** §5's table gives
`{T_bare}` -> `{T}` while `{T}` (the running form) expands to the article `select`, so the *output* of a
bare-only message is textually the running short form. `expand` is therefore idempotent **on
already-expanded text** — the spec's own wording — and not on a bare-only string, which is a short form,
not expanded text: a second call on it would read the bare argument as the running form. Every expansion
that produces an article or pronoun `select` is rescan-safe (its outer span is not a grammar token), so the
property holds for every message that carries one. Making it hold for a bare-only message too would need
§5's bare row to emit a select-bearing no-op; that is an owner/spec change, not a reader change.

Read fresh on every call, never transcribed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ...briefkit.render import BriefRefusal
from ...workspace_roots import content_root

__all__ = [
    "REGISTRY_REL",
    "FAMILIES",
    "FORMS",
    "PRONOUNS",
    "RESERVED_SUFFIXES",
    "GENDER",
    "NUMBER",
    "ARTICLE",
    "FEATURES",
    "SLUG_RE",
    "ROLE_ID_RE",
    "GrammarRefusal",
    "Literal",
    "Token",
    "Markup",
    "Grammar",
    "load_grammar",
    "parse",
    "expand",
    "tokens_used",
    "literal_text",
    "slug_for",
    "render_for_brief",
]

REGISTRY_REL = "data/seed/narrative/_registry/tokens.v1.json"

#: The three entity families the registry declares. The four runtime slots are the fourth family `Token`
#: carries; they live in their own block because they are filled by the game, not by a name.
FAMILIES: "tuple[str, ...]" = ("lead", "character", "role")
#: `epithet` is a character-only form; a lead, role or slot taking it is refused by name.
FORMS: "tuple[str, ...]" = ("start", "bare", "epithet")
PRONOUNS: "tuple[str, ...]" = ("subj", "obj", "poss")
SLOTS: "tuple[str, ...]" = ("place", "supply", "reward", "cost")
MARKUP_TAGS: "tuple[str, ...]" = ("em", "whisper", "shout", "pause")
#: Every suffix `expand` owns, plus the three ICU argument suffixes it creates. A slug or role id ending in
#: one is refused, so a token always parses one way (`_subj` cannot be a slug's own tail).
RESERVED_SUFFIXES: "tuple[str, ...]" = ("_epithet", "_start", "_bare", "_subj", "_obj", "_poss",
                                        "_article", "_gender", "_number")
#: The closed feature enums. A declaration: a new value is a reviewed change in this module AND in
#: `tokens.v1.json`, and `load_grammar` refuses a registry that disagrees.
GENDER: "tuple[str, ...]" = ("male", "female", "neuter", "none")
NUMBER: "tuple[str, ...]" = ("singular", "plural", "none")
ARTICLE: "tuple[str, ...]" = ("definite", "none")
FEATURES: "Mapping[str, tuple[str, ...]]" = {"gender": GENDER, "number": NUMBER, "article": ARTICLE}

#: The id grammar guarantees the leading letter (contract §3: body `[a-z0-9-]+` beginning with a letter).
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
ROLE_ID_RE = re.compile(r"^[a-z][a-z_]*$")

_TOP_KEYS = frozenset({"schemaVersion", "registryVersion", "entityFamilies", "leads", "forms",
                       "pronouns", "slots", "features", "markup"})
_FAMILY_KEYS = frozenset({"pattern", "description", "negative"})
_PROSE_KEYS = frozenset({"description", "negative"})
_MARKUP_KEYS = frozenset({"shape", "description", "negative"})
_SHAPES: "tuple[str, ...]" = ("paired", "empty")
_ICU_IN_SHORT_FORM = re.compile(r"\b(select|plural)\b")
#: An ICU argument used as a selector — the mark of text `expand` has already produced.
_EXPANDED = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*_(article|gender)\s*,\s*select")


class GrammarRefusal(BriefRefusal):
    """A string outside the grammar, or a registry that cannot serve it. `reason` is the closed name a
    test pins; `position` is the character index of the offending span (`None` for a registry defect)."""

    def __init__(self, reason: str, message: str, *, position: "int | None" = None) -> None:
        self.reason = reason
        self.position = position
        where = "" if position is None else f" at {position}"
        super().__init__(f"{reason}{where}: {message}")


@dataclass(frozen=True)
class Literal:
    """Literal words — the only segment the prose rules inspect."""

    text: str


@dataclass(frozen=True)
class Token:
    """An entity or slot token. `name` is the base spelling without any form/pronoun suffix
    (`c_<slug>`, never `c_<slug>_start`); `form` is one of `running`, a member of `FORMS`, or a pronoun."""

    family: str
    name: str
    form: str


@dataclass(frozen=True)
class Markup:
    """A semantic tag: `kind` is `open`, `close` or `empty`."""

    tag: str
    kind: str


@dataclass(frozen=True)
class Grammar:
    """A loaded, validated registry. Immutable; nothing in this package writes it."""

    registry_version: int
    families: "Mapping[str, Mapping[str, str]]"
    leads: "Mapping[str, Mapping[str, str]]"
    forms: "Mapping[str, Mapping[str, str]]"
    pronouns: "Mapping[str, Mapping[str, str]]"
    slots: "Mapping[str, Mapping[str, str]]"
    features: "Mapping[str, tuple[str, ...]]"
    markup: "Mapping[str, Mapping[str, str]]"

    def row_for(self, name: str) -> "tuple[str, Mapping[str, str]]":
        """The registry row that describes a declared token NAME, with its label. Refuses a name the
        grammar does not own."""
        if name in self.leads:
            return f"lead {name!r}", self.leads[name]
        if name.startswith("c_"):
            return f"character {name!r}", self.families["character"]
        if name.startswith("role_"):
            return f"role {name!r}", self.families["role"]
        if name in self.slots:
            return f"slot {name!r}", self.slots[name]
        raise GrammarRefusal("unknown_token", f"{name!r} is no lead, character, role or slot token")


def _refuse(reason: str, message: str, *, position: "int | None" = None) -> "GrammarRefusal":
    return GrammarRefusal(reason, message, position=position)


def _read_json(path: Path) -> "dict[str, Any]":
    if not path.exists():
        raise _refuse("registry_missing", f"the token grammar registry does not exist: {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise _refuse("registry_malformed", f"{path}: the registry must be a JSON object")
    return doc


def _check_keys(doc: "Mapping[str, Any]", allowed: "frozenset[str]", label: str) -> None:
    unknown = sorted(set(doc) - allowed)
    if unknown:
        raise _refuse("registry_malformed", f"{label} has unknown key(s) {unknown} — allowed: "
                                           f"{sorted(allowed)}")
    missing = sorted(allowed - set(doc))
    if missing:
        raise _refuse("registry_malformed", f"{label} is missing required key(s) {missing}")


def _prose(rows: "Mapping[str, Any]", label: str, *, keys: "frozenset[str]" = _PROSE_KEYS
           ) -> "dict[str, dict]":
    out: "dict[str, dict]" = {}
    for name, row in rows.items():
        if not isinstance(row, dict):
            raise _refuse("registry_malformed", f"{label} {name!r} must be an object")
        _check_keys(row, keys, f"{label} {name!r}")
        for key in keys:
            if not isinstance(row[key], str) or not row[key].strip():
                raise _refuse("registry_malformed", f"{label} {name!r} has no {key}")
        out[str(name)] = dict(row)
    return out


def _closed(rows: "Mapping[str, Any]", label: str, expected: "Sequence[str]") -> "dict[str, dict]":
    out = _prose(rows, label)
    if sorted(out) != sorted(expected):
        raise _refuse("registry_malformed",
                      f"{label} must be exactly {list(expected)}, got {sorted(out)}")
    return out


def load_grammar(path: "Path | str | None" = None) -> Grammar:
    """Load and validate `tokens.v1.json`.

    Refuses, naming the key: an unknown or missing key; a row without a description or a negative clause;
    a family pattern that is not a regex; a form, pronoun, slot, tag or feature set that is not exactly the
    closed declaration in this module; a markup `shape` outside `paired | empty`.
    """
    registry_path = Path(path) if path is not None else content_root() / REGISTRY_REL
    doc = _read_json(registry_path)
    label = str(registry_path)
    _check_keys(doc, _TOP_KEYS, label)
    if doc["schemaVersion"] != 1:
        raise _refuse("registry_malformed", f"{label}: schemaVersion must be 1")
    if not isinstance(doc["registryVersion"], int) or isinstance(doc["registryVersion"], bool):
        raise _refuse("registry_malformed", f"{label}: registryVersion must be an integer")

    families_raw = doc["entityFamilies"]
    if not isinstance(families_raw, dict):
        raise _refuse("registry_malformed", f"{label}: entityFamilies must be an object")
    families = _prose(families_raw, "family", keys=_FAMILY_KEYS)
    if sorted(families) != sorted(FAMILIES):
        raise _refuse("registry_malformed",
                      f"{label}: entityFamilies must be exactly {list(FAMILIES)}, got "
                      f"{sorted(families)}")
    for name, row in families.items():
        try:
            re.compile(str(row["pattern"]))
        except re.error as error:
            raise _refuse("registry_malformed",
                          f"{label}: family {name!r} pattern is not a regex ({error})") from None

    leads = _prose(doc["leads"], "lead")
    if not leads:
        raise _refuse("registry_malformed", f"{label}: leads must declare at least one lead token")
    for name in leads:
        if not re.match(families["lead"]["pattern"], name):
            raise _refuse("registry_malformed",
                          f"{label}: lead {name!r} does not match the lead family pattern")

    forms = _closed(doc["forms"], "form", FORMS)
    pronouns = _closed(doc["pronouns"], "pronoun", PRONOUNS)
    slots = _closed(doc["slots"], "slot", SLOTS)

    features_raw = doc["features"]
    if not isinstance(features_raw, dict):
        raise _refuse("registry_malformed", f"{label}: features must be an object")
    _check_keys(features_raw, frozenset(FEATURES), f"{label}: features")
    features: "dict[str, tuple[str, ...]]" = {}
    for name, expected in FEATURES.items():
        declared = features_raw[name]
        if not isinstance(declared, list) or tuple(declared) != tuple(expected):
            raise _refuse("registry_malformed",
                          f"{label}: feature {name!r} must be exactly {list(expected)}, got {declared!r}")
        features[name] = tuple(expected)

    markup_raw = doc["markup"]
    if not isinstance(markup_raw, dict):
        raise _refuse("registry_malformed", f"{label}: markup must be an object")
    markup = _prose(markup_raw, "markup", keys=_MARKUP_KEYS)
    if sorted(markup) != sorted(MARKUP_TAGS):
        raise _refuse("registry_malformed",
                      f"{label}: markup must be exactly {list(MARKUP_TAGS)}, got {sorted(markup)}")
    for name, row in markup.items():
        if row["shape"] not in _SHAPES:
            raise _refuse("registry_malformed",
                          f"{label}: markup {name!r} shape {row['shape']!r} is outside {list(_SHAPES)}")

    return Grammar(registry_version=int(doc["registryVersion"]), families=families, leads=leads,
                   forms=forms, pronouns=pronouns, slots=slots, features=features, markup=markup)


def _ends_reserved(text: str) -> "str | None":
    return next((suffix for suffix in RESERVED_SUFFIXES if text.endswith(suffix)), None)


def _split_form(body: str) -> "tuple[str, str]":
    """`(base, form)` — the longest owned suffix wins; no suffix means the running form."""
    for suffix, form in (("_epithet", "epithet"), ("_start", "start"), ("_bare", "bare"),
                         ("_subj", "subj"), ("_obj", "obj"), ("_poss", "poss")):
        if body.endswith(suffix) and len(body) > len(suffix):
            return body[: -len(suffix)], form
    return body, "running"


def _token(body: str, grammar: Grammar, position: int) -> Token:
    base, form = _split_form(body)
    if base in grammar.leads:
        family = "lead"
        if form == "epithet":
            raise _refuse("suffix_on_lead",
                          f"{body!r} uses the epithet form, which is a character form only",
                          position=position)
    elif base.startswith("c_"):
        family = "character"
        slug = base[2:]
        if slug.endswith("_epithet"):
            raise _refuse("epithet_takes_no_form",
                          f"the epithet form {base!r} takes no further form or pronoun suffix",
                          position=position)
        if not SLUG_RE.match(slug):
            raise _refuse("malformed_slug",
                          f"character slug {slug!r} must match ^[a-z][a-z0-9_]*$", position=position)
        reserved = _ends_reserved(slug)
        if reserved is not None:
            raise _refuse("reserved_suffix",
                          f"character slug {slug!r} ends in the reserved suffix {reserved!r}",
                          position=position)
    elif base.startswith("role_"):
        family = "role"
        role_id = base[5:]
        if form != "running":
            raise _refuse("suffix_on_role",
                          f"a role token takes the running form only, got {body!r}", position=position)
        if not ROLE_ID_RE.match(role_id):
            raise _refuse("malformed_role",
                          f"role id {role_id!r} must match ^[a-z][a-z_]*$", position=position)
        reserved = _ends_reserved(role_id)
        if reserved is not None:
            raise _refuse("reserved_suffix",
                          f"role id {role_id!r} ends in the reserved suffix {reserved!r}",
                          position=position)
    elif base in grammar.slots:
        family = "slot"
        if form != "running":
            raise _refuse("suffix_on_slot",
                          f"a runtime slot takes no form or pronoun suffix, got {body!r}",
                          position=position)
    else:
        raise _refuse("unknown_family",
                      f"{{{body}}} is neither a family token ({list(FAMILIES)}) nor a slot "
                      f"({list(grammar.slots)})", position=position)
    if family == "character" and form == "epithet":
        return Token(family=family, name=base, form=form)
    if family in ("lead", "character") and form not in ("running", "start", "bare", *PRONOUNS):
        raise _refuse("unknown_form", f"{body!r} names form {form!r}, outside the grammar",
                      position=position)
    return Token(family=family, name=base, form=form)


def parse(text: str, grammar: "Grammar | None" = None) -> "tuple[Literal | Token | Markup, ...]":
    """Split `text` into `Literal`, `Token` and `Markup` segments.

    Refuses, naming the position and the offending span: an unknown family or slot; a malformed slug; a
    form or pronoun suffix on a role or a slot; an unbalanced brace; a stray brace; a `<`/`>` inside a
    token; an empty token; an unknown or unbalanced tag; a tag nested inside the same tag; a stray angle
    bracket; and any `select`, `plural` or `#` in a short-form string (the model writes short forms only).
    """
    grammar = grammar if grammar is not None else load_grammar()
    segments: "list[Literal | Token | Markup]" = []
    buffer: "list[str]" = []
    open_tags: "list[str]" = []

    def flush() -> None:
        if buffer:
            segments.append(Literal("".join(buffer)))
            buffer.clear()

    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "{":
            flush()
            close = text.find("}", index + 1)
            if close < 0:
                raise _refuse("unbalanced_brace", f"the token opened at {index} never closes",
                              position=index)
            body = text[index + 1: close]
            if not body:
                raise _refuse("empty_token", "an empty token carries no family", position=index)
            # ICU syntax is checked first: an already-expanded span is also brace-bearing, and the
            # short-form string is what this closure refuses.
            if "#" in body or _ICU_IN_SHORT_FORM.search(body):
                raise _refuse("icu_in_short_form",
                              f"{body!r} carries ICU syntax; write the short form and let `expand` "
                              f"produce ICU", position=index)
            if "{" in body or "}" in body:
                raise _refuse("stray_brace", f"a literal brace inside the token {body!r}",
                              position=index)
            if "<" in body or ">" in body:
                raise _refuse("stray_angle", f"an angle bracket inside the token {body!r}",
                              position=index)
            segments.append(_token(body, grammar, index))
            index = close + 1
        elif char == "}":
            raise _refuse("stray_brace", "a closing brace with no open token", position=index)
        elif char == "<":
            flush()
            close = text.find(">", index + 1)
            if close < 0:
                raise _refuse("stray_angle", f"the tag opened at {index} never closes", position=index)
            body = text[index + 1: close]
            segments.append(_markup(body, open_tags, index, grammar))
            index = close + 1
        elif char == ">":
            raise _refuse("stray_angle", "a closing angle bracket with no open tag", position=index)
        else:
            buffer.append(char)
            index += 1
    flush()
    if open_tags:
        raise _refuse("unbalanced_tag",
                      f"tag(s) {open_tags} are never closed", position=length)
    return tuple(segments)


def _markup(body: str, open_tags: "list[str]", position: int, grammar: Grammar) -> Markup:
    if body.startswith("/"):
        tag = body[1:]
        if tag not in grammar.markup:
            raise _refuse("unknown_tag", f"</{tag}> is no markup tag", position=position)
        if not open_tags or open_tags[-1] != tag:
            raise _refuse("unbalanced_tag", f"</{tag}> closes nothing open here", position=position)
        open_tags.pop()
        return Markup(tag=tag, kind="close")
    if body.endswith("/"):
        tag = body[:-1]
        if tag not in grammar.markup:
            raise _refuse("unknown_tag", f"<{tag}/> is no markup tag", position=position)
        if grammar.markup[tag]["shape"] != "empty":
            raise _refuse("unbalanced_tag", f"<{tag}/> is a paired tag written empty", position=position)
        return Markup(tag=tag, kind="empty")
    if body not in grammar.markup:
        raise _refuse("unknown_tag", f"<{body}> is no markup tag", position=position)
    if grammar.markup[body]["shape"] != "paired":
        raise _refuse("unbalanced_tag", f"<{body}> is an empty tag written paired", position=position)
    if body in open_tags:
        raise _refuse("nested_tag", f"<{body}> nests inside itself", position=position)
    open_tags.append(body)
    return Markup(tag=body, kind="open")


def _icu_argument(token: Token) -> str:
    return f"{token.name}_epithet" if token.form == "epithet" else token.name


def _running(argument: str) -> str:
    return ("{" + argument + "_article, select, definite {the {" + argument + "}} other {{"
            + argument + "}}}")


def _start(argument: str) -> str:
    return ("{" + argument + "_article, select, definite {The {" + argument + "}} other {{"
            + argument + "}}}")


def _pronoun(argument: str, *, male: str, female: str, neuter: str, other: str) -> str:
    return ("{" + argument + "_gender, select, male {" + male + "} female {" + female + "} neuter {"
            + neuter + "} other {" + other + "}}")


def _expand_token(token: Token) -> str:
    """§5's expansion table, exactly. A slot and an epithet pass through as their own ICU argument."""
    argument = _icu_argument(token)
    if token.family == "slot" or token.form == "epithet":
        return "{" + argument + "}"
    if token.form == "running":
        return _running(argument)
    if token.form == "start":
        return _start(argument)
    if token.form == "bare":
        return "{" + argument + "}"
    if token.form == "subj":
        return _pronoun(argument, male="he", female="she", neuter="it", other=_running(argument))
    if token.form == "obj":
        return _pronoun(argument, male="him", female="her", neuter="it", other=_running(argument))
    if token.form == "poss":
        return _pronoun(argument, male="his", female="her", neuter="its",
                        other=_running(argument) + "'s")
    raise _refuse("unknown_form", f"{token.name!r} names form {token.form!r}, outside the grammar")


def _escape_icu(text: str) -> str:
    """Double an apostrophe that would otherwise open an ICU quoted span, so English contractions
    survive. A lone trailing apostrophe is literal in ICU and is left alone."""
    out: "list[str]" = []
    for index, char in enumerate(text):
        if char == "'" and index + 1 < len(text) and text[index + 1] in "{}#'":
            out.append("''")
        else:
            out.append(char)
    return "".join(out)


def _matching_brace(text: str, start: int) -> int:
    """The index of the `}` closing the `{` at `start`, counting nesting (an expanded ICU span nests);
    `-1` when it never closes."""
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _is_expanded(body: str) -> bool:
    """A span `expand` has already produced, or any other ICU the runtime owns: it carries a nested
    brace, a comma or a select/plural keyword, none of which a short form may contain."""
    return "{" in body or "," in body or bool(_ICU_IN_SHORT_FORM.search(body))


def expand(text: str, grammar: "Grammar | None" = None) -> str:
    """Rewrite the model's short forms into ICU MessageFormat, once.

    Markup passes through verbatim — mapping a tag to lingui's rich-text form is the codegen bridge's job.
    Literal apostrophes that would start an ICU quoted span are doubled. Text `expand` has already
    produced is returned unchanged (the `_EXPANDED` guard) and every ICU span it meets is copied
    verbatim, so a second call on an expanded message changes nothing; see the module docstring for the
    one boundary, a message that is only a bare form.
    """
    grammar = grammar if grammar is not None else load_grammar()
    if _EXPANDED.search(text):
        return text
    out: "list[str]" = []
    literal: "list[str]" = []

    def flush() -> None:
        if literal:
            out.append(_escape_icu("".join(literal)))
            literal.clear()

    index = 0
    while index < len(text):
        char = text[index]
        if char == "{":
            close = _matching_brace(text, index)
            if close < 0:
                raise _refuse("unbalanced_brace", f"the token opened at {index} never closes",
                              position=index)
            body = text[index + 1: close]
            flush()
            if _is_expanded(body):
                out.append(text[index: close + 1])
            else:
                out.append(_expand_token(_token(body, grammar, index)))
            index = close + 1
        elif char == "}":
            raise _refuse("stray_brace", "a closing brace with no open token", position=index)
        else:
            literal.append(char)
            index += 1
    flush()
    return "".join(out)


def tokens_used(text: str, grammar: "Grammar | None" = None) -> "frozenset[str]":
    """The token names `text` uses, with form and pronoun suffixes dropped and the epithet form kept —
    the shape a seed's `tokens` declaration carries."""
    return frozenset(
        f"{segment.name}_epithet" if segment.form == "epithet" else segment.name
        for segment in parse(text, grammar) if isinstance(segment, Token)
    )


def literal_text(text: str, grammar: "Grammar | None" = None) -> str:
    """The literal segments joined — the only part the digit-free and no-literal-name rules inspect."""
    return "".join(segment.text for segment in parse(text, grammar) if isinstance(segment, Literal))


def _slug_body(character_id: str) -> str:
    body = character_id.split(".", 1)[1] if "." in character_id else character_id
    return body.replace(".", "_").replace("-", "_")


def slug_for(character_id: str, *, corpus: "Iterable[str]" = ()) -> str:
    """The slug a character id resolves to: its body with `.` and `-` replaced by `_`.

    Refuses a slug that is not `^[a-z][a-z0-9_]*$`, one ending in a reserved suffix (so a token parses
    one way), and a collision — another id in `corpus` producing the same slug. The inverse is over the
    corpus, never string surgery.
    """
    slug = _slug_body(character_id)
    if not SLUG_RE.match(slug):
        raise _refuse("malformed_slug",
                      f"character id {character_id!r} yields slug {slug!r}, outside ^[a-z][a-z0-9_]*$")
    reserved = _ends_reserved(slug)
    if reserved is not None:
        raise _refuse("reserved_suffix",
                      f"character id {character_id!r} yields slug {slug!r}, ending in the reserved "
                      f"suffix {reserved!r}")
    collisions = sorted(other for other in corpus if other != character_id
                        and _slug_body(other) == slug)
    if collisions:
        raise _refuse("slug_collision",
                      f"character id {character_id!r} and {collisions} both yield slug {slug!r}")
    return slug


def render_for_brief(declared_tokens: "Sequence[str]", grammar: "Grammar | None" = None) -> str:
    """Each declared token with its registry description and negative clause, written literally into a
    brief. An undeclared token does not appear; a declared one the grammar does not own is refused."""
    grammar = grammar if grammar is not None else load_grammar()
    lines = []
    for name in declared_tokens:
        _label, row = grammar.row_for(str(name))
        lines.append(f"{{{name}}} — {row['description']} Negative: {row['negative']}")
    return "\n".join(lines)
