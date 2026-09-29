"""The eight `run-control` selectors (creature-seed module 9, spec-run-control.md §4) — "generate
what we want." Every selector resolves to a species id list with ZERO model calls; `--basis
inferred` and `--unresolved` are computable from provenance alone, which is the whole payoff
after a full run.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..anchor.emit import stale_ids

KNOWN_KINDS = frozenset({
    "all", "side", "family", "species", "pipeline", "basis", "unresolved", "stale",
})


class UnknownSelectorKind(ValueError):
    pass


def resolve_selector(
    selector: Mapping[str, Any],
    *,
    dump_species: Sequence[Mapping[str, Any]],   # rows from corpus-dump: {speciesId, side, ...}
    anchors: Sequence[Mapping[str, Any]] = (),   # already-emitted anchor entries
    current_dump_hash: str = "",
    current_prompt_versions: "Mapping[str, int] | None" = None,
) -> "list[str]":
    """`selector` is `{"kind": <one of KNOWN_KINDS>, ...kind-specific keys}`. Every branch reads
    only `dump_species`/`anchors` — never calls a model, proven by `every_selector_resolves_
    without_a_model_call` never even importing a caller."""
    kind = selector.get("kind")
    if kind not in KNOWN_KINDS:
        raise UnknownSelectorKind(f"unknown selector kind {kind!r} (known: {sorted(KNOWN_KINDS)})")

    all_ids = sorted({s["speciesId"] for s in dump_species})

    if kind == "all":
        return all_ids

    if kind == "side":
        side = selector["side"]
        return sorted(s["speciesId"] for s in dump_species if s.get("side") == side)

    if kind == "family":
        family = selector["family"]
        return sorted(a["speciesId"] for a in anchors if family in (a.get("family") or []))

    if kind == "species":
        requested = set(selector["species"])
        return sorted(requested & set(all_ids))

    if kind == "pipeline":
        # "one judgement across the roster" — every species, scoped by the caller to run only
        # this one pipeline; the selector's job is just to name which species, which is all.
        return all_ids

    if kind == "basis":
        basis = selector["basis"]
        return sorted(a["speciesId"] for a in anchors if a.get("basis") == basis)

    if kind == "unresolved":
        out = []
        for a in anchors:
            for field in ("elementPrimary", "elementSecondary", "aptitudePrimary",
                          "aptitudeSecondary", "rarity", "threatBand", "deployMode"):
                if a.get(field) == "unresolved":
                    out.append(a["speciesId"])
                    break
        return sorted(out)

    if kind == "stale":
        return stale_ids(anchors, current_dump_hash=current_dump_hash,
                         current_prompt_versions=dict(current_prompt_versions or {}))

    raise UnknownSelectorKind(kind)  # unreachable — KNOWN_KINDS check above already guards this
