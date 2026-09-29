"""The gloss commit step (spec-gloss-fill.md §4, NS15).

Two rules shape it:

- **Only accepted rows, and only once every rejection has an accepted replacement.** The reviewer's
  verdicts are append-only; a rejected motif whose replacement has not been accepted yet makes the commit
  REFUSE rather than write a registry that silently drops an idea.
- **Byte-identical on rerun.** Rows go out in sorted key order with a canonical dump and no timestamp, so a
  second commit of the same input writes the same bytes (the registry is a tracked, reviewed artifact, and
  a spurious diff is noise a reviewer cannot distinguish from a real change).

A rejected gloss is never hand-typed: its reviewer reason is what the next run's brief names
(`regeneration_requests`), and every row carries the generator provenance the registry loader requires.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ....workspace_roots import content_root

__all__ = ["REGISTRY_REL", "regeneration_requests", "canonical_document", "review_sample",
           "commit_glosses"]

REGISTRY_REL = "data/seed/narrative/_registry/motif-glosses.en.v1.json"


def _registry_path(registry_path: "Path | str | None") -> Path:
    if registry_path is not None:
        return Path(registry_path)
    return content_root() / REGISTRY_REL


def regeneration_requests(verdicts: "Mapping[str, Sequence[Mapping[str, str]]]") -> "dict[str, str]":
    """motif -> the reason its latest verdict was a rejection. These are the rows a rerun must regenerate
    first, and the reason is named in that motif's brief (`spec-quality-gates.md` §5: name the defect)."""
    requests: "dict[str, str]" = {}
    for motif, history in verdicts.items():
        latest = history[-1] if history else None
        if latest and latest.get("verdict") == "reject":
            requests[motif] = str(latest.get("reason") or "")
    return requests


def canonical_document(header: Mapping[str, Any], rows: "Mapping[str, Mapping[str, Any]]") -> bytes:
    """The registry file's bytes: sorted `glosses` keys, two-space indent, CJK unescaped, one trailing
    newline, NO timestamp — so the same rows always produce the same bytes."""
    document = {**header, "glosses": {motif: dict(rows[motif]) for motif in sorted(rows)}}
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def review_sample(rows: "Mapping[str, Mapping[str, Any]]", *, sample_size: int,
                  run_id: str) -> "dict[str, list]":
    """The reviewer's sitting: core `stratified_sample` over the SENSE, seeded from the run id, so the
    same run always shows the same rows. One per non-empty sense stratum is guaranteed by the sampler
    itself; the rest are apportioned by stratum size."""
    from ....sampling import stratified_sample

    by_sense: "dict[str, list]" = {}
    for motif in sorted(rows):
        by_sense.setdefault(str(rows[motif].get("sense") or "none"), []).append(motif)
    return stratified_sample(by_sense, sample_size, metric_id="motif-gloss", revision=run_id)


def commit_glosses(rows: "Mapping[str, Mapping[str, Any]]", *, model: str, prompt_version: str,
                   verdicts: "Mapping[str, Sequence[Mapping[str, str]]] | None" = None,
                   registry_path: "Path | str | None" = None) -> Path:
    """Write the accepted (and unsampled) rows into the registry.

    Refuses when a rejected motif has no accepted replacement among `rows`. `model` and `prompt_version`
    are stamped on every row that does not already carry them, so provenance records what ran.
    """
    outstanding = sorted(motif for motif in regeneration_requests(verdicts or {}) if motif not in rows)
    if outstanding:
        raise ValueError(
            f"refusing to commit: {len(outstanding)} rejected gloss(es) have no accepted replacement yet "
            f"({outstanding}) — regenerate them with their reason named first")

    path = _registry_path(registry_path)
    header = json.loads(path.read_text(encoding="utf-8"))
    stamped: "dict[str, dict]" = {}
    for motif, row in rows.items():
        stamped[motif] = {
            "gloss": row["gloss"], "sense": row["sense"],
            "model": row.get("model") or model,
            "promptVersion": row.get("promptVersion") or prompt_version,
        }
    path.write_bytes(canonical_document(header, stamped))
    return path
