"""seedsmith.numerics.tier_bands_io — load/save `tier-bands.v{n}.json`
(spec-numerics.md §3.1: "Constants — tier-bands — data/seed/items/_tuning/tier-bands.v{n}.json").

Kept separate from `model.TierBands` so the dataclass itself stays pure (no I/O), matching the
same "loading is pure, a separate layer does the reading" split as `corpus`/`corpus.loader`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .model import OpWeight, TierBands

TUNING_DIR = Path(__file__).resolve().parents[4] / "data" / "seed" / "items" / "_tuning"
_VERSION_RE = re.compile(r"tier-bands\.v(\d+)\.json$")


def _op_weights_from_json(raw: "dict[str, int]") -> "dict[OpWeight, int]":
    by_value = {op.value: op for op in OpWeight}
    return {by_value[key]: value for key, value in raw.items()}


def load(version: "int | str" = "latest", *, tuning_dir: Path = TUNING_DIR) -> TierBands:
    if version == "latest":
        candidates = sorted(
            (int(m.group(1)), p) for p in tuning_dir.glob("tier-bands.v*.json")
            if (m := _VERSION_RE.search(p.name))
        )
        if not candidates:
            raise FileNotFoundError(f"no tier-bands.v*.json under {tuning_dir}")
        path = candidates[-1][1]
    else:
        path = tuning_dir / f"tier-bands.v{int(version)}.json"

    data = json.loads(path.read_text(encoding="utf-8"))
    return TierBands(
        version=data["version"],
        base_share_permille=data["baseSharePermille"],
        channel_weight_permille=dict(data["channelWeightPermille"]),
        op_weight_permille=_op_weights_from_json(data["opWeightPermille"]),
    )


def read_meta(version: "int | str" = "latest", *, tuning_dir: Path = TUNING_DIR) -> "dict | None":
    """The `_meta` block of a published version, or `None` if that version has none.

    Kept out of `TierBands` deliberately: `_meta` is provenance (who generated it, and the file's
    own "never hand-edit" instruction), never an input to any formula, so the dataclass stays a
    pure numeric surface. `save()` takes it back as an explicit argument — see the note there.
    """
    if version == "latest":
        candidates = sorted(
            (int(m.group(1)), p) for p in tuning_dir.glob("tier-bands.v*.json")
            if (m := _VERSION_RE.search(p.name))
        )
        if not candidates:
            raise FileNotFoundError(f"no tier-bands.v*.json under {tuning_dir}")
        path = candidates[-1][1]
    else:
        path = tuning_dir / f"tier-bands.v{int(version)}.json"
    return json.loads(path.read_text(encoding="utf-8")).get("_meta")


def save(tuning: TierBands, *, tuning_dir: Path = TUNING_DIR,
         meta: "dict | None" = None) -> Path:
    """Write `tier-bands.v{version}.json`. Versions are immutable — publishing over one raises.

    `meta` is written back as the file's `_meta` block. Passing it is how a publish keeps the
    file's own provenance and its "Never hand-edit this file" instruction; dropping it would make
    every published version after v1 silently lose the one line that tells the next reader which
    tool owns the numbers.
    """
    path = tuning_dir / f"tier-bands.v{tuning.version}.json"
    if path.exists():
        raise FileExistsError(f"{path} already exists — versions are immutable once published")
    data = {
        "schemaVersion": 1,
        "version": tuning.version,
        **({"_meta": meta} if meta is not None else {}),
        "baseSharePermille": tuning.base_share_permille,
        "channelWeightPermille": dict(tuning.channel_weight_permille),
        "opWeightPermille": {op.value: w for op, w in tuning.op_weight_permille.items()},
    }
    tuning_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
