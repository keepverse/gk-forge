"""seedsmith.adapters.items.gemgen.schema — the model's answer schema, `audit_schema`-clean.

Only `name`/`nameKey`/(when the family is elemental)`element`/`blocked` are ever asked of the
model — see `brief.py`'s own docstring for why `tags` and `powerBand` never appear here.
`audit_schema` (`pipeline.model`) is the mechanical guard that a schema like this cannot smuggle a
magnitude past review; `test_sockets_gen.py` runs it against `gem_answer_schema()` the same way
`test_set_charm_gen.py` runs it against `setgen/schema.py`.

`validate_answer` is the local half of `pipeline.model.Pipeline`'s own guardrail #5 ("validate
before accept"): this module has no live model call to gate (see `run.py`'s own docstring — the
call itself is made by the shared `workflow` graph, not here), so an already-received answer still
needs the same structural check a real pipeline's schema-validated-output mode would apply.
"""
from __future__ import annotations

from . import emit
from .. import registries
from ....pipeline.model import BLOCKED_FIELD, audit_schema


def gem_answer_schema(*, elemental: bool = False) -> dict:
    properties: dict = {
        BLOCKED_FIELD: {"type": "string"},
        "name": {"type": "string", "minLength": 1, "maxLength": 40},
        # ⛔ maxLength added 2026-09-08: same class of gap as setgen/schema.py's nameKey (a real
        # incident there) — `pattern` alone is not enforced at decode time, so without a length
        # bound this field was unconstrained during generation.
        "nameKey": {"type": "string", "pattern": emit.NAME_KEY_RE.pattern, "maxLength": 80},
    }
    if elemental:
        elements = sorted(registries.load_vocabularies()["element"])
        properties["element"] = {"type": "string", "enum": elements}
    return {"type": "object", "properties": properties, "additionalProperties": False}


def validate_answer(answer: dict, *, elemental: bool = False) -> "list[str]":
    """Structural checks over an already-received answer. Returns the defects found; an empty list
    means the answer is usable. A `blocked` answer is legal and short-circuits every other check —
    "I can't" is a reportable outcome, never a defect to list reasons for."""
    if not isinstance(answer, dict):
        return ["answer is not an object"]
    if answer.get(BLOCKED_FIELD):
        return []

    errors: "list[str]" = []
    name = answer.get("name")
    if not isinstance(name, str) or not (1 <= len(name) <= 40):
        errors.append("name must be a 1-40 character string")

    name_key = answer.get("nameKey")
    if not isinstance(name_key, str) or not emit.NAME_KEY_RE.match(name_key):
        errors.append(f"nameKey must match {emit.NAME_KEY_RE.pattern!r}")

    if elemental:
        legal = registries.load_vocabularies()["element"]
        element = answer.get("element")
        if element not in legal:
            errors.append(f"element must be one of {sorted(legal)}")
    elif answer.get("element") is not None:
        errors.append("element was answered but this family has no per-element variant")

    return errors


__all__ = ["gem_answer_schema", "validate_answer", "audit_schema", "BLOCKED_FIELD"]
