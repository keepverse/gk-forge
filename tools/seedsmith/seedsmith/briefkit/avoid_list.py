"""seedsmith.briefkit.avoid_list — the one shared IP avoid-list helper (ip-censor IC-3/IC-4).

Reads the committed registry data file (`gk-data/packs/fusion/data/seed/ip-censor/_registry/marks.v1.json`) and
renders every player-facing alias spelling as a single brief line. No model call, no retry, no
answer-side refusal — the release scan stays the gate; this is only the free prompt half.

Two tools, no shared code (`spec-wiring.md` §Tool shape): this helper reads the registry's
**data file** by its versioned contract and never imports `ipcensor`. `ipcensor`'s `registry`
module stays the validating authority; this helper throws on any shape it cannot read rather
than guessing.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

__all__ = [
    "PLAYER_SURFACES",
    "DEFAULT_REGISTRY_FILE",
    "load_avoid_terms",
    "render_avoid_line",
]

#: The two surfaces whose text a generator produces (registry `Surface` values). A group scoped
#: to neither (e.g. a code-identifier-only concern) never reaches a brief.
PLAYER_SURFACES = frozenset({"player-name", "player-prose"})

#: `gk-forge/tools/seedsmith/seedsmith/briefkit/avoid_list.py` → parents are briefkit, the seedsmith
#: package, the tool root, `tools/`, then the repo root — the same depth `nodegen/emit.py`'s own
#: `REPO_ROOT` (`parents[6]` from one level deeper) already encodes.
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_REGISTRY_FILE = REPO_ROOT / "data" / "seed" / "ip-censor" / "_registry" / "marks.v1.json"


def load_avoid_terms(registry_file: "Path | None" = None) -> "tuple[str, ...]":
    """Every in-scope alias spelling, casefold-unique, sorted.

    In scope means the alias's group scope — or the alias's own narrower scope, when it
    declares one (the `pvz` short-alias shape) — includes `player-name` or `player-prose`.
    Uniqueness is by `str.casefold()`; the displayed spelling per fold-group is the
    lexicographically smallest, so the result never depends on file order. Throws naming the
    key on any shape it cannot read; never defaults.
    """
    path = Path(registry_file) if registry_file is not None else DEFAULT_REGISTRY_FILE
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("groups"), list):
        raise ValueError(f"{path}: registry is missing 'groups' — refusing to guess the shape")
    by_fold: "dict[str, list[str]]" = {}
    for group in doc["groups"]:
        if not isinstance(group, dict):
            raise ValueError(f"{path}: a registry group is not an object — refusing to guess")
        mark = group.get("mark", "?")
        scope = group.get("scope")
        if not isinstance(scope, list) or not scope:
            raise ValueError(
                f"{path}: group {mark!r} is missing 'scope' — refusing to guess")
        aliases = group.get("aliases")
        if not isinstance(aliases, list):
            raise ValueError(
                f"{path}: group {mark!r} is missing 'aliases' — refusing to guess")
        group_scope = {str(s) for s in scope}
        for alias in aliases:
            if not isinstance(alias, dict):
                raise ValueError(
                    f"{path}: group {mark!r} holds a non-object alias — refusing to guess")
            text = alias.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError(
                    f"{path}: group {mark!r} holds an alias missing 'text' — refusing to guess")
            own_scope = alias.get("scope")
            effective = ({str(s) for s in own_scope} if isinstance(own_scope, list)
                         else group_scope)
            if effective & set(PLAYER_SURFACES):
                by_fold.setdefault(text.casefold(), []).append(text)
    return tuple(sorted(
        (min(spellings) for spellings in by_fold.values()),
        key=str.casefold,
    ))


def render_avoid_line(terms: "Sequence[str]") -> str:
    """The one brief line. Empty tuple -> empty string, so an adapter never prints an empty list."""
    listed = [str(t) for t in terms]
    if not listed:
        return ""
    return ("IP avoid-list — never use these third-party names in a node name, nameKey or "
            f"flavor: {', '.join(listed)}.")
