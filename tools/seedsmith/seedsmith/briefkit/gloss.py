"""The motif gloss registry and its one lookup (spec-gloss-registry.md, map row 3).

**The defect this exists for.** The Delve event brief injects raw Chinese motifs and tells the model
"Use at least one of the listed motifs" (`adapters/dungeon/briefs.py:324`), and the leaked words in the
committed corpus are exactly those motifs (53 of 54 events). `gloss-fill` produces one target-language
gloss per motif; this module is the data contract and the lookup every brief reads.

**The lookup refuses; it never passes a raw token through.** A caller that wants to go ahead without a
gloss has no API to do it with: `GlossTable.gloss` and `gloss_all` raise `GlossMissing`, which lists
EVERY unglossed motif in the request (not the first) and subclasses `BriefRefusal` — so a brief builder
that already refuses on a citation refuses on this too.

**Every row is generated output.** Rows are written only by `gloss-fill`'s commit step after review, and
a rejected gloss is regenerated with the reviewer's reason named, never hand-typed (`spec-gloss-fill.md`
§4). This module commits the file with its header and an empty `glosses` object: until `gloss-fill` runs,
every lookup refuses, which is the honest state.

Read fresh on every call, never transcribed, and `gloss.maxWords` is read from the narrative generation
budget (`gk-data/packs/fusion/data/seed/narrative/_plan/budget.v1.json`), never a code constant.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from string import ascii_letters
from typing import Any, Iterable, Mapping, Sequence

from ..workspace_roots import content_root
from .render import BriefRefusal

__all__ = [
    "DEFAULT_LOCALE",
    "Sense",
    "SENSE",
    "GlossRow",
    "GlossTable",
    "GlossMissing",
    "load_glosses",
    "coverage_report",
    "GLOSS_ALLOWED_CHARS",
]

DEFAULT_LOCALE = "en"

_REGISTRY_REL = "data/seed/narrative/_registry/motif-glosses.{locale}.v1.json"
_BUDGET_REL = "data/seed/narrative/_plan/budget.v1.json"
_SOURCE_REGISTRY_REL = "data/seed/creatures/_registry/motifs.v1.json"

_TOP_KEYS = frozenset({"schemaVersion", "registryVersion", "locale", "source", "glosses"})
_SOURCE_KEYS = frozenset({"registry", "registryVersion"})
_ROW_KEYS = frozenset({"gloss", "sense", "model", "promptVersion"})

#: A gloss is a short English phrase, so a strict allow-list is enough here and this module does not
#: need `script-check`'s general classifier (spec §3). Anything else — a digit, a CJK character, a
#: fullwidth form, a symbol — is refused by name.
GLOSS_ALLOWED_CHARS = frozenset(ascii_letters) | frozenset(" -'")

#: `motif-glosses.<code>.v1.json` — the file name carries the locale too, so a copy under the wrong
#: name cannot silently serve the wrong language.
_FILE_NAME = re.compile(r"^motif-glosses\.([a-z]{2,3})\.v\d+\.json$")


class Sense(Enum):
    """The kind of meaning a gloss carries — `gloss-fill`'s closed enum, shared as a declaration. It
    stratifies the review sample; it is NOT a part-of-speech tag for grammar. `none` means the sense
    could not be placed and is a review signal, not an error."""

    CONCRETE = "concrete"
    ABSTRACT = "abstract"
    ACTION = "action"
    QUALITY = "quality"
    NONE = "none"


SENSE: "tuple[str, ...]" = tuple(s.value for s in Sense)


class GlossMissing(BriefRefusal):
    """Raised with EVERY unglossed motif in the request.

    A subclass of `BriefRefusal`, so a brief builder that already refuses on a citation refuses on this
    too. `motifs` is the sorted, de-duplicated list; the message names them all, because a repair
    prompt that fixes one motif at a time costs one round trip per motif."""

    def __init__(self, motifs: "Iterable[str]", *, locale: str = DEFAULT_LOCALE) -> None:
        self.motifs: "tuple[str, ...]" = tuple(sorted(dict.fromkeys(motifs)))
        super().__init__(
            f"{len(self.motifs)} motif(s) have no {locale} gloss: {', '.join(self.motifs)} — run "
            f"gloss-fill (a brief never receives a raw motif)")


@dataclass(frozen=True)
class GlossRow:
    """One registry row. `spec-gloss-fill.md` owns the shape; `model`/`promptVersion` are required so a
    bad batch is scoped by version rather than by eyeballing dates."""

    key: str
    gloss: str
    sense: Sense
    model: str
    prompt_version: str


@dataclass(frozen=True)
class GlossTable:
    """A loaded, validated table. `rows` is read-only by convention: nothing in this package writes it."""

    locale: str
    registry_version: int
    source_registry: str
    source_registry_version: int
    rows: "Mapping[str, GlossRow]"

    def gloss(self, motif: str) -> str:
        """The gloss for `motif`, or `GlossMissing` naming it. Never the motif, never a placeholder."""
        row = self.rows.get(motif)
        if row is None:
            raise GlossMissing([motif], locale=self.locale)
        return row.gloss

    def gloss_all(self, motifs: "Sequence[str]") -> "tuple[str, ...]":
        """Order-preserving glosses for `motifs`; raises once, listing every missing one."""
        missing = self.missing(motifs)
        if missing:
            raise GlossMissing(missing, locale=self.locale)
        return tuple(self.rows[motif].gloss for motif in motifs)

    def missing(self, motifs: "Iterable[str]") -> "tuple[str, ...]":
        """The requested motifs with no row, sorted and de-duplicated — a reading, for reports."""
        return tuple(sorted(dict.fromkeys(m for m in motifs if m not in self.rows)))

    def senses(self) -> "tuple[str, ...]":
        return tuple(sorted({row.sense.value for row in self.rows.values()}))


def _refuse(message: str) -> "BriefRefusal":
    return BriefRefusal(message)


def _read_json(path: Path, label: str) -> "dict[str, Any]":
    if not path.exists():
        raise _refuse(f"{label} does not exist: {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise _refuse(f"{label} must be a JSON object: {path}")
    return doc


def _max_words(budget_path: "Path | None") -> int:
    """Read `gloss.maxWords` from the budget file. There is deliberately no fallback constant: a bound
    that no file owns is exactly the code-owned tunable this project forbids."""
    path = budget_path or (content_root() / _BUDGET_REL)
    doc = _read_json(path, "narrative budget")
    block = doc.get("gloss")
    if not isinstance(block, dict) or "maxWords" not in block:
        raise _refuse(f"{path}: missing the gloss block with its maxWords row")
    value = block["maxWords"]
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _refuse(f"{path}: gloss.maxWords must be a positive integer, got {value!r}")
    return value


def _check_keys(doc: "Mapping[str, Any]", allowed: "frozenset[str]", label: str) -> None:
    unknown = sorted(set(doc) - allowed)
    if unknown:
        raise _refuse(f"{label} has unknown key(s) {unknown} — allowed: {sorted(allowed)}")
    missing = sorted(allowed - set(doc))
    if missing:
        raise _refuse(f"{label} is missing required key(s) {missing}")


def _validate_gloss(motif: str, gloss: Any, max_words: int, label: str) -> str:
    if not isinstance(gloss, str) or not gloss.strip():
        raise _refuse(f"{label}: gloss for motif {motif!r} is empty")
    if gloss != gloss.strip():
        raise _refuse(f"{label}: gloss for motif {motif!r} has leading/trailing whitespace")
    digit = next((c for c in gloss if c.isdigit()), None)
    if digit is not None:
        raise _refuse(f"{label}: gloss for motif {motif!r} contains a digit ({digit!r})")
    bad = next((c for c in gloss if c not in GLOSS_ALLOWED_CHARS), None)
    if bad is not None:
        raise _refuse(f"{label}: gloss for motif {motif!r} contains {bad!r} (U+{ord(bad):04X}), outside "
                      f"the allowed gloss characters (letters, space, hyphen, apostrophe)")
    words = len(gloss.split())
    if words > max_words:
        raise _refuse(f"{label}: gloss for motif {motif!r} is {words} words, over gloss.maxWords="
                      f"{max_words}")
    if gloss == motif:
        raise _refuse(f"{label}: gloss for motif {motif!r} is the motif itself — a raw token passed "
                      f"through, never a translation")
    return gloss


def load_glosses(locale: str = DEFAULT_LOCALE, path: "Path | None" = None, *,
                 budget_path: "Path | None" = None) -> GlossTable:
    """Load and validate the gloss registry for `locale`.

    Refuses, naming the offending key, on: an unknown or missing key; a `locale` that differs from the
    requested one or from the file name's own code; an empty, digit-bearing, foreign-script or
    over-`maxWords` gloss; a `sense` outside the closed enum; an empty `model`/`promptVersion`; and a
    gloss equal to its own motif. A moved `source.registryVersion` is NOT a refusal — it makes the table
    *stale*, a reading `coverage_report` prints.
    """
    registry_path = path or (content_root() / _REGISTRY_REL.format(locale=locale))
    doc = _read_json(registry_path, "motif gloss registry")
    label = str(registry_path)
    _check_keys(doc, _TOP_KEYS, label)

    declared = doc["locale"]
    if declared != locale:
        raise _refuse(f"{label}: locale {declared!r} does not match the requested locale {locale!r}")
    match = _FILE_NAME.match(registry_path.name)
    if match and match.group(1) != declared:
        raise _refuse(f"{label}: file name says locale {match.group(1)!r} but the document says "
                      f"{declared!r}")

    source = doc["source"]
    if not isinstance(source, dict):
        raise _refuse(f"{label}: source must be an object")
    _check_keys(source, _SOURCE_KEYS, f"{label}: source")
    if not isinstance(source["registry"], str) or not source["registry"]:
        raise _refuse(f"{label}: source.registry must be a non-empty path string")
    if not isinstance(source["registryVersion"], int) or isinstance(source["registryVersion"], bool):
        raise _refuse(f"{label}: source.registryVersion must be an integer")
    if not isinstance(doc["registryVersion"], int) or isinstance(doc["registryVersion"], bool):
        raise _refuse(f"{label}: registryVersion must be an integer")

    glosses = doc["glosses"]
    if not isinstance(glosses, dict):
        raise _refuse(f"{label}: glosses must be an object keyed by motif")

    max_words = _max_words(budget_path)
    rows: "dict[str, GlossRow]" = {}
    for motif, row in glosses.items():
        row_label = f"{label}: row {motif!r}"
        if not isinstance(row, dict):
            raise _refuse(f"{row_label} must be an object")
        _check_keys(row, _ROW_KEYS, row_label)
        gloss = _validate_gloss(motif, row["gloss"], max_words, row_label)
        try:
            sense = Sense(row["sense"])
        except ValueError:
            raise _refuse(f"{row_label}: sense {row['sense']!r} is outside the closed enum {list(SENSE)}"
                          ) from None
        for key in ("model", "promptVersion"):
            if not isinstance(row[key], str) or not row[key].strip():
                raise _refuse(f"{row_label}: {key} is empty — provenance is required")
        rows[motif] = GlossRow(key=motif, gloss=gloss, sense=sense, model=row["model"],
                               prompt_version=row["promptVersion"])

    return GlossTable(locale=declared, registry_version=doc["registryVersion"],
                      source_registry=source["registry"],
                      source_registry_version=source["registryVersion"], rows=rows)


def _load_source_motifs(source_path: "Path | None") -> "tuple[list[str], int]":
    path = source_path or (content_root() / _SOURCE_REGISTRY_REL)
    doc = _read_json(path, "creature motif registry")
    motifs = doc.get("motifs")
    if not isinstance(motifs, list):
        raise _refuse(f"{path}: motifs must be a list")
    version = doc.get("registryVersion")
    return [m for m in motifs if isinstance(m, str)], version if isinstance(version, int) else 0


def coverage_report(table: GlossTable, *, source_motifs: "Sequence[str] | None" = None,
                    source_path: "Path | None" = None) -> "dict[str, Any]":
    """The readings this registry owes a reviewer. Nothing here is a gate.

    `orphans` are rows whose motif is no longer in the source list (kept, because a motif can return);
    `unglossed` is the work `gloss-fill` still owes; `sourceVersionTrails` says whether the table was
    filled against an older motif registry than the one on disk.
    """
    if source_motifs is None:
        live, live_version = _load_source_motifs(source_path)
    else:
        live, live_version = list(source_motifs), table.source_registry_version
    rows = set(table.rows)
    source = set(live)
    return {
        "locale": table.locale,
        "rows": len(rows),
        "orphans": sorted(rows - source),
        "unglossed": sorted(source - rows),
        "registryVersion": table.registry_version,
        "sourceRegistryVersion": table.source_registry_version,
        "liveSourceRegistryVersion": live_version,
        "sourceVersionTrails": live_version > table.source_registry_version,
    }
