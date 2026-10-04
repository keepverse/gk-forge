"""seedsmith.adapters.trees.identity.generate_identity — the tree-identity STAGE's own resolution
function (`seedsmith-content-standard`, Task 17, spec-passive-tree-identity-content.md §5). Mirrors
`adapters.trees.species.generate_codex.resolve_codex_summaries` as closely as a two-field stage
allows: pure result-producing, no persistence of its own — the caller decides where a committed
per-tree identity file lives (`gk-data/packs/fusion/data/seed/passive-tree/identity/<treeId>.json`, per this module's
own spec §6), the same "this module returns results in memory" boundary `generate_codex.py`
states for itself.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ....pipeline.llm_caller import LlmCallerConfig
from ....workflow.runner import MAX_WORKERS

SAMPLES_PER_TREE = 3
#: Real, already-generated node content this stage grounds its brief on — never invented
#: independently (spec §2/§4).
MAX_SAMPLE_NODES = 6


def real_sample_nodes(seed_json: str) -> "list[tuple[str, str]]":
    """Reads up to `MAX_SAMPLE_NODES` real `(name, flavor)` pairs from a tree's own already-
    committed `nodes/<treeId>.json` content — the exact real shape `ferocity.json` and its 41
    siblings already carry. A node with no `name`/`flavor` yet (tree-language has not reached it)
    is skipped, never fabricated into a sample."""
    doc = json.loads(seed_json)
    pairs: "list[tuple[str, str]]" = []
    for node in doc.get("nodes", []):
        name, flavor = node.get("name"), node.get("flavor")
        if name and flavor:
            pairs.append((name, flavor))
        if len(pairs) >= MAX_SAMPLE_NODES:
            break
    return pairs


def resolve_tree_identities(
    trees: "Sequence[tuple[str, str, list[str], list[tuple[str, str]]]]", *,
    provenance_base: "Mapping[str, Any]",
    call: "Callable[..., str] | None" = None,
    config: LlmCallerConfig | None = None,
    workers: int = MAX_WORKERS,
) -> "tuple[dict[str, dict], dict[str, dict], dict[str, dict]]":
    """`trees` is `(treeId, category, branches, sampleNodes)` quadruples — the caller's own
    already-loaded real tree data, never re-derived here (this module owns the model call, not the
    upstream data, mirroring `resolve_codex_summaries`'s own boundary exactly).

    Returns `(fresh, unresolved, results)`:

    * `fresh` — `{treeId: {"name": str, "description": str, "_provenance": {...}}}`, one entry per
      tree whose `name` resolved. **Real, measured recalibration (2026-09-08, same session):** the
      first real PoC run against the live model voted BOTH fields by exact match and resolved only
      1 of 3 real trees — both failures were `description_vote_unresolved`, the exact same failure
      shape this session already diagnosed and fixed once today for favour-fit (independent
      free-text generations rarely converge byte-for-byte on a full sentence; a short NAME is a
      different kind of field — closer to a stable identifier — and did converge, including on
      both trees that failed overall). Fix: `name` alone is voted (3-way exact match, the SAME
      proven `codexSummary`-style mechanism); once it resolves, `description` is taken directly
      from the FIRST sample that produced the winning name — guaranteeing the returned pair
      genuinely came from one real, coherent generation together, without requiring three
      independent creative sentences to match exactly.
    * `unresolved` — `{treeId: {"reason": ..., ...}}`: `"name_vote_unresolved"` (name hit a 1-1-1
      split), or `"insufficient_valid_samples"` (fewer than `SAMPLES_PER_TREE` samples ever
      validated).
    * `results` — the per-sample-state graph outcome, keyed by the sample's own subject id.
    """
    from ....workflow.graphs.tree_identity import build_tree_identity_graph, state_for_tree_identity
    from ....workflow.runner import run_many
    from ...creatures.anchor.vote import resolve_vote

    persisted: "dict[str, dict]" = {}
    app = build_tree_identity_graph(
        on_persist=lambda k, v: persisted.__setitem__(k, v), config=config, call=call)

    tree_samples: "dict[str, list[str]]" = {}
    states: "list[dict]" = []
    for tree_id, category, branches, sample_nodes in trees:
        sample_ids: "list[str]" = []
        for sample_index in range(SAMPLES_PER_TREE):
            subject_id = f"{tree_id}-identity-sample-{sample_index}"
            state = state_for_tree_identity(subject_id, tree_id, category, branches, sample_nodes)
            states.append(state)
            sample_ids.append(subject_id)
        tree_samples[tree_id] = sample_ids

    results = run_many(app, states, max_workers=workers)

    fresh: "dict[str, dict]" = {}
    unresolved: "dict[str, dict]" = {}
    for tree_id, sample_ids in tree_samples.items():
        samples = [
            persisted[sid] for sid in sample_ids
            if sid in persisted and isinstance(persisted[sid], dict)
            and "name" in persisted[sid] and "description" in persisted[sid]
        ]
        if len(samples) != SAMPLES_PER_TREE:
            unresolved[tree_id] = {
                "reason": "insufficient_valid_samples",
                "validSamples": len(samples), "samplesExpected": SAMPLES_PER_TREE,
            }
            continue

        name_vote = resolve_vote([s["name"] for s in samples])
        if name_vote.value is None:
            unresolved[tree_id] = {"reason": "name_vote_unresolved", "confidence": name_vote.confidence}
            continue

        # The paired description comes from the FIRST sample that produced the winning name — a
        # real, coherent (name, description) pair from one actual generation, never a vote across
        # independent sentences (see this function's own docstring for the real, measured reason).
        paired_description = next(s["description"] for s in samples if s["name"] == name_vote.value)

        provenance = dict(provenance_base)
        provenance["nameVoteConfidence"] = name_vote.confidence
        if name_vote.minority:
            provenance["nameVoteMinority"] = name_vote.minority
        fresh[tree_id] = {
            "name": name_vote.value, "description": paired_description, "_provenance": provenance,
        }

    return fresh, unresolved, results


def write_identity_file(identity_root: Path, tree_id: str, entry: "Mapping[str, Any]") -> Path:
    """The real per-tree identity file writer (spec §6): `gk-data/packs/fusion/data/seed/passive-tree/identity/
    <treeId>.json`, matching the existing `nodes/<treeId>.json`/`plan/<treeId>.v1.json` per-tree
    convention. Canonical serialization (sorted keys, 2-space indent) matching this program's own
    established writer discipline elsewhere (`emit.py`, `run_ledger.py`)."""
    identity_root.mkdir(parents=True, exist_ok=True)
    path = identity_root / f"{tree_id}.json"
    path.write_text(
        json.dumps(dict(entry, treeId=tree_id), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    return path
