"""`fusion-recipe-reconcile` (creature-seed module 17, spec-fusion-recipe-generator.md §3/§3a) — the
deterministic reconciler, SOLE write authority for the committed fusion-recipe seed. Runs the
existing `CreatureRecipeCatalog.Build()` (via the `gk-forge/tools/CreatureRecipeReconcileInput` CLI seam, never
reimplemented here) for the deterministic pass, then reconciles each deficit's per-member-voted
proposal (§2, `vote.py`) against the same validation rules the deterministic pass already implies —
owner lock 6 (no `CaptureOnly` input), pair uniqueness across BOTH sources, `inputA != inputB` —
before it may enter the committed seed. A proposal that fails ANY check, or that never resolved a
vote, is refused: the output is reported as unresolved and ships with NO recipe entry (matching
`SpeciesBuildPlanCatalog.SharesFor`'s own "no entry, not a made-up one" rule) — this module never
invents a fallback pairing on a validation failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .emit import DEFAULT_OUTPUT_RELATIVE, check as emit_check, write as emit_write
from .prompts import DeficitOutput, FusionCandidate
from .vote import assign_input_a_b, resolve_fusion_pair_vote
from ....tooling import run_tool

REPO_ROOT = Path(__file__).resolve().parents[6]  # tools/seedsmith/seedsmith/adapters/creatures/fusion/reconcile.py -> repo root

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from ....workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

DEFAULT_SEAM_PROJECT = _owned("tools/CreatureRecipeReconcileInput")

#: §3a: bump when the propose prompt/schema shape changes in a way that should force every
#: existing gap-fill entry to be re-derived, even though its candidate pool is unchanged.
PROMPT_VERSION = 1

#: Given a deficit output + its bounded candidate pool + the pairs already claimed elsewhere,
#: return exactly 3 raw samples (each a proposed (inputA, inputB) pair, or None for a
#: heal-exhausted sample) — the real implementation calls a live model (Checkpoint 8a, owner-run);
#: `reconcile()` itself only needs SOMETHING with this shape, real or injected.
ProposeFn = Callable[
    [DeficitOutput, "list[FusionCandidate]", "list[tuple[str, str]]"],
    "list[tuple[str, str] | None]",
]


@dataclass(frozen=True)
class ReconcileOutcome:
    recipes: "dict[str, dict]"      # recipeId -> committed entry (spec §4 shape)
    unresolved: "list[str]"         # deficit output ids that got no recipe — named, not hidden
    model_calls_made: "list[str]"   # deficit output ids that actually invoked propose_fn this run


def candidate_pool_hash(candidates: "Sequence[dict]") -> str:
    """§3a's `corpusContentHash` — over the EXACT candidate pool shown for ONE deficit, never the
    whole corpus, so an unrelated species change can never invalidate an already-resolved gap-fill.
    Canonicalized (sorted by id, stable key order) before hashing so the same pool always hashes
    identically regardless of the seam's own JSON ordering."""
    canon = json.dumps(sorted(candidates, key=lambda c: c["speciesId"]), sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()


def reconcile(
    seam: dict, propose_fn: ProposeFn, *, existing_seed: "dict[str, dict] | None" = None,
) -> ReconcileOutcome:
    """`seam` is `gk-forge/tools/CreatureRecipeReconcileInput`'s own JSON shape (`eligibleOutputs`,
    `deterministicRecipes`, `deficits`) — the CLI seam into the real C#, reused not reimplemented.
    `existing_seed` is the currently-committed file's own parsed content (`None` on a first run) —
    used for §3a's freeze-on-commit check: an existing gap-fill entry whose `corpusContentHash`
    still matches and whose `promptVersion` is current is kept VERBATIM, no model call made.
    """
    recipes: "dict[str, dict]" = {}
    used_pairs: "set[frozenset]" = set()

    for r in seam["deterministicRecipes"]:
        recipes[r["recipeId"]] = {
            "outputSpeciesId": r["outputSpeciesId"],
            "inputSpeciesIdA": r["inputSpeciesIdA"],
            "inputSpeciesIdB": r["inputSpeciesIdB"],
            "crossRungGapFill": False,
        }
        used_pairs.add(frozenset((r["inputSpeciesIdA"], r["inputSpeciesIdB"])))

    unresolved: "list[str]" = []
    model_calls_made: "list[str]" = []

    # Pinned SpeciesId-ordinal order (spec §3 step 2's own tie-break): which proposal wins a
    # usedPairs collision between two different deficits is a reproducible fact of THIS order,
    # never incidental dict/batch order.
    for deficit in sorted(seam["deficits"], key=lambda d: d["outputSpeciesId"]):
        output_id = deficit["outputSpeciesId"]
        recipe_id = f"recipe.{output_id}"
        pool_hash = candidate_pool_hash(deficit["candidatePool"])
        candidate_by_id = {c["speciesId"]: c for c in deficit["candidatePool"]}

        existing_entry = (existing_seed or {}).get(recipe_id)
        existing_prov = (existing_entry or {}).get("provenance") if existing_entry else None
        if (
            existing_prov is not None
            and existing_prov.get("corpusContentHash") == pool_hash
            and existing_prov.get("promptVersion") == PROMPT_VERSION
        ):
            # §3a freeze: unchanged candidate pool, current prompt version — kept verbatim, no
            # model call this run, and its pair stays claimed under used_pairs exactly as before.
            recipes[recipe_id] = existing_entry
            used_pairs.add(frozenset((existing_entry["inputSpeciesIdA"], existing_entry["inputSpeciesIdB"])))
            continue

        output = DeficitOutput(species_id=output_id, element_primary=deficit["elementPrimary"], rarity=deficit["rarity"])
        candidates = [
            FusionCandidate(
                species_id=c["speciesId"], element_primary=c["elementPrimary"], rarity=c["rarity"],
                acquisition=tuple(c["acquisition"]), rung_distance=c["rungDistance"],
            )
            for c in deficit["candidatePool"]
        ]
        claimed_pairs_shown = [tuple(sorted(p)) for p in used_pairs]

        samples = propose_fn(output, candidates, claimed_pairs_shown)
        model_calls_made.append(output_id)
        vote = resolve_fusion_pair_vote(samples)

        if vote.pair is None:
            unresolved.append(output_id)
            continue

        a_raw, b_raw = vote.pair
        if a_raw not in candidate_by_id or b_raw not in candidate_by_id:
            unresolved.append(output_id)  # proposed something outside the shown pool — refused, not trusted
            continue
        # Owner lock 6 bars an EXCLUSIVELY CaptureOnly input, matching CreatureRecipeCatalog.cs's own
        # established rule everywhere else in this program (`s.Acquisition != CreatureAcquisition.
        # CaptureOnly`, an exact-equality check) — a species carrying Summonable alongside
        # CaptureOnly is NOT capture-only in the sense the lock cares about (a player can still
        # summon it), so `"CaptureOnly" in acquisition` alone is the wrong, stricter check: it would
        # wrongly refuse a real, legal candidate the C# seam's own CandidatePoolBelow already
        # admitted into the shown pool under this exact same rule.
        if candidate_by_id[a_raw]["acquisition"] == ["CaptureOnly"] or candidate_by_id[b_raw]["acquisition"] == ["CaptureOnly"]:
            unresolved.append(output_id)  # owner lock 6, unconditional — an LLM proposal is not an exception
            continue
        if a_raw == b_raw:
            unresolved.append(output_id)
            continue
        if frozenset((a_raw, b_raw)) in used_pairs:
            unresolved.append(output_id)  # duplicate across deterministic OR another proposal — never reused
            continue

        input_a, input_b = assign_input_a_b(
            (a_raw, b_raw),
            candidate_elements={sid: c["elementPrimary"] for sid, c in candidate_by_id.items()},
            output_element_primary=output.element_primary,
        )

        nearest = deficit.get("nearestPopulatedRung")
        cross_rung = not (candidate_by_id[input_a]["rarity"] == nearest and candidate_by_id[input_b]["rarity"] == nearest)

        used_pairs.add(frozenset((input_a, input_b)))
        recipes[recipe_id] = {
            "outputSpeciesId": output_id,
            "inputSpeciesIdA": input_a,
            "inputSpeciesIdB": input_b,
            "crossRungGapFill": cross_rung,
            "provenance": {"corpusContentHash": pool_hash, "promptVersion": PROMPT_VERSION},
        }

    return ReconcileOutcome(recipes=recipes, unresolved=unresolved, model_calls_made=model_calls_made)


def _last_top_level_json(stdout: str) -> "dict | None":
    """The seam's payload, from the LAST top-level JSON value on `stdout` -- the contract the doc
    comment above `run_seam_cli` states. Host chatter shares this stream: `dotnet run`'s own build
    summary when a build is triggered, and the HOST's `[save-identity] migrated save identities;
    report: {...}` line, which is what actually broke the first-brace parse (measured 2026-09-22:
    its brace sits at char 64, and `json.loads` then reported `Extra data: line 2 column 1 (char
    639)` -- the real payload's start -- so the failure described the host's log line, not the seam).

    A candidate counts only when it CONSUMES the rest of stdout, so an earlier top-level value.
    (which by definition has the payload after it) is rejected rather than silently returned. Line
    starts are tried first because the payload is one `Console.WriteLine`, which keeps this O(1)
    parses on the real 400 KB payload instead of re-decoding every nested brace."""
    decoder = json.JSONDecoder()
    braces = [i for i, ch in enumerate(stdout) if ch == "{"]
    line_starts = [i for i in braces if i == 0 or stdout[i - 1] == "\n"]
    for candidates in (line_starts, braces):
        for start in reversed(candidates):
            try:
                value, end = decoder.raw_decode(stdout, start)
            except json.JSONDecodeError:
                continue
            if stdout[end:].strip() == "":
                return value
    return None


def run_seam_cli(*, project: Path = DEFAULT_SEAM_PROJECT, seed_dir: "Path | None" = None) -> dict:
    """The real CLI seam (spec §3 step 1: "via a CLI seam into the real C#, never reimplemented").
    A genuine subprocess call — this is what proves `reconcile.py` actually reads
    `CreatureRecipeCatalog`'s own live output rather than a second, parallel guess at it."""
    args = ["dotnet", "run", "--project", str(project), "--"]
    if seed_dir is not None:
        args += ["--seed", str(seed_dir)]
    result = run_tool(args, cwd=REPO_ROOT, refusal=RuntimeError,
                      what="the fusion corpus reconciliation this module shells out for")
    if result.returncode != 0:
        raise RuntimeError(f"{project} exited {result.returncode}: {result.stderr}")

    # `dotnet run` can print its own build summary (warnings included) to STDOUT ahead of the
    # program's own output when a build is triggered, and the host prints its save-identity migration
    # report there too — the seam's actual JSON is always the LAST top-level value on stdout
    # (Program.cs's own single `Console.WriteLine(JsonSerializer...)`), so the LAST value that
    # consumes the rest of stdout is the payload, never the first `{`.
    payload = _last_top_level_json(result.stdout)
    if payload is None:
        raise RuntimeError(f"{project} produced no JSON on stdout:\n{result.stdout[:2000]}")
    return payload


def load_existing_seed(path: Path) -> "dict[str, dict] | None":
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _default_propose_fn(output: DeficitOutput, candidates: "list[FusionCandidate]", claimed: "list[tuple[str, str]]"):
    """Checkpoint 8a's own owner-run wiring point — a real local-model call (matching T2.11's own
    established `pipeline.llm_caller.call_with_self_heal` pattern, `build_fusion_proposal_brief` /
    `build_fusion_proposal_schema` from `prompts.py`/`schema.py`) belongs here. Deliberately NOT
    implemented in this task: this repo has no live model access to verify a wired call against,
    and shipping an untested integration would look done without being proven — the same
    "never fabricate, name the gap" rule this whole module enforces on ITS OWN output, applied to
    this code. `reconcile()` never calls this at all when there are zero deficits (the real
    zero-shortfall case), so a corpus with no shortfall reconciles correctly today with no
    changes needed here.
    """
    raise NotImplementedError(
        "no live model wiring in this build — pass a real propose_fn (Checkpoint 8a, owner-run) "
        "or run this command with --deterministic-only"
    )


def _deterministic_only_propose_fn(output: DeficitOutput, candidates: "list[FusionCandidate]", claimed: "list[tuple[str, str]]"):
    """`--deterministic-only`'s own propose_fn: makes NO model call and resolves nothing, for every
    deficit, every time. Lets `reconcile` produce (and `--check` verify) a genuinely honest committed
    seed — every deterministic recipe real, every unresolved deficit named in the run's own report,
    zero gap-fills fabricated — before Checkpoint 8a's real model pass ever runs. Not a stand-in for
    that pass: a later real run against the SAME committed file only ADDS gap-fill entries (§3a's own
    freeze-on-commit never touches an entry this mode could have written, since this mode writes
    none), so this mode and Checkpoint 8a's own real pass can never conflict or need reconciling
    against each other.
    """
    return [None, None, None]


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Reconcile fusion recipes: deterministic pass + voted gap-fills.")
    ap.add_argument("--check", action="store_true", help="compare against the committed seed; write nothing; exit 1 if stale")
    ap.add_argument("--deterministic-only", action="store_true",
                     help="make no model call; every deficit ships unresolved, named in the report — "
                          "for producing/refreshing a committed seed before Checkpoint 8a's real pass runs")
    ap.add_argument("--seam-project", type=Path, default=DEFAULT_SEAM_PROJECT)
    ap.add_argument("--seed", type=Path, default=None, help="override the anchor seed directory the C# seam reads")
    ap.add_argument("--out", type=Path, default=REPO_ROOT.joinpath(*DEFAULT_OUTPUT_RELATIVE))
    args = ap.parse_args(argv)

    propose_fn = _deterministic_only_propose_fn if args.deterministic_only else _default_propose_fn
    seam = run_seam_cli(project=args.seam_project, seed_dir=args.seed)
    existing = load_existing_seed(args.out)
    outcome = reconcile(seam, propose_fn, existing_seed=existing)

    if args.check:
        problems = emit_check(outcome.recipes, args.out)
        if problems:
            for p in problems:
                print(p, file=sys.stderr)
            return 1
        print(f"--check: clean, {len(outcome.recipes)} recipe(s) match {args.out}")
        return 0

    wrote = emit_write(outcome.recipes, args.out)
    print(f"{len(outcome.recipes)} recipe(s) reconciled "
          f"({len(seam['deterministicRecipes'])} deterministic, {len(outcome.recipes) - len(seam['deterministicRecipes'])} gap-filled) "
          f"-> {args.out} ({'written' if wrote else 'unchanged'})")
    if outcome.unresolved:
        print(f"{len(outcome.unresolved)} output(s) unresolved, no recipe written: {', '.join(outcome.unresolved)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
