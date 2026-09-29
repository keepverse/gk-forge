"""The three roots a path is resolved from: content, core, workspace.

Resolver contract: tasks/keepverse-split-plan.md "Resolver contract". Before the Keepverse split all
three are the legacy repo root. After it, content is a gk-data pack (which mirrors the legacy repo
layout, so `gk-data/packs/fusion/data/seed/...` literals stay valid), core is gk-core, and workspace is the Keepverse root
that holds docs/ and tasks/.

Order: the KEEPVERSE_*_ROOT environment override wins; otherwise walk up from `start` (default: this
file) to the first legacy repo (FusionRpg.slnx next to gk-data/packs/fusion/data/seed/) or Keepverse workspace (gk-core/
next to gk-data/). Nothing found raises; a root is never guessed.

A copy of this module lives at gk-core/scripts/lib/keepverse_roots.py; keep the two identical.
"""

from __future__ import annotations

import os
from pathlib import Path

PACK_ENV = "KEEPVERSE_PACK"
DEFAULT_PACK = "fusion"  # structural: the pack the current corpus ships as (decision D7)


class RootNotFound(RuntimeError):
    pass


def _layout(start: Path) -> tuple[str, Path]:
    here = start.resolve()
    for d in (here, *here.parents):
        if (d / "FusionRpg.slnx").is_file() and (d / "data" / "seed").is_dir():
            return "legacy", d
        if (d / "gk-core").is_dir() and (d / "gk-data").is_dir():
            return "workspace", d
    raise RootNotFound(f"no legacy repo or Keepverse workspace above {here}")


def _start(start: Path | None) -> Path:
    return Path(start) if start is not None else Path(__file__).parent


def _env(name: str) -> Path | None:
    v = os.environ.get(name)
    return Path(v) if v else None


def content_root(start: Path | None = None) -> Path:
    """Root that repo-relative content paths (gk-data/packs/fusion/data/seed, gk-data/packs/fusion/data/generated, content) resolve from."""
    if (p := _env("KEEPVERSE_CONTENT_ROOT")) is not None:
        return p
    kind, d = _layout(_start(start))
    if kind == "legacy":
        return d
    pack = d / "gk-data" / "packs" / os.environ.get(PACK_ENV, DEFAULT_PACK)
    if not pack.is_dir():
        raise RootNotFound(f"content pack {pack} does not exist")
    return pack


def core_root(start: Path | None = None) -> Path:
    """Root of the engine repo: src/, tests/, gk-core/data/tuning/."""
    if (p := _env("KEEPVERSE_CORE_ROOT")) is not None:
        return p
    kind, d = _layout(_start(start))
    return d if kind == "legacy" else d / "gk-core"


def workspace_root(start: Path | None = None) -> Path:
    """Root holding docs/ and tasks/."""
    if (p := _env("KEEPVERSE_WORKSPACE_ROOT")) is not None:
        return p
    return _layout(_start(start))[1]
