"""Kind-level generation order, derived rather than declared (spec-planner.md, plan P2).

The incident this exists for: **274 same-stage errors.** A generation stage carried a hand-written
label, the kind graph beneath it changed, and the label did not. Every one of those errors was a
reference to a kind that had not been generated yet.

The structural fix is to stop stating the order at all. A kind's `reference_fields` already say
which of its fields hold cross-kind references; the order follows from those, so there is no second
copy to drift. **A stage label is a fact written down twice, and the copy nobody edits is the one
that goes stale.**

Two algorithms, each chosen for what it reports rather than only what it computes:

- **Kahn** gives layers, not just a sequence. Layers say what may be generated *in parallel*, which
  a plain topological order flattens away for no reason.
- **Tarjan** names a cycle's exact members. "Cycle detected" sends a human to read the whole graph;
  "`recipe` and `unique` reference each other" sends them to two files.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

__all__ = ["KindOrder", "OrderCycle", "derive_kind_order", "kind_edges", "strongly_connected"]


@dataclass(frozen=True)
class OrderCycle:
    """A dependency cycle, with its members named.

    Ordering is impossible while one exists, and *which* kinds form it is the only fact that makes
    the failure fixable — so it is a field, not a log line.
    """

    members: tuple[str, ...]

    def explain(self) -> str:
        return (
            f"dependency cycle among {len(self.members)} kind(s): "
            f"{' -> '.join(self.members)} -> {self.members[0]}"
        )


@dataclass(frozen=True)
class KindOrder:
    layers: tuple[tuple[str, ...], ...]
    cycles: tuple[OrderCycle, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.cycles

    @property
    def flat(self) -> tuple[str, ...]:
        return tuple(kind for layer in self.layers for kind in layer)

    def stage_of(self, kind: str) -> int:
        """Which layer a kind generates in. Raises for an unknown kind rather than returning a
        sentinel — a stage of -1 silently sorts first, which is the failure mode this whole module
        exists to remove."""
        for i, layer in enumerate(self.layers):
            if kind in layer:
                return i
        raise KeyError(f"kind {kind!r} is not in the derived order")


def kind_edges(
    kinds: Sequence[object],
    entry_kind_of: Mapping[str, str],
    edges: Iterable[object],
) -> dict[str, set[str]]:
    """Collapse entry-level edges into a kind-level dependency graph.

    `kinds` are `KindSpec`s (duck-typed on `.kind` and `.reference_fields`, so a test can pass a
    stub without importing the adapter). `entry_kind_of` maps an entry id to its kind, and `edges`
    are `corpus.discover_edges` output — **reused, not reinvented**, per the plan: entry-level
    reference discovery already exists and already handles nested paths and skip-fields.

    An edge counts only when its source field is one the kind declares as a reference field. That
    is what stops a `nameKey` that happens to look like an id from inventing a dependency — the
    same distinction `discover_edges`' own `skip_fields` draws, applied one level up.

    Direction: `A -> B` means "A references B", so **B must be generated first**. The topological
    sort below reverses accordingly; getting this backwards produces an order that is exactly wrong
    everywhere, which is why it is stated here rather than left to the reader.
    """
    refs_by_kind = {k.kind: frozenset(getattr(k, "reference_fields", frozenset())) for k in kinds}
    graph: dict[str, set[str]] = {k.kind: set() for k in kinds}

    for edge in edges:
        from_kind = entry_kind_of.get(edge.from_id)
        to_kind = entry_kind_of.get(edge.to_id)
        if from_kind is None or to_kind is None:
            continue                       # a dangling ref is Linkage's finding, not ordering's
        if from_kind == to_kind:
            continue                       # self-reference within a kind orders nothing
        # `members[0].ref` -> `members`: the declared field is the root of the path.
        root = edge.via.split(".", 1)[0].split("[", 1)[0]
        if root not in refs_by_kind.get(from_kind, frozenset()):
            continue
        graph[from_kind].add(to_kind)

    return graph


def derive_kind_order(graph: Mapping[str, set[str]]) -> KindOrder:
    """Kahn's algorithm into layers, with Tarjan naming any cycle.

    A kind with no references generates first. Within a layer, kinds are sorted by id so the order
    is reproducible — an ordering that varies between runs cannot be diffed, and this one is meant
    to be compared against a historical order.
    """
    cycles = tuple(
        OrderCycle(tuple(sorted(scc)))
        for scc in strongly_connected(graph)
        if len(scc) > 1 or any(n in graph.get(n, ()) for n in scc)
    )
    if cycles:
        return KindOrder(layers=(), cycles=cycles)

    # in_degree counts references *out* of a kind: a kind that references two others waits for both.
    remaining = {k: set(v) for k, v in graph.items()}
    dependents: dict[str, set[str]] = defaultdict(set)
    for k, refs in graph.items():
        for r in refs:
            dependents[r].add(k)

    layers: list[tuple[str, ...]] = []
    ready = deque(sorted(k for k, refs in remaining.items() if not refs))
    placed: set[str] = set()

    while ready:
        layer = tuple(sorted(ready))
        layers.append(layer)
        placed.update(layer)
        ready.clear()
        for kind in layer:
            for dependent in sorted(dependents.get(kind, ())):
                remaining[dependent].discard(kind)
                if not remaining[dependent] and dependent not in placed:
                    if dependent not in ready:
                        ready.append(dependent)

    return KindOrder(layers=tuple(layers))


def strongly_connected(graph: Mapping[str, set[str]]) -> list[list[str]]:
    """Tarjan's SCC, iterative.

    Iterative rather than recursive on purpose: the recursive form is shorter, and it dies with a
    `RecursionError` on a deep graph — a failure that looks like a crash in this module rather than
    the "your graph is deep" it actually is.

    Returns every component, including singletons; the caller decides which count as cycles (a
    singleton is only a cycle if it references itself).
    """
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    result: list[list[str]] = []
    counter = 0

    for root in sorted(graph):
        if root in index:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, child_i = work[-1]
            if child_i == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)

            children = sorted(graph.get(node, ()))
            if child_i < len(children):
                work[-1] = (node, child_i + 1)
                child = children[child_i]
                if child not in index:
                    work.append((child, 0))
                elif child in on_stack:
                    low[node] = min(low[node], index[child])
            else:
                if low[node] == index[node]:
                    component: list[str] = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        component.append(w)
                        if w == node:
                            break
                    result.append(component)
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])

    return result
