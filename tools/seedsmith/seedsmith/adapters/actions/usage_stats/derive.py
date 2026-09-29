"""seedsmith.adapters.actions.usage_stats.derive --- FC1 `usage-stats`
(spec-usage-stats.md, roster-balance program).

Measures how evenly the three propose pipelines (`general_propose`/`family_propose`/
`signature_propose`) actually draw from the 98 authored atom/affix families
(`gk-data/packs/fusion/data/seed/items/affix-families/*.json`). Nothing else in this repo does this:
`coverage_report.derive.atom_family_namespace_findings` validates that a picked family id is one of
the 98 -- it has never tallied how OFTEN each one is picked, which is the question this module
answers. Measured directly, 2026-09-06, over every real committed round: 216 accepted candidates,
59 of 98 families ever used, 39 never used, top-10 families = 45.1% of every pick.

Pure and model-free. Reads committed round files and the family corpus; writes nothing.
"""
from __future__ import annotations

import glob
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

__all__ = [
    "load_affix_family_ids", "load_round_files", "tally_usage", "evenness", "top_n_share",
    "never_used", "UsageReport", "build_report", "canonical_dump",
]

#: Rounds recorded specifically to compare a DIFFERENT model against the baseline
#: (the refuted 2026-09-04 model-swap experiment) are deliberately real output, but not real
#: PRODUCTION output -- mixing them into the tally would double-count the same briefs under a model
#: this repo does not run in practice. Excluded by filename, not by any content heuristic.
_EXCLUDED_SUFFIX = "-model-experiment.json"

_SCOPES: "tuple[str, ...]" = ("general", "family", "signature")

#: The runtime pre-acceptance scratch dir a machine that has run the actions pipeline has populated.
#: Gitignored (`.gitignore` `/data/seed/actions/_candidates/`), so it is absent from every fresh
#: checkout -- before the fixture below, a clean checkout therefore read an EMPTY corpus and reported
#: `acceptedCount: 0` (SGC5-F1).
_RUNTIME_CANDIDATES_PREFIX: "tuple[str, ...]" = ("data", "seed", "actions", "_candidates")
#: The tracked minimal round corpus (one accepted candidate -- the pinned general-propose worked
#: example) committed for exactly the case the runtime dir is absent. Deliberately NOT mixed into a
#: real corpus: `_round_corpus_root` returns the runtime dir whenever it holds any real round file, so
#: a machine that ran the pipeline never double-counts the fixture's single candidate.
_FIXTURE_CANDIDATES_PREFIX: "tuple[str, ...]" = ("data", "seed", "actions", "_fixtures")


def _has_real_round_file(root: Path) -> bool:
    """True when `root` holds at least one round file this module would actually tally -- the
    model-experiment file is excluded by name, so a dir holding only that one is not a corpus."""
    for scope in _SCOPES:
        for path in (root / scope).glob("round-*.json"):
            if not path.name.endswith(_EXCLUDED_SUFFIX):
                return True
    return False


def _round_corpus_root(repo_root: Path) -> Path:
    """The runtime scratch dir when a machine has run the actions pipeline, else the tracked fixture
    -- so the report is reproducible on a clean checkout instead of empty, and a real corpus is never
    diluted by the fixture."""
    runtime = repo_root.joinpath(*_RUNTIME_CANDIDATES_PREFIX)
    if _has_real_round_file(runtime):
        return runtime
    return repo_root.joinpath(*_FIXTURE_CANDIDATES_PREFIX)


def load_affix_family_ids(root: Path) -> "frozenset[str]":
    """The real, full 98-family namespace -- read fresh, never hand-listed, so a corpus change is
    picked up with no code edit (the same discipline `atom_family_namespace_findings` already uses
    for its own membership check)."""
    ids: "set[str]" = set()
    for path in sorted((root / "data" / "seed" / "items" / "affix-families").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        entries = doc.get("entries", doc) if isinstance(doc, dict) else doc
        for entry in entries:
            fam_id = entry.get("id")
            if fam_id:
                ids.add(fam_id)
    return frozenset(ids)


def _round_number(path: Path) -> int:
    """`round-903.json` -> 903, `round-1.json` -> 1. Used only to find the LATEST round per scope --
    never to order output, which stays sorted on scope/id."""
    stem = path.stem  # "round-903"
    try:
        return int(stem.rsplit("-", 1)[-1])
    except ValueError:
        return -1


def load_round_files(candidates_root: Path) -> "dict[str, list[tuple[int, list[Mapping[str, Any]]]]]":
    """Every real committed round file per scope, as `(roundNumber, rows)`, excluding the
    model-experiment file by name. An unreadable file is a named error -- never a silent skip, since
    a corrupt round silently dropped from the tally would understate real usage without anyone
    noticing."""
    out: "dict[str, list[tuple[int, list[Mapping[str, Any]]]]]" = {s: [] for s in _SCOPES}
    for scope in _SCOPES:
        scope_dir = candidates_root / scope
        if not scope_dir.exists():
            continue
        for path in sorted(scope_dir.glob("round-*.json")):
            if path.name.endswith(_EXCLUDED_SUFFIX):
                continue
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"usage-stats: could not read {path} -- {exc}") from exc
            rows = doc.get("entries", doc) if isinstance(doc, dict) else doc
            out[scope].append((_round_number(path), list(rows)))
    return out


def tally_usage(rows: Sequence[Mapping[str, Any]]) -> "Counter[str]":
    """One accepted row counts each of its OWN families once, never once per occurrence -- a
    2-family bundle contributes 1 to each of its two families, not weighted by bundle size.
    Weighting by bundle size would conflate "this bundle is big" with "this family is popular",
    which are different facts. Only `outcome == "accepted"` rows contribute; `unresolved` and
    `blocked` rows produced no real content and must not count as if they had."""
    counts: "Counter[str]" = Counter()
    for row in rows:
        if row.get("outcome") != "accepted":
            continue
        families = (row.get("draft") or {}).get("atomFamilies") or []
        counts.update(set(families))
    return counts


def evenness(counts: "Mapping[str, int]", population: "frozenset[str]") -> float:
    """Normalised Shannon entropy over the FULL population, not only the families that appear -- a
    family with zero picks is a real data point, not an absence of one, and must pull the number
    down exactly as it would if it were being measured directly. `1.0` is perfectly uniform, `0.0` is
    everything in one family."""
    n = sum(counts.values())
    k = len(population)
    if k <= 1 or n == 0:
        return 0.0
    h = 0.0
    for fam in population:
        c = counts.get(fam, 0)
        if c == 0:
            continue
        p = c / n
        h -= p * math.log2(p)
    return h / math.log2(k)


def top_n_share(counts: "Mapping[str, int]", n: int) -> float:
    """The share of all picks held by the n most-picked families -- 0.0 when there is no usage at
    all, never a division error."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    top = sorted(counts.values(), reverse=True)[:n]
    return sum(top) / total


def never_used(counts: "Mapping[str, int]", population: "frozenset[str]") -> "list[str]":
    """Every family with zero real picks, named individually and sorted -- 39 different,
    individually addressable facts, not one number FC3 cannot act on."""
    return sorted(fam for fam in population if counts.get(fam, 0) == 0)


class UsageReport:
    """The full report: all-time and latest-round usage, kept SEPARATE deliberately -- all-time
    answers "how are we doing", latest-round answers "what should change next", and conflating them
    would let one old, no-longer-representative round keep suppressing a family the current
    pipeline already handles fine."""

    def __init__(self, *, population: "frozenset[str]",
                all_time: "Counter[str]", latest_round: "Counter[str]",
                accepted_count: int, latest_round_numbers: "Mapping[str, int]") -> None:
        self.population = population
        self.all_time = all_time
        self.latest_round = latest_round
        self.accepted_count = accepted_count
        self.latest_round_numbers = dict(latest_round_numbers)

    def to_dict(self) -> "dict[str, Any]":
        pop_sorted = sorted(self.population)
        return {
            "schemaVersion": 1,
            "kind": "action-family-usage-report",
            "populationSize": len(self.population),
            "acceptedCount": self.accepted_count,
            "latestRoundNumbers": dict(sorted(self.latest_round_numbers.items())),
            "allTime": {
                "familiesUsed": sum(1 for f in pop_sorted if self.all_time.get(f, 0) > 0),
                "neverUsed": never_used(self.all_time, self.population),
                "evennessMilli": round(evenness(self.all_time, self.population) * 1000),
                "top10SharePermille": round(top_n_share(self.all_time, 10) * 1000),
                "counts": {f: self.all_time.get(f, 0) for f in pop_sorted if self.all_time.get(f, 0) > 0},
            },
            "latestRound": {
                "familiesUsed": sum(1 for f in pop_sorted if self.latest_round.get(f, 0) > 0),
                "neverUsed": never_used(self.latest_round, self.population),
                "evennessMilli": round(evenness(self.latest_round, self.population) * 1000),
                "top10SharePermille": round(top_n_share(self.latest_round, 10) * 1000),
                "counts": {f: self.latest_round.get(f, 0) for f in pop_sorted if self.latest_round.get(f, 0) > 0},
            },
        }


def build_report(repo_root: Path) -> UsageReport:
    """The real, live report -- reads the real family corpus and every real committed round file.
    Pure aside from the two reads; no write, no model call. The round files come from the runtime
    `_candidates/` scratch dir when the machine has run the pipeline, and from the tracked minimal
    fixture otherwise (see `_round_corpus_root`)."""
    population = load_affix_family_ids(repo_root)
    by_scope = load_round_files(_round_corpus_root(repo_root))

    all_time: "Counter[str]" = Counter()
    latest_round: "Counter[str]" = Counter()
    latest_numbers: "dict[str, int]" = {}
    accepted_count = 0

    for scope, rounds in by_scope.items():
        if not rounds:
            continue
        for _, rows in rounds:
            all_time.update(tally_usage(rows))
            accepted_count += sum(1 for r in rows if r.get("outcome") == "accepted")
        latest_no, latest_rows = max(rounds, key=lambda pair: pair[0])
        latest_numbers[scope] = latest_no
        latest_round.update(tally_usage(latest_rows))

    return UsageReport(population=population, all_time=all_time, latest_round=latest_round,
                       accepted_count=accepted_count, latest_round_numbers=latest_numbers)


def canonical_dump(doc: "Mapping[str, Any]") -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
