"""seedsmith.adapters.actions.innate_picker.derive — spec-innate-picker.md §3's algorithm
(module A-S6, build order 7 of 7 model-free). Pure derivation; the one file that touches disk is
the sibling entrypoint `../generate_innate_picker.py`, matching every `derive.py` in this adapter
family.

**Model calls: none — permanently, not provisionally** (spec's own opening line). The innate is a
free sixth action slot outside `LoadoutSet.MaxSize = 5` (`LoadoutSet.cs:40`), so choosing it is a
magnitude decision (how much power is free) — out of a model's reach for good, unlike every other
module in this program whose "model-free" status is provisional.

**Real input gap, same shape every prior module in this session has documented rather than
papered over.** This module's real input — "the accepted corpus, A-S3 survivors plus everything
already accepted" — does not exist yet (A-S4, `validate-heal`, is a later, unbuilt module, so A-S3
has never run for real). Every function below is proven against synthetic, in-memory
accepted-row/candidate fixtures (`tests/test_innate_picker.py`), the same discipline
`dedup_select`/`coverage_report` used against their own not-yet-existing real inputs.

**A genuine schema gap this module had to close, flagged rather than hidden — `elementMatch`'s own
input field.** Spec §3.2 defines `elementMatch` as comparing "a seed's declared element affinity"
against the species' catalog element, and constraint 1 (map §3) restates the same "declared
element affinity" phrase. But no action-seed field carries one anywhere in the shipped shape: an
atom family's own element is a per-roll `{variant}` template resolved at layer 4
(`gk-data/packs/fusion/data/seed/items/affix-families/g-on-hit.json:29` etc — `"params": {"element": "{variant}"}`),
never fixed at seed time, and `kinds.py`'s own `ACTION_SEED_REQUIRED`/`ACTION_SEED_OPTIONAL`
(spec-corpus-loader.md §3 step 4's own transcribed shape) name no `element`/`elementAffinity`
field at all — confirmed by a direct read of `kinds.py`, not assumed. This module reads an
OPTIONAL `elementAffinity` field permissively (`row.get("elementAffinity")`, `None` when absent),
the same "read what's there, never invent it" discipline `dedup_select.derive.parse_candidate`
already uses for `briefId`/`rationale` (fields also outside the declared shape): nothing in
`kinds.py`'s loader forbids an extra field on an envelope row, so a future A-P module can start
writing a real element id there (e.g. `"fire"`) without any change here, and every real candidate
today — which never carries the field — scores `elementMatch: 0` honestly rather than crashing or
guessing.

**A genuine arithmetic-derivation gap, resolved and flagged — what `M_t` in §3.3 actually ranges
over.** Spec §3.3 defines `M_t` as "the observed maximum of term `t`" and `base_t = base_{t+1} *
(M_{t+1} + 1)`, `score = Σ_t ((long)base_t * (term_t + offset_t) * w_t) / 1000`. Taken as the RAW
term (§3.2's own table — term 5 is literally `-rungCeiling`, ranging -10..-1), `M_5` would be
negative, making `base_4 = base_5 * (M_5 + 1)` collapse to 0 whenever the best (lowest) rungCeiling
in the eligible set is 1 — silently erasing every lower-priority term's contribution. The only
self-consistent reading (and the one this module implements): `M_t` is the observed maximum of the
SHIFTED value `term_t + offset_t` — the same quantity the score formula's own `(term_t +
offset_t)` factor uses — which is always non-negative (`offset_t` is 0 for every term except
`-rungCeiling`, whose `+cap` shift is exactly what makes it usable as a radix count in the first
place). For terms 1-4 (`offset_t = 0`) this is identical to the raw reading, so the correction is
invisible except for term 5.

**The `+cap` offset's own source — no second rung curve, no new literal.** `cap` is the species scope's
own window ceiling, loaded from the published rung table by the entrypoint
(`distribution_planner.derive.load_scope_windows(path)["species"][1]`) and passed down as a required
parameter — ST3 (`spec-scope-window-tunables.md` contract 3) moved it there from the code constant this
module used to import, so a retuned window reaches the picker through the file and nowhere else. This
module still reads `rungBand` as-is, shifting it by that one shared value, nothing else (spec §4's own
"never introduce a second rung curve").
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import AbstractSet, Mapping, Sequence

from ..characteristic_pool.catalog import SpeciesRow
from ..characteristic_pool.derive import CATEGORIES
from ..vocab import SCOPES
from .tuning import InnateWeights

__all__ = [
    "SpeciesRoleLean", "parse_role_lean_doc", "InnateCandidate", "parse_candidate",
    "is_eligible", "validate_eligible_set", "compute_terms", "compute_score",
    "Pick", "pick_for_species", "pick_all_species", "build_entries",
    "apply_promotions", "reduce_round_survivors_to_markers",
    "corpus_hash", "build_envelope", "build_committed_envelope", "canonical_dump",
]

# The repo-wide `long` bound (docs/architecture/numeric-types.md's numeric-overflow table) — same guard
# `distribution_planner/derive.py`'s own `_widen_mul` uses; Python ints never actually overflow, so
# this is an EXPLICIT check standing in for the `long` every C# consumer eventually reads this as.
_LONG_MAX = 9_223_372_036_854_775_807
_LONG_MIN = -9_223_372_036_854_775_808


def _widen_mul(a: int, b: int) -> int:
    a = int(a)
    b = int(b)
    product = a * b
    if product > _LONG_MAX or product < _LONG_MIN:
        raise OverflowError(f"_widen_mul({a}, {b}) = {product} does not fit a long "
                            f"({_LONG_MIN}..{_LONG_MAX})")
    return product


def _check_long(value: int) -> int:
    if value > _LONG_MAX or value < _LONG_MIN:
        raise OverflowError(f"{value} does not fit a long ({_LONG_MIN}..{_LONG_MAX})")
    return value


# The species rung window's own ceiling -- see the module docstring's "+cap offset" note. It is
# NOT a constant here any more: ST3 (`spec-scope-window-tunables.md` contract 3) made the windows a
# published tunable, so the entrypoint loads them once (`load_scope_windows`) and passes the ceiling
# down as the required `cap` every stage below takes. There is deliberately no default: a silent
# fallback is exactly the code literal this module exists without.


# ---------------------------------------------------------------------------------------------
# role-lean.json (A-S0) — the same fields `distribution_planner.derive.parse_species_anchor`
# reads, plus `leanOrder`/`leanSource`, which that function does not carry.
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SpeciesRoleLean:
    species_key: str
    family: "str | None"
    lean_order: "tuple[str, ...]"
    lean_source: str                    # "floor" | "derived" | "derived-nofloor"
    motifs: "tuple[str, ...]"


def parse_role_lean_doc(doc: Mapping[str, object]) -> "dict[str, SpeciesRoleLean]":
    out: "dict[str, SpeciesRoleLean]" = {}
    for e in doc["entries"]:
        out[e["speciesKey"]] = SpeciesRoleLean(
            species_key=e["speciesKey"], family=e.get("family"),
            lean_order=tuple(e["leanOrder"]), lean_source=e["leanSource"],
            motifs=tuple(e.get("motifs") or ()),
        )
    return out


# ---------------------------------------------------------------------------------------------
# §3.1 — candidate parsing + eligibility.
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class InnateCandidate:
    id: str
    scope: str
    scope_key: "str | None"
    category: str
    rung_ceiling: int
    kind_hint: "str | None"
    motifs_used: "tuple[str, ...]"
    element_affinity: "str | None"       # see module docstring's schema-gap note


def parse_candidate(row: Mapping[str, object], *, cap: int) -> InnateCandidate:
    cid = row.get("id")
    if not cid or not isinstance(cid, str):
        raise ValueError(f"candidate row missing a real string 'id' -- got {cid!r}")

    scope = row.get("scope")
    if scope not in SCOPES:
        raise ValueError(f"{cid}: scope {scope!r} is not real vocabulary {sorted(SCOPES)} -- refused")

    category = row.get("category")
    if category not in CATEGORIES:
        raise ValueError(f"{cid}: category {category!r} is not real vocabulary -- refused")

    rung_band = row.get("rungBand")
    if not isinstance(rung_band, (list, tuple)) or len(rung_band) != 2:
        raise ValueError(f"{cid}: rungBand must be a 2-element [min, max] -- got {rung_band!r}")
    rung_ceiling = rung_band[1]
    if isinstance(rung_ceiling, bool) or not isinstance(rung_ceiling, int) \
            or not (1 <= rung_ceiling <= cap):
        raise ValueError(f"{cid}: rungBand ceiling {rung_ceiling!r} must be a plain int in 1..{cap}")

    return InnateCandidate(
        id=cid, scope=scope, scope_key=row.get("scopeKey"), category=category,
        rung_ceiling=rung_ceiling, kind_hint=row.get("kindHint"),
        motifs_used=tuple(row.get("motifsUsed") or ()),
        element_affinity=row.get("elementAffinity"),
    )


def is_eligible(c: InnateCandidate, species_key: str, family_key: "str | None",
               already_promoted: "Sequence[str] | set") -> bool:
    """§3.1: species- or family-scoped for THIS species/its family, `kindHint != 'basic'`, and not
    already claimed by an earlier species this run. `scope == 'general'` (or any scope that is
    neither) always falls through to `False` -- a general-scoped action is never eligible,
    structurally, not by a special case."""
    if c.scope == "species":
        if c.scope_key != species_key:
            return False
    elif c.scope == "family":
        if family_key is None or c.scope_key != family_key:
            return False
    else:
        return False
    if c.kind_hint == "basic":
        return False
    if c.id in already_promoted:
        return False
    return True


def validate_eligible_set(eligible: Sequence[InnateCandidate]) -> None:
    """Defense in depth over `is_eligible`'s own filter (spec §5 'general leaks in'): even a
    hand-assembled or corrupted eligible set is refused here, naming the offending scope, before
    any scoring happens."""
    for c in eligible:
        if c.scope == "general":
            raise ValueError(
                f"{c.id}: scope 'general' is never eligible for an innate pick -- the innate is "
                f"the species signature, a shared floor row cannot be one -- refused")


# ---------------------------------------------------------------------------------------------
# §3.2 — the five raw terms.
# ---------------------------------------------------------------------------------------------

def compute_terms(c: InnateCandidate, role_lean: SpeciesRoleLean, eligible_count: int,
                  category_counts: Mapping[str, int], element_primary: str,
                  element_secondary: "str | None") -> "dict[str, int]":
    """Raw terms, exactly as spec §3.2's table defines them -- `rungCeiling` stored RAW (positive,
    the display shape spec §2's JSONC example shows), never pre-negated/pre-shifted; the shift
    into ranking/scoring space happens once, in `compute_score`."""
    if role_lean.lean_source == "floor":
        # A genuine uniform five-way tie (F12): every candidate scores 0 here, for EVERY species
        # whose own derivation landed on the flat floor -- never for a family-less
        # (`derived-nofloor`) species, which still has a real, differentiated `leanOrder`.
        role_lean_match = 0
    else:
        role_lean_match = len(CATEGORIES) - role_lean.lean_order.index(c.category)

    motif_coverage = len(set(role_lean.motifs) & set(c.motifs_used))

    if c.element_affinity is not None and c.element_affinity == element_primary:
        element_match = 2
    elif c.element_affinity is not None and c.element_affinity == element_secondary:
        element_match = 1
    else:
        element_match = 0

    category_scarcity = eligible_count - category_counts[c.category]

    return {
        "roleLeanMatch": role_lean_match, "motifCoverage": motif_coverage,
        "elementMatch": element_match, "categoryScarcity": category_scarcity,
        "rungCeiling": c.rung_ceiling,
    }


# ---------------------------------------------------------------------------------------------
# §3.3 — the tunable, `long`, positional-radix score. See module docstring for the `M_t` /
# `+cap`-offset derivation this function implements.
# ---------------------------------------------------------------------------------------------

def compute_score(terms: Mapping[str, int], cap: int, m2: int, m3: int, m4: int, m5_shifted: int,
                  weights: InnateWeights) -> int:
    base5 = 1
    base4 = _widen_mul(base5, m5_shifted + 1)
    base3 = _widen_mul(base4, m4 + 1)
    base2 = _widen_mul(base3, m3 + 1)
    base1 = _widen_mul(base2, m2 + 1)

    term5_shifted = cap - terms["rungCeiling"]         # -rungCeiling + cap, folded into one step

    total = 0
    total += _widen_mul(_widen_mul(base1, terms["roleLeanMatch"]), weights.role_lean_match_milli)
    total += _widen_mul(_widen_mul(base2, terms["motifCoverage"]), weights.motif_coverage_milli)
    total += _widen_mul(_widen_mul(base3, terms["elementMatch"]), weights.element_match_milli)
    total += _widen_mul(_widen_mul(base4, terms["categoryScarcity"]), weights.category_scarcity_milli)
    total += _widen_mul(_widen_mul(base5, term5_shifted), weights.rung_ceiling_milli)
    _check_long(total)
    return total // 1000                                # 1000 = per-mille scale, structural, ONE division


# ---------------------------------------------------------------------------------------------
# §3.4 — the pick, per species and over the whole roster.
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Pick:
    species_key: str
    innate_action_id: "str | None"
    terms: "dict[str, int] | None"
    score: "int | None"
    runner_up: "str | None"
    eligible_count: int
    reason: "str | None"


def pick_for_species(*, species_key: str, family_key: "str | None",
                     role_lean: "SpeciesRoleLean | None", element_primary: str,
                     element_secondary: "str | None", ordered_candidates: Sequence[InnateCandidate],
                     already_promoted: "set[str]", weights: InnateWeights, cap: int) -> Pick:
    """`ordered_candidates` must already be the total order (byte-wise ascending on `id`) —
    `pick_all_species` sorts once, up front; this function only filters, never re-sorts, so the
    result never depends on the CALLER's own input order."""
    if role_lean is None:
        return Pick(species_key, None, None, None, None, 0, "no role-lean entry")

    eligible = [c for c in ordered_candidates
               if is_eligible(c, species_key, family_key, already_promoted)]
    validate_eligible_set(eligible)

    if not eligible:
        return Pick(species_key, None, None, None, None, 0, "no eligible action")

    eligible_count = len(eligible)
    category_counts: "Counter[str]" = Counter(c.category for c in eligible)

    raw_terms = {
        c.id: compute_terms(c, role_lean, eligible_count, category_counts, element_primary,
                            element_secondary)
        for c in eligible
    }
    m2 = max(t["motifCoverage"] for t in raw_terms.values())
    m3 = max(t["elementMatch"] for t in raw_terms.values())
    m4 = max(t["categoryScarcity"] for t in raw_terms.values())
    m5_shifted = max(cap - t["rungCeiling"] for t in raw_terms.values())

    scored = sorted(
        ((compute_score(raw_terms[c.id], cap, m2, m3, m4, m5_shifted, weights), c.id) for c in eligible),
        key=lambda row: (-row[0], row[1]),               # score desc, actionId ordinal asc
    )
    winner_score, winner_id = scored[0]
    runner_up = scored[1][1] if len(scored) > 1 else None

    return Pick(species_key, winner_id, raw_terms[winner_id], winner_score, runner_up,
               eligible_count, None)


def pick_all_species(*, species_rows: Sequence[SpeciesRow],
                     role_lean_by_key: Mapping[str, SpeciesRoleLean],
                     candidate_rows: Sequence[Mapping[str, object]], weights: InnateWeights,
                     cap: int) -> "tuple[list[Pick], dict[str, str]]":
    """§3.4 steps 1-4 over the whole roster. `species_rows` must already be catalog order
    (`characteristic_pool.catalog.load_catalog`'s own order) — this function does not re-sort it,
    so a caller that shuffles the SPECIES list is exactly what a promotion-ordering test needs to
    exercise. The candidate list, in contrast, IS sorted here (byte-wise on `id`), so shuffling
    CANDIDATE input order never changes anything (Checkpoint 5)."""
    ordered = sorted((parse_candidate(r, cap=cap) for r in candidate_rows), key=lambda c: c.id)

    already_promoted: "set[str]" = set()
    picks: "list[Pick]" = []
    promotions: "dict[str, str]" = {}
    for species in species_rows:
        role_lean = role_lean_by_key.get(species.species_id)
        pick = pick_for_species(
            species_key=species.species_id, family_key=role_lean.family if role_lean else None,
            role_lean=role_lean, element_primary=species.element_primary,
            element_secondary=species.element_secondary, ordered_candidates=ordered,
            already_promoted=already_promoted, weights=weights, cap=cap,
        )
        picks.append(pick)
        if pick.innate_action_id is not None:
            already_promoted.add(pick.innate_action_id)
            promotions[pick.innate_action_id] = species.species_id
    return picks, promotions


def build_entries(picks: Sequence[Pick]) -> "list[dict]":
    """Spec §2's JSONC shape exactly: a picked entry carries `terms`/`score`/`runnerUp`/
    `eligibleCount`; a null pick carries only `reason` -- never a fabricated `eligibleCount: 0` key
    the spec's own empty-set example does not show."""
    out: "list[dict]" = []
    for p in sorted(picks, key=lambda p: p.species_key):
        entry_id = f"innate.{p.species_key}"
        if p.innate_action_id is None:
            out.append({"id": entry_id, "speciesKey": p.species_key, "innateActionId": None,
                       "reason": p.reason})
        else:
            out.append({"id": entry_id, "speciesKey": p.species_key,
                       "innateActionId": p.innate_action_id, "terms": p.terms, "score": p.score,
                       "runnerUp": p.runner_up, "eligibleCount": p.eligible_count})
    return out


# ---------------------------------------------------------------------------------------------
# §3.4 step 6b (review F14) — the promotion MOVE, this module's own direction (A-S3 writes INTO
# `_rounds/`; this module writes OUT of it). Pure functions; the actual file move (reading
# survivors.json, writing the new committed file, rewriting survivors.json in place) is the
# entrypoint's own job, matching every sibling `derive.py`/`generate_*.py` split in this family.
# ---------------------------------------------------------------------------------------------

def apply_promotions(round_rows: Sequence[Mapping[str, object]],
                     promotions: Mapping[str, str]) -> "list[dict]":
    """Every round row this module commits, unchanged EXCEPT the picked winner's own `kindHint`,
    overwritten to `'innate'`. "Retire" is not a third state (spec §3.4 step 6b): a non-picked,
    already-accepted candidate is committed exactly as accepted."""
    out: "list[dict]" = []
    for row in round_rows:
        row = dict(row)
        if row.get("id") in promotions:
            row["kindHint"] = "innate"
        # item-content `granted-action-text` (T14): every committed row must name the display key
        # its description resolves under -- `ActionCorpusBriefJson.Parse` REFUSES a committed row
        # without one, so a promotion that omitted it would break the server's own boot import of
        # the whole file. The key is structural (`<id>.desc`); the SENTENCE behind it is authored
        # content that lands in `gk-content/content/display/en.json`, and the corpus guard
        # (`GrantedActionTextTests`) is what demands it. A row that already carries an authored key
        # keeps it.
        row.setdefault("descriptionKey", f"{row['id']}.desc")
        out.append(row)
    return sorted(out, key=lambda r: r["id"])


def reduce_round_survivors_to_markers(round_rows: Sequence[Mapping[str, object]]) -> "list[dict]":
    """The round file's own post-promotion shape (spec §3.4 step 6b): every id becomes a bare
    `{"id": ..., "promoted": true}` marker, never a second full row -- "one id exists in exactly
    one place" (the FULL row, once this module runs, lives only in the newly committed file).

    **What this does and does not buy, verified rather than assumed (see this module's own build
    report for the direct probe).** A-C1's `load_committed` already excludes `_rounds/` from its
    own graph construction via a scratch-copy (`load.py:_load_committed_corpus`), built before this
    module existed -- so `load_committed` never sees a round-file row, marker or full, either way;
    that exclusion alone is what keeps `load_committed(actions_root)` free of a duplicate-id
    `CorpusLoadError` (acceptance #9b). Reducing to a marker does NOT, by itself, make a genuinely
    RAW `Corpus.load(actions_root)` call (bypassing `load_committed`'s exclusion entirely) safe --
    `Corpus.add`'s duplicate check keys purely on `entry.id`, so a marker carrying the SAME id as
    the committed row still collides under a literal whole-tree walk (confirmed directly: `Corpus.
    load` over such a tree still raises `CorpusLoadError`, marker or not). What the reduction
    genuinely buys is keeping the round file's OWN content honest -- a promoted id no longer
    pretends to be live, un-promoted candidate content sitting in TWO places at once."""
    return [{"id": row["id"], "promoted": True} for row in sorted(round_rows, key=lambda r: r["id"])]


def merge_committed(existing_rows: "Sequence[Mapping[str, object]]",
                    promoted_rows: "Sequence[Mapping[str, object]]") -> "list[dict]":
    """Union an S6 re-run's fresh promotions into an already-written `committed-round-<n>.json`.

    Re-running S6 for a round must never overwrite that round's committed output with only the
    CURRENT survivors (which hold leftovers, not the round's full output — measured 2026-09-15:
    re-running S6 round-1 replaced its 19 committed rows with the 1 leftover survivor). Existing
    rows survive; fresh promotions join; on an id conflict the fresh row wins (it reflects the
    current picks). Sorted by id — deterministic. In the normal flow (no prior committed file,
    or survivors already markers) this is a no-op shape: empty + promotions == promotions."""
    merged: "dict[str, dict]" = {}
    for row in existing_rows:
        if row.get("id") is not None:
            merged[row["id"]] = dict(row)
    for row in promoted_rows:
        if row.get("id") is not None:
            merged[row["id"]] = dict(row)
    return [merged[key] for key in sorted(merged)]


def drop_committed_full_rows(round_rows: "Sequence[Mapping[str, object]]",
                             committed_ids: "AbstractSet[str]") -> "list[dict]":
    """Cross-round producer repair (Phase-4 A4, 2026-09-15): a LATER round's S6 run commits ids
    that may still sit as FULL rows in an EARLIER round's survivors file (measured: round-1 held
    11 full rows committed by round-2000's run) — `reduce_round_survivors_to_markers` only ever
    marked the round S6 itself promoted. A full row whose id is committed becomes a bare marker;
    markers, genuinely-new full rows, and rows without ids pass through unchanged, order kept.
    Committed (promoted, authoritative) wins — the same precedence the A-S5 consumer guard (J)
    applies when it must."""
    out: "list[dict]" = []
    for row in round_rows:
        if (not row.get("promoted") and "scope" in row
                and row.get("id") in committed_ids):
            out.append({"id": row["id"], "promoted": True})
        else:
            out.append(dict(row))
    return out


# ---------------------------------------------------------------------------------------------
# Envelope assembly + write -- sorted keys, fixed indent, trailing `\n`, explicit nulls, same
# discipline every `canonical_dump`/`build_envelope` in this adapter family already uses.
# ---------------------------------------------------------------------------------------------

def corpus_hash(accepted_rows: Sequence[Mapping[str, object]]) -> str:
    ordered = sorted(accepted_rows, key=lambda r: r.get("id", ""))
    blob = json.dumps(ordered, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_envelope(entries: "list[dict]", meta: dict) -> dict:
    return {"schemaVersion": 1, "kind": "action-innate", "_meta": meta, "entries": entries}


def build_committed_envelope(entries: "list[dict]", meta: dict) -> dict:
    return {"schemaVersion": 1, "kind": "action-seed", "_meta": meta, "entries": entries}


def canonical_dump(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
