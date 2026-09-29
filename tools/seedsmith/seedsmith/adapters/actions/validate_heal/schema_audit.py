"""seedsmith.adapters.actions.validate_heal.schema_audit --- Stage 0's fourth assertion
(spec-validate-heal.md SS2 Stage 0): "every property has a description, and every description
contains a negative clause." Implemented as a mechanical check, per the spec's own words, so it is a
test rather than a review habit.

**Deliberately NOT added to `pipeline.model.audit_schema`.** Acceptance criterion 1 names exactly
THREE extensions living there ("this module's three extensions... live in pipeline/model.py");
acceptance criterion 2 scopes the description rule to "every property of every one of the three
[pipeline] schemas", never every seedsmith schema. Folding it into the shared `audit_schema` would
make it fire on every pre-existing seedsmith pipeline the moment this module's own Stage 0 tests
touch `Pipeline.__post_init__` --- most of which predate this rule and carry no `description` at
all (`AFFIX_SCHEMA`'s own `name`/`refs` properties, for one). Keeping it local here is what lets
Stage 0's own AFFIX_SCHEMA fix stay a one-property, nothing-else-changes patch (SS6 hazard 1).
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from ....pipeline.model import SchemaDefect

__all__ = ["audit_descriptions"]

#: A mechanical "not"/"never" check, word-bounded so it does not fire on a substring like
#: "notice" or "innovation". Matches spec-validate-heal.md SS2 Stage 0's own wording: "a
#: 'not'/'never' sentence naming what the field is not."
_NEGATIVE_CLAUSE_RE = re.compile(r"\b(not|never)\b", re.IGNORECASE)


def audit_descriptions(schema: Mapping[str, Any], *, path: str = "$") -> "list[SchemaDefect]":
    """Walks `properties`/`items`/`anyOf`/`oneOf`/`allOf` exactly like `pipeline.model.audit_schema`
    (same recursion shape, so a description missing three levels deep is exactly as findable as a
    top-level one). Every PROPERTY (not the schema root itself, which has no "description" of its
    own in any schema in this program) must carry a non-empty `description` string containing a
    negative clause.
    """
    defects: "list[SchemaDefect]" = []

    for name, sub in (schema.get("properties") or {}).items():
        if not isinstance(sub, dict):
            continue
        prop_path = f"{path}.{name}"
        desc = sub.get("description")
        if not isinstance(desc, str) or not desc.strip():
            defects.append(SchemaDefect(prop_path, "missing a description"))
        elif not _NEGATIVE_CLAUSE_RE.search(desc):
            defects.append(SchemaDefect(
                prop_path,
                f"description {desc!r} carries no negative clause (a 'not'/'never' sentence "
                f"naming what the field is NOT)",
            ))
        defects.extend(audit_descriptions(sub, path=prop_path))

    items = schema.get("items")
    if isinstance(items, dict):
        defects.extend(audit_descriptions(items, path=f"{path}[]"))
    elif isinstance(items, list):
        for i, sub in enumerate(items):
            if isinstance(sub, dict):
                defects.extend(audit_descriptions(sub, path=f"{path}[{i}]"))

    for keyword in ("anyOf", "oneOf", "allOf"):
        for i, sub in enumerate(schema.get(keyword) or ()):
            if isinstance(sub, dict):
                defects.extend(audit_descriptions(sub, path=f"{path}.{keyword}[{i}]"))

    return defects
