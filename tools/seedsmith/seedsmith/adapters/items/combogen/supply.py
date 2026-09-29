"""seedsmith.adapters.items.combogen.supply — the PRECHECK, before the first model call.

⛔ **Before, not after.** `Registration/IngredientUnsatisfiable` (`metrics/linkage.py`) is
`gates = True`: it gates CI unconditionally, and it has done since the `seed_graph` cutover. A
102-entry run that mints ingredient families no gem supplies is 102 wasted calls *plus* a red gate,
and the failure is invisible until the whole run has finished. So the supplied set is computed here
and handed to the schema as a **closed enum** — the model is never offered a family no insert can
satisfy, which makes the finding unproducible from a well-formed answer rather than merely rare.

Measured 2026-09-05 against the live corpus: **40 gems across 34 families.** That is a real
constraint, not a formality — the 102 combinations draw four ingredients each from those 34.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[6]
GEM_DIR = REPO_ROOT / "data" / "seed" / "items" / "gems"


class SupplyRefused(ValueError):
    """The precheck failed. Raised rather than reported: a run that starts against an unsatisfiable
    vocabulary produces content the gate will reject, and the cheapest place to stop is here."""


@dataclass(frozen=True)
class SupplyReport:
    families: "tuple[str, ...]"
    gem_count: int
    #: `family -> the power bands a live gem supplies it at`, for the brief's own display.
    bands: "dict[str, tuple[str, ...]]"

    @property
    def family_count(self) -> int:
        return len(self.families)

    def refuse(self, wanted: "list[str] | tuple[str, ...]") -> "list[str]":
        """Every ingredient family in `wanted` that no live gem supplies, as messages. Empty = legal.

        Returns ALL of them, not the first: an author fixing a generated draft should see the whole
        refusal, and a report naming one of four problems produces four round trips.
        """
        supplied = set(self.families)
        return [
            f"IngredientUnsatisfiable: no gem in the corpus supplies family {family!r}; the "
            f"{self.family_count} supplied families come from {self.gem_count} shipped gems"
            for family in sorted({f for f in wanted if f not in supplied})
        ]


def load_gems(directory: "Path | None" = None) -> "list[dict]":
    """Every shipped gem row, read fresh. Exemplars live under `_exemplars/`, which this glob never
    reaches — the same directory-scoped exclusion `setgen.vocab.load_families` uses."""
    gems: "list[dict]" = []
    for path in sorted((directory or GEM_DIR).glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("kind") != "gem":
            continue
        gems.extend(doc.get("entries", []))
    return gems


def build(directory: "Path | None" = None) -> SupplyReport:
    gems = load_gems(directory)
    bands: "dict[str, set[str]]" = {}
    for gem in gems:
        family = gem.get("family")
        if not family:
            # Not silently dropped: a gem with no family supplies nothing and can never satisfy an
            # ingredient, so it is a corpus defect the caller should see rather than a row to skip.
            raise SupplyRefused(
                f"gem {gem.get('id')!r} declares no `family`; it can satisfy no ingredient and "
                f"the supplied-family set would be quietly one short")
        bands.setdefault(family, set()).add(str(gem.get("powerBand") or "?"))
    return SupplyReport(
        families=tuple(sorted(bands)),
        gem_count=len(gems),
        bands={f: tuple(sorted(b)) for f, b in bands.items()},
    )


def precheck(wanted: "list[str] | tuple[str, ...]",
             report: "SupplyReport | None" = None) -> SupplyReport:
    """Raise unless every wanted family is supplied. The one call a run makes before spending a
    token."""
    supply = report or build()
    problems = supply.refuse(wanted)
    if problems:
        raise SupplyRefused("; ".join(problems))
    return supply
