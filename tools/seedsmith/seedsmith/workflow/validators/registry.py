"""Tier labelling (spec-quality-gates.md §2.4) — so a pass rate can never be reported as quality."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Sequence

__all__ = ["Tier", "TIER", "ValidatorResult", "run_validators"]


class Tier(Enum):
    """What a check can actually prove."""
    CONSTRAINED_DECODING = 1   # shape — invalid output is unsampleable
    DETERMINISTIC = 2          # mechanical properties — a token is present/absent
    JUDGEMENT = 3              # coherence — needs a model, and is not free


#: Every validator in this package is tier 2. Recorded explicitly so a caller must go out of its
#: way to mislabel one.
TIER: "dict[str, Tier]" = {
    "motif_coverage": Tier.DETERMINISTIC,
    "anti_motif_violation": Tier.DETERMINISTIC,
    "field_echo": Tier.DETERMINISTIC,
    "non_empty": Tier.DETERMINISTIC,
    "language_consistency": Tier.DETERMINISTIC,
    "subject_name_echo": Tier.DETERMINISTIC,
    "script_policy": Tier.DETERMINISTIC,
}


@dataclass(frozen=True)
class ValidatorResult:
    """⚠️ `passed` means MECHANICALLY VALID, never 'good'.

    Measured: 8/8 first-attempt pass on content that was visibly shoehorned
    (`"会以极高的 伤害 压制 僵尸"` — motifs pasted in with spaces around them). "Uses the token" is
    checkable; "uses it meaningfully" is not. `summary()` refuses to render without saying so."""
    defects: "list[str]"
    tier: Tier = Tier.DETERMINISTIC

    @property
    def passed(self) -> bool:
        return not self.defects

    def summary(self) -> str:
        verdict = "mechanically valid" if self.passed else f"{len(self.defects)} defect(s)"
        return f"[tier {self.tier.value}: {self.tier.name.lower()}] {verdict}"


def run_validators(
    draft: "Mapping[str, Any]",
    context: "Mapping[str, Any]",
    validators: "Sequence[Callable[[Mapping, Mapping], list]]",
) -> ValidatorResult:
    defects: "list[str]" = []
    for v in validators:
        defects.extend(v(draft, context))
    return ValidatorResult(defects=defects)
