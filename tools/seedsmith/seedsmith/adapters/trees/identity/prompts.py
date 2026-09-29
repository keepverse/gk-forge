"""seedsmith.adapters.trees.identity.prompts — the tree-identity brief
(spec-passive-tree-identity-content.md §4). Mirrors `adapters.trees.species.prompts`'s own
`CODEX_SYSTEM_PROMPT`/`build_codex_context`/`build_codex_brief` shape: a system prompt with the
same negative-clause discipline, and a context/brief pair built from real, already-generated
content rather than invented independently.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

PROMPT_VERSION = "tree-identity/1"

TREE_IDENTITY_SYSTEM_PROMPT = (
    "You name a passive skill tree and write ONE sentence describing what kind of build it "
    "rewards, based ONLY on the tree's own already-written trait names and flavor text given "
    "below. You do not invent new mechanics or lore — you read what is already there and give it "
    "a name and a one-line pitch to the player. Never write a number. Never name a stat, a "
    "channel, an aptitude, an element, a status, or any other mechanics term by its game name — "
    "translate the mechanism into what it means for how the player plays."
)


def build_identity_context(
    tree_id: str, category: str, branches: "Sequence[str]",
    sample_nodes: "Sequence[tuple[str, str]]",
) -> "dict[str, Any]":
    """`sample_nodes`: up to 6 real `(name, flavor)` pairs from the tree's OWN already-generated
    nodes (`gk-data/packs/fusion/data/seed/passive-tree/nodes/<treeId>.json`) — the tree's own real content is what
    grounds this brief, mirroring `build_codex_context`'s own "read the anchor's real fields,
    never invent" discipline."""
    return {
        "treeId": tree_id,
        "category": category,
        "branches": list(branches),
        "sampleNodes": [(n, f) for n, f in sample_nodes],
    }


def build_identity_brief(context: "Mapping[str, Any]") -> str:
    lines = [f"Tree id: {context['treeId']}", f"Category: {context['category']}"]
    if context.get("branches"):
        lines.append(f"Branches: {', '.join(context['branches'])}")
    sample_nodes = context.get("sampleNodes") or []
    if sample_nodes:
        lines.append("This tree's own already-written traits (a sample):")
        for name, flavor in sample_nodes:
            lines.append(f"  - {name}: {flavor}")
    lines += [
        "",
        "Give this tree a short, evocative NAME (2-4 words, at most 40 characters) and write ONE "
        "sentence (at most 160 characters) describing what kind of build it rewards, grounded in "
        "the traits above. No numbers. No mechanics terms by name.",
    ]
    return "\n".join(lines)
