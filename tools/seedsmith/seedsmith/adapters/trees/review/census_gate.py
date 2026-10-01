"""seedsmith.adapters.trees.review.census_gate — the `sheetRead` refusal gate (task H7,
spec-tree-review.md §5.5, §5.6, Success criteria).

**What this module is for, in one sentence.** `trees review --census` must refuse to start
against a lot whose review queue holds no `sheetRead` row, or whose latest row names a
`sheetRevision` other than the one the sheet on disk carries right now. §5.5's own words: *"it
does not prove anyone understood the name-token panel; it proves the sheet for THIS revision was
opened and closed by a named person at a recorded time, and it fails loudly when a reviewer
starts a census against a stale sheet — which is the failure that actually happens."*

**What this module is NOT.** It never renders a sheet, never computes a `sheetRevision`, and
never writes a `sheetRead` row. All three are `gk-web/web/fusion-rpg-web/scripts/render-tree-cards.mjs`'s
own job (`--sheet` and `--sheet-read` CLI modes) — spec §5.4's "one implementation... not two"
rule applies here exactly as it does to `formatMagnitude`: a second, Python-side sheet renderer
would be a second source of truth for what a reviewer is asked to read. This module only reads
the two committed JSON artifacts that script produces:

  - `<sheetDir>/<lot>/sheet.json` — the sidecar the `--sheet` mode writes beside the committed
    `sheet.html`, carrying the CURRENT `sheetRevision` for that lot.
  - `<reviewDir>/<lot>.json` — the SAME file `appendVerdict` (H6) already writes verdict rows
    into, extended with one more top-level array, `sheetReads`, that the `--sheet-read` mode
    appends to. One file per lot, not a second file format (H7's own resolved ambiguity: the
    alternative was a third file shape, which the spec's own §5.6 "not a second source of truth"
    discipline argues against).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


#: Matches `render-tree-cards.mjs`'s own `DEFAULT_REVIEW_DIR` — same file, read from the Python
#: side rather than a second, drifting constant.
DEFAULT_REVIEW_DIR = _owned("data/seed/passive-tree") / "_review"

#: Matches the spec's own "Project structure" entry, `docs/research/passive-tree/_review/<lot>/
#: sheet.html — the corpus sheet - COMMITTED`. The sidecar `sheet.json` this module reads lives
#: beside it, in the same per-lot directory.
DEFAULT_SHEET_DIR = _owned("docs/research/passive-tree") / "_review"


class SheetNotRendered(Exception):
    """No `sheet.json` exists for this lot yet — `--sheet` has never been run against it, so
    there is nothing a `sheetRead` row could possibly be current against. Distinct from
    `CensusRefused`: this is "the sheet was never built," not "it was read and then changed."""


class CensusRefused(Exception):
    """§5.5: a census may not start without a CURRENT `sheetRead` acknowledgment. The message
    always names which of the two failures fired (missing row vs. stale row) — `verdict.py`'s own
    "a rejection names the rule" discipline (§6.1), applied to a refusal rather than a reject."""


@dataclass(frozen=True)
class SheetReadRow:
    """One `{lot, sheetRevision, by, utc}` acknowledgment (§5.5's own exact shape)."""

    lot: str
    sheet_revision: str
    by: str
    utc: str


def read_current_sheet_revision(sheet_dir: "Path | str", lot: str) -> str:
    """The `sheetRevision` the sheet ON DISK carries right now, read from
    `<sheet_dir>/<lot>/sheet.json` — never recomputed here (that would be a second
    implementation of the hash `render-tree-cards.mjs --sheet` already owns)."""
    sheet_json = Path(sheet_dir) / lot / "sheet.json"
    if not sheet_json.is_file():
        raise SheetNotRendered(
            f"no sheet rendered for lot {lot!r} — expected {sheet_json}; run "
            f"`node web/fusion-rpg-web/scripts/render-tree-cards.mjs --sheet --lot {lot}` first")
    try:
        data = json.loads(sheet_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as ex:
        raise SheetNotRendered(f"{sheet_json} is not valid JSON: {ex}") from ex
    revision = data.get("sheetRevision")
    if not revision:
        raise SheetNotRendered(f"{sheet_json} carries no sheetRevision")
    return str(revision)


def _load_review_queue(review_dir: "Path | str", lot: str) -> "dict[str, Any]":
    path = Path(review_dir) / f"{lot}.json"
    if not path.is_file():
        return {"lot": lot, "entries": [], "sheetReads": []}
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.setdefault("entries", [])
    doc.setdefault("sheetReads", [])
    return doc


def latest_sheet_read(review_dir: "Path | str", lot: str) -> "SheetReadRow | None":
    """The most recently appended `sheetReads` row for `lot`, or `None` if the queue holds none
    — `--sheet-read` appends (never overwrites, matching `appendVerdict`'s own discipline), so the
    LAST matching entry is always the current acknowledgment."""
    doc = _load_review_queue(review_dir, lot)
    rows = [r for r in doc.get("sheetReads", []) if r.get("lot") == lot]
    if not rows:
        return None
    last = rows[-1]
    return SheetReadRow(
        lot=str(last["lot"]),
        sheet_revision=str(last["sheetRevision"]),
        by=str(last.get("by", "unknown")),
        utc=str(last.get("utc", "")),
    )


def assert_may_start_census(
    sheet_dir: "Path | str", review_dir: "Path | str", lot: str,
) -> SheetReadRow:
    """The gate itself. Raises `CensusRefused`, naming the reason, unless the review queue's
    latest `sheetRead` row names the sheet's CURRENT `sheetRevision`. Returns the accepted row on
    success, so a caller that wants to log who cleared the gate does not have to re-read the file.

    Two, and only two, refusal reasons — matching the todo's own verification line
    ("a census against a missing row and against a stale row both refuse"):

    1. **Missing row** — `latest_sheet_read` returns `None`. Nobody has dismissed this lot's sheet
       at all.
    2. **Stale row** — a row exists, but its `sheet_revision` does not match what the sheet on
       disk carries right now. The sheet changed (a new plan, a regenerated corpus, a fixed
       finding) since it was last read, so the old acknowledgment no longer means anything.

    `SheetNotRendered` (no sheet built at all) is allowed to propagate rather than being folded
    into `CensusRefused` — it is a different failure ("nothing to read yet" vs. "read the wrong
    thing"), and collapsing the two would hide which one actually happened.
    """
    current_revision = read_current_sheet_revision(sheet_dir, lot)
    row = latest_sheet_read(review_dir, lot)
    if row is None:
        raise CensusRefused(
            f"lot {lot!r} has no sheetRead row — read the corpus sheet at "
            f"{Path(sheet_dir) / lot / 'sheet.html'}, then dismiss it (`node "
            f"web/fusion-rpg-web/scripts/render-tree-cards.mjs --sheet-read --lot {lot} "
            f"--by <you>`) before starting a census")
    if row.sheet_revision != current_revision:
        raise CensusRefused(
            f"lot {lot!r}'s sheetRead row names revision {row.sheet_revision!r}, but the sheet "
            f"on disk is now {current_revision!r} — the sheet changed since it was last read; "
            f"dismiss the CURRENT sheet before starting a census")
    return row
