"""`PowerSeed` — the frozen record `power-parse` emits per species (spec-power-parse.md).

Held separate from `parse.py` so a downstream module (`threat-band`) can import the shape without
importing the regex machinery that produces it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# C# `long` bound (docs/architecture/numeric-types.md's overflow table, rule 1: "long for any magnitude"). A value that
# would not survive this round-trip is a defect in the capture or the parse, raised here rather
# than silently clamped downstream where the cause would be lost.
LONG_MAX = 9_223_372_036_854_775_807
LONG_MIN = -9_223_372_036_854_775_808

Basis = Literal["observed", "stated", "inferred", "blocked"]


class MagnitudeOverflow(ValueError):
    """An extracted magnitude would not survive a C# `long` round-trip."""


def assert_long_safe(value: int, *, field: str) -> int:
    if not (LONG_MIN <= value <= LONG_MAX):
        raise MagnitudeOverflow(f"{field}={value} does not fit in a 64-bit long")
    return value


@dataclass(frozen=True)
class PowerSeed:
    """One species' power seed. Exactly one `basis` per spec §2 — never a per-field basis."""

    side: str
    type_id: int
    basis: Basis

    # The value `threat-band`'s score formula actually reads — sourced from the structured
    # capture when basis == "observed", from the parsed flavour text when basis == "stated",
    # and None for "inferred" (classify-pipelines supplies the band from lore, Q26) and "blocked".
    toughness: "int | None"
    damage: "int | None"

    # Parse-only fields, always populated when the text pattern matches — independent of basis,
    # because a disagreement between an observation and the text is evidence, not an error
    # (spec §2: "A disagreement is recorded, not resolved here").
    text_toughness: "int | None"
    text_damage: "int | None"
    shot_count: "int | None"
    interval_ms: "int | None"

    disagreement_toughness: bool
    disagreement_damage: bool

    #: The third score term (creature-seed R-CS5, 2026-09-18). Declared LAST and defaulted, so
    #: every existing constructor and fixture keeps its exact previous behaviour: a seed built
    #: without a cost scores exactly as it did before the term existed.
    cost: "int | None" = None

    def __post_init__(self) -> None:
        for field_name in ("toughness", "damage", "cost", "text_toughness", "text_damage",
                           "shot_count", "interval_ms"):
            value = getattr(self, field_name)
            if value is not None:
                assert_long_safe(value, field=field_name)
