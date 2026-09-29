"""DERIVED anchor fields and deterministic post-processing (spec-classify-pipelines.md §4).
`posture` and `pure` are computed, never authored — a model that can write them can contradict its
own primary answer (anchor-contract boundaries). `variant-count` is clamped deterministically from
`rarity`, never left to the model to decide how many.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .schema import APTITUDE_POSTURE, RARITY, THREAT_BAND
from ..power.bands import classify

VARIANT_COUNT_TUNING_DIR = Path(__file__).resolve().parents[6] / "data" / "tuning"


def derive_posture(aptitude_primary: str) -> str:
    """`aptitude_primary == "unresolved"` is the same real, documented outcome
    `clamp_variant_count` guards against (spec-classify-pipelines.md §4: two failed repairs, then
    the field is unresolved and reported) — a posture cannot be derived from an input that was
    never itself resolved, so this propagates the same "unresolved" string rather than crashing or
    guessing. Found by the same real T2.11 run (2026-09-02) that found the `clamp_variant_count`
    gap, one species later."""
    if aptitude_primary not in APTITUDE_POSTURE:
        return "unresolved"
    return APTITUDE_POSTURE[aptitude_primary]


def derive_pure(aptitude_primary: str, aptitude_secondary: str) -> bool:
    """Q2: both aptitudes share a posture (or there is no secondary) -> pure. A flag, never a
    rejection (spec §4's `pure-flag` row).

    `pure` has no "unresolved" representation of its own (it is strictly boolean on both the
    Python schema and the C# `AnchorRow.Pure` reader) — when either aptitude is unresolved,
    `False` is written as an explicit, documented placeholder, never a guess presented as real:
    the species is already flagged unresolved through `aptitudePrimary`/`posture` themselves, and
    nothing here claims `pure` was actually determined.
    """
    if aptitude_primary not in APTITUDE_POSTURE:
        return False
    if aptitude_secondary == "none":
        return True
    if aptitude_secondary not in APTITUDE_POSTURE:
        return False
    return APTITUDE_POSTURE[aptitude_primary] == APTITUDE_POSTURE[aptitude_secondary]


def derive_species_kind(
    *, resolves_natively: bool, mimic_of: "int | None" = None, current: "str | None" = None,
) -> str:
    """`SPECIES_KIND` for one row (creature-seed R-CS2/R-CS3/R-CS4, owner-ruled 2026-09-17).

    DERIVED, never authored: "is this row a real creature" is a fact about the corpus, not a
    judgement about a creature, which is why `schema.py`'s OWNERSHIP puts it beside `posture`/
    `pure`/`basis` rather than in the model's CLASSIFIED set.

    The rule, in the order R-CS2 states it — a species is legitimate when it has a resolvable id by
    **either** route, never when the id is natively its own:

    1. it resolves to a real game type      -> `creature`
    2. it declares a mimic (a deliberately borrowed lawn type id) -> `mimic`
    3. neither                              -> `excluded`

    ⚠️ **This is deliberately NOT an enforcement gate.** The obvious-looking check — "every species
    must resolve to a real `PlantType`/`ZombieType` member" — was proposed and OVERTURNED, because
    it would close the species corpus to extension: a new special species, authored rather than
    mined from the lawn, would fail for the crime of being new. That is the same Open/Closed defect
    this repo spent 2026-09-17 fixing one population over. So this function MARKS; it never refuses.

    `mimic_of` is the borrowed type id, taken at face value — whether a mimic is declared per
    species or per family is a genuine spec-level question R-CS2 left open, and guessing an answer
    here would be inventing content. Nothing declares one today.

    `current` is the row's existing kind, honoured when it is already `mimic`: a mimic is a
    DELIBERATE declaration, and a pass that re-derived it away because the borrowed id happens to
    resolve natively would silently erase the one thing the declaration exists to record.
    """
    if current == "mimic" or mimic_of is not None:
        return "mimic"
    return "creature" if resolves_natively else "excluded"


def resolve_unresolved_threat_band(threat_band: str, *, tuning) -> "tuple[str, bool]":
    """creature-corpus-self-heal F1 (2026-09-04): the ONE field this codebase already has a real,
    owner-sanctioned deterministic default for. `creature-threat.v1.json`'s own `inferredDefaultRung`
    exists precisely for "no reliable signal, use the sanctioned default" (its own doc comment:
    "the sanctioned fallback for exactly this case, not an invented default") — previously wired
    for the "no computable score at all" case (`inferred`/`blocked` basis with nothing to score),
    but a genuine 3-way vote split (`threat_band == "unresolved"`) is the SAME semantic category:
    no reliable signal exists either way. This is the first real caller of that value for THIS
    specific case, not a second, invented default.

    Investigated in 2026-09-04 and NOT extended to `aptitudePrimary`/`rarity`/`elementPrimary`:
    none of those three had an equivalent real, already-sanctioned fallback anywhere in this repo
    at the time — `aptitudes.v2.json` has no stat-to-aptitude mapping, and `elementPrimary` is
    purely thematic with no numeric anchor at all; those two still correctly stay "unresolved" and
    reported. **`rarity` is different as of 2026-09-07** — see `resolve_unresolved_rarity` below,
    added on explicit owner direction: rarity is this game's own invented mechanism, not an
    almanac/PvZ property, so "the LLM vote never converged" is not a reason to leave it unresolved
    forever when a deterministic engine can fill the gap.

    Returns `(value, was_deterministic)` — the second element lets a caller record HONEST
    provenance (this was never a real judgment, an LLM never decided it) rather than silently
    looking identical to a real classification.
    """
    if threat_band != "unresolved":
        return threat_band, False
    return tuning.threshold_for_rung(tuning.inferred_default_rung).id, True


def resolve_threat_band(threat_band: "str | None", seed, *, tuning) -> "tuple[str, str]":
    """Score first, default second — and return WHICH, so the corpus can tell a real
    classification from a sanctioned fallback (threat-band-fill T3). The fallback is correct
    (creature-threat.v1.json's own `inferredDefaultRung` exists for exactly this case); what
    was missing is the trace.

    `seed` is the species' `PowerSeed` from the current dump, or `None` when the species is
    absent from it — `classify` itself returns `None` for `inferred`/`blocked` basis by design,
    so both "no seed" and "no signal" land on the sanctioned default, never a guess. A MISSING
    field (`None`) fills exactly like a vote-split `"unresolved"`: 719 shipped species carry no
    `threatBand` at all and read as the default rung at runtime — the fill writes what the
    runtime was silently assuming, scored where a signal exists. This does
    NOT replace `resolve_unresolved_threat_band` (kept for its existing callers and tests); it
    is the score-first path `fix_unresolved` uses."""
    if threat_band not in ("unresolved", None):
        return threat_band, "authored"
    scored = classify(seed, tuning) if seed is not None else None
    if scored is not None:
        return scored.id, "scored"
    return tuning.threshold_for_rung(tuning.inferred_default_rung).id, "default"


def load_rarity_power_fallback(version: "int | str" = 1) -> "dict[str, str]":
    """`threatBand id -> rarity id`, from `creature-rarity-power-fallback.v{version}.json`. A table,
    never a formula — same discipline `ThreatTuning` itself uses, because the ladder is fixed by a
    reviewed file, not computed. Loaded fresh each call (this runs once per self-heal pass, not a
    hot path)."""
    path = VARIANT_COUNT_TUNING_DIR / f"creature-rarity-power-fallback.v{int(version)}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {row["threatBand"]: row["rarity"] for row in raw["rarityByThreatRung"]}


def resolve_unresolved_rarity(rarity: str, threat_band: str, *, mapping: "dict[str, str]") -> "tuple[str, bool]":
    """creature-corpus-self-heal Phase H (2026-09-07, owner-directed): rarity is OUR game's own
    mechanism, not an almanac/PvZ property — "if the LLM cannot solve it, just define a
    deterministic engine to solve it." Reuses `threatBand`'s own already-validated power banding
    (a species' parsed toughness/damage, bucketed by `creature-threat.v1.json`'s real p10..p90
    deciles) via a rank-preserving correspondence in `creature-rarity-power-fallback.v1.json` —
    stronger species land on rarer rungs, and no second, independent power curve is invented.

    Only fires when BOTH `rarity` is a genuine vote-split ("unresolved") AND `threat_band` is
    itself a real rung (already resolved, or resolved earlier in the SAME fix pass by
    `resolve_unresolved_threat_band` — callers should pass that function's own output, not the
    original value, so the two fallbacks chain). If `threat_band` has no signal either, there is
    nothing to derive from and `rarity` correctly stays "unresolved" and reported — this is a
    fallback, not a guess invented from nothing.

    Returns `(value, was_deterministic)`, same contract as `resolve_unresolved_threat_band`, so a
    caller can stamp honest provenance (`"deterministic-fallback"`, never faked as a real LLM
    judgment)."""
    if rarity != "unresolved":
        return rarity, False
    if threat_band not in mapping:
        return rarity, False
    return mapping[threat_band], True


@lru_cache(maxsize=None)
def load_rank_grid(version: "int | str" = 1) -> "dict[tuple[str, str], str]":
    """`(threatBand, rarity) -> rank`, from `creature-rank.v{version}.json` (spec-species-rank.md §2).

    Validated for FULL coverage against the two CLOSED vocabularies the grid is indexed by
    (`THREAT_BAND` × `RARITY`, both declaring reads — never retyped here): a pair with no cell
    would silently derive `"unresolved"` for a real species, which is a TABLE defect, not a corpus
    gap, so it raises here rather than being discovered downstream as missing content.

    Cached because the file is committed and immutable for a given version, and `derive_rank` runs
    once per species per write path (three call sites over ~900 species) — this is a pure read of a
    committed file, so the cache cannot go stale within a process.
    """
    path = VARIANT_COUNT_TUNING_DIR / f"creature-rank.v{int(version)}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    grid = {(c["threatBand"], c["rarity"]): c["rank"] for c in raw["grid"]}
    missing = [(t, r) for t in THREAT_BAND for r in RARITY if (t, r) not in grid]
    if missing:
        raise ValueError(
            f"creature-rank.v{int(version)}.json covers {len(grid)} cell(s) but is missing "
            f"{len(missing)} of the {len(THREAT_BAND) * len(RARITY)} real (threatBand, rarity) "
            f"pairs, e.g. {missing[:3]}")
    return grid


def derive_rank(threat_band: "str | None", rarity: "str | None", *, version: "int | str" = 1) -> str:
    """The rank rung for one species (spec-species-rank.md §1) — the grid's own cell for the
    resolved `(threatBand, rarity)` pair, or the literal `"unresolved"` when either input is not.

    Threat selects the ROW, rarity selects the COLUMN, the cell holds the rank: the two axes are
    never conflated, and nothing here reads a magnitude. Rank is identity — it gates and displays;
    it never prices, scales, or contests.

    Only a literal `"unresolved"` (or an absent field — 721 of 906 real anchors carried no
    `threatBand` when this was measured, 2026-09-20) blocks rank: Assumption 4's rule is "skip,
    don't fabricate", so an unresolved input propagates rather than defaulting through the table.
    An out-of-vocabulary pair is treated the same way rather than crashing a whole run (the shape
    `clamp_variant_count` already established): `load_rank_grid` asserts the grid's own coverage,
    so reaching that branch means the ANCHOR carries a value outside the closed vocabulary, which
    the anchor audit already reports.
    """
    if threat_band in (None, "", "unresolved") or rarity in (None, "", "unresolved"):
        return "unresolved"
    return load_rank_grid(version).get((threat_band, rarity), "unresolved")


def load_aptitude_fallback(version: "int | str" = 1) -> str:
    """`inferredDefaultAptitude` from `creature-aptitude-fallback.v{version}.json`."""
    path = VARIANT_COUNT_TUNING_DIR / f"creature-aptitude-fallback.v{int(version)}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw["inferredDefaultAptitude"]


def resolve_unresolved_aptitude(aptitude: str, *, default: str) -> "tuple[str, bool]":
    """creature-corpus-self-heal Phase I (2026-09-07, owner-directed): unlike `rarity`, no real
    fallback signal exists for `aptitudePrimary` — measured directly, not assumed: of the 151
    species with a computable power score AND a resolved aptitude, a one-way ANOVA of score by
    aptitude comes back at F≈1.34 (noise, not separation), and 10 of the 11 real unresolved
    species have no computable score at all to feed a classifier with in the first place.

    The owner's direction, given that negative finding: aptitude is our own invented mechanism
    too, so a flat, undisguised default is fine when a real derivation genuinely does not exist —
    "we make up it" rather than leave it unresolved forever. This is NOT a `resolve_unresolved_*`
    sibling that derives from another field the way `resolve_unresolved_rarity` derives from
    `threatBand` — there is nothing to derive from, so `creature-aptitude-fallback.v1.json`'s own
    `_note` says so plainly rather than dressing up an invented pick as a calculation.

    Returns `(value, was_deterministic)`, same contract as the other `resolve_unresolved_*`
    functions, so a caller can stamp honest provenance (`"deterministic-fallback"`, never faked as
    a real LLM judgment)."""
    if aptitude != "unresolved":
        return aptitude, False
    return default, True


def resolve_secondary_element_from_fusion_lineage(
    element_secondary: str, element_primary: str, *,
    input_a_element: "str | None", input_b_element: "str | None",
) -> "tuple[str, bool]":
    """creature-corpus-self-heal follow-up (2026-09-07, owner-directed): a DIFFERENT signal source
    from the `resolve_unresolved_*` family above, and deliberately not one of them. Those three
    only ever fire on a genuine `"unresolved"` vote-split; `elementSecondary` is usually a real,
    resolved LLM judgment of `"none"` — the per-species lore classifier (`element-secondary`'s own
    prompt) reads only ONE species' own flavor text, so it structurally cannot see that a fusion
    OUTPUT species was built from two other species that each carry their own real element. This
    function supplies exactly that cross-species signal, which is why it can override an
    already-resolved `"none"` rather than only an `"unresolved"` value — a fusion creature literally
    made partly from a Fire-element parent plausibly carries some of that nature, and CreatureRecipe
    generation already assigns `inputA` to match the output's own `elementPrimary` (verified
    live against the real 713-recipe corpus: 685/693 candidates), so `inputB`'s own element is
    usually the one piece of real information the output's own classification never had a chance
    to consider.

    Owner direction (2026-09-07): "not every creature has a secondary element and that is normal" —
    this only fires when EXACTLY ONE of the two parents' own `elementPrimary` differs from the
    output's own `elementPrimary`. Zero such parents means both parents already agree with the
    output (real signal that this species is intentionally single-typed, not a gap to fill).
    TWO such parents — both differ from the output AND from each other — means `inputA`'s own
    "should match" assumption failed for this recipe (confirmed live: `CreatureRecipeCatalog.
    TryFindPair`'s own candidate ordering is a PREFERENCE, not a filter — when no candidate at
    the eligible rung shares the output's element, `inputA` is picked by the ordinal tie-break
    alone and carries no elemental meaning), so neither parent can be trusted as "the other
    element" with any more confidence than a coin flip — left unresolved, same honesty standard
    as the zero-candidate case, never guessed.

    Returns `(value, was_deterministic)`, same contract as the `resolve_unresolved_*` family, so a
    caller stamps honest provenance — `"fusion-lineage-derived"`, never `"deterministic-fallback"`
    (that tag means "no real signal existed"; this one means "real cross-species signal existed
    and was used") and never faked as a real LLM judgment.
    """
    if element_secondary not in ("none", ""):
        return element_secondary, False
    candidates = {e for e in (input_a_element, input_b_element) if e and e != element_primary}
    if len(candidates) != 1:
        return element_secondary, False
    return next(iter(candidates)), True


def _load_variant_count_bands(version: "int | str" = 1) -> dict:
    path = VARIANT_COUNT_TUNING_DIR / f"creature-variant-count.v{int(version)}.json"
    return json.loads(path.read_text(encoding="utf-8"))["countByRarity"]


def clamp_variant_count(variants: "list[str]", rarity: str, *, version: "int | str" = 1) -> "list[str]":
    """The `variant-count` validator (spec §4): the COUNT comes from `rarity`'s band, never from
    the model. Truncates deterministically (keeps the model's own first N, preserving its
    ordering) or extends deterministically (appends the lowest-ordinal VARIANTS values not
    already present, so two runs over the same input produce the identical extension — 'normal'
    is always first to be added since every species can plausibly have it).

    `rarity == "unresolved"` is a real, documented outcome (spec-classify-pipelines.md §4: "two
    repairs, then the field is unresolved and reported") — a vote's own 1-1-1 split, never
    invented here. There is no band to clamp against without a resolved rarity, so this is a
    no-op rather than a guess: the model's own `variants` pass through unchanged, exactly as
    `emit.py` already writes an unresolved field explicitly rather than defaulting it. Found by
    a real classification run (`creatures run resume`, 2026-09-02) crashing the whole run on the
    first species whose rarity vote didn't settle — the deterministic clamp's own precondition
    (a resolved rarity) was never actually guaranteed by anything upstream of it.
    """
    from .schema import VARIANTS

    bands = _load_variant_count_bands(version)
    if rarity not in bands:
        return list(dict.fromkeys(variants))  # de-dupe only; no band to clamp against
    lo, hi = bands[rarity]

    result = list(dict.fromkeys(variants))  # de-dupe, preserve order
    if len(result) > hi:
        return result[:hi]
    if len(result) < lo:
        for candidate in VARIANTS:
            if len(result) >= lo:
                break
            if candidate not in result:
                result.append(candidate)
    return result
