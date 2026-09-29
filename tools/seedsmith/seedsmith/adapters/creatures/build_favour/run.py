"""`lead-relabel-pass`'s pass-2 wiring — the staleness rule and the re-led anchor entry.

Spec: `docs/architecture/empire-progression/spec-lead-relabel-pass.md` ("Where the answer lives",
"Staleness", "Secondary"). Two halves: the STALENESS rule and the entry transform live here (EP2.11),
the model-run orchestration lands beside them (EP2.12). Pure functions over mappings — no IO, no model,
no clock — so the rules can be tested without a corpus or a call.

The anchor is the answer's home (map D4): a re-label is written INTO the anchor, through the same
`emit.py` every other pass uses, with its provenance attached. Nothing here writes a file; the caller
(EP2.12) does, through the emit.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..anchor.derive import derive_posture, derive_pure
from ..anchor.emit import write_family_file
from ..anchor.prompts import PipelineSpec, SpeciesLore
from ..anchor.provenance import PROMPT_VERSIONS, ReleadProvenance
from ..anchor.schema import APTITUDES
from .accept import EXCLUDED_KIND, Candidate, accept, over_cap_sources
from .relead import RELEAD, ReleadVote, resolve_relead_vote

#: The pass-1 pipeline that owns `aptitudePrimary`. Pass 2 re-labels the field this pipeline answers, so
#: once it re-runs — a prompt-version bump, or a fresh capture — the re-label describes an answer that
#: no longer exists.
PASS_ONE_PIPELINE = "aptitude-primary"


def relead_is_stale(
    entry: Mapping[str, Any],
    *,
    current_prompt_versions: Mapping[str, int] = PROMPT_VERSIONS,
) -> bool:
    """Has pass 1 re-run for this species since its re-label?

    Two recorded-value comparisons, never an mtime (`emit.stale_ids`' own rule):

    - the block's `promptVersion` against the CURRENT pass-1 version — a bumped prompt means pass 1 was
      re-asked, so the re-label was an answer to a question that has changed;
    - the block's `dumpHash` against the entry's own `_provenance.dumpHash` — pass 1 re-derived the row
      against a different capture, so the re-label's evidence is stale even when the prompt did not move.

    An entry with no block is not stale: there is nothing to drop.
    """
    block = (entry.get("_provenance") or {}).get("relead")
    if not block:
        return False
    if block.get("promptVersion") != current_prompt_versions.get(PASS_ONE_PIPELINE):
        return True
    return block.get("dumpHash") != (entry.get("_provenance") or {}).get("dumpHash")


def drop_stale_releads(
    entries: Iterable[Mapping[str, Any]],
    *,
    current_prompt_versions: Mapping[str, int] = PROMPT_VERSIONS,
) -> "tuple[list[dict[str, Any]], list[str]]":
    """`(kept, requeued)` — the entry list with every stale block DROPPED, and the species ids queued
    for pass 2 again.

    The pass-1 answer stands for a dropped row: the block goes, `aptitudePrimary` is untouched. Inputs
    are never mutated — a rule that edits the corpus while judging it is a rule nobody can test.
    """
    kept: "list[dict[str, Any]]" = []
    requeued: "list[str]" = []
    for entry in entries:
        if not relead_is_stale(entry, current_prompt_versions=current_prompt_versions):
            kept.append(dict(entry))
            continue
        provenance = dict(entry.get("_provenance") or {})
        provenance.pop("relead", None)
        cleaned = dict(entry)
        cleaned["_provenance"] = provenance
        kept.append(cleaned)
        species_id = entry.get("speciesId")
        if species_id:
            requeued.append(species_id)
    return kept, sorted(requeued)


def apply_relead(
    entry: Mapping[str, Any],
    *,
    new_primary: str,
    block: ReleadProvenance,
) -> "dict[str, Any]":
    """The re-led entry: the primary pass 2 chose, the secondary swapped when it collides, `posture`
    and `pure` re-derived, and the provenance block attached.

    Only an ACCEPTED decision gets here (`accept.accept` is the quota): a refused or unresolved species
    keeps its pass-1 primary and, deliberately, gains no block — there is nothing to claim.

    - **The swap** (spec "Secondary"): when the new primary equals the current secondary the two swap,
      so no species ever ends with `aptitudePrimary == aptitudeSecondary` — the corruption the planner
      guards against is prevented here, at the source.
    - **Re-derived, never authored** (spec-classify-pipelines.md §4): `posture` and `pure` are computed
      from the NEW primary by `derive.py`, exactly as pass 1 computes them, so a re-label cannot
      contradict its own answer.
    - The block must describe THIS row: its `fromPrimary` is checked against the entry's own primary.
    """
    if new_primary not in APTITUDES:
        raise ValueError(f"relead target {new_primary!r} is not one of the twelve aptitude ids")

    previous = entry.get("aptitudePrimary")
    if block.from_primary != previous:
        raise ValueError(
            f"provenance says fromPrimary {block.from_primary!r} but this row leads {previous!r} — "
            "the block must describe the change it is attached to")

    secondary = entry.get("aptitudeSecondary")
    if secondary == new_primary:
        secondary = previous

    provenance = dict(entry.get("_provenance") or {})
    provenance["relead"] = block.to_dict()

    updated = dict(entry)
    updated["aptitudePrimary"] = new_primary
    updated["aptitudeSecondary"] = secondary
    updated["posture"] = derive_posture(new_primary)
    updated["pure"] = derive_pure(new_primary, secondary)
    updated["_provenance"] = provenance
    return updated


# ── EP2.12: the pass itself — plan (always), ask (only when writing), decide, write ────────────
#
# Inputs, pinned in the C# readers' own discipline (H7): a tuning publish moves these constants in the
# SAME commit. `power/bands.py`'s `TUNING_KEY = "creature-threat.v2"` is the Python precedent for a
# literal pin, and it is why these are literals rather than "the highest version on disk" — the pass
# must not silently follow a publish the readers have not been moved to.

TUNING_FILE = "species-build.v5.json"
MEASURE_REL = ("data", "generated", "creatures", "_species-build-measure.json")
ANCHORS_REL = ("data", "seed", "creatures", "species")
DUMP_REL = ("data", "seed", "creatures", "_dump")


@dataclass(frozen=True)
class AnchorTree:
    """The emitted anchor tree, read once: entries by id, the full entry list per family file (a write
    must rewrite the WHOLE file, not just the touched row), and the file each id lives in."""

    root: Path
    entries_by_id: "dict[str, dict[str, Any]]"
    entries_by_file: "dict[str, tuple[dict[str, Any], ...]]"
    path_by_id: "dict[str, str]"


@dataclass(frozen=True)
class Asked:
    """One species pass 2 will ask about."""

    species_id: str
    current: str
    current_secondary: str


@dataclass(frozen=True)
class PassPlan:
    """What the pass will do — the dry-run artefact AND the run's own input, so the two cannot differ.

    `lead_counts`/`species_count`/`largest_shape_permille` come straight out of the measure artifact:
    the cap is judged on the population the measure counted, and a Python recount (a different filter,
    a stale tree) must never silently change who gets asked.
    """

    cap_count: int
    species_count: int
    lead_counts: "dict[str, int]"
    over_cap: "tuple[str, ...]"
    asked: "tuple[Asked, ...]"
    requeued: "tuple[str, ...]"
    shape_cap: "int | None"
    largest_shape_permille: "int | None"
    lead_cap_permille: "int | None"
    measure_hash: str
    tree: AnchorTree

    def summary(self) -> "dict[str, Any]":
        """The printed plan: the candidate list and the quota's arithmetic, never a model's answer."""
        return {
            "measureHash": self.measure_hash,
            "speciesCount": self.species_count,
            "capCount": self.cap_count,
            "leadCapPermille": self.lead_cap_permille,
            "overCap": list(self.over_cap),
            "leadCounts": dict(sorted(self.lead_counts.items())),
            "asked": [{"speciesId": a.species_id, "current": a.current} for a in self.asked],
            "requeued": list(self.requeued),
            "shapeCapPermille": self.shape_cap,
            "largestShapePermille": self.largest_shape_permille,
        }


def read_anchor_tree(root: Path) -> AnchorTree:
    """Every family file under `root`, ordinal by path. A `_`-prefixed sibling is an index or a
    manifest, never a family file (the same skip the corpus tools make)."""
    entries_by_id: "dict[str, dict[str, Any]]" = {}
    entries_by_file: "dict[str, tuple[dict[str, Any], ...]]" = {}
    path_by_id: "dict[str, str]" = {}
    anchors_root = root.joinpath(*ANCHORS_REL)
    for path in sorted(anchors_root.rglob("*.json")):
        if path.name.startswith("_"):
            continue
        entries = tuple(json.loads(path.read_text(encoding="utf-8")))
        relative = path.relative_to(root).as_posix()
        entries_by_file[relative] = entries
        for entry in entries:
            species_id = entry.get("speciesId")
            if species_id:
                entries_by_id[species_id] = entry
                path_by_id[species_id] = relative
    return AnchorTree(root, entries_by_id, entries_by_file, path_by_id)


def load_plan(
    root: Path,
    *,
    measure_path: "Path | None" = None,
    tuning_path: "Path | None" = None,
    limit: "int | None" = None,
    current_prompt_versions: Mapping[str, int] = PROMPT_VERSIONS,
) -> PassPlan:
    """The plan: which leads are over the cap, and therefore which species pass 2 asks about.

    The measure is READ, never recomputed — that is the artifact's whole purpose. `cap_count` applies
    the published per-mille cap to the measure's OWN species count, and `over_cap_sources` names the
    source aptitudes from the measure's OWN lead counts.
    """
    measure_file = measure_path or root.joinpath(*MEASURE_REL)
    tuning_file = tuning_path or root.joinpath("data", "tuning", TUNING_FILE)
    if not measure_file.exists():
        raise FileNotFoundError(
            f"{measure_file} is missing — run `dotnet run --project tools/CreatureBuildPlanGen` first; "
            "the pass never counts the corpus itself")
    measure_bytes = measure_file.read_bytes()
    measure = json.loads(measure_bytes.decode("utf-8"))
    tuning = json.loads(tuning_file.read_text(encoding="utf-8"))

    cap_permille = tuning.get("leadCapPermille")
    if cap_permille is None:
        raise ValueError(f"{tuning_file} publishes no leadCapPermille (species-build v5+)")
    species_count = int(measure["speciesCount"])
    lead_counts = {name: int(count) for name, count in measure["leadCountByAptitude"].items()}
    cap_count = cap_permille * species_count // 1000
    over_cap = over_cap_sources(lead_counts, cap_count)

    tree = read_anchor_tree(root)
    _, requeued = drop_stale_releads(
        list(tree.entries_by_id.values()), current_prompt_versions=current_prompt_versions)

    asked = [
        Asked(species_id=species_id, current=entry["aptitudePrimary"],
              current_secondary=entry.get("aptitudeSecondary") or "none")
        for species_id, entry in sorted(tree.entries_by_id.items())
        # Over-cap lead AND a real creature: an `excluded` row is never counted, so it is never asked
        # (R-CS4 — the one filter, `accept`'s own predicate).
        if entry.get("aptitudePrimary") in over_cap and entry.get("speciesKind") != EXCLUDED_KIND
    ]
    if limit is not None:
        asked = asked[:max(0, limit)]

    return PassPlan(
        cap_count=cap_count, species_count=species_count, lead_counts=lead_counts,
        over_cap=over_cap, asked=tuple(asked), requeued=tuple(requeued),
        shape_cap=tuning.get("shapeCapPermille"),
        largest_shape_permille=measure.get("largestShapePermille"),
        lead_cap_permille=cap_permille,
        measure_hash=hashlib.sha256(measure_bytes).hexdigest(),
        tree=tree,
    )


def _accepted_block(
    *, entry: Mapping[str, Any], vote: ReleadVote, measure_hash: str,
    current_prompt_versions: Mapping[str, int],
) -> ReleadProvenance:
    """The block an ACCEPTED decision carries. Every field is a label, an index or an identifier —
    nothing a model chose — and the pass-1 version and capture are the ones the re-label was judged
    against, which is exactly what the staleness rule later compares."""
    return ReleadProvenance(
        from_primary=entry["aptitudePrimary"],
        prompt_version=current_prompt_versions[PASS_ONE_PIPELINE],
        dump_hash=(entry.get("_provenance") or {}).get("dumpHash", ""),
        votes=vote.votes,
        confidence=vote.confidence,
        measure_hash=measure_hash,
        outcome="accepted",
    )


def graph_ask(spec: PipelineSpec = RELEAD, *, call: "Any" = None, config: "Any" = None):
    """The default `ask`: three samples through pass 1's own generate/validate/persist wiring, built
    HERE because the relead spec is deliberately not a `PIPELINES` member (`spec_for` would KeyError on
    it, and adding it there would move that dict's eight-member pin).

    The model call is injected exactly as `build_pipeline_graph` injects it, so a caller can prove zero
    calls happen by handing in a raising stub — which is what `--dry-run` and the tests do.
    """
    from ....workflow.graphs.base import build_generation_graph
    from ....workflow.nodes.generate import make_generate_node
    from ....workflow.nodes.persist import make_persist_node
    from ....workflow.nodes.validate import make_validate_node
    from ....workflow.state import new_state

    graph = build_generation_graph(
        generate=make_generate_node(
            system=spec.system_prompt, schema=spec.schema, config=config, call=call),
        validate=make_validate_node(()),
        persist=make_persist_node(None),
    )

    def ask(lore: SpeciesLore, context: Mapping[str, Any]) -> "list[dict[str, Any]]":
        samples: "list[dict[str, Any]]" = []
        for _ in range(3):
            state = new_state(
                lore.species_id, brief=spec.build_brief(lore, dict(context)), context=dict(context))
            draft = graph.invoke(state).get("draft")
            samples.append(dict(draft) if isinstance(draft, dict) else {})
        return samples

    return ask


def execute(
    plan: PassPlan,
    *,
    ask: "Any" = None,
    write: bool = False,
    lore_by_id: "Mapping[str, SpeciesLore] | None" = None,
    current_prompt_versions: Mapping[str, int] = PROMPT_VERSIONS,
) -> "dict[str, Any]":
    """Run the pass.

    `write=False` is the dry run: the plan comes back and NOTHING else happens — `ask` is never invoked
    (no model call) and no file is touched.

    `write=True` asks every planned species, resolves each vote, runs stage A's quota over the whole
    candidate list, applies each ACCEPTED re-label to its anchor (secondary swap, `posture`/`pure`
    re-derived, provenance attached) and rewrites the touched family files through `emit` — the same
    writer every other pass uses, so the corpus keeps one serialisation and one truth.
    """
    summary = plan.summary()
    if not write:
        summary.update({"dryRun": True, "callsMade": 0, "written": [], "decisions": []})
        return summary

    if ask is None:
        ask = graph_ask()
    if lore_by_id is None:
        raise ValueError(
            "write=True needs lore_by_id (the dump's almanac rows) — a re-label judged without the "
            "lore would be invented, not classified")

    votes: "dict[str, ReleadVote]" = {}
    unanswered = 0
    for waiting in plan.asked:
        lore = lore_by_id.get(waiting.species_id)
        if lore is None:
            unanswered += 1
            continue
        context = {
            "order": list(APTITUDES), "current": waiting.current,
            "leadCount": plan.lead_counts.get(waiting.current, 0), "speciesCount": plan.species_count,
            "capCount": plan.cap_count,
        }
        samples = ask(lore, context)
        unanswered += sum(1 for s in samples if not s)
        votes[waiting.species_id] = resolve_relead_vote(samples)

    candidates = [
        Candidate(a.species_id, a.current, votes[a.species_id].value if a.species_id in votes else None)
        for a in plan.asked
    ]
    decisions = accept(candidates, plan.lead_counts, plan.cap_count)

    updated = dict(plan.tree.entries_by_id)
    touched: "set[str]" = set()
    for decision in decisions:
        if decision.outcome != "accepted":
            continue
        entry = updated[decision.species_id]
        block = _accepted_block(
            entry=entry, vote=votes[decision.species_id], measure_hash=plan.measure_hash,
            current_prompt_versions=current_prompt_versions)
        updated[decision.species_id] = apply_relead(entry, new_primary=decision.primary, block=block)
        touched.add(plan.tree.path_by_id[decision.species_id])

    written: "list[str]" = []
    for rel in sorted(touched):
        entries = [updated.get(e.get("speciesId"), e) for e in plan.tree.entries_by_file[rel]]
        write_family_file(plan.tree.root.joinpath(rel), entries)
        written.append(rel)

    counts: "dict[str, int]" = {}
    for decision in decisions:
        counts[decision.outcome] = counts.get(decision.outcome, 0) + 1
    summary.update({
        "dryRun": False,
        "callsMade": 3 * (len(plan.asked) - unanswered),
        "unansweredSamples": unanswered,
        "written": written,
        "outcomes": dict(sorted(counts.items())),
        "decisions": [
            {"speciesId": d.species_id, "primary": d.primary, "outcome": d.outcome} for d in decisions
        ],
    })
    return summary


def load_lore(root: Path, *, dump_rel: "tuple[str, ...]" = DUMP_REL) -> "dict[str, SpeciesLore]":
    """`speciesId -> SpeciesLore` from the committed capture's almanac rows — the same rows, through the
    same helper (`run.runner._species_rows`/`_lore_for`), that pass 1 shows a model, so pass 2 cannot
    show it a different creature."""
    from ..run.runner import _lore_for, _species_rows

    rows = _species_rows(root.joinpath(*dump_rel))
    return {row["speciesId"]: _lore_for(row) for row in rows if row.get("speciesId")}
