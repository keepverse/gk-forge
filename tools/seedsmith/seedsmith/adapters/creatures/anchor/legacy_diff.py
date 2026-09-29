"""The legacy diff (creature-seed module 8, spec-anchor-emit.md §6, T2.7) — compares the new
re-derivation against what the old C# generator (`CreatureSpeciesCatalog.Generated.cs`) assigned for
the shipped 84 species, field by field. **A disagreement is not automatically wrong** — the old
generator assigned elements by a hash, not by reading anything — this is the sanity check
available before 820 more species are trusted, not a correctness gate.

Deliberately does not read `CreatureSpeciesCatalog.Generated.cs` itself here: that is a C# source
file, and parsing it from Python is exactly the kind of fragile, unreviewable coupling this
program avoids elsewhere (`no SQL in tools/`, `canonical bytes only`). The legacy side is passed
in as plain dicts — a small future export step (or a one-off read) produces those, this module
only computes and reports the comparison.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

#: The fields this diff actually compares — the ones both the old generator and the new anchor
#: independently assign. Everything else (attackTempo, reach, kit-shape fields, ...) has no old
#: counterpart at all; comparing them would report 100% disagreement against nothing.
COMPARED_FIELDS = ("elementPrimary", "deployMode", "acquisition", "variants")


@dataclass(frozen=True)
class FieldAgreement:
    field: str
    total: int
    agree: int
    disagree: int

    @property
    def agree_rate(self) -> float:
        return self.agree / self.total if self.total else 0.0


def _values_agree(a: Any, b: Any) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return sorted(a) == sorted(b)
    return a == b


def diff_legacy(
    new_anchors: Sequence[Mapping[str, Any]],
    legacy_entries: Sequence[Mapping[str, Any]],
    *, legacy_id_key: str = "id", new_id_key: str = "speciesId",
) -> "dict[str, FieldAgreement]":
    """Field-by-field agreement over the species present in BOTH sets — a species only the new
    run covers (820 of them) contributes nothing here by construction; that is correct, not a
    gap, since there is no legacy value to compare against.
    """
    legacy_by_id = {e[legacy_id_key]: e for e in legacy_entries}
    report: "dict[str, FieldAgreement]" = {}

    for field in COMPARED_FIELDS:
        total = agree = 0
        for anchor in new_anchors:
            sid = anchor.get(new_id_key)
            legacy = legacy_by_id.get(sid)
            if legacy is None or field not in legacy:
                continue
            total += 1
            if _values_agree(anchor.get(field), legacy.get(field)):
                agree += 1
        report[field] = FieldAgreement(field=field, total=total, agree=agree, disagree=total - agree)

    return report


def format_report(report: Mapping[str, FieldAgreement]) -> str:
    lines = ["legacy diff — field agreement over species present in both sets:"]
    for field, fa in report.items():
        lines.append(f"  {field}: {fa.agree}/{fa.total} agree ({fa.agree_rate * 100:.1f}%), {fa.disagree} disagree")
    return "\n".join(lines)
