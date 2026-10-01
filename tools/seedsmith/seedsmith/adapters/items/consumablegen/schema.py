"""seedsmith.adapters.items.consumablegen.schema — the closed vocabularies a `consumable` entry is
validated against, ported from real, code-and-doc sources (never invented here):

- `classId` / the two seam columns (`grantsActionId`, `cooldownKey`) — `kinds.py:98-101`'s real,
  ported `consumable` `KindSpec` (itself ported from `KindCatalog.cs`), narrowed to the **three**
  classes v1 may author (`restore`, `draught`, `ward`) per
  `docs/architecture/item/ssot-consumables.md` §3.1's own table — `board`/`revive`/`utility` are
  "declare only" there, each blocked on a named, unbuilt executor, and none of the 60 shipped rows
  uses one (measured below in `test_consumables_gen.py`).
- `useContext` — `ssot-consumables.md` §5.2's closed set (`menu` · `dispatch` · `battle` · `lawn`),
  narrowed to the three v1 may author. `lawn` is refused outright (§9 item 5(b)'s own current
  answer), so it is never offered to the model and never accepted from one.
- `powerBand` — `gk-data/packs/fusion/data/seed/items/_registry/bands.v1.json`'s frozen 5-rung enum, read fresh (not
  transcribed), the same discipline `registries.py` already uses for every other closed vocabulary
  it loads.
- `family` — **the one EXTERNAL reference in this module**
  (`pipeline/dependency_validator.py`'s `EXTERNAL` kind). `load_atom_family_names()` parses
  `docs/architecture/effect-atom/atom-family-library.md` §3 (the family library, not the sparse
  `gk-data/packs/fusion/data/seed/atoms/*.json` generated-instance corpus `items/registries.py:load_atom_families()`
  already owns for `unique` — a different, much smaller vocabulary answering a different question).
  This program never authors a family id itself; it only ever checks one the model proposed against
  this real, closed list. An unresolved `family` is reported as a gap for effect-atom to fix
  (dependency_validator's own EXTERNAL contract: validated like a hard reference, never backfilled).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

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


# --- classId / useContext -----------------------------------------------------------------------
# ssot-consumables.md §3.1's full six-value taxonomy, kept for validating an EXISTING corpus row
# (the reconcile path reads all 60 shipped rows and must not choke on a class id none of them use
# today) -- but never offered to a generation brief, which only ever shows AUTHORABLE_CLASS_IDS.
CLASS_IDS = frozenset({"restore", "draught", "ward", "board", "revive", "utility"})
AUTHORABLE_CLASS_IDS = frozenset({"restore", "draught", "ward"})

USE_CONTEXTS = frozenset({"menu", "dispatch", "battle", "lawn"})
AUTHORABLE_USE_CONTEXTS = frozenset({"menu", "dispatch", "battle"})  # never `lawn` -- ssot §9 item 5(b)

# --- powerBand ------------------------------------------------------------------------------------
_BANDS_REGISTRY = _owned("data/seed/items/_registry/bands.v1.json")


def load_power_bands() -> "tuple[str, ...]":
    """The frozen 5-rung ladder, read fresh from the registry every call -- never hardcoded, per
    this program's own verification discipline (a registry bump must be visible here without an
    edit)."""
    doc = json.loads(_BANDS_REGISTRY.read_text(encoding="utf-8"))
    return tuple(doc["powerBand"]["enum"])


# --- family: the EXTERNAL reference into atom-family-library.md -----------------------------------

_ATOM_FAMILY_LIBRARY_DOC = _owned("docs/architecture/effect-atom/atom-family-library.md")
_LIBRARY_SECTION_START = "## 3. The library"
_LIBRARY_SECTION_END = "## 4. Domains"

#: A table-row family cell is a bare lowercase kebab/underscore identifier -- never a channel path
#: (those carry a dot, e.g. `combat.power.*`, and are never legal `family` values themselves), never
#: a flavour word (those are the OTHER pipe-column, never backticked in the family column), and
#: never a code symbol (those carry an uppercase letter, e.g. `ApplyStatusToZombie`, `ModifyStat`).
_FAMILY_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]+$")

#: §3.2's own status-channel families are named in a PROSE sentence, not a table row (the table-row
#: parser below deliberately does not scan prose, to avoid picking up stray lowercase code words
#: like `tier` or `variant` that appear backticked elsewhere in the same section). Transcribed here
#: with the exact source sentence recorded as `_STATUS_CHANNEL_FAMILIES_CITATION` below, mirroring
#: `items/registries.py`'s own `HYBRID_FRAME_CITATION` precedent -- a test asserts the citation is
#: still a live substring of the doc, so a future edit that changes this rule cannot silently drift.
_STATUS_CHANNEL_FAMILIES = frozenset({"affliction", "stalwart", "immunity", "susceptibility"})
_STATUS_CHANNEL_FAMILIES_CITATION = (
    "Plus **4 status-channel families** (not element-expanded): `affliction` (`status.power.*` by "
    "category), `stalwart` (`status.resist.*`), `immunity` (`status.immune.{tag}`), "
    "`susceptibility` (`status.expose.*`"
)


def _table_row_family_tokens(section_text: str) -> "set[str]":
    names: "set[str]" = set()
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells:
            continue
        first = cells[0]
        if not first:
            continue
        low = first.lower()
        if low == "family" or set(first) <= {"-", " ", ":"}:
            continue  # header row / separator row
        if "owed to seedsmith" in low:
            continue  # a reserved channel slot with no family id minted yet -- not a legal value
        for token in first.split("·"):  # "·" -- a cell may list several names, e.g. a shared row
            token = token.strip().strip("`").strip()
            if token and _FAMILY_TOKEN_RE.match(token):
                names.add(token.replace("_", "-"))
    return names


def load_atom_family_names() -> "frozenset[str]":
    """The full, real, closed `atom.<family>` vocabulary — read fresh from
    `atom-family-library.md` §3 every call, never cached or transcribed wholesale. Underscore forms
    in the doc are display shorthand for a kebab-case `family_id` (the doc's own naming note, §2:
    "`elemental_power` here is `atom.elemental-power` in the table"), so every token is normalized
    underscore -> hyphen before the `atom.` prefix is added — this is what makes `atom.elemental-power`
    (the real value `k2.json` ships) resolve against a doc that spells it `elemental_power`.
    """
    text = _ATOM_FAMILY_LIBRARY_DOC.read_text(encoding="utf-8")
    start = text.index(_LIBRARY_SECTION_START)
    end = text.index(_LIBRARY_SECTION_END, start)
    section = text[start:end]
    names = _table_row_family_tokens(section) | _STATUS_CHANNEL_FAMILIES
    return frozenset(f"atom.{n}" for n in sorted(names))


def is_real_atom_family(value: object) -> bool:
    """`resolve_hard` for the `family` EXTERNAL manifest entry (`dependency_validator.validate`) --
    exact id must exist verbatim in the real, current family library."""
    return isinstance(value, str) and value in load_atom_family_names()
