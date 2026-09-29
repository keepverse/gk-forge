"""seedsmith.budget.model — `BudgetRow`, `Provenance`, `Tolerance` (spec-budget.md §3).

Tolerance is asymmetric on purpose: being three uniques short of target and three over are not
the same event — short means a gap a player can feel, over means content nobody asked for but
nobody is hurt by. Symmetric tolerance forces one threshold to be wrong.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Derivation(Enum):
    STATED = "stated"
    STRUCTURAL = "structural"
    PROPORTIONAL = "proportional"


@dataclass(frozen=True)
class Tolerance:
    under: int = 0
    over: int = 0

    def contains(self, observed: int, target: int) -> bool:
        return target - self.under <= observed <= target + self.over


@dataclass(frozen=True)
class Provenance:
    value: int
    source: str
    status: str
    authoritative: bool = False


@dataclass(frozen=True)
class BudgetRow:
    dimension: str                          # "kind:unique", "role×frame:base-type", …
    target: int
    tolerance: Tolerance
    derivation: Derivation
    rationale: str
    provenance: "tuple[Provenance, ...]" = field(default_factory=tuple)

    @property
    def conflict(self) -> bool:
        """A row where no source is marked authoritative is a conflict — `metrics` refuses to
        run distribution checks against it (spec-budget.md §2): a target nobody has adjudicated
        is not a target, and measuring against it produces confident nonsense."""
        if not self.provenance:
            return False
        return not any(p.authoritative for p in self.provenance)
