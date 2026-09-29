"""seedsmith.adapters.trees.plan.ids — node id minting (ruling R3, task B1).

`skill.<treeSlug>-<branch>-t<tier>-<nodeKey>`. No `/`, no dot inside the body — the verified
`container_id` grammar (`item/seed-contract.md:132`) forbids both. `nodeKey` is minted ONCE by the
plan and READ BACK on regeneration, never recomputed from position — the plan is therefore not a
pure function of its inputs alone; the committed plan (if one exists) is itself an input, and
`--emit` refuses to mint a new key over an existing one.
"""
from __future__ import annotations

import re

_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*$")
_NODE_KEY_RE = re.compile(r"^[a-z][a-z0-9]*$")
_BRANCH_SLUGS = {"offensive": "off", "defensive": "def"}


class IdMintError(ValueError):
    """A node id could not be formed or would collide with an existing one."""


# J1 (2026-09-07): the first real ids to exercise this grammar that were never a plain aptitude name —
# 5 of the 24 real status ids legitimately contain `_` or `.` (`charm_pulse`, `pact_mark`,
# `nerve.afflicted`, `nerve.shaken`, `nerve.unsettled`, all confirmed live against
# `gk-data/packs/fusion/data/seed/statuses/roster.json`) — `tree_id` itself must stay exactly the real id everywhere else
# (gate quantities, file names, the roster lookup), so this maps ONLY the id-minting grammar's own
# stricter, separator-free `tree_slug` onto it, never the id itself. Concatenation, not a hyphen:
# a hyphen is already a structural separator in `skill.<treeSlug>-<branch>-t<tier>-<nodeKey>`, so
# inserting one here would make the id ambiguous to parse back apart. Checked against all 42 real tree
# ids (12 aptitudes + 6 elements + 24 statuses) for collisions after stripping — none.
_SLUG_STRIP_RE = re.compile(r"[._]")


def tree_slug_for(tree_id: str) -> str:
    """The safe, `_SLUG_RE`-legal slug for `tree_id` inside a minted node id — never used for the
    tree's own real identity (gate quantity, file name, roster lookup, `affix.species.<id>.*`'s own
    namespace), only for this grammar.

    Task J8 (2026-09-07): also lowercases, for the identical reason the separator-strip was added
    2026-09-07 — the first real ids to exercise this grammar that are not already lowercase.
    `primary_tree_spec` has always lowercased its OWN `aptitude_id` before setting `tree_id`
    (`aptitude_id.lower()`), because every roster id it reads is PascalCase ("Might") while every
    downstream consumer of THAT tree's `tree_id` was fine with the lowered form becoming the real
    identity. A species tree cannot do the same: its real id ("AbyssSwordStar") must stay
    case-exact everywhere else (the roster, gate quantities, and — checked directly — the
    `affix.species.<speciesId>.*` namespace `SpeciesUniquenessMetric`'s own U3 pattern and J7's
    `--species-id` flag both already key on), so the fold has to happen HERE, in the slug alone,
    not by lowercasing `tree_id` itself the way `primary_tree_spec` safely could. Checked against
    the real 904-species corpus before shipping this: 904 distinct ids strip+lower to 904 distinct
    slugs — zero collisions — the same real-data verification `_SLUG_STRIP_RE`'s own 2026-09-07
    addition already used for its 42-tree check.
    """
    return _SLUG_STRIP_RE.sub("", tree_id).lower()


def branch_slug(branch: str) -> str:
    if branch not in _BRANCH_SLUGS:
        raise IdMintError(f"unknown branch '{branch}' — expected one of {sorted(_BRANCH_SLUGS)}")
    return _BRANCH_SLUGS[branch]


def node_id(tree_slug: str, branch: str, tier: int, node_key: str) -> str:
    """`skill.<treeSlug>-<branch>-t<tier>-<nodeKey>` — the grammar R3 names, forbidding `/` and `.`
    inside the body (`item/seed-contract.md:132`'s `container_id` rule, reused verbatim)."""
    if not _SLUG_RE.match(tree_slug):
        raise IdMintError(f"tree_slug '{tree_slug}' must be lowercase alphanumeric, starting with a letter")
    if not _NODE_KEY_RE.match(node_key):
        raise IdMintError(f"node_key '{node_key}' must be lowercase alphanumeric, starting with a letter")
    if tier < 1:
        raise IdMintError(f"tier must be >= 1, got {tier}")
    return f"skill.{tree_slug}-{branch_slug(branch)}-t{tier}-{node_key}"


def mint_node_keys(tree_slug: str, branch: str, tier: int, count: int,
                   existing: "dict[tuple[str, int, int], str]",
                   next_ordinal: "dict[tuple[str, str, int], int]") -> "list[str]":
    """Mint `count` node keys for one `(branch, tier)` slot, reading back any keys already minted
    for that exact `(branch, tier, index)` position rather than re-deriving them. `existing` maps
    `(branch, tier, index) -> node_key` from a previously-committed plan (empty on a first emit).
    `next_ordinal` tracks the per-`(tree, branch, tier)` synthetic-name counter across calls so a
    second call for the same slot in the same run never reuses a name — mutated in place.

    Returns the `count` node keys for this slot, in index order. A key already committed at a given
    index is returned unchanged (R3: read back, never re-minted); an index with no prior key gets a
    freshly synthesized one (`n<ordinal>` — the language stage names nodes for real; this is a
    structural placeholder key, matching the plan's own "no node text" boundary).
    """
    if count < 1:
        raise IdMintError(f"count must be >= 1, got {count}")
    key = (tree_slug, branch, tier)
    counter_start = next_ordinal.get(key, 0)
    result: "list[str]" = []
    for index in range(count):
        existing_key = existing.get((branch, tier, index))
        if existing_key is not None:
            result.append(existing_key)
            continue
        ordinal = counter_start
        counter_start += 1
        result.append(f"n{ordinal}")
    next_ordinal[key] = counter_start
    return result


def refuse_if_key_reused(minted: "list[str]") -> None:
    """A single emit must never mint the same node_key twice inside one tree — that would collide
    in the id grammar (`skill.<tree>-<branch>-t<tier>-<nodeKey>` is unique per (branch, tier)
    already, but a mint bug producing a repeated ordinal inside one slot is exactly the kind of
    silent collision R3 exists to prevent)."""
    seen: "set[str]" = set()
    for key in minted:
        if key in seen:
            raise IdMintError(f"node_key '{key}' minted twice in the same slot")
        seen.add(key)
