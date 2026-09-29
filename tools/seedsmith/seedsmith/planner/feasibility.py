"""Three-layer feasibility for a demand→slot assignment (spec-planner.md, plan P1).

The layers run cheapest-first and short-circuit, because the cheap one catches the common case and
the expensive one is only worth paying for when it does not:

1. **Pigeonhole**, O(n) — if total demand exceeds total capacity, nothing else can help.
2. **Hopcroft-Karp maximum bipartite matching**, O(E*sqrt(V)) — totals can fit while a *subset*
   still cannot, and only a matching sees that.
3. **Koenig's theorem**, on failure only — turns the maximum matching into a minimum vertex cover.
   That cover **is** the binding constraint, so an infeasible plan is refused by *name* rather than
   with a bare "infeasible" that leaves a human to guess which demands were the problem.

The incident this exists for: 75 uniques into 40 slots, refused with no indication of *which*
demands collided, which cost a manual bisect. A refusal that cannot be acted on is barely better
than a crash.

**Balanced demand is constructed, not searched.** When the demand is exactly n themes x n axes per
role, the closed-form cyclic Latin square `axis = (roleIndex + themeIndex) mod n` is already a valid
assignment, so emitting it directly is both faster and provably collision-free. Searching for a
structure you can write down is how a planner ends up with a runtime nobody can predict.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

__all__ = [
    "Demand",
    "FeasibilityResult",
    "BindingConstraint",
    "check_feasibility",
    "latin_square_axes",
    "maximum_matching",
    "minimum_vertex_cover",
]


@dataclass(frozen=True)
class Demand:
    """One thing that needs a slot, and the slots it could legally take.

    `key` is the caller's own id and is echoed back in any finding, so a refusal names the demand in
    the caller's vocabulary rather than in an index this module invented.
    """

    key: str
    allowed_slots: frozenset[str]


@dataclass(frozen=True)
class BindingConstraint:
    """*Why* a plan is infeasible, in terms the caller can act on.

    `demands` and `slots` together are the minimum vertex cover: the smallest set of demands and
    slots whose removal would make the rest matchable. Every unmatched demand is competing for
    exactly these slots — that is the sentence a human needs, and it is what Koenig's theorem gives
    for free once a maximum matching exists.
    """

    demands: tuple[str, ...]
    slots: tuple[str, ...]
    unmatched: tuple[str, ...]

    def explain(self) -> str:
        slots = ", ".join(self.slots) if self.slots else "(no slots)"
        unmatched = ", ".join(self.unmatched)
        return (
            f"{len(self.unmatched)} demand(s) cannot be placed: {unmatched}. "
            f"The binding constraint is {len(self.slots)} slot(s) [{slots}] "
            f"contested by {len(self.demands)} demand(s)."
        )


@dataclass(frozen=True)
class FeasibilityResult:
    feasible: bool
    layer: str
    assignment: Mapping[str, str] = field(default_factory=dict)
    constraint: BindingConstraint | None = None
    detail: str = ""


def check_feasibility(
    demands: Sequence[Demand],
    capacity: Mapping[str, int],
) -> FeasibilityResult:
    """Run the three layers in order, stopping at the first that decides.

    `capacity` maps slot id to how many demands that slot can hold. A slot with capacity > 1 is
    expanded into that many independent seats, because a matching is defined over single-occupancy
    vertices — doing the expansion here keeps the caller's model (a slot holds k things) separate
    from the algorithm's (a seat holds one).
    """
    if not demands:
        return FeasibilityResult(True, layer="pigeonhole", detail="no demand")

    total_capacity = sum(max(0, n) for n in capacity.values())

    # ---- Layer 1: pigeonhole, O(n) -------------------------------------------------------------
    if len(demands) > total_capacity:
        return FeasibilityResult(
            False,
            layer="pigeonhole",
            constraint=BindingConstraint(
                demands=tuple(d.key for d in demands),
                slots=tuple(sorted(capacity)),
                unmatched=tuple(d.key for d in demands[total_capacity:]),
            ),
            detail=f"total demand {len(demands)} exceeds total capacity {total_capacity}",
        )

    # ---- Layer 2: maximum bipartite matching, O(E*sqrt(V)) --------------------------------------
    seats = _expand_seats(capacity)
    adjacency = {
        d.key: tuple(seat for seat in seats if seats[seat] in d.allowed_slots)
        for d in demands
    }
    matching = maximum_matching([d.key for d in demands], adjacency)

    if len(matching) == len(demands):
        return FeasibilityResult(
            True,
            layer="matching",
            assignment={demand: seats[seat] for demand, seat in matching.items()},
            detail=f"matched {len(matching)} demand(s)",
        )

    # ---- Layer 3: Koenig, only once we already know it fails -------------------------------------
    cover_demands, cover_seats = minimum_vertex_cover(
        [d.key for d in demands], adjacency, matching
    )
    unmatched = tuple(sorted(d.key for d in demands if d.key not in matching))
    return FeasibilityResult(
        False,
        layer="koenig",
        constraint=BindingConstraint(
            demands=tuple(sorted(cover_demands)),
            slots=tuple(sorted({seats[s] for s in cover_seats})),
            unmatched=unmatched,
        ),
        detail=(
            f"totals fit ({len(demands)} <= {total_capacity}) but a subset does not: "
            f"{len(unmatched)} demand(s) unplaceable"
        ),
    )


def _expand_seats(capacity: Mapping[str, int]) -> dict[str, str]:
    """seat id -> slot id. Sorted, so the assignment is deterministic across runs."""
    seats: dict[str, str] = {}
    for slot in sorted(capacity):
        for i in range(max(0, capacity[slot])):
            seats[f"{slot}#{i}"] = slot
    return seats


def maximum_matching(
    left: Sequence[str],
    adjacency: Mapping[str, Sequence[str]],
) -> dict[str, str]:
    """Hopcroft-Karp: returns `left -> right` for a maximum matching.

    Chosen over the simpler Hungarian augmenting-path loop because that one is O(V*E): at the sizes
    this planner already hit (75 demands, 40 slots, dense allowance) the difference is the gap
    between an instant answer and one slow enough that someone reaches for a smaller corpus, which
    is exactly how a feasibility check stops being run.

    Deterministic: `left` is consumed in the caller's order and adjacency in its own, so the same
    input always produces the same matching — the property that makes an assignment reproducible.
    """
    INF = float("inf")
    match_left: dict[str, str] = {}
    match_right: dict[str, str] = {}
    dist: dict[str, float] = {}

    def bfs() -> bool:
        queue: deque[str] = deque()
        for u in left:
            if u not in match_left:
                dist[u] = 0
                queue.append(u)
            else:
                dist[u] = INF
        found = False
        while queue:
            u = queue.popleft()
            for v in adjacency.get(u, ()):
                w = match_right.get(v)
                if w is None:
                    found = True
                elif dist[w] == INF:
                    dist[w] = dist[u] + 1
                    queue.append(w)
        return found

    def dfs(u: str) -> bool:
        for v in adjacency.get(u, ()):
            w = match_right.get(v)
            if w is None or (dist[w] == dist[u] + 1 and dfs(w)):
                match_left[u] = v
                match_right[v] = u
                return True
        dist[u] = INF
        return False

    while bfs():
        for u in left:
            if u not in match_left:
                dfs(u)

    return match_left


def minimum_vertex_cover(
    left: Sequence[str],
    adjacency: Mapping[str, Sequence[str]],
    matching: Mapping[str, str],
) -> tuple[set[str], set[str]]:
    """Koenig's theorem: a maximum matching becomes a minimum vertex cover.

    The construction: let `Z` be every unmatched left vertex plus everything alternately reachable
    from it (unmatched edges going right, matched edges coming back left). The cover is
    `(left - Z) union (right and Z)`.

    Why bother: the cover is the *smallest* set of vertices touching every edge, so it is precisely
    the set of slots the unplaceable demands are all fighting over. Reporting it turns "infeasible"
    into "these 5 demands all need one of these 2 slots", which is actionable.
    """
    matched_right = {v: u for u, v in matching.items()}

    z_left: set[str] = {u for u in left if u not in matching}
    z_right: set[str] = set()
    frontier = deque(z_left)

    while frontier:
        u = frontier.popleft()
        for v in adjacency.get(u, ()):
            if v in z_right or matching.get(u) == v:
                continue          # matched edges are only traversed right->left
            z_right.add(v)
            w = matched_right.get(v)
            if w is not None and w not in z_left:
                z_left.add(w)
                frontier.append(w)

    cover_left = {u for u in left if u not in z_left}
    return cover_left, z_right


def latin_square_axes(roles: Sequence[str], themes: Sequence[str]) -> dict[tuple[str, str], int]:
    """The balanced case, constructed rather than searched.

    For n roles x n themes, `axis = (roleIndex + themeIndex) mod n` is a cyclic Latin square: every
    role sees each axis exactly once, and so does every theme. That is the assignment a matching
    would eventually find, so finding it is wasted work — and the closed form is verifiable by
    inspection in a way a search result never is.

    Raises when the demand is not square, rather than returning something that merely looks like a
    Latin square: a near-miss here is a collision at generation time, far from its cause.
    """
    n = len(roles)
    if n == 0:
        return {}
    if len(themes) != n:
        raise ValueError(
            f"latin square needs a square demand: {len(roles)} role(s) but {len(themes)} theme(s)"
        )

    return {
        (role, theme): (r + t) % n
        for r, role in enumerate(roles)
        for t, theme in enumerate(themes)
    }


def latin_square_collisions(
    assignment: Mapping[tuple[str, str], int],
    roles: Iterable[str],
    themes: Iterable[str],
) -> list[str]:
    """Every (role, theme) pair that repeats an axis within its own row or column.

    Kept separate from the constructor on purpose: a construction that verifies itself proves only
    that it agrees with itself. This is callable against *any* assignment, including one a future
    search produces.
    """
    findings: list[str] = []

    for role in roles:
        seen: dict[int, str] = {}
        for (r, theme), axis in assignment.items():
            if r != role:
                continue
            if axis in seen:
                findings.append(f"role {role}: axis {axis} used by both {seen[axis]} and {theme}")
            else:
                seen[axis] = theme

    for theme in themes:
        seen_r: dict[int, str] = {}
        for (role, t), axis in assignment.items():
            if t != theme:
                continue
            if axis in seen_r:
                findings.append(f"theme {theme}: axis {axis} used by both {seen_r[axis]} and {role}")
            else:
                seen_r[axis] = role

    return findings
