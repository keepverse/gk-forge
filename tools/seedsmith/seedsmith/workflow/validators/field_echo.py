"""`field_echo` and `non_empty` (spec-quality-gates.md §2.2)."""
from __future__ import annotations

import re
from typing import Any, Mapping

__all__ = ["field_echo", "non_empty", "subject_name_echo"]

#: A separator after the echoed name is what distinguishes prompt leakage from legitimate prose.
#: `"DOCTRINE: ..."` is leakage; `"The doctrine of the Shell"` is a real sentence, and a rule that
#: rejected any mention of the field name would pass its own rejection test while breaking prose.
_SEPARATORS = (":", "：", "-", "—", "–", "=")


def field_echo(draft: "Mapping[str, Any]", context: "Mapping[str, Any]") -> "list[str]":
    """Reject a field whose value opens with its own name followed by a separator.

    ⛔ Observed defect: **7 of 8 outputs** in the real run began `"DOCTRINE: ..."` — the model
    echoing the prompt's field label into the value. Nothing caught it, and it would have shipped
    into the corpus. Small, and it generalises to any workflow."""
    defects: "list[str]" = []
    for name, value in draft.items():
        if not isinstance(value, str):
            continue
        stripped = value.lstrip()
        head = stripped[:len(name)]
        if head.lower() != name.lower():
            continue
        rest = stripped[len(name):].lstrip()
        if rest[:1] in _SEPARATORS:
            defects.append(
                f"field {name!r} echoes its own name back as a label "
                f"({stripped[:len(name) + 2]!r}...) — return the value only")
    return defects


def non_empty(draft: "Mapping[str, Any]", context: "Mapping[str, Any]") -> "list[str]":
    """Shape backstop behind constrained decoding: required fields must carry real content."""
    required = context.get("requiredFields") or []
    defects: "list[str]" = []
    for name in required:
        value = draft.get(name)
        if not isinstance(value, str) or not value.strip():
            defects.append(f"field {name!r} is missing or empty (got {value!r})")
    return defects


#: What a message calls the thing that collided when the caller does not say.
#:
#: FIXED DEFECT. Both messages below used to hardcode `commander effect` / `the creature's`, and
#: `subject_name_echo`'s ONLY caller is the passive-tree node path
#: (`adapters/trees/nodegen/run.py`) — so every node refusal told the operator it was a commander
#: effect named after a creature. `adapters/dungeon/pipelines.py` already does this correctly at four
#: sites ("another event", "another encounter", "another room", "another domain"), so the shared
#: primitive was the one place out of step with the convention. The cost was measurable, not cosmetic:
#: because the message names the kind, a 12.5 MB BCU2.12 failure ledger read as 984 distinct shapes
#: until the quoted name was masked out.
#:
#: The kind travels in `context` rather than a new parameter, so `name_collision` stays a pure
#: function of `(draft, context)` and stays testable without a corpus — the property its own
#: docstring claims.
DEFAULT_SUBJECT_KIND = "generated entry"


def _subject_kind(context: "Mapping[str, Any]") -> str:
    kind = str(context.get("subjectKind") or "").strip()
    return kind or DEFAULT_SUBJECT_KIND


def subject_name_echo(draft: "Mapping[str, Any]", context: "Mapping[str, Any]") -> "list[str]":
    """Reject a `name` that is just the subject's own display name.

    ⛔ Found by `SemanticDedup/NearDuplicate` on the FIRST real run, not by any per-item check:
    **83 of 83** generated commander effects were named identically to their creature
    (`commander-effect.cactus` named `仙人掌`, same as the creature `cactus`). A per-item validator
    cannot see that — it needs the corpus — which is exactly why the corpus-level metric exists.

    Same class as `field_echo`, one level out: there the value echoed its FIELD name, here it
    echoes its SUBJECT name. Both are uninformative output that passes every other check.
    """
    subject = str(context.get("displayName") or "").strip()
    if not subject:
        return []
    name = str(draft.get("name") or "").strip()
    if name and name == subject:
        kind = _subject_kind(context)
        return [f"field 'name' is just the subject's own name ({name!r}) — give this {kind} its "
                f"own distinct name, not a copy of its subject's"]
    return []


def name_collision(draft: "Mapping[str, Any]", context: "Mapping[str, Any]") -> "list[str]":
    """Reject a `name` already taken by a DIFFERENT subject.

    ⛔ The residue `subject_name_echo` could not reach. After it cut same-as-its-own-creature names
    from 83 to 6, `SemanticDedup/NearDuplicate` still reported 6 GAPs — all **sibling pairs**
    (`doublecherry`/`doubleshooter`, `dollgold`/`dollsilver`, `pot`/`pumpkin`,
    `starfruit`/`starpea`, `jalapeno`/`jalastar`, `chomper`/`nutchomper`). Siblings share families
    and therefore motifs, so the model converges on the same name for both — and no check that sees
    one draft at a time can possibly notice.

    `subject_name_echo` compares the draft to ITS OWN subject; this compares it to every OTHER
    subject's committed name. Same family of defect, one more level out, and the third time this
    program has learned that per-item validation cannot see a corpus-level property.

    `takenNames` is supplied by the caller (the generator passes every committed name except this
    subject's own), so the validator stays a pure function of `(draft, context)` and remains
    testable without a corpus.
    """
    taken = context.get("takenNames") or ()
    name = str(draft.get("name") or "").strip()
    if not name:
        return []
    if name in set(taken):
        kind = _subject_kind(context)
        return [f"field 'name' ({name!r}) is already used by another {kind} — this one "
                f"needs a distinct name; siblings share motifs, so vary the wording deliberately"]
    return []
