"""seedsmith.adapters.trees.plan.tuning — the Python reader over `gk-core/data/tuning/passive-tree.v1.json`
(task B1). A1 built the C# side (`PassiveTreeTuning.cs`) for the RPG runtime; `tree-plan` is a
Python/seedsmith module and needs its own typed view of the same file — same `_require` mould as
`adapters.items.setgen.tuning` and `adapters.trees.targets`, deliberately NOT shared code with the
C# loader (different languages, same file, same discipline).

Only the keys `tree-plan` itself owns (spec-tree-plan.md §Tunables) are read here. `tree-binder`'s,
`tree-state`'s and `tree-resolve`'s keys live in the same file but are that module's concern when
their own Python readers (if any) land.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[6]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from ....workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

TUNING_PATH = _owned("data/tuning/passive-tree.v1.json")


class PassiveTreePlanTuningError(ValueError):
    """The tuning file is missing a key `tree-plan` needs. T5: no built-in default."""


def _require(doc: dict, *path: str):
    node = doc
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise PassiveTreePlanTuningError(
                f"passive-tree tuning is missing {'.'.join(path)!r} — refusing to substitute a "
                f"default; an unreviewed number here reaches every generated tree")
        node = node[key]
    return node


def load(path: "Path | None" = None) -> dict:
    """Returns the subset of `passive-tree.v1.json` `tree-plan` owns, as a plain nested dict
    (matching `build_plan`'s own access pattern — `tuning["tierLadder"]["reqScalePoints"]` etc.)
    rather than a dataclass, since `tree-binder`/`tree-state`/`tree-resolve` will each want their
    own typed slice of the SAME file later and a single shared dataclass would grow one field per
    module with no natural owner."""
    doc = json.loads((path or TUNING_PATH).read_text(encoding="utf-8"))
    return {
        "tierLadder": {"reqScalePoints": int(_require(doc, "tierLadder", "reqScalePoints"))},
        "budget": {
            "treeTotalPoints": int(_require(doc, "budget", "treeTotalPoints")),
            "branchSplitMilli": int(_require(doc, "budget", "branchSplitMilli")),
        },
        "potency": {
            "maxNodeShareMilli": int(_require(doc, "potency", "maxNodeShareMilli")),
            "minTerminalWidth": int(_require(doc, "potency", "minTerminalWidth")),
            "bandEdgesMilli": [int(x) for x in _require(doc, "potency", "bandEdgesMilli")],
        },
        "mechanism": {
            "rampStartMilli": int(_require(doc, "mechanism", "rampStartMilli")),
            "rampEndMilli": int(_require(doc, "mechanism", "rampEndMilli")),
        },
        "archetype": {"rewardSpreadMaxRatioMilli": int(_require(doc, "archetype", "rewardSpreadMaxRatioMilli"))},
        "exclusion": {"targetShareMilli": int(_require(doc, "exclusion", "targetShareMilli"))},
        "archetypeAssignment": str(_require(doc, "archetypeAssignment")),
        "designTarget": {"thetaAllIn": int(_require(doc, "designTarget", "thetaAllIn"))},
        "unlockCost": {
            "firstPoints": int(_require(doc, "unlockCost", "firstPoints")),
            "stepPoints": int(_require(doc, "unlockCost", "stepPoints")),
        },
    }
