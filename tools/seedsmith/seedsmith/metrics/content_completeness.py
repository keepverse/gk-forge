"""seedsmith.metrics.content_completeness — the generalized missing-field metric registry
(spec-content-completeness-core.md §5, `seedsmith-content-standard` Task 3).

Generalizes `Quality/FlavourMissing`'s (`metrics/quality.py:24`) own per-domain narrowing
(`FLAVOR_EXPECTED_KINDS`, a hardcoded frozenset) into a registration: a domain calls
`register_completeness` once instead of a shared module growing a new domain-specific branch every
time. `FlavourMissing` itself is re-expressed as the FIRST registered spec (items) below, proving
the generalization is additive — `metrics/quality.py`'s own class is untouched and still registered
separately in `report/cli.py`, so nothing that already depends on `Quality/FlavourMissing`'s exact
id/behavior breaks; `Content/FieldMissing` is a new, second metric that happens to reuse the same
predicate shape for items today, not a replacement.

A companion `Content/FieldStale` metric reports the staleness signal from `pipeline/staleness.py` —
also `gates=False`, also never a regeneration trigger (spec §3): staleness here is read-only
information for a person deciding whether to run `--force`, never an input to what an automatic
resumed run does.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping

from .model import Ctx, Finding, Loop, Metric, Severity

__all__ = [
    "CompletenessSpec",
    "register_completeness",
    "registered_specs",
    "clear_registry",
    "ContentFieldMissing",
    "ContentLanguageContamination",
    "ContentFieldStale",
]


@dataclass(frozen=True)
class CompletenessSpec:
    """One domain's own definition of "missing" for one field. `is_missing` overrides the default
    falsy-check when a domain's own "missing" isn't simply "falsy" (e.g. an intentionally-empty
    string is a real, distinct value for that domain's schema — the plan's own Risks table names
    this exact failure mode) — each domain's own module spec states which shape it needs."""

    domain: str
    kinds: "frozenset[str]"
    field: str
    is_missing: "Callable[[Mapping], bool] | None" = None

    def missing(self, entry) -> bool:
        if self.is_missing is not None:
            return self.is_missing(entry.data)
        return not entry.get(self.field)


_REGISTRY: "list[CompletenessSpec]" = []


def register_completeness(spec: CompletenessSpec) -> None:
    """Idempotent by equality — real gap found building `content-completeness-items` (Task 6):
    `report/cli.py`'s own `build_registry()` is the one real production call site that needs a
    domain's spec present on every real run, but it is also called repeatedly within a single
    pytest process (once per test that exercises `check`), and `tests/test_content_completeness.py`
    calls `clear_registry()` in its own `tearDown` for test isolation. Without idempotency, either
    `build_registry()` re-appends the same spec on every call (inflating findings — a spec that
    registers `n` times reports the same missing entry `n` times), or a test-suite-order dependent
    `clear_registry()` call silently empties the registry for whatever real code path runs next in
    the same process. Skipping an exact duplicate (frozen-dataclass `==`) makes `build_registry()`
    safe to call any number of times and safe to call after a test has cleared the registry — it
    always re-establishes its own domain specs before returning."""
    if spec in _REGISTRY:
        return
    _REGISTRY.append(spec)


def registered_specs() -> "tuple[CompletenessSpec, ...]":
    return tuple(_REGISTRY)


def clear_registry() -> None:
    """Test-only: `_REGISTRY` is module-level state, so a test suite that registers a spec must be
    able to reset it rather than leaking into unrelated tests' corpus scans."""
    _REGISTRY.clear()


class ContentFieldMissing(Metric):
    id = "Content/FieldMissing"
    family = "Content"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"corpus"})
    covers: tuple[str, ...] = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        findings = []
        for spec in _REGISTRY:
            for kind in sorted(spec.kinds):
                entries = ctx.corpus.by_kind(kind)
                if not entries:
                    continue
                missing = [e for e in entries if spec.missing(e)]
                if not missing:
                    continue
                sample = ", ".join(e.id for e in missing[:3])
                more = f", +{len(missing) - 3} more" if len(missing) > 3 else ""
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=f"{spec.domain}:{kind}",
                    message=f"{len(missing)} of {len(entries)} '{kind}' entries in domain "
                            f"{spec.domain!r} have no {spec.field!r} ({sample}{more})",
                    evidence={"domain": spec.domain, "field": spec.field,
                             "missingCount": len(missing), "totalCount": len(entries)}))
        return findings


class ContentLanguageContamination(Metric):
    """Task 4b: registers the fixed, bidirectional `language_consistency` check
    (`workflow/validators/language.py`) into `core`'s own registry, so every domain that adopts
    `content-completeness-core` gets it for free rather than importing `language_consistency`
    piecemeal the way creatures/passive-tree do today. Runs the check against every registered
    spec's own `field` (the same text this module already treats as this domain's player-facing
    content) — a domain does not register separately for this; it comes with `CompletenessSpec`."""

    id = "Content/LanguageContamination"
    family = "Content"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"corpus"})
    covers: tuple[str, ...] = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        from ..workflow.validators.language import language_consistency

        findings = []
        for spec in _REGISTRY:
            for kind in sorted(spec.kinds):
                for entry in ctx.corpus.by_kind(kind):
                    value = entry.get(spec.field)
                    if not isinstance(value, str) or not value.strip():
                        continue
                    defects = language_consistency({spec.field: value}, {})
                    for defect in defects:
                        findings.append(Finding(
                            metric=self.id, severity=Severity.GAP,
                            subject=f"{spec.domain}:{entry.id}",
                            message=f"{entry.id!r} ({spec.domain}/{kind}): {defect}",
                            evidence={"domain": spec.domain, "kind": kind, "field": spec.field}))
        return findings


class ContentFieldStale(Metric):
    """Reports staleness per `pipeline/staleness.py` — never a regeneration trigger (spec §3).
    A domain opts in by giving its entries a `_stalenessKey` alongside the field this checks;
    a domain that never stamps one simply reports nothing here, which is correct (NOT_MEASURED-
    shaped silence, not a false claim of freshness)."""

    id = "Content/FieldStale"
    family = "Content"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"corpus"})
    covers: tuple[str, ...] = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        from ..pipeline.staleness import is_stale

        findings = []
        for spec in _REGISTRY:
            for kind in sorted(spec.kinds):
                entries = ctx.corpus.by_kind(kind)
                stale = [e for e in entries if e.get("_stalenessCurrentKey") is not None
                        and is_stale(e.get("_provenance"), e.get("_stalenessCurrentKey"))]
                if not stale:
                    continue
                sample = ", ".join(e.id for e in stale[:3])
                more = f", +{len(stale) - 3} more" if len(stale) > 3 else ""
                findings.append(Finding(
                    metric=self.id, severity=Severity.NOTE, subject=f"{spec.domain}:{kind}",
                    message=f"{len(stale)} of {len(entries)} '{kind}' entries in domain "
                            f"{spec.domain!r} are stale ({sample}{more}) — re-run with --force to "
                            f"refresh them; a resumed run will NOT touch these automatically",
                    evidence={"domain": spec.domain, "staleCount": len(stale),
                             "totalCount": len(entries)}))
        return findings
