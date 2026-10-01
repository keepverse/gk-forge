"""seedsmith.adapters.items.combogen.tuning — the pure parser over BOTH tuning files.

⚠ **Two files, one view, and the split is the point.** The current `sockets` revision is module 16's
and already carries D20's ingredient count, the attuned tier bonus, the structural ceiling and the
fifteen per-role ceilings. `gk-core/data/tuning/strain-splice.v1.json` is this
module's and carries only what module 16 does not own. Reading both here — rather than copying six
values into one file — is what stops the generator and the runtime evaluator disagreeing about how
many ingredients a Strain takes.

No key has a default. A missing one raises at load, because a generator silently running on a
default is how an unreviewed number reaches 102 entries (module 13's own reasoning, restated because
this parser is a second instance of it, not a reference to it).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ....tooling import run_tool

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

#: Mirrors the C# `SocketTuningFiles.StrainSplice` (strain-splice-host SSH7.1) — still v1, and it moves
#: with that constant when SSH7.7 publishes the ladder.
STRAIN_SPLICE_PATH = _owned("data/tuning/strain-splice.v1.json")
SOCKETS_PATH = _owned("data/tuning/sockets.v3.json")

#: Mirror of the C# `SocketLimits.SocketCircuitSize` (4): one complete circuit's width. Structural,
#: not tunable — a Strain consumes exactly one circuit. The parity test
#: `python_and_csharp_readings_agree_on_the_shipped_tuning` reads the C# source and asserts the two
#: agree, so one cannot move without the other failing.
CIRCUIT_SIZE = 4

#: Keys this module must never define, because module 16 already does. Checked at load against the
#: strain-splice file's own text, so a well-meaning copy-paste fails instead of forking the value.
SOCKETS_OWNED_KEYS: "tuple[str, ...]" = (
    "maxCombosPerActor", "attunedTierBonus", "ingredientCount", "structuralCeiling",
    "socketCeiling", "attunedEffectiveCountBonus",
)


@dataclass(frozen=True)
class TierLadderRung:
    """One rung of the tier ladder — the Python mirror of the C# `TierLadderRung` (SSH7.1/SSH7.2), so
    a generator and the evaluator read the same ladder and cannot disagree about which rung a fill
    reaches."""

    rung: int
    floors: "tuple[int, ...]"
    grant_delta: int


class ComboTuningError(ValueError):
    """A tuning file is structurally unusable for combination generation. Raised at load, so a
    defect lands before the first model call rather than on the hundredth combination."""


@dataclass(frozen=True)
class ComboTuning:
    # --- from the `sockets` revision (module 16's) ---
    ingredient_count: int
    structural_ceiling: int
    attuned_tier_bonus: int
    insert_tier_count: int
    socket_ceiling: "dict[str, int]"

    # --- from strain-splice.v1.json (this module's) ---
    min_tier_plan: "tuple[int, ...]"
    tier_ladder: "tuple[TierLadderRung, ...]"
    base_tier: "dict[str, int]"
    catalogue_size_bar: int
    exact_duplicate_names_max: int
    near_duplicate_rate_max_permille: int

    def host_roles(self) -> "tuple[str, ...]":
        """The roles whose ceiling reaches D20's ingredient count — the only chassis a Strain or a
        Splice can ever live in. The Python mirror of `SocketGeometry.RolesThatCanHostAStrain`;
        a test asserts the two agree against the same shipped file.
        """
        return tuple(sorted(r for r, c in self.socket_ceiling.items()
                            if c >= self.ingredient_count))

    def geometric_combo_ceiling(self, host_roles: "tuple[str, ...] | None" = None) -> int:
        """How many complete `SocketCircuitSize`-socket circuits the offered roles can hold between
        them: `sum(floor(ceiling(r) / CIRCUIT_SIZE) for r in roles)`.

        A READING, never compared to a count: R12 retired the per-actor cap (strain-splice-host
        SSH4.2), so there is no backstop left for this to be measured against. A four-socket role is
        ONE complete circuit; a six-socket role is one circuit plus a two-socket remainder that only
        resonance can use, so it counts once. The Python mirror of
        `SocketGeometry.GeometricCombinationCeiling` (SSH6.1, combo-budget §2).
        """
        roles = host_roles if host_roles is not None else self.host_roles()
        return sum(self.socket_ceiling.get(r, 0) // CIRCUIT_SIZE for r in roles)

    def reachable_combo_ceiling(self, admitted_roles: "tuple[str, ...]") -> int:
        """The same sum over only the roles at least one recipe admits — the Python twin of
        `SocketGeometry.ReachableCombinationCeiling`. An unpinned recipe admits every role."""
        return self.geometric_combo_ceiling(admitted_roles)

    def base_tier_for(self, combination_kind: str) -> int:
        if combination_kind not in self.base_tier:
            raise ComboTuningError(
                f"no baseTier row for combination kind {combination_kind!r} — the rows are "
                f"{sorted(self.base_tier)}")
        return self.base_tier[combination_kind]

def latest_materials_path() -> Path:
    """The highest `materials.v{n}.json` by FILENAME revision — what
    `gk-core/tools/tuning/publish.py`'s own `latest_version` reads. `materials` has no `SocketTuningFiles`
    constant yet (SSH8.4 adds it), so the report and its parity test resolve it the way the publisher
    does rather than hard-coding a revision that the next publish would stale."""
    candidates = []
    for path in (_owned("data/tuning")).glob("materials.v*.json"):
        middle = path.name[len("materials") + 2:-len(".json")]
        if middle.isdigit():
            candidates.append((int(middle), path))
    if not candidates:
        raise ComboTuningError("no materials.v*.json under data/tuning")
    return max(candidates)[1]



def combo_budget_dump(items_root: "Path | None" = None, *,
                      validator_project: "Path | None" = None) -> dict:
    """The C# `ComboPricing` computation, as JSON (SSH6.4, plan Defaults: *"a JSON dump written by
    the C# `ComboPricing` computation, read by the report"*).

    ⛔ **Never a Python re-implementation of `ActorPowerCache.Compose`.** `power(c, k)` is the price of
    an atom, and a second implementation of it is the defect this dump exists to make impossible, so
    the report shells out to `gk-forge/tools/ItemSeedValidator --combo-budget-dump` — the same
    tool-and-authority pattern `items repair-names` uses for collision groups. Raises RuntimeError if
    the tool cannot run, because a report rendered against a guessed price is worse than no report."""
    root = Path(items_root or (_owned("data/seed/items")))
    project = validator_project or (_owned("tools/ItemSeedValidator/ItemSeedValidator.csproj"))
    if not project.exists():
        raise RuntimeError(f"ItemSeedValidator project not found at {project}")
    proc = run_tool(
        ["dotnet", "run", "--project", str(project), "--", str(root), "--combo-budget-dump"],
        cwd=str(REPO_ROOT), refusal=RuntimeError,
        what="the C# ComboPricing price this report reads instead of re-implementing",
    )
    if proc.returncode != 0 or "{" not in proc.stdout:
        raise RuntimeError(
            f"combo-budget-dump failed ({proc.returncode}): {proc.stderr.strip()[:400]}")
    text = proc.stdout[proc.stdout.index("{"):]
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"combo-budget-dump returned unparseable JSON ({exc}); head: {text[:200]!r}") from exc


def _read_tier_ladder(path: Path, ss: dict) -> "tuple[TierLadderRung, ...]":
    """The optional `recipe.tierLadder`. Absent is NOT a substituted default: it is the one-rung
    ladder the shipped `minTierPlan` describes (rung 1, those floors, no grant delta), which is what
    keeps a file with no ladder loading with exactly its old behaviour — the same rule the C# parser
    states."""
    recipe = _require(ss, path.name, "recipe")
    rows = recipe.get("tierLadder")
    if rows is None:
        plan = tuple(int(t) for t in _require(ss, path.name, "recipe", "minTierPlan"))
        return (TierLadderRung(rung=1, floors=plan, grant_delta=0),)

    if not isinstance(rows, list):
        raise ComboTuningError(f"{path.name}: recipe.tierLadder is not an array")
    ladder = []
    for row in rows:
        if not isinstance(row, dict):
            raise ComboTuningError(f"{path.name}: a recipe.tierLadder row is not an object")
        floors = row.get("floors")
        if not isinstance(floors, list) or not all(isinstance(f, int) for f in floors):
            raise ComboTuningError(f"{path.name}: a recipe.tierLadder row carries no integer floors")
        ladder.append(TierLadderRung(rung=int(row.get("rung", 0)),
                                     floors=tuple(floors),
                                     grant_delta=int(row.get("grantDelta", 0))))
    return tuple(ladder)


def _require(doc: dict, source: str, *path: str):
    node = doc
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise ComboTuningError(
                f"{source} is missing {'.'.join(path)!r} — refusing to substitute a default; an "
                f"unreviewed number here reaches every generated combination")
        node = node[key]
    return node


def load(strain_splice_path: "Path | None" = None,
         sockets_path: "Path | None" = None) -> ComboTuning:
    ss_path = strain_splice_path or STRAIN_SPLICE_PATH
    sk_path = sockets_path or SOCKETS_PATH
    ss_text = ss_path.read_text(encoding="utf-8")
    ss = json.loads(ss_text)
    sk = json.loads(sk_path.read_text(encoding="utf-8"))

    _refuse_forked_keys(ss, ss_path.name)

    tuning = ComboTuning(
        ingredient_count=int(_require(sk, sk_path.name, "strainSplice", "ingredientCount")),
        structural_ceiling=int(_require(sk, sk_path.name, "structuralCeiling")),
        attuned_tier_bonus=int(_require(sk, sk_path.name, "resonance", "attunedTierBonus")),
        insert_tier_count=int(_require(sk, sk_path.name, "insertTiers", "count")),
        socket_ceiling={str(k): int(v)
                        for k, v in _require(sk, sk_path.name, "socketCeiling").items()},
        min_tier_plan=tuple(int(t) for t in _require(ss, ss_path.name, "recipe", "minTierPlan")),
        tier_ladder=_read_tier_ladder(ss_path, ss),
        base_tier={str(k): int(v)
                   for k, v in _require(ss, ss_path.name, "recipe", "baseTier").items()},
        catalogue_size_bar=int(_require(ss, ss_path.name, "learnability", "catalogueSizeBar")),
        exact_duplicate_names_max=int(
            _require(ss, ss_path.name, "distinctness", "exactDuplicateNamesMax")),
        near_duplicate_rate_max_permille=int(
            _require(ss, ss_path.name, "distinctness", "nearDuplicateRateMaxPermille")),
    )
    _validate(tuning)
    return tuning


def _validate_tier_ladder(t: ComboTuning) -> None:
    """The ladder's own load rules, mirroring the C# `StrainSpliceTuning.ValidateTierLadder` rule for
    rule (SSH7.1/SSH7.3) — the same throws, so a generator and the runtime evaluator cannot disagree
    about which ladder is legal. Every one is a throw, never a clamp: a ladder whose rungs do not
    ascend, whose per-position floors fall, whose grant deltas do not start at 0 and rise, or whose
    top rung grants past the atom ladder, would silently make a better-attuned fill worth nothing."""
    from ....numerics.model import TIER_COUNT

    ladder = t.tier_ladder
    if not ladder:
        raise ComboTuningError("recipe.tierLadder is empty — a ladder needs a rung")

    first = ladder[0]
    if first.rung != 1 or first.grant_delta != 0:
        raise ComboTuningError(
            f"recipe.tierLadder starts at rung {first.rung} with grantDelta {first.grant_delta}; "
            "rung 1 IS the base tier, so it carries no grant delta and the ladder starts there")

    for index, rung in enumerate(ladder):
        if rung.rung != index + 1:
            raise ComboTuningError(
                f"recipe.tierLadder rung {rung.rung} sits at index {index} — the rungs are a closed "
                "ascending ladder 1..n, never renumbered or skipped")
        if len(rung.floors) != t.ingredient_count:
            raise ComboTuningError(
                f"recipe.tierLadder rung {rung.rung} carries {len(rung.floors)} floors but the "
                f"ingredient count is {t.ingredient_count} — the floors are zipped onto the "
                "ingredient multiset, so a length mismatch drops or invents one")
        for position, floor in enumerate(rung.floors):
            if not (1 <= floor <= t.insert_tier_count):
                raise ComboTuningError(
                    f"recipe.tierLadder rung {rung.rung} position {position} names tier {floor}, "
                    f"outside the shipped insert ladder [1..{t.insert_tier_count}]")
            if position > 0 and floor < rung.floors[position - 1]:
                raise ComboTuningError(
                    f"recipe.tierLadder rung {rung.rung} floors are not ascending at position "
                    f"{position} ({floor} below {rung.floors[position - 1]})")
            if index > 0 and floor < ladder[index - 1].floors[position]:
                raise ComboTuningError(
                    f"recipe.tierLadder rung {rung.rung} position {position} floor {floor} is below "
                    f"rung {index} at {ladder[index - 1].floors[position]} — a higher rung can never "
                    "ask for less")
        if index > 0 and rung.grant_delta <= ladder[index - 1].grant_delta:
            raise ComboTuningError(
                f"recipe.tierLadder rung {rung.rung} grantDelta {rung.grant_delta} does not rise "
                f"above rung {index} at {ladder[index - 1].grant_delta} — a rung that grants no more "
                "than the one below it is not a rung")

    top_base = max(t.base_tier.values())
    top = top_base + ladder[-1].grant_delta + t.attuned_tier_bonus
    if top > TIER_COUNT:
        raise ComboTuningError(
            f"recipe.tierLadder's top grantDelta ({ladder[-1].grant_delta}) plus the top base tier "
            f"({top_base}) plus attunement ({t.attuned_tier_bonus}) grants tier {top}, above the atom "
            f"ladder's {TIER_COUNT} — a combination granted there would bind no atom. Extend the "
            "ladder or lower the rung; never clamp.")


def _keys(node, out: "set[str]") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            out.add(key)
            _keys(value, out)
    elif isinstance(node, list):
        for value in node:
            _keys(value, out)


def _refuse_forked_keys(doc: dict, name: str) -> None:
    """A value module 16 owns, re-declared here, is a fork — and a forked ingredient count is how a
    generator authors 102 combinations the runtime evaluator can never match.

    Walks the KEYS at every depth rather than searching the file text: the ownership note in this
    very file names all six of them in prose, and a substring search would refuse the document that
    explains why they are absent.
    """
    present: "set[str]" = set()
    _keys(doc, present)
    found = [k for k in SOCKETS_OWNED_KEYS if k in present]
    if found:
        raise ComboTuningError(
            f"{name} declares {found}, which data/tuning/{SOCKETS_PATH.name} already owns (module 16). "
            f"Two sources of truth for an ingredient count or an attunement bonus is how a "
            f"generated combination stops matching the evaluator that has to fire it — read them "
            f"from {SOCKETS_PATH.name} instead")


def _validate(t: ComboTuning) -> None:
    """The structural invariants, each with its own message so a balance pass reads which one it
    broke."""
    if t.ingredient_count < 1:
        raise ComboTuningError(
            f"strainSplice.ingredientCount {t.ingredient_count} is below 1 — a combination with no "
            f"ingredients fires on an empty item")
    if t.ingredient_count > t.structural_ceiling:
        raise ComboTuningError(
            f"strainSplice.ingredientCount {t.ingredient_count} exceeds structuralCeiling "
            f"{t.structural_ceiling} — no item could ever hold one, so all 102 would be inert")
    _validate_tier_ladder(t)

    if len(t.min_tier_plan) != t.ingredient_count:
        raise ComboTuningError(
            f"recipe.minTierPlan has {len(t.min_tier_plan)} entries but D20 fixes the ingredient "
            f"count at {t.ingredient_count} — the plan is zipped onto the ingredients, so a "
            f"length mismatch silently drops or invents a min tier")
    if list(t.min_tier_plan) != sorted(t.min_tier_plan):
        raise ComboTuningError(
            f"recipe.minTierPlan {list(t.min_tier_plan)} is not ascending — it is zipped onto the "
            f"ingredient multiset sorted by family id, so the order decides which duplicate gets "
            f"the cheaper tier and is load-bearing")
    for tier in t.min_tier_plan:
        if not (1 <= tier <= t.insert_tier_count):
            raise ComboTuningError(
                f"recipe.minTierPlan names tier {tier}, outside the shipped insert ladder "
                f"[1..{t.insert_tier_count}] ({SOCKETS_PATH.name} insertTiers.count) — an ingredient "
                f"no insert can satisfy makes the combination unbuildable")
    if not t.base_tier:
        raise ComboTuningError("recipe.baseTier is empty — every combination kind needs a tier")
    for kind, tier in t.base_tier.items():
        if tier < 1:
            raise ComboTuningError(
                f"recipe.baseTier.{kind} is {tier}; a granted tier below 1 grants nothing")
    if t.attuned_tier_bonus < 0:
        raise ComboTuningError(
            f"resonance.attunedTierBonus {t.attuned_tier_bonus} is negative — D22-as-amended makes "
            f"matching affinity a BONUS; a negative value turns it back into a penalty gate")
    if t.catalogue_size_bar < 1:
        raise ComboTuningError(
            "learnability.catalogueSizeBar below 1 is unreachable — the bar is a report threshold, "
            "not a cap, and a bar nothing can clear reports on every run")
    if t.exact_duplicate_names_max < 0 or t.near_duplicate_rate_max_permille < 0:
        raise ComboTuningError("a distinctness threshold is never negative")
