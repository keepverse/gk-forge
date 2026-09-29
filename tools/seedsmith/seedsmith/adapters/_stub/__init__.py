"""seedsmith.adapters._stub — a tiny invented feature, used only by the test suite
(spec-foundation §2). If the core ever reaches into item concepts, this stops passing — a cheap,
loud, continuous proof that the feature seam is real.

Two kinds (`widget`, `gadget`), two dimensions (`color`, `size`), one channel (`power`), and one
illegal combination (`color=red` × `size=large`) so `LegalityFn`'s `False` branch is always
exercised, never merely declared.
"""
from __future__ import annotations

from ..base import Channel, Dimension, KindSpec, RegistrySet, Unit

WIDGET = KindSpec(kind="widget", directory="widgets", namespace="widget",
                  required=frozenset({"id"}), optional=frozenset({"color"}))
GADGET = KindSpec(kind="gadget", directory="gadgets", namespace="gadget",
                  required=frozenset({"id"}), optional=frozenset({"size"}))

COLOR = Dimension(id="color", values=("red", "blue"), field="color",
                  applies_to=frozenset({"widget"}))
SIZE = Dimension(id="size", values=("small", "large"), field="size",
                 applies_to=frozenset({"gadget"}))


def _legal(dim_a: str, value_a: str, dim_b: str, value_b: str) -> bool:
    pair = {(dim_a, value_a), (dim_b, value_b)}
    if pair == {("color", "red"), ("size", "large")}:
        return False
    return True


def _power_reference_base(_level: int) -> int:
    # 100, not a token value like 1 or 10: numerics.resolve()'s m1 = round(share x base / 1000)
    # needs a base large enough that a realistic share (tens of permille) doesn't round to 0,
    # exactly the failure mode this constant was originally too small to avoid.
    return 100


POWER = Channel(id="power", unit=Unit.GAME_UNITS, reference_base=_power_reference_base,
                group="primary", ops=frozenset({"Flat"}))

REGISTRIES = RegistrySet(
    vocabularies={
        "tags": frozenset({"shiny", "dull"}),
        # allocated partitions — Coverage/EmptyPartition diffs this against occupied ones
        "partitions": frozenset({"a", "b"}),
    },
    versions={"tags": 1, "partitions": 1},
)


class StubAdapter:
    """Implements `SeedAdapter` structurally (via `@runtime_checkable Protocol`) — no explicit
    base class needed, matching how a real `items` adapter will also just implement the methods."""

    def kinds(self) -> list[KindSpec]:
        return [WIDGET, GADGET]

    def dimensions(self) -> list[Dimension]:
        return [COLOR, SIZE]

    def legal_combinations(self):
        return _legal

    def registries(self) -> RegistrySet:
        return REGISTRIES

    def channels(self) -> list[Channel]:
        return [POWER]
