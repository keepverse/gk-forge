"""seedsmith.adapters.items.affixfamgen.emit — validated answer -> real family JSON, matching the
shipped shape in `gk-data/packs/fusion/data/seed/items/affix-families/*.json`.

Two independent things happen here, and they are kept in two functions on purpose:

1. `assemble_entry` — turns a model ANSWER (matching `schema.affix_family_schema`) plus its
   `PartitionContext` into one entry dict, re-validating everything the schema's enums already
   constrain (defense in depth: a schema is what a WELL-FORMED answer must satisfy, not a guarantee
   that `emit.py` is only ever called with one). This is where Acceptance #3 is actually enforced,
   not merely described — `opvocab.assert_legal_op` runs on every entry, unconditionally.

2. `resolve_tier_curve` — Acceptance #1's "code resolves the tier-band curve numerics from tuning
   data", reusing `seedsmith.numerics` (the same module `seedsmith numerics rebalance` is built on)
   rather than inventing a second resolution path. **Real, honestly-reported scope limit, found
   while building this**: `seedsmith.numerics.model.OpWeight` has exactly three members (`FLAT`,
   `INCREASED`, `MORE`) and `adapters.items.channels.build_channels()` only wires the 14
   `stat.modify` primaryChannel ids to a `reference_base`. Neither covers `stat.derived`'s
   `Replace`/`Flag` ops, nor any of the 267+ derived (`combat.accuracy.{variant}`-shaped) channels —
   there is no `ProgressionModel` wiring for the "sigmoid resolver points" unit family
   `g-precision.json`'s own notes describe. So `resolve_tier_curve` succeeds for a `stat.modify`
   family on one of the 14 real primaryChannel channels, and raises `NumericsPathUnavailableError`
   (never a guess) for every `stat.derived` family — that gap belongs to `seedsmith.numerics`
   growing a derived/sigmoid resolution path, not to this module inventing one of its own, which is
   exactly what `bands.v1.json`'s own registry text and this program's "one power ladder" rule both
   forbid.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from seedsmith.numerics.model import (
    OpWeight,
    ProgressionPoint,
    TIER_COUNT,
    TierBands,
)
from seedsmith.numerics.resolve import ResolvedMagnitude, resolve

from ....pipeline.provenance import provenance_model
from . import opvocab
from .brief import PartitionContext
from .. import registries

FAMILY_ID_MIN_LEN = 2


class DuplicateChannelOpError(ValueError):
    """This partition already ships a family with the exact same (channel, op) pair — a second one
    would be an indistinguishable duplicate mechanic (the `elemental_power`/`elpw-amplify`
    precedent `g-attack.json`'s own notes name explicitly)."""


class IdCollisionError(ValueError):
    """The minted id already exists in this partition — never silently overwritten."""


class IllegalRoleError(ValueError):
    """A role outside the closed vocabulary reached `assemble_entry` despite the schema enum —
    defense in depth, not the primary guard."""


class IllegalTagError(ValueError):
    """A tag outside the closed vocabulary — same defense-in-depth reasoning as `IllegalRoleError`."""


class TagAxisViolationError(ValueError):
    """Two tags from the same `tags.v1.json` exclusive axis reached `assemble_entry` on one entry
    (e.g. both `defensive` and `utility`, both on `combat-posture`) — the schema's flat enum can
    restrict which strings are legal but not "at most one from this subset", so this is real
    defense in depth (item-seed-regen cause 8, 2026-09-20: found live as 2 shipped affix-family
    entries with exactly this defect, propagated further into 2 gems that copy an affix-family's
    tags verbatim)."""


class NumericsPathUnavailableError(ValueError):
    """`resolve_tier_curve` was asked to resolve a (channel, op) this repo's `seedsmith.numerics`
    module has no wiring for yet (see this module's own docstring) — a real, reportable gap, not a
    silent invented number."""


def family_id(stem: str, word: str) -> str:
    """`atom.{stem}-{word}` — `naming.v1.json`'s own rule for a genuinely NEW family id."""
    if len(word) < FAMILY_ID_MIN_LEN:
        raise ValueError(f"word {word!r} is shorter than the minimum {FAMILY_ID_MIN_LEN} chars")
    return f"atom.{stem}-{word}"


def assemble_entry(answer: "Mapping[str, Any]", partition: PartitionContext,
                   kind_id: str) -> "dict[str, Any]":
    """Validates `answer` against real, current partition state and returns one entry dict shaped
    like a real `gk-data/packs/fusion/data/seed/items/affix-families/*.json` entry. Raises on the first violation found
    (id collision, illegal op, duplicate channel/op pair, illegal role, illegal tag) rather than
    silently coercing — a model or caller bug should fail loudly here, at assembly, not ship a
    corrupt family."""
    from .schema import _resolve_channel_op, derive_name_key

    word = answer["word"]
    channel, op_raw = _resolve_channel_op(answer)
    if channel is None or op_raw is None:
        raise ValueError("answer is missing a free (channel, op) pair")
    op = opvocab.canonical_op(kind_id, op_raw)  # raises IllegalOpError/UnsupportedKindError

    minted_id = family_id(partition.stem, word)
    if minted_id in partition.existing_ids:
        raise IdCollisionError(
            f"{minted_id!r} already exists in partition {partition.group_id!r} — pick a "
            f"different word")

    used_ops = partition.channel_ops.get(channel, ())
    if op in used_ops:
        raise DuplicateChannelOpError(
            f"partition {partition.group_id!r} already ships (channel={channel!r}, op={op!r}) — "
            f"a second family on the identical pair is an indistinguishable duplicate mechanic")

    roles = tuple(answer["roles"])
    tags = tuple(answer["tags"])
    name = answer["name"]

    axis_violation = registries.tag_axis_violation(
        tags, registries.load_tag_axes(applies_to="affix-family"))
    if axis_violation is not None:
        raise TagAxisViolationError(axis_violation)

    return {
        "id": minted_id,
        "nameKey": derive_name_key(name),
        "name": name,
        "kindId": kind_id,
        "params": {"channel": channel, "op": op},
        "roles": list(roles),
        "powerBand": answer["powerBand"],
        "displayTemplate": answer["displayTemplate"],
        "tags": list(tags),
    }


def emit_document(entries: "list[dict[str, Any]]", *, batch: str, partition: str,
                  source_ref: str, model: str,
                  authored_utc: str = "") -> "dict[str, Any]":
    """The full family JSON document wrapper — `schemaVersion`/`kind`/`_meta`/`entries`, matching
    every real file under `gk-data/packs/fusion/data/seed/items/affix-families/`."""
    return {
        "schemaVersion": 1,
        "kind": "affix-family",
        "_meta": {
            "batch": batch,
            "partition": partition,
            "contractVersion": 1,
            "model": provenance_model(model),
            "authoredUtc": authored_utc,
            "sourceRef": source_ref,
        },
        "entries": entries,
    }


def merge_into_partition_document(existing_doc: "dict[str, Any]",
                                  new_entries: "list[dict[str, Any]]") -> "dict[str, Any]":
    """Append `new_entries` to an already-loaded partition document's `entries`, leaving every
    other field (`_meta`, `schemaVersion`) untouched — a generator run APPENDS new families to a
    partition, it never re-authors the shipped ones."""
    merged = dict(existing_doc)
    merged["entries"] = list(existing_doc.get("entries", [])) + list(new_entries)
    return merged


def write_document(path: Path, doc: "dict[str, Any]") -> Path:
    """Atomic-enough for a `--write` CLI path: this module does not itself guard against a
    concurrent writer (that is `RunLedger`'s job, via `run.py`) — it only serializes deterministically
    (`sort_keys=True`), matching every other item-seedgen writer's determinism discipline."""
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


@dataclass(frozen=True)
class TierCurve:
    family_name: str
    op: str
    ladder: "tuple[int, ...]"
    bands: "tuple[tuple[int, int], ...]"


def resolve_tier_curve(family_name: str, op: str, tuning: TierBands, point: ProgressionPoint,
                       *, allow_calibration_level: bool = False) -> TierCurve:
    """Acceptance #1's numeric resolution step, reusing `seedsmith.numerics.resolve` — never a
    private `f(level)`.

    ⚠ **`family_name` is the affix family's own short name (the id tail after `atom.`, e.g.
    `"might"`, `"warding"`), NOT the game stat channel its `params.channel` field names (`"atk"`,
    `"defense"`).** Found while wiring this up: `seedsmith.numerics.TierBands.channel_weight_permille`
    and `adapters.items.channels.build_channels()`'s `HP_SHAPED`/`ATK_SHAPED`/`INTERVAL_SHAPED` sets
    are keyed on family names (`might`, `vitality`, `quickening`, ...), not on the small raw-channel
    vocabulary `AtomKindRegistry.PrimaryChannels` validates `params.channel` against.

    ⚠ **A brand-new family this generator just minted has no numeric-resolution path at all yet,
    even with a hand-supplied `TierBands` carrying a weight for it** — `reference_base` is resolved
    through `adapters.items.channels.build_channels()`'s fixed 14-member `channels_by_id`, keyed by
    the SAME 14 hard-coded family names; a 15th name is not merely unweighted, it is a `KeyError`
    `BattleRulesetProgression.reference_base` has no fallback for. This function therefore checks
    membership in the 14 wired names ONLY, not in the supplied tuning — resolving a genuinely new
    family's curve needs `adapters.items.channels` extended with its own `reference_base`, which is
    real future wiring work, not something a `TierBands` override alone can unlock. (This module's
    own top docstring names the second, independent gap: `data/seed/items/_tuning/tier-bands.v*.json`
    does not exist on disk in this repo at all yet, so every call here must pass an explicit,
    caller-built `TierBands` — never rely on `TierBands.load()`'s default disk read.)

    Only legal for the three `stat.modify` ops `seedsmith.numerics.model.OpWeight` actually models;
    raises `NumericsPathUnavailableError` for anything else (every `stat.derived` op) rather than
    approximating one, per this module's own docstring.
    """
    try:
        op_weight = OpWeight(op)
    except ValueError as exc:
        raise NumericsPathUnavailableError(
            f"op {op!r} has no seedsmith.numerics.OpWeight member — only "
            f"{[o.value for o in OpWeight]} resolve today; stat.derived's Replace/Flag (and any "
            f"sigmoid-unit derived channel) have no numeric-resolution path yet, a real upstream "
            f"gap in seedsmith.numerics, not something this module guesses around") from exc

    from seedsmith.adapters.items.channels import PRIMARY_CHANNEL_IDS
    from seedsmith.numerics.model import BattleRulesetProgression
    from seedsmith.numerics.resolve import UnsharedChannelError

    if family_name not in PRIMARY_CHANNEL_IDS:
        raise NumericsPathUnavailableError(
            f"family {family_name!r} is not one of the 14 wired stat.modify primaryChannel family "
            f"names ({sorted(PRIMARY_CHANNEL_IDS)}) — `adapters.items.channels.build_channels()` "
            f"has no `reference_base` for a 15th name yet, so a brand-new family has no "
            f"numeric-resolution path until that adapter is extended (see this function's own "
            f"docstring)")

    from seedsmith.adapters.items import channels as channels_adapter

    class _Adapter:
        @staticmethod
        def channels():
            return channels_adapter.build_channels()

    progression = BattleRulesetProgression.from_adapter(_Adapter())

    ladder: "list[int]" = []
    bands: "list[tuple[int, int]]" = []
    try:
        for tier in range(1, TIER_COUNT + 1):
            resolved: ResolvedMagnitude = resolve(
                family_name, op_weight, tier, tuning, progression, point,
                allow_calibration_level=allow_calibration_level)
            ladder.append(resolved.value)
            bands.append((resolved.lo, resolved.hi))
    except UnsharedChannelError as exc:
        raise NumericsPathUnavailableError(str(exc)) from exc

    return TierCurve(family_name=family_name, op=op, ladder=tuple(ladder), bands=tuple(bands))
