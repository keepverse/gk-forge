"""seedsmith.adapters.actions.migrate_retired_description — retire the dead `description` field
from the committed action-seed corpus (owner ruling 2026-10-05).

Mirrors `adapters/trees/nodegen/migrate_retired_atk.py`'s own shape exactly — detect / fix /
apply-to-real-corpus / CLI with `--check` — because this is the same KIND of work: "a mechanical
rewrite over an already-committed corpus, no model call, no prompt involved". Retiring a *channel*
(`progression.bonus.atk`) and retiring a *field* are the same operation on the bytes.

**What is retired and why, verified against the code rather than assumed.** `description` was
emitted only by `description_backfill/` (this directory's former `generate_action_descriptions.py`),
whose entire purpose was to stamp one English sentence onto each committed row. Nothing reads it:

- `FusionRpg.Core.Actions.ActionRow` has no `Description` field — it carries `DescriptionKey` and
  nothing else, and its own doc comment says the key is "never the sentence itself".
- `ActionCorpusBriefJson.Parse` reads `descriptionKey` and never a `description` element; it
  deliberately declines an unknown-key check, so the field was silently discarded.
- `ActionCorpusComposer` forwards only `DescriptionKey`; `ActionCorpusImporter.SamePayload`
  compares only `DescriptionKey`.
- The player-visible sentence resolves through `ItemCard.GrantedActionLines` →
  `LookupString(a.DescriptionKey)` → `__rendered`, and the lookup table is
  `gk-content/content/display/en.json` (`DisplayTemplates.cs`'s `DisplayStringCatalog.ParseMap`).

So the prose the corpus carried was NOT the prose a player read. Measured on the committed tree
before this module existed: 181 rows carry a `description`; of those, 25 `descriptionKey`s exist in
the display catalog and **none** of the 25 matched its catalog row (0 verbatim) — 25 rows
contradicting the text a player actually sees, and 181 unread.

**`_provenance` goes with it, and this is a deliberate part of the same rewrite, not a separate
decision.** Every one of the 180 generated rows carries a `_provenance` block whose `pipeline` is
`seedsmith.adapters.actions.description_backfill` and whose `finding` is
`Content/FieldMissing:actions:action-seed` — a metric registration this change also retires. Leaving
it would leave the corpus claiming a generator produced a field it no longer has. The AUTHORED row
(`authored-basics.json`'s `act.attack`) carries no `_provenance` and is skipped by the `_meta.authored`
check below, so its authored prose is never touched — that file's own `_meta.authored` states "A
generator must never write here".

**`_meta.corpusHash` is deliberately NOT recomputed**, matching `migrate_retired_atk.py`'s own rule
and `description_backfill/derive.py`'s: that field is `ip.corpus_hash` over the FULL cross-file
accepted set at the generating run's time, not a hash of one file's rows, so a mechanical per-file
rewrite cannot compute it correctly and must not pretend to.

**Never a re-generation.** No model is called, no quota is re-drawn, no id is re-picked: this only
removes keys. That is the same "no stage that calls a model is re-run, and nothing else moves"
acceptance the passive-tree migration holds itself to.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from ...pipeline.provenance import PROVENANCE_FIELD

__all__ = [
    "RetiredDescriptionHit", "find_retired_descriptions", "migrate_retired_descriptions",
    "apply_to_action_file", "apply_to_real_corpus", "is_authored_document", "RETIRED_FIELD",
    "RETIRED_PIPELINE", "DEFAULT_ACTIONS_ROOT",
]

#: The retired field. Named once so a reader does not have to trust the prose above.
RETIRED_FIELD = "description"

#: The pipeline name the retired `_provenance` blocks carry. A row whose `_provenance.pipeline` is
#: anything ELSE belongs to a different generator and keeps its block untouched — this module removes
#: its own subsystem's stamp, not every stamp.
RETIRED_PIPELINE = "seedsmith.adapters.actions.description_backfill"

REPO_ROOT = Path(__file__).resolve().parents[5]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from ...workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative


DEFAULT_ACTIONS_ROOT = _owned("data/seed/actions")


@dataclass(frozen=True)
class RetiredDescriptionHit:
    """One committed `action-seed` row this module changes, and why it changed."""

    path: str
    entry_id: str
    drops_description: bool
    drops_provenance: bool
    provenance_pipeline: "str | None"


def is_authored_document(doc: "Mapping[str, Any]") -> bool:
    """True when the FILE declares itself authored via its own `_meta.authored`.

    Read from the document's `_meta`, not from any row, and structurally rather than by naming a
    file — so an authored file that lands later is skipped the moment it appears, which is the
    difference between a contract and a transcription.
    """
    meta = doc.get("_meta")
    return isinstance(meta, dict) and bool(meta.get("authored"))


def find_retired_descriptions(doc: "Mapping[str, Any]") -> "list[RetiredDescriptionHit]":
    """Detect. One hit per entry carrying the retired field, or a `_provenance` block this module's
    own retired pipeline stamped. Empty on an already-migrated (or never-affected) file."""
    hits: "list[RetiredDescriptionHit]" = []
    for row in doc.get("entries", []) or []:
        if not isinstance(row, dict):
            continue
        prov = row.get(PROVENANCE_FIELD)
        pipeline = prov.get("pipeline") if isinstance(prov, dict) else None
        drops_provenance = pipeline == RETIRED_PIPELINE
        drops_description = RETIRED_FIELD in row
        if not (drops_description or drops_provenance):
            continue
        hits.append(RetiredDescriptionHit(
            path="", entry_id=str(row.get("id")),
            drops_description=drops_description, drops_provenance=drops_provenance,
            provenance_pipeline=pipeline))
    return hits


def migrate_retired_descriptions(doc: "Mapping[str, Any]") -> "tuple[dict, list[RetiredDescriptionHit]]":
    """Fix, pure. Returns a NEW doc with the retired field (and this module's own retired
    pipeline's `_provenance`) removed; every other key on the row — `id`, `name`, `descriptionKey`,
    `rungBand`, `atomFamilies`, `motifsUsed`, and every other authored field — is carried through
    BY IDENTITY, never rebuilt. `_meta`, `kind` and `schemaVersion` are untouched.

    An AUTHORED document is returned unchanged with an empty hit list: `authored-basics.json`'s own
    `_meta.authored` says a generator must never write there, and its `description` is authored
    prose, not this module's output. That refusal is structural (a `_meta` check), not a filename.
    """
    if is_authored_document(doc):
        return dict(doc), []

    hits = find_retired_descriptions(doc)
    if not hits:
        return dict(doc), []

    by_id = {hit.entry_id: hit for hit in hits}

    new_entries = []
    for row in doc.get("entries", []) or []:
        if not isinstance(row, dict):
            new_entries.append(row)
            continue
        hit = by_id.get(str(row.get("id")))
        if hit is None:
            new_entries.append(row)
            continue
        kept = {k: v for k, v in row.items()
                if not (k == RETIRED_FIELD or (k == PROVENANCE_FIELD and hit.drops_provenance))}
        new_entries.append(kept)

    return {**dict(doc), "entries": new_entries}, hits


def apply_to_action_file(path: Path) -> "list[RetiredDescriptionHit]":
    """Read one committed `data/seed/actions/*.json`, migrate, and — only if anything changed —
    write back through `json.dumps(..., sort_keys=True, indent=2)` + a trailing newline, the SAME
    writer shape `innate_picker.canonical_dump` uses, so a touched file keeps the corpus's shipped
    formatting exactly and an untouched file is byte-for-byte identical."""
    doc: "dict[str, Any]" = json.loads(path.read_text(encoding="utf-8"))
    new_doc, hits = migrate_retired_descriptions(doc)
    if not hits:
        return hits
    hits = [replace(hit, path=path.name) for hit in hits]
    path.write_text(
        json.dumps(new_doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    return hits


def apply_to_real_corpus(actions_root: "Path | None" = None) -> "dict[str, list[RetiredDescriptionHit]]":
    """Walks every committed `*.json` directly under `actions_root` (the real shipped
    `gk-data/packs/fusion/data/seed/actions/`), fixing each in place. Returns
    `{filename: [hit, ...]}` for every file that had at least one retired field — a clean file is
    simply absent and left byte-for-byte untouched, the same guarantee `apply_to_action_file` gives.

    **Root files only, never `_rounds/`.** `_rounds/` is pre-acceptance scratch that
    `_manifest.json` declares excluded, and `generate_innate_picker`'s own promotion sweep is what
    owns those rows. `authored-basics.json` IS visited and IS read — it is refused by the `_meta`
    check, which is why it is safe to visit it at all."""
    root = actions_root or DEFAULT_ACTIONS_ROOT
    results: "dict[str, list[RetiredDescriptionHit]]" = {}
    for path in sorted(root.glob("*.json")):
        hits = apply_to_action_file(path)
        if hits:
            results[path.name] = hits
    return results


def main(argv=None) -> int:
    """`python -m seedsmith.adapters.actions.migrate_retired_description [--check] [--json]`.

    Default: apply the retirement to the real shipped committed corpus. `--check`: report only, write
    nothing, exit 1 if any retired field is still present, 0 when the corpus is already clean — the
    CI contract `migrate_retired_atk.main` and `migrate_legacy_shards.main` already established."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="report findings only; do not write; exit 1 if any are found")
    parser.add_argument("--json", action="store_true", help="machine-readable result on stdout")
    parser.add_argument("--actions-root", type=Path, default=None,
                        help="override the corpus root (default: the real shipped actions tree)")
    args = parser.parse_args(argv)

    root = args.actions_root or DEFAULT_ACTIONS_ROOT

    if args.check:
        total = 0
        files = 0
        for path in sorted(root.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            for hit in find_retired_descriptions(doc):
                if is_authored_document(doc):
                    continue
                what = []
                if hit.drops_description:
                    what.append("description")
                if hit.drops_provenance:
                    what.append(f"_provenance({hit.provenance_pipeline})")
                print(f"{path.name}[{hit.entry_id}]: {' + '.join(what)}")
                total += 1
            if find_retired_descriptions(doc) and not is_authored_document(doc):
                files += 1
        if args.json:
            print(json.dumps({"status": "clean" if total == 0 else "stale", "files": files,
                              "rows": total}, indent=2))
        if total == 0:
            print("clean — no retired `description` field on any generated action-seed row")
            return 0
        print(f"{total} row(s) across {files} file(s) still carry the retired `description` field")
        return 1

    results = apply_to_real_corpus(root)
    total = sum(len(v) for v in results.values())
    if args.json:
        print(json.dumps({"status": "clean" if total == 0 else "migrated",
                          "files": len(results), "rows": total,
                          "per_file": {k: len(v) for k, v in results.items()}}, indent=2))
    if not results:
        print("clean — no retired `description` field found, nothing written")
        return 0
    for name, hits in results.items():
        print(f"wrote {name}: {len(hits)} row(s) retired")
    print(f"wrote {len(results)} file(s), {total} row(s) retired")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())