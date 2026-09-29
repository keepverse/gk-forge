"""seedsmith.adapters.items.defaults — machine-local items-generate defaults from `.env`.

Spec-foundation §7.3: every flag has a config equivalent; the flag wins. LLM transport keys live
in `pipeline.llm_caller`; this module owns the items-only production-tree / out-dir knobs so an
operator can run `items generate --kind set --write` or `items fill` without retyping
`--out-dir` / `--allow-production-tree` on every invocation.
"""
from __future__ import annotations

from pathlib import Path

from ...pipeline.llm_caller import read_dotenv_values
from .setgen.seedfile import ITEM_SEED_ROOT, PRODUCTION_KIND_DIRS

#: Truthy spellings for `SEEDSMITH_ALLOW_PRODUCTION_TREE` (case-insensitive).
_TRUTHY = frozenset({"1", "true", "yes", "on"})

#: Production write targets for kinds that use `--out-dir` (set/charm/combination).
PRODUCTION_OUT_DIRS: "dict[str, Path]" = {
    **PRODUCTION_KIND_DIRS,
    "combination": ITEM_SEED_ROOT / "combinations",
}

#: Dependency-ordered kind walk for `items fill` — mirrors item-seedgen-map.md §5 phases.
FILL_KIND_ORDER: "tuple[str, ...]" = (
    "affix-family",
    "material",
    "gem",
    "consumable",
    "enhancement-milestone",
    "base-type",
    "set",
    "charm",
    "recipe",
    "combination",
    "drop-table",
)


def allow_production_tree(*, dotenv_path: Path | None = None,
                          cli_allow: bool = False) -> bool:
    """True when the CLI flag is set or `.env` has `SEEDSMITH_ALLOW_PRODUCTION_TREE=1`."""
    if cli_allow:
        return True
    raw = read_dotenv_values(dotenv_path).get("SEEDSMITH_ALLOW_PRODUCTION_TREE", "")
    return raw.strip().lower() in _TRUTHY


def default_out_dir(kind: str, *, dotenv_path: Path | None = None) -> str:
    """Production out-dir for `kind`, or `SEEDSMITH_ITEMS_OUT_DIR` when set (applies to all
    out-dir kinds). Empty string when the kind has no production out-dir (passthrough gens write
    in-module)."""
    values = read_dotenv_values(dotenv_path)
    override = values.get("SEEDSMITH_ITEMS_OUT_DIR", "").strip()
    if override:
        return override
    path = PRODUCTION_OUT_DIRS.get(kind)
    return str(path) if path is not None else ""


def resolve_out_dir_arg(kind: str, cli_out_dir: str, *, allow_production: bool,
                        dotenv_path: Path | None = None) -> str:
    """CLI `--out-dir` wins; else production default when allow-production is on."""
    if (cli_out_dir or "").strip():
        value = cli_out_dir.strip()
        # Operators commonly invoke the module from gk-forge/tools/seedsmith.  A production-relative
        # path must still point at the repository's data tree, not tools/seedsmith/data.  Keep
        # arbitrary scratch paths relative to the caller; only normalize the documented tree.
        if allow_production:
            candidate = Path(value)
            parts = [part.casefold() for part in candidate.parts]
            marker = ["data", "seed", "items"]
            if not candidate.is_absolute() and parts[:3] == marker:
                return str(ITEM_SEED_ROOT.joinpath(*candidate.parts[3:]))
        return value
    if allow_production:
        return default_out_dir(kind, dotenv_path=dotenv_path)
    return ""
