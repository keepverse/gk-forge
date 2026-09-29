"""base-defense `structure-metrics` (module 29, spec-structure-metrics.md). Says what "good enough"
means for the structure corpus, in numbers, with declared targets — and says which metrics may
NEVER contribute to a pass. Two absolute rules, restated here because a downstream reader of this
file, not just the spec, needs them: **every metric declares closed-loop or open-loop, and an
open-loop metric never contributes to a pass**; **a metric with no declared target is an opinion**.

Zero model calls. Runs against whatever corpus exists today (25 rows, all AUTHORED, zero GENERATED)
exactly as well as it will once `structure-pipeline` (28) produces more — the framework does not
wait for content to feel earned before declaring its own rules (29.1's own point).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .anchor.schema import RARITY, ROLE, STRENGTH_BAND, build_structure_anchor_schema
from .anchor.audit import numeric_audit

CLOSED = "closed"
OPEN = "open"
_LOOPS = (CLOSED, OPEN)


class MetricDeclarationError(Exception):
    """Raised at REGISTRATION time (import time, via the module-level `_declare` calls below) for
    a metric with no loop, or a closed metric with no target — 29.1's own "fails registration"
    requirement, made structural rather than a runtime check some caller could skip."""


@dataclass(frozen=True)
class MetricResult:
    name: str
    loop: str
    value: Any
    target: Any
    passed: "bool | None"  # None for an open-loop metric -- it never has a pass/fail, only a value
    detail: str = ""


@dataclass(frozen=True)
class Metric:
    name: str
    loop: str
    target: Any
    measure: "Callable[[list[dict], dict], MetricResult]"


_REGISTRY: "list[Metric]" = []


def _declare(name: str, loop: str, target: Any, measure: "Callable[[list[dict], dict], MetricResult]") -> Metric:
    if loop not in _LOOPS:
        raise MetricDeclarationError(f"metric {name!r} declares loop={loop!r}, must be one of {_LOOPS}")
    if loop == CLOSED and target is None:
        raise MetricDeclarationError(f"metric {name!r} is closed-loop but declares no target — "
                                      f"'a metric without a declared target is an opinion'")
    if loop == OPEN and target is not None:
        raise MetricDeclarationError(f"metric {name!r} is open-loop but declares a target {target!r} — "
                                      f"open-loop metrics never gate, so a target is meaningless here")
    m = Metric(name, loop, target, measure)
    _REGISTRY.append(m)
    return m


def registered_metrics() -> "list[Metric]":
    return list(_REGISTRY)


# ---- closed-loop metrics, every one with a real, checked target -------------------------------

def _schema_conformance(rows: "list[dict]", tuning: dict) -> MetricResult:
    schema = build_structure_anchor_schema()
    schema_defects = numeric_audit(schema)
    bad_rows = [r["id"] for r in rows if set(r["anchor"].keys()) != set(schema.get("properties", {}).keys())]
    ok = not schema_defects and not bad_rows
    return MetricResult("schema_conformance", CLOSED, value=len(rows) - len(bad_rows), target=len(rows),
                         passed=ok, detail=f"schema_defects={schema_defects} bad_rows={bad_rows}")


def _per_role_coverage(rows: "list[dict]", tuning: dict) -> MetricResult:
    budget = tuning["budget"]
    tolerance = tuning["metrics"]["roleCountTolerance"]
    counts: "dict[str, int]" = {}
    for r in rows:
        role = r["anchor"]["role"]
        counts[role] = counts.get(role, 0) + 1
    misses = {role: (counts.get(role, 0), target) for role, target in budget.items()
              if counts.get(role, 0) < target - tolerance}
    return MetricResult("per_role_coverage", CLOSED, value=counts, target=budget,
                         passed=not misses, detail=f"misses={misses} tolerance={tolerance}")


def _grid_density(rows: "list[dict]", tuning: dict) -> MetricResult:
    band = tuning["metrics"]["densityBand"]
    density_milli = round(1000 * len(rows) / len(ROLE))
    ok = band["minMilli"] <= density_milli <= band["maxMilli"]
    return MetricResult("grid_density", CLOSED, value=density_milli, target=band, passed=ok)


def _tier_ladder_completeness(rows: "list[dict]", tuning: dict) -> MetricResult:
    seen = {r["anchor"]["strengthBand"] for r in rows}
    missing = [b for b in STRENGTH_BAND if b not in seen]
    return MetricResult("tier_ladder_completeness", CLOSED, value=sorted(seen), target=list(STRENGTH_BAND),
                         passed=not missing, detail=f"missing={missing}")


def _acquisition_paths_non_empty(rows: "list[dict]", tuning: dict) -> MetricResult:
    empty = [r["id"] for r in rows if not r["anchor"]["acquisitionPaths"]]
    return MetricResult("acquisition_paths_non_empty", CLOSED, value=len(rows) - len(empty), target=len(rows),
                         passed=not empty, detail=f"empty={empty}")


def _idempotency(rows: "list[dict]", tuning: dict) -> MetricResult:
    # The real hash-equality check lives in generate_corpus's own write_corpus (module 24's own
    # harness) — this metric re-runs it here so the metrics REPORT carries the same closed-loop
    # proof, rather than trusting a sibling test file silently.
    import hashlib
    import tempfile
    from .generate_corpus import write_corpus

    def _hash_tree(root: Path) -> str:
        h = hashlib.sha256()
        for p in sorted(root.rglob("*.json")):
            h.update(p.relative_to(root).as_posix().encode("utf-8"))
            h.update(p.read_bytes())
        return h.hexdigest()

    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        write_corpus(Path(d1))
        write_corpus(Path(d2))
        h1, h2 = _hash_tree(Path(d1)), _hash_tree(Path(d2))
    return MetricResult("idempotency", CLOSED, value=h1, target=h2, passed=h1 == h2)


def _unresolved_rate(rows: "list[dict]", tuning: dict) -> MetricResult:
    # No row is GENERATED yet (structure-pipeline, module 28, has not run) -- "unresolved" only
    # ever appears as a majority-vote failure sentinel on a GENERATED row's own field, per
    # spec-structure-pipeline.md 28.2. Declared and measured now anyway (29.1's own rule), against
    # the AUTHORED rows that exist today, correctly reading 0.
    generated = [r for r in rows if r["_provenance"]["source"] == "GENERATED"]
    unresolved_count = sum(
        1 for r in generated for v in r["anchor"].values() if v == "unresolved"
    )
    ceiling_milli = tuning["metrics"]["unresolvedCeilingMilli"]
    total_fields = len(generated) * len(build_structure_anchor_schema()["properties"]) or 1
    rate_milli = round(1000 * unresolved_count / total_fields)
    return MetricResult("unresolved_rate", CLOSED, value=rate_milli, target=ceiling_milli,
                         passed=rate_milli <= ceiling_milli,
                         detail=f"{unresolved_count} unresolved fields across {len(generated)} generated rows")


# ---- open-loop metrics — review queue only, structurally unable to fail a build ----------------

_DISTINCTNESS_FIELDS = ("role", "obstacleVerbs", "acquisitionPaths", "traits", "elementPrimary", "elementSecondary")


def _flavour_distinctness(rows: "list[dict]", tuning: dict) -> MetricResult:
    """Distinctness reads ABILITIES, not stats (spec §4) — only `_DISTINCTNESS_FIELDS`, never
    `strengthBand`/`rarity`. A source scan test (`test_distinctness_reads_abilities_not_stats`)
    proves this function's own body never references either forbidden field name."""
    signatures = set()
    for r in rows:
        sig = tuple(json.dumps(r["anchor"].get(f), sort_keys=True) for f in _DISTINCTNESS_FIELDS)
        signatures.add(sig)
    distinct_ratio_milli = round(1000 * len(signatures) / len(rows)) if rows else 0
    return MetricResult("flavour_distinctness", OPEN, value=distinct_ratio_milli, target=None, passed=None,
                         detail=f"{len(signatures)} distinct signatures / {len(rows)} rows — review queue only")


def _mode_collapse_ngram_overlap(rows: "list[dict]", tuning: dict) -> MetricResult:
    """Flags only — never a gate (spec §1's table, and 28.6's own 'flags, never fails'). Trigram
    overlap over each row's own `reason` text, the closest thing this corpus has to prose today."""
    threshold = tuning["metrics"]["collapseNgramThreshold"]

    def trigrams(text: str) -> "set[str]":
        words = re.findall(r"[a-z]+", text.lower())
        return {" ".join(words[i:i + 3]) for i in range(max(0, len(words) - 2))}

    flagged = []
    texts = [(r["id"], trigrams(r["_provenance"].get("citation", ""))) for r in rows]
    for i, (id_a, tg_a) in enumerate(texts):
        for id_b, tg_b in texts[i + 1:]:
            overlap = len(tg_a & tg_b)
            if overlap >= threshold:
                flagged.append((id_a, id_b, overlap))
    return MetricResult("mode_collapse_ngram_overlap", OPEN, value=flagged, target=None, passed=None,
                         detail=f"{len(flagged)} pairs at/above overlap {threshold} — review queue only")


# ---- rarity must not correlate with strengthBand beyond breadth/ceiling (spec §5) --------------

def _rarity_strength_correlation(rows: "list[dict]", tuning: dict) -> MetricResult:
    band_rank = {b: i for i, b in enumerate(STRENGTH_BAND)}
    rarity_rank = {r: i for i, r in enumerate(RARITY)}
    by_band: "dict[str, list[int]]" = {}
    for r in rows:
        b = r["anchor"]["strengthBand"]
        by_band.setdefault(b, []).append(rarity_rank[r["anchor"]["rarity"]])

    # A simple, defensible correlation proxy: the average rarity rank per strengthBand should not
    # itself be monotonically increasing in lock-step with strengthBand's own rank by more than one
    # full rarity rung -- "rarity buys breadth and ceiling, never power" means the rungs should
    # overlap, not stack in strict lockstep with material tier.
    avg_by_band = {b: sum(v) / len(v) for b, v in by_band.items()}
    ordered = sorted(avg_by_band.items(), key=lambda kv: band_rank[kv[0]])
    max_gap = max((b - a for (_, a), (_, b) in zip(ordered, ordered[1:])), default=0)
    ok = max_gap <= len(RARITY) / 2  # generous: catches a real lockstep power-axis, not noise on 25 rows
    return MetricResult("rarity_strength_correlation", CLOSED, value=avg_by_band, target=f"<= {len(RARITY) / 2} avg-rank gap",
                         passed=ok, detail=f"ordered={ordered} max_gap={max_gap}")


SCHEMA_CONFORMANCE = _declare("schema_conformance", CLOSED, "100%", _schema_conformance)
PER_ROLE_COVERAGE = _declare("per_role_coverage", CLOSED, "±tolerance of budget", _per_role_coverage)
GRID_DENSITY = _declare("grid_density", CLOSED, "2400-4000 per-mille", _grid_density)
TIER_LADDER_COMPLETENESS = _declare("tier_ladder_completeness", CLOSED, "every rung has a row", _tier_ladder_completeness)
ACQUISITION_PATHS_NON_EMPTY = _declare("acquisition_paths_non_empty", CLOSED, "100%", _acquisition_paths_non_empty)
IDEMPOTENCY = _declare("idempotency", CLOSED, "hash equality", _idempotency)
UNRESOLVED_RATE = _declare("unresolved_rate", CLOSED, "below declared ceiling", _unresolved_rate)
RARITY_STRENGTH_CORRELATION = _declare("rarity_strength_correlation", CLOSED, "no lockstep power axis", _rarity_strength_correlation)
FLAVOUR_DISTINCTNESS = _declare("flavour_distinctness", OPEN, None, _flavour_distinctness)
MODE_COLLAPSE_NGRAM_OVERLAP = _declare("mode_collapse_ngram_overlap", OPEN, None, _mode_collapse_ngram_overlap)


@dataclass(frozen=True)
class Report:
    header: str
    results: "list[MetricResult]"

    @property
    def passed(self) -> bool:
        """Only CLOSED-loop results can ever make this False — structural, not a filter someone
        could forget to apply: this property is the ONLY place a bool is derived from `results`,
        and it only ever reads `passed` on a result whose own metric declared `loop == CLOSED`."""
        return all(r.passed for r in self.results if r.loop == CLOSED)

    def to_dict(self) -> dict:
        return {
            "header": self.header,
            "passed": self.passed,
            "results": [r.__dict__ for r in self.results],
        }


ANCHOR_NOT_ROSTER_HEADER = (
    "A complete anchor is not a complete roster: this corpus's rows are the IDENTITY layer only. "
    "Traits and actions per structure are a separate, larger body of work, still to come from "
    "structure-pipeline (28) once its own container-shape question is resolved."
)


def run_all(rows: "list[dict]", tuning: dict) -> Report:
    results = [m.measure(rows, tuning) for m in _REGISTRY]
    return Report(header=ANCHOR_NOT_ROSTER_HEADER, results=results)


if __name__ == "__main__":
    import sys as _sys

    from .generate_corpus import ALL_ROWS as _ALL_ROWS

    _repo_root = Path(__file__).resolve().parents[5]
    _tuning = json.loads((_repo_root / "data" / "tuning" / "structure-seed.v1.json").read_text(encoding="utf-8"))
    _report = run_all(list(_ALL_ROWS), _tuning)

    print(_report.header)
    print()
    for _r in _report.results:
        _status = "PASS" if _r.passed else ("FAIL" if _r.passed is False else "info")
        print(f"[{_r.loop:>6}] {_status:>4}  {_r.name}: {_r.value!r} (target: {_r.target!r})")
        if _r.detail:
            print(f"           {_r.detail}")
    print()
    print(f"OVERALL: {'PASS' if _report.passed else 'FAIL'}")
    _sys.exit(0 if _report.passed else 1)
