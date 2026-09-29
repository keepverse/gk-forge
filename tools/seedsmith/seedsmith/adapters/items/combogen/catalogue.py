"""seedsmith.adapters.items.combogen.catalogue — the 127-against-45 learnability report.

⛔ **The debt is measured, not implied.** ssot-sockets §4.4 sized the learnable catalogue at ~45
("twenty-five generated containers plus <= 20 words… that is a size a player can learn. Four hundred
would not be"). D20's 102 takes it to 127 — **2.8x the stated bar**, and §8.2's wiki-dependency
failure is LIVE the day the run completes.

⚠ **Reported, never enforced.** A threshold that refused the 102nd combination would be a hard
content ceiling of exactly the kind AGENTS.md forbids. What the report does instead is name the two
mitigations as REQUIREMENTS with their owner: module 20's compendium reveal and socket-UI preview.
`spec-strain-splice-gen.md` promotes both from niceties by name, and this is where that promotion
survives contact with a run.

The resonance half of the count is **derived from module 16's own tuning**, not transcribed: pure
thresholds x concrete elements, plus the ring pairs, plus eclipse, plus the diversity thresholds.
Adding a seventh element grows the catalogue here by construction rather than by an edit nobody
makes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .tuning import SOCKETS_PATH, ComboTuning

REPO_ROOT = Path(__file__).resolve().parents[6]
CORE_REGISTRY = REPO_ROOT / "data" / "seed" / "items" / "_registry" / "core.v1.json"

#: The two mitigations §4.4 names and D20 promotes. Their owner is module 20, `item-surfaces`.
REQUIRED_MITIGATIONS: "tuple[tuple[str, str], ...]" = (
    ("compendium reveal",
     "a combination is revealed once the player has held every ingredient at least once — "
     "content the game gives you, not knowledge you import"),
    ("socket-UI preview",
     "what the current fill produces, and what is one insert away; at four ingredients the hint "
     "must also cover one SWAP away"),
)
MITIGATION_OWNER = "module 20 (item-surfaces)"


@dataclass(frozen=True)
class CatalogueReport:
    resonances: int
    strains: int
    splices: int
    bar: int

    @property
    def total(self) -> int:
        return self.resonances + self.strains + self.splices

    @property
    def over_bar(self) -> bool:
        return self.total > self.bar

    @property
    def ratio_permille(self) -> int:
        """How far over the bar, in per-mille. Integer arithmetic, multiplied before dividing, and
        the single division happens exactly once at the end — the same rule the C# side applies to
        every per-mille magnitude, restated for the tool that quotes the number."""
        return (self.total * 1000) // self.bar

    def to_dict(self) -> dict:
        return {
            "resonances": self.resonances,
            "strains": self.strains,
            "splices": self.splices,
            "total": self.total,
            "learnableBar": self.bar,
            "overBar": self.over_bar,
            "ratioPermille": self.ratio_permille,
            "requiredMitigations": [
                {"requirement": name, "detail": detail, "owner": MITIGATION_OWNER}
                for name, detail in REQUIRED_MITIGATIONS
            ],
            "enforced": False,
            "whyNotEnforced":
                "a threshold that refused the 102nd combination would be a hard content ceiling; "
                "the bar is a design report and the mitigations are the fix",
        }


def generated_resonance_count(sockets_path: "Path | None" = None,
                              core_path: "Path | None" = None) -> int:
    """Pure + Ring + Eclipse + Diversity, derived from the shipped tuning and element roster.

    The mirror of module 16's `ResonanceGenerator`, which computes the same count in C# off
    `ElementRoster.Concrete`. A test asserts the two agree; two derivations that agree are worth
    more than one derivation and one literal.
    """
    sockets = json.loads((sockets_path or SOCKETS_PATH).read_text(encoding="utf-8"))
    core = json.loads((core_path or CORE_REGISTRY).read_text(encoding="utf-8"))
    concrete = len(core["elements"]["concrete"])
    resonance = sockets["resonance"]
    pure = concrete * len(resonance["pureThresholds"])
    ring = len(resonance["ringOrder"])
    eclipse = 1
    diversity = len(resonance["diversityThresholds"])
    return pure + ring + eclipse + diversity


def report(tuning: ComboTuning, *, strains: int, splices: int,
           sockets_path: "Path | None" = None,
           core_path: "Path | None" = None) -> CatalogueReport:
    return CatalogueReport(
        resonances=generated_resonance_count(sockets_path, core_path),
        strains=strains,
        splices=splices,
        bar=tuning.catalogue_size_bar,
    )
