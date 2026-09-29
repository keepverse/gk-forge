"""seedsmith.adapters.items.setgen.answers — the authored-answer transport, and the schema check
a replayed answer does not get for free.

⛔ **Why this exists at all.** Module 13 built everything a generation run needs except the step
that turns a brief into an answer, and recorded that gap as *"the generation graph is not wired,
and `--write` says so instead of writing nothing."* The graph's `generate` node takes an injected
`call` (`make_generate_node(..., call=...)`) precisely so the transport is replaceable — the same
seam `creature_anchor.py` and `effect_affix.py` already rely on for their tests. This module supplies
the transport that reads answers a model already authored, from a file, instead of opening a
socket. It imports nothing from `pipeline.llm_caller`, so a run driven by it **cannot** reach the
network, and a test asserts that by module text.

⚠ **Constrained decoding is what a live call gets and a replayed one does not.** `Pipeline`'s
`audit_schema` proves the SCHEMA is clean; a real endpoint additionally refuses to sample a
response that violates it. An authored answer arrives as plain JSON with no such guarantee, so the
schema has to be enforced here, on the way in. `schema_defects` is that enforcement — it is
deliberately a small walker over exactly the keywords these two schemas use
(`type`/`enum`/`required`/`additionalProperties`/`minItems`/`maxItems`/`minLength`/`maxLength`/
`pattern`) rather than a dependency: `jsonschema` is not in `pyproject.toml`'s pins, and adding a
runtime dependency to close a fifty-line gap is the wrong trade for a program whose central claim
is byte-identical reproducibility.

⭐ **A subject may carry MORE THAN ONE authored attempt, and that is not a convenience.** The graph
routes `validate -> generate` with the named defects appended when a draft is rejected, so a repair
pass is a real edge in the shipped design. A transport that could only answer once would make that
edge unreachable and quietly turn every rejection into an escalation. Attempts are consumed in
order; running out is `AnswerExhausted`, which is an honest escalation rather than a silent replay
of the answer that was already refused.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

#: The answer-file envelope this module reads. Bumped when the envelope changes, never when the
#: content schema does — the content schema is `setgen.schema`'s and is versioned by `promptVersion`.
ANSWER_FILE_SCHEMA_VERSION = 1


class AnswerFileError(ValueError):
    """The answer file is structurally unusable. Raised at load, before a single row is emitted."""


class AnswerMissing(LookupError):
    """No authored answer for a brief the run planned. Raised rather than defaulted: a generation
    run that silently skips a subject reports fewer rows than it planned and says nothing."""


class AnswerExhausted(LookupError):
    """Every authored attempt for this subject has already been consumed and the graph asked for
    another. The honest outcome is an escalation, not a replay of a refused draft.

    ⭐ **It carries the defects it was asked to repair.** The repair prompt is the only place those
    strings exist by the time the transport is reached — the graph appends them to the brief — and
    losing them would turn a precise refusal into *"the batch stopped."* `subject_id` and `defects`
    are what the batch driver turns into an escalated row.
    """

    def __init__(self, message: str, *, subject_id: str = "", defects: "tuple[str, ...]" = ()):
        super().__init__(message)
        self.subject_id = subject_id
        self.defects = tuple(defects)


#: `make_generate_node` appends rejected-attempt defects under this exact header. Read here rather
#: than re-derived: if the node's wording changes, this stops matching and the escalation loses its
#: reasons — which a test pins by driving a real repair pass.
REPAIR_HEADER = "Your previous attempt was REJECTED for:"


def defects_in_prompt(user: str) -> "tuple[str, ...]":
    """The named defects a repair prompt carries, or `()` for a first attempt."""
    _, _, tail = user.partition(REPAIR_HEADER)
    if not tail:
        return ()
    out: "list[str]" = []
    for line in tail.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            out.append(stripped[2:])
    return tuple(out)


@dataclass(frozen=True)
class AnswerFile:
    """`{subjectId: [attempt, ...]}` plus the envelope fields a run is checked against."""

    kind: str
    population: str
    prompt_version: str
    by_subject: "dict[str, tuple[dict, ...]]"

    @property
    def subject_ids(self) -> "tuple[str, ...]":
        return tuple(sorted(self.by_subject))

    def attempts_for(self, subject_id: str) -> "tuple[dict, ...]":
        return self.by_subject.get(subject_id, ())


def load_answers(path: Path) -> AnswerFile:
    """Parse and structurally check an authored-answer file.

    Refuses rather than defaults, for `tuning.py`'s stated reason: a generator running on a
    substituted value is how an unreviewed decision reaches every generated entry.
    """
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AnswerFileError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise AnswerFileError(f"{path} must hold a JSON object, got {type(doc).__name__}")

    version = doc.get("schemaVersion")
    if version != ANSWER_FILE_SCHEMA_VERSION:
        raise AnswerFileError(
            f"{path} declares schemaVersion {version!r}; this reader understands "
            f"{ANSWER_FILE_SCHEMA_VERSION} only")
    for key in ("kind", "population", "promptVersion", "answers"):
        if key not in doc:
            raise AnswerFileError(f"{path} is missing {key!r}")
    answers = doc["answers"]
    if not isinstance(answers, dict) or not answers:
        raise AnswerFileError(f"{path}'s `answers` must be a non-empty object keyed by subjectId")

    by_subject: "dict[str, tuple[dict, ...]]" = {}
    for subject_id, value in answers.items():
        attempts = value if isinstance(value, list) else [value]
        for attempt in attempts:
            if not isinstance(attempt, dict):
                raise AnswerFileError(
                    f"{path}: answer for {subject_id!r} is a {type(attempt).__name__}, not an object")
        if not attempts:
            raise AnswerFileError(f"{path}: answer list for {subject_id!r} is empty")
        by_subject[subject_id] = tuple(attempts)

    return AnswerFile(kind=str(doc["kind"]), population=str(doc["population"]),
                      prompt_version=str(doc["promptVersion"]), by_subject=by_subject)


# --------------------------------------------------------------------------------------------
# The schema check a replayed answer does not get from the endpoint.
# --------------------------------------------------------------------------------------------

def _declared_types(schema: "dict[str, Any]") -> "set[str]":
    declared = schema.get("type")
    return {declared} if isinstance(declared, str) else set(declared or ())


def _allows_null(schema: "dict[str, Any]") -> bool:
    """Whether an ABSENT key satisfies a `required` entry for this property.

    ⛔ 2026-09-08: `set_schema`/`charm_schema` moved every optional field from "absent from
    `required`" to "`required`, but typed `[X, "null"]`" — a concession the live endpoint's own
    constrained-decoding sampler needed (see `set_schema`'s own docstring for the evidence), not a
    new semantic requirement on hand-authored/replayed answers. A field typed this way must keep
    meaning exactly what an absent key always meant, so a required-but-nullable key that is simply
    MISSING from a replayed draft is not a defect — only a required, NON-nullable key missing
    still is.
    """
    return "null" in _declared_types(schema)


def schema_defects(draft: Any, schema: "dict[str, Any]", *, path: str = "$") -> "list[str]":
    """Every way `draft` violates `schema`, as messages naming the field AND the offending value.

    The strings become the repair prompt (`make_validate_node`'s own contract), so "the field is
    wrong" is never enough — the message says which value was seen and what was legal.

    `type` may be a bare string or a list including `"null"` (`set_schema`/`charm_schema`'s
    2026-09-08 required+nullable fields) — `draft is None` is checked once, up front, against
    whichever of those two shapes declared it.
    """
    types = _declared_types(schema)

    if draft is None:
        if "null" in types or not types:
            return []
        return [f"{path}: expected {sorted(types)}, got null"]

    concrete = next((t for t in types if t != "null"), None)
    defects: "list[str]" = []

    if concrete == "object":
        if not isinstance(draft, dict):
            return [f"{path}: expected an object, got {type(draft).__name__}"]
        properties = schema.get("properties") or {}
        for key in schema.get("required") or ():
            if key not in draft and not _allows_null(properties.get(key) or {}):
                defects.append(f"{path}: required field {key!r} is missing")
        if schema.get("additionalProperties") is False:
            for key in draft:
                if key not in properties:
                    defects.append(
                        f"{path}: unknown field {key!r} — the schema is closed, and the legal "
                        f"fields are {sorted(properties)}")
        for key, sub in properties.items():
            if key in draft:
                defects.extend(schema_defects(draft[key], sub, path=f"{path}.{key}"))
        return defects

    if concrete == "array":
        if not isinstance(draft, list):
            return [f"{path}: expected an array, got {type(draft).__name__}"]
        low, high = schema.get("minItems"), schema.get("maxItems")
        if low is not None and len(draft) < low:
            defects.append(f"{path}: {len(draft)} entries is below the minimum of {low}")
        if high is not None and len(draft) > high:
            defects.append(f"{path}: {len(draft)} entries is above the maximum of {high}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(draft):
                defects.extend(schema_defects(item, item_schema, path=f"{path}[{index}]"))
        return defects

    if concrete == "string":
        if not isinstance(draft, str):
            return [f"{path}: expected a string, got {type(draft).__name__}"]
        enum = schema.get("enum")
        if enum is not None and draft not in enum:
            defects.append(f"{path}: {draft!r} is not one of {list(enum)}")
        low, high = schema.get("minLength"), schema.get("maxLength")
        if low is not None and len(draft) < low:
            defects.append(f"{path}: {len(draft)} characters is below the minimum of {low}")
        if high is not None and len(draft) > high:
            defects.append(f"{path}: {len(draft)} characters is above the maximum of {high}")
        pattern = schema.get("pattern")
        if pattern is not None and not re.search(pattern, draft):
            defects.append(f"{path}: {draft!r} does not match the required pattern {pattern}")
        return defects

    if concrete == "integer":
        # `bool` is an `int` in Python and would slip through a bare isinstance check.
        if isinstance(draft, bool) or not isinstance(draft, int):
            return [f"{path}: expected an integer, got {type(draft).__name__}"]
        enum = schema.get("enum")
        if enum is not None and draft not in enum:
            defects.append(f"{path}: {draft} is not one of {list(enum)}")
        return defects

    return defects


# --------------------------------------------------------------------------------------------
# The transport itself.
# --------------------------------------------------------------------------------------------

class ReplayTransport:
    """A `call(system, user, *, config, schema)` that returns an AUTHORED answer, never a live one.

    ⚠ **Two ways to know which subject is being answered, and the reliable one is preferred.**
    `make_generate_node` hands its caller `(system, user)` and nothing else — by design, a transport
    has no business knowing what a subject is. So the fallback is *longest brief that prefixes the
    prompt* (a repair pass appends the named defects, hence prefix and not equality).

    ⛔ **That fallback is not sufficient on its own, and pretending otherwise cross-serves answers.**
    Two subjects built from the same theme produce byte-identical briefs — `re_running_over_
    unchanged_themes_is_byte_identical` is module 13's own guarantee that they do — and the prefix
    match then silently hands subject A's answer to subject B. Found by a test that planted exactly
    that case. So the batch driver, which runs subjects one at a time, sets `current_subject_id`
    before each call and the transport uses it; the prefix path is the fallback, and an ambiguous
    prefix RAISES rather than picking one.
    """

    def __init__(self, briefs: "dict[str, str]", answers: AnswerFile,
                 *, seen: "dict[str, int] | None" = None):
        self._briefs = dict(briefs)
        self._answers = answers
        self._consumed = seen if seen is not None else {}
        self._ordered = sorted(briefs.items(), key=lambda kv: -len(kv[1]))
        #: Set by the batch driver before each subject. `None` means "recover it from the prompt".
        self.current_subject_id: "str | None" = None

    def _subject_for(self, user: str) -> str:
        if self.current_subject_id is not None:
            return self.current_subject_id
        matches = [sid for sid, brief in self._ordered if brief and user.startswith(brief)]
        if not matches:
            raise AnswerMissing(
                "the prompt does not begin with any planned subject's brief — the answer file and "
                "the run plan were assembled from different inputs")
        longest = len(self._briefs[matches[0]])
        tied = [sid for sid in matches if len(self._briefs[sid]) == longest]
        if len(tied) > 1:
            raise AnswerMissing(
                f"the prompt matches {len(tied)} subjects with identical briefs ({sorted(tied)}) — "
                f"the transport cannot tell them apart, and guessing would serve one subject's "
                f"answer as another's. Drive the batch subject by subject instead")
        return matches[0]

    def __call__(self, system: str, user: str, *, config=None, schema=None) -> str:  # noqa: ARG002
        subject_id = self._subject_for(user)
        attempts = self._answers.attempts_for(subject_id)
        if not attempts:
            raise AnswerMissing(
                f"no authored answer for subject {subject_id!r} — the run planned it and the "
                f"answer file does not carry it")
        index = self._consumed.get(subject_id, 0)
        if index >= len(attempts):
            raise AnswerExhausted(
                f"subject {subject_id!r} has {len(attempts)} authored attempt(s) and the graph "
                f"asked for attempt {index + 1}; the previous draft was refused and there is no "
                f"repaired answer to serve",
                subject_id=subject_id, defects=defects_in_prompt(user))
        self._consumed[subject_id] = index + 1
        return json.dumps(attempts[index], ensure_ascii=False)


def replay_caller(briefs: "dict[str, str]", answers: AnswerFile,
                  *, seen: "dict[str, int] | None" = None) -> ReplayTransport:
    return ReplayTransport(briefs, answers, seen=seen)
