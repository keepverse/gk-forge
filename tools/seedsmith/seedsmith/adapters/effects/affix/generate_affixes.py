"""Real-run entrypoint for `affix-authoring` (T7.1/T7.2, spec-affix-authoring.md, effect-pipeline
module 9). Committed so the run is reproducible, matching `generate_commander_effects.py`'s own
precedent.

⛔ **The eligible-atom pool, made concrete rather than left unspecified.** Neither this module's own
spec nor any earlier task named where a run's own `eligibleAtoms` should come from — recorded as a
genuine open question in `tasks/seed-to-concrete-todo.md` (T7.1's own evidence block). Resolved here
the same way `commander_effect`'s own subjects come from a committed tree: the pool is every atom id
the REAL shipped seed tree (`gk-data/packs/fusion/data/seed/atoms/**.json`) actually carries — not invented, not narrowed
by a guess at which atoms "should" be biddable, the whole shared library the model may pick from.
`--only` narrows it to a themed subset for a smaller, more controllable run.

⛔ **T7.2 (2026-09-05): every draw is now a real 3-way vote, not a single unpermuted call.**
`spec-affix-authoring.md`'s own "Voted fields" section requires the affix's **name/identity** and
its **ref bundle composition** to be 3-way voted, "same machinery, same `resolve_vote` semantics" as
`creature-seed`'s own `classify-pipelines` (Q25 precedent) — but until this pass, `generate_affixes.py`
made exactly one model call per draw, so there was never a second or third sample to vote over.
`run_voted_draws` below is now that caller: THREE permuted samples per draw (`permute.order_for`,
seeded with `sample_index` INSIDE the seed per spec-option-permutation.md §3 — three votes over three
identical option orders is one sample with extra steps), `name` voted scalar via `vote.resolve_vote`.
`resolve_vote`/`order_for` are reused verbatim (per spec's own "Ask first: forking any piece of the
reused machinery" boundary); no new permutation-seeding logic is added here.

⛔ **Fixed 2026-09-06 (see [[affix-authoring-vote-bug]]): `refs` votes per-MEMBER
(`vote.resolve_set_vote`), never as one flattened whole-bundle string through `resolve_vote`.** The
original pass used `resolve_vote(canonical_bundle_key(refs))` — scalar equality over the WHOLE sorted
bundle — which a real run against the live model measured at ~90% `vote_unresolved` (9/10 and 9/10
across two real 10-draw batches), the exact SMOKE BATCH failure mode already found and fixed for
`creature-seed`'s own family/signature proposals: exact agreement across an entire 2+-member set, sampled
three times independently, is combinatorially rare even when every member was individually
well-agreed. `resolve_set_vote` credits a member into the resolved bundle once 2 of 3 samples chose
it, discarding nothing at the aggregation level that per-member evidence already settled. A resolved
bundle can still land below the schema's `minItems: 2` (a real, distinct, newly-handled case — see
`bundle_too_small_after_vote` below), which whole-bundle voting could never produce (its winning value
was always a real 2+-member sample to begin with).

Usage:
    python -m seedsmith.adapters.effects.affix.generate_affixes --dry-run   # briefs only
    python -m seedsmith.adapters.effects.affix.generate_affixes --count 5   # real model calls
    python -m seedsmith.adapters.effects.affix.generate_affixes --species-id Alpha --count 8

⛔ **`--species-id` (task J7, spec-species-tree.md §5.2/§5.3 rule 3), added 2026-09-07.** Investigated
against the real code before writing anything: as shipped, this tool could not target
`affix.species.<speciesId>.*` at all — `ID_PREFIX`/`OUTPUT_DIR` were bare module constants, not
parameters, and `gk-data/packs/fusion/data/seed/passive-tree/species/<speciesId>.json` (spec's own Project structure
table) is silent on where a species' OWN affix corpus should live. **Decision made and stated here,
not left unresolved**: one file per species, `data/seed/effects/affixes/species/<speciesId>.json`,
mirroring the identical per-species-file convention that table already uses for the tree's own
seed/plan/concrete stages — never one shared 6,720-entry file, and never per-node files (too
granular, nothing needs that resolution). `--species-id` derives `id_prefix`, `output_dir` and
`filename` from ONE flag so a caller cannot typo a prefix that drifts from `SpeciesUniquenessMetric`'s
own `affix.species.<speciesId>.*` pattern (`metrics/passive_tree.py`, task J6); every underlying
function still accepts the raw `id_prefix`/`output_dir`/`filename` parameters directly; for tests.
Every parameter below defaults to EXACTLY its old hardcoded value, so every pre-existing call site
(`run_t71_claude_propose.py`, both test files, the plain `--count N` CLI form) is unaffected byte for
byte. `next_draw_start_index` itself needed no change: draw numbering restarts at 0 inside a fresh
per-species file, which is collision-free by construction since the SPECIES id is already embedded in
the full affix id (`affix.species.Alpha.affix-draw-000` vs `affix.species.Beta.affix-draw-000` are
different ids even though `affix-draw-000` repeats). **The 6,720-affix production run itself is
deliberately NOT launched by this change** — it remains its own scheduled decision (spec's own
"largest unbudgeted item in the program" framing), now unblocked rather than attempted blind.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from ....pipeline.llm_caller import LlmCallerConfig, resolve_live_transport
from ....workflow.runner import MAX_WORKERS
from ....workflow.state import new_state
from .prompts import ID_PREFIX, build_brief, build_context, entry_for

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

ATOMS_ROOT = _owned("data/seed/atoms")
OUTPUT_DIR = _owned("data/seed/effects/affixes")

#: The real, committed member vocabulary of the one slot DOMAIN this repo actually documents.
#: `RpgStore.Containers.cs`'s own `DomainMembers` returns `ElementRoster.Concrete` for `"element"`
#: and an empty list for every other domain name — so `element` is not merely the first domain, it
#: is the only one with members at all. Read from the real roster rather than hardcoded.
ELEMENT_ROSTER = _owned("data/seed/elements/roster.json")

PROMPT_VERSION = "affix-authoring/1"

#: Every draw is voted over exactly this many permuted samples — spec-affix-authoring.md's own
#: "Voted fields" section, same `resolve_vote` 3-0/2-1/1-1-1 contract as `creature-seed`.
SAMPLES_PER_DRAW = 3


def derive_atom_id(entry: "dict") -> str:
    """Mirrors `AtomRow.DeriveId` exactly (`AtomRow.cs`): `family.t{tier}` or
    `family.{variant}.t{tier}` — the SAME split, so an id computed here always matches what the C#
    importer derives from the identical seed row."""
    family = entry["family"]
    tier = entry["tier"]
    variant = entry.get("variant") or ""
    return f"{family}.{variant}.t{tier}" if variant else f"{family}.t{tier}"


def load_eligible_atoms(atoms_root: Path, only: "list[str] | None" = None) -> "dict[str, bool]":
    """Every atom id the real shipped seed tree carries, mapped to whether IT OWN row declares a
    trigger — read fresh each call, never cached (a dev-run tool, not a hot path). Mirrors
    `AffixValidator.AffixClassOfAtom`'s own rule exactly: an atom's OWN `when.trigger` presence,
    never a kind-level default — the real seed row already carries this, so `derive_affix_class`
    reads real data here, not a guess."""
    has_trigger: "dict[str, bool]" = {}
    for path in sorted(atoms_root.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("kind") != "atom":
            continue
        for entry in doc.get("entries", []):
            atom_id = derive_atom_id(entry)
            has_trigger[atom_id] = bool((entry.get("when") or {}).get("trigger"))
    if only:
        wanted = set(only)
        has_trigger = {k: v for k, v in has_trigger.items() if k in wanted}
    return has_trigger


def load_element_domain(roster_path: "Path | None" = None) -> "set[str]":
    """The real concrete element ids (`fire/ice/air/earth/light/dark`), read from the committed
    roster — never a hardcoded list, so a roster change is picked up rather than silently diverged
    from."""
    path = roster_path or ELEMENT_ROSTER
    if not path.exists():
        return set()
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {e["id"] for e in doc.get("entries", []) if e.get("id")}


def load_slot_eligible_families(atoms_root: "Path | None" = None,
                                element_domain: "set[str] | None" = None) -> "dict[str, dict]":
    """Which atom families a SLOT could parameterise, DERIVED from the real catalog rather than
    invented — `family -> {"variants": [...], "domain": "element" | None}`.

    **What a slot needs, and why this is a derivation and not a new vocabulary.** An affix slot
    (`spec-affix-schema.md` §"What is genuinely new here": `slot E1 : domain = element, pick = 1`,
    ref `atom.elemental-power.$E1`) is a parameterised atom reference: it names a DOMAIN and lets one
    choice be shared across several refs. The catalog's own unique key is already
    `(family_id, tier, variant)`, so the families a slot could vary over are exactly those carrying
    **more than one variant** — the same "read what the shipped data already says" move
    `AffixTags.Of` makes when it derives an affix's tags from its refs instead of having them
    authored.

    **`domain` is the honest half.** A multi-variant family is only *groundable* for a model when its
    variant axis matches a real, named domain with real members. Today that is `element` and nothing
    else. A family whose variants are opaque discriminators (`a`/`b`/`c`) is structurally
    slot-shaped but semantically empty: asking a model to pick a domain for it would be asking it to
    invent a vocabulary, which is precisely the "plausible-looking guess" P1 forbids — the same
    reason `gk-data/packs/fusion/data/seed/items/affix-families/g-armour.json`'s own authoring notes give for refusing to
    invent a `variants.generate` vocabulary for channel-pairs.

    **Expected to be empty of groundable rows today, and that is the correct answer, not a bug.**
    Nothing in the shipped tree uses an element-variant axis yet, so this returns the structurally
    eligible families with `domain: None`. It lights up on its own the day E30's element pools ship
    a family whose variants are real element ids — no code change needed, which is the whole point
    of deriving it rather than hand-listing it.
    """
    root = atoms_root or ATOMS_ROOT
    domain = element_domain if element_domain is not None else load_element_domain()

    variants: "dict[str, set[str]]" = {}
    for path in sorted(root.rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("kind") != "atom":
            continue
        for entry in doc.get("entries", []):
            v = entry.get("variant")
            if v:
                variants.setdefault(entry["family"], set()).add(v)

    out: "dict[str, dict]" = {}
    for family, vs in sorted(variants.items()):
        if len(vs) < 2:
            continue  # one variant is not an axis to vary over
        out[family] = {
            "variants": sorted(vs),
            "domain": "element" if domain and vs <= domain else None,
        }
    return out


def groundable_slot_families(registry: "Mapping[str, dict]") -> "dict[str, dict]":
    """The subset a model could actually be asked to pick a slot domain for — those whose variant
    axis resolves to a real, named domain. Empty today, by design (see the loader's docstring)."""
    return {f: r for f, r in registry.items() if r["domain"] is not None}


def load_existing(output_dir: "Path | None" = None, filename: str = "all.json") -> "dict[str, dict]":
    """`output_dir=None` (the default) resolves the CURRENT module-level `OUTPUT_DIR` at call time,
    never a value captured once at import time — a plain `output_dir: Path = OUTPUT_DIR` default
    would bind early and silently ignore a caller (or a test) that monkeypatches `OUTPUT_DIR`
    afterward, exactly the footgun `adapters.trees.targets.load`'s own `path: "Path | None" = None`
    already avoids for the identical reason. Caught by this module's own test while writing it."""
    path = (output_dir if output_dir is not None else OUTPUT_DIR) / filename
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {e["id"]: e for e in doc.get("entries", [])}


def next_draw_start_index(existing: "Mapping[str, dict]") -> int:
    """Fixed 2026-09-06 (see [[affix-authoring-vote-bug]]): `draw_id` used to always start at
    `affix-draw-000` on every invocation, so a later run's `draw-000` silently OVERWROTE an earlier
    run's already-accepted `affix.authored.affix-draw-000` entry the moment it happened to resolve
    (`merged = {**existing, **fresh}` lets `fresh` win) — observed for real: the original pilot
    "Frostbite Venom" (`generatedUtc: 2026-09-04`) was overwritten by a coincidentally
    near-identical re-generation during a later run the same session. Every future run now continues
    from one past the highest existing draw index, so a new batch can only ever ADD entries, never
    silently replace one a previous run already committed."""
    max_index = -1
    for affix_id in existing:
        suffix = affix_id.rsplit("affix-draw-", 1)
        if len(suffix) != 2 or not suffix[1].isdigit():
            continue
        max_index = max(max_index, int(suffix[1]))
    return max_index + 1


def run_voted_draws(
    *,
    count: int,
    eligible: "list[str]",
    atom_triggers: "Mapping[str, bool]",
    provenance_base: "Mapping[str, Any]",
    theme_hint: str = "",
    start_index: int = 0,
    call: "Callable[..., str] | None" = None,
    config: LlmCallerConfig | None = None,
    workers: int = MAX_WORKERS,
    id_prefix: "str | None" = None,
) -> "tuple[dict[str, dict], dict[str, dict], dict[str, dict]]":
    """Draws `count` affix bundles, THREE permuted samples each: `name` voted scalar via
    `vote.resolve_vote` (`creature-seed`'s own `run_one_species` machinery, 2026-09-02), the ref bundle
    voted per-member via `vote.resolve_set_vote` (fixed 2026-09-06 — see the module docstring's own
    [[affix-authoring-vote-bug]] note).

    Each sample runs the FULL `build_affix_authoring_graph` (generate -> validate -> repair ->
    persist/escalate), so a sample that never produces a schema-valid bundle contributes nothing to
    that draw's vote rather than polluting it with an invalid value — the same "only a validated
    draft counts" discipline the graph already enforces for a single-sample run.

    Returns `(fresh, unresolved, results)`:
      * `fresh` — committed entries keyed by affix id, one per draw where `name` resolved (3-0 or
        2-1) AND the per-member ref vote resolved at least 2 members. Never contains a fabricated
        guess.
      * `unresolved` — keyed by draw id, the reason a draw produced no entry: a 1-1-1 split on `name`
        or zero ref members reaching a majority (`"vote_unresolved"`); a resolved ref vote landing
        below the schema's 2-member minimum (`"bundle_too_small_after_vote"`); or fewer than
        `SAMPLES_PER_DRAW` samples ever validated (`"insufficient_valid_samples"`) — a dead sample is
        not a silent drop, it shows up here.
      * `results` — the per-sample-state graph outcome, keyed by the sample's own subject id, for a
        caller's own `byOutcome` accounting (unchanged shape from before this pass).

    `call` is injected (never imported directly) so a test proves the exact number of model calls
    made without reaching the network — the same contract every graph in this program already
    honours.

    `id_prefix=None` (the default) resolves the CURRENT module-level `ID_PREFIX` at call time, the
    same late-binding reason `load_existing`'s own `output_dir` parameter above uses `None` rather
    than `= ID_PREFIX` directly. Task J7's own `--species-id` CLI flag is what overrides it to
    `"affix.species.<speciesId>."`, never a caller hand-typing a prefix that could drift from
    `SpeciesUniquenessMetric`'s own U3 pattern.
    """
    from ....workflow.graphs.effect_affix import build_affix_authoring_graph
    from ....workflow.runner import run_many
    from ...creatures.anchor.permute import order_for
    from ...creatures.anchor.vote import resolve_set_vote, resolve_vote
    from .derive import derive_affix_class

    if config is None:
        config = resolve_live_transport()
    persisted: "dict[str, dict]" = {}
    app = build_affix_authoring_graph(
        on_persist=lambda k, v: persisted.__setitem__(k, v), config=config, call=call)

    # THREE permuted samples per draw — `sample_index` lives INSIDE `order_for`'s own seed
    # (species_id|field|sample_index), so a rerun over the same draw id reproduces the identical
    # three permutations; three votes over three identical option orders would be one sample with
    # extra steps, exactly what spec-option-permutation.md §3 warns against.
    draw_samples: "dict[str, list[str]]" = {}
    states: "list[dict]" = []
    for i in range(start_index, start_index + count):
        draw_id = f"affix-draw-{i:03d}"
        sample_ids: "list[str]" = []
        for sample_index in range(SAMPLES_PER_DRAW):
            shuffled = order_for(draw_id, "eligibleAtoms", sample_index, eligible)
            context = build_context(shuffled, theme_hint=theme_hint)
            brief = build_brief(context)
            subject_id = f"{draw_id}-sample-{sample_index}"
            states.append(new_state(subject_id, brief=brief, context=context))
            sample_ids.append(subject_id)
        draw_samples[draw_id] = sample_ids

    results = run_many(app, states, max_workers=workers)

    fresh: "dict[str, dict]" = {}
    unresolved: "dict[str, dict]" = {}
    for draw_id, sample_ids in draw_samples.items():
        samples = [
            persisted[sid] for sid in sample_ids
            if sid in persisted and isinstance(persisted[sid], dict) and "refs" in persisted[sid]
        ]
        if len(samples) != SAMPLES_PER_DRAW:
            unresolved[draw_id] = {
                "reason": "insufficient_valid_samples",
                "validSamples": len(samples),
                "samplesExpected": SAMPLES_PER_DRAW,
            }
            continue

        name_vote = resolve_vote([s.get("name", "") for s in samples])
        # Per-MEMBER majority, not whole-bundle string equality (the SMOKE BATCH fix, ported here
        # 2026-09-06 — see [[affix-authoring-vote-bug]]): a real run measured ~90% unresolved under
        # `resolve_vote(canonical_bundle_key(...))` because exact agreement across a whole 2+-member
        # bundle, sampled independently three times, is combinatorially rare even when every member
        # was individually well-agreed. `resolve_set_vote` credits a member the moment 2 of 3 samples
        # pick it, the same fix `creature-seed`'s own SMOKE BATCH defect already applied.
        refs_vote = resolve_set_vote([s.get("refs") or [] for s in samples])

        # Never the first sample by default (spec §4/vote.py's own explicit warning) — a 1-1-1 on
        # name, or no member reaching a majority on refs, means this draw has no resolved identity
        # or no resolved bundle, so it is recorded as unresolved rather than shipping one voted
        # field next to a guessed other.
        if name_vote.value is None or refs_vote.confidence == "unresolved":
            unresolved[draw_id] = {
                "reason": "vote_unresolved",
                "name": {"confidence": name_vote.confidence},
                "refs": {"confidence": refs_vote.confidence, "tally": refs_vote.tally},
            }
            continue

        winning_refs = list(refs_vote.values)
        if len(winning_refs) < 2:
            # A per-member vote can resolve fewer than 2 members even when it is not "unresolved"
            # (e.g. one atom reaches 2/3 and every other candidate stays below threshold) — the
            # schema's own `minItems: 2` makes a 1-member "bundle" invalid content, not a smaller
            # valid one, so this is its own named reason rather than a silently-shipped bad entry.
            unresolved[draw_id] = {
                "reason": "bundle_too_small_after_vote",
                "refs": {"confidence": refs_vote.confidence, "resolved": winning_refs,
                         "tally": refs_vote.tally},
            }
            continue

        affix_class = derive_affix_class(
            winning_refs, has_trigger=lambda a: atom_triggers.get(a, False))

        provenance = dict(provenance_base)
        provenance["voteConfidence"] = {"name": name_vote.confidence, "refs": refs_vote.confidence}
        minority: "dict[str, Any]" = {}
        if name_vote.minority:
            minority["name"] = name_vote.minority
        if refs_vote.minority:
            minority["refs"] = list(refs_vote.minority)
        if minority:
            provenance["voteMinority"] = minority

        affix_id = f"{id_prefix if id_prefix is not None else ID_PREFIX}{draw_id}"
        draft = {"name": name_vote.value, "refs": winning_refs}
        fresh[affix_id] = entry_for(
            draft, affix_id=affix_id, affix_class=affix_class, provenance=provenance)

    return fresh, unresolved, results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Author named, multi-atom affix bundles.")
    ap.add_argument("--dry-run", action="store_true", help="assemble briefs, make no model calls")
    ap.add_argument(
        "--count", type=int, default=1,
        help="how many independent bundles to draw — each draw makes THREE permuted model calls "
             "and votes name+refs (spec-affix-authoring.md's own 'Voted fields'), not one")
    ap.add_argument("--only", default="", help="comma-separated atom ids to narrow the eligible pool")
    ap.add_argument("--theme", default="", help="an optional theme hint in the brief")
    ap.add_argument("--endpoint", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--workers", type=int, default=MAX_WORKERS)
    ap.add_argument(
        "--species-id", default="",
        help="task J7: author into affix.species.<speciesId>.* / "
             "data/seed/effects/affixes/species/<speciesId>.json instead of the shared "
             "affix.authored.* / all.json corpus — one flag, so the id prefix and the U3 "
             "namespace pattern (metrics/passive_tree.py) can never drift apart")
    args = ap.parse_args(argv)

    species_id = args.species_id.strip()
    if species_id:
        id_prefix = f"affix.species.{species_id}."
        output_dir = OUTPUT_DIR / "species"
        output_filename = f"{species_id}.json"
        partition = species_id
    else:
        id_prefix = ID_PREFIX
        output_dir = OUTPUT_DIR
        output_filename = "all.json"
        partition = "all"

    only = [a.strip() for a in args.only.split(",") if a.strip()] or None
    atom_triggers = load_eligible_atoms(ATOMS_ROOT, only)
    eligible = sorted(atom_triggers)
    if len(eligible) < 2:
        raise SystemExit(
            f"REFUSING TO RUN: only {len(eligible)} eligible atom(s) found under {ATOMS_ROOT} "
            "(--only may have narrowed it too far) — a bundle needs at least two.")

    if args.dry_run:
        context = build_context(eligible, theme_hint=args.theme)
        brief = build_brief(context)
        print(f"{len(eligible)} eligible atoms; no model calls made.")
        print("--- sample brief (sample 0 of 3 — a real run permutes the atom order per draw) ---")
        print(brief)
        return 0

    config = dataclasses.replace(resolve_live_transport(args.endpoint, args.model),
                                 attempts=2, retry_delay=1.0, timeout=420)
    provenance_base = {
        "pipeline": "affix-authoring",
        "model": config.model,
        "promptVersion": PROMPT_VERSION,
        "generatedUtc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    existing = load_existing(output_dir, output_filename)
    start_index = next_draw_start_index(existing)

    fresh, unresolved, results = run_voted_draws(
        count=args.count, eligible=eligible, atom_triggers=atom_triggers,
        provenance_base=provenance_base, theme_hint=args.theme, start_index=start_index,
        config=config, workers=args.workers, id_prefix=id_prefix)

    merged = {**existing, **fresh}
    entries = [merged[k] for k in sorted(merged)]

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / output_filename).write_text(
        json.dumps({"schemaVersion": 1, "kind": "affix", "_meta": {"partition": partition},
                   "entries": entries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    by_outcome: "dict[str, int]" = {}
    for r in results.values():
        by_outcome[r.get("outcome", "?")] = by_outcome.get(r.get("outcome", "?"), 0) + 1

    print(json.dumps({
        "partition": partition,
        "outputPath": str(output_dir / output_filename),
        "eligibleAtoms": len(eligible),
        "draws": args.count,
        "samplesPerDraw": SAMPLES_PER_DRAW,
        "resolvedDraws": len(fresh),
        "unresolvedDraws": len(unresolved),
        "unresolvedDetail": unresolved,
        "totalEntries": len(entries),
        "byOutcome": by_outcome,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
