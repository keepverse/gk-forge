"""seedsmith.adapters.items.affixfamgen.run — wires `pipeline.run_ledger.RunLedger` for
Acceptance #4 ("Output through generator-harness's ledger") and the spec's own testing strategy
("Harness tests: resume/reconcile/overwrite").

One ledger row per `FamilyRequest` (`groupId:kindId:word`), matching the `<module-id>.ledger.json`
convention `setgen`'s own `set-charm-gen.ledger.json` and this program's harness spec both use.

**Reconcile, not just resume.** `is_valid` re-checks the REAL, current partition file on disk —
mirroring `run_ledger.RunLedger.plan`'s own doc ("a corpus a hand edit broke out of band gets
reconciled on the next run rather than silently skipped forever"): a ledger row claiming a family
was written is only trusted if that family's minted id still exists in
`data/seed/items/affix-families/g-<group>.json` right now.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from seedsmith.pipeline.run_ledger import RunLedger

from . import brief as brief_mod
from . import emit
from . import schema as schema_mod

REPO_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_LEDGER = REPO_ROOT / "data" / "seed" / "items" / "_runs" / "affix-families-gen.ledger.json"


@dataclass(frozen=True)
class FamilyRequest:
    """One unit of work: author one new family, on one partition, of one declared kind."""

    group_id: str
    kind_id: str
    word: str

    @property
    def subject_id(self) -> str:
        return f"{self.group_id}:{self.kind_id}:{self.word}"


@dataclass(frozen=True)
class PlanResult:
    to_generate: "tuple[FamilyRequest, ...]"
    already_done: "tuple[str, ...]"

    @property
    def complete(self) -> bool:
        return not self.to_generate


def _minted_id_for(request: FamilyRequest, *, families_dir: "Path | None") -> "str | None":
    """The id this request would mint, or `None` if its partition has no shipped file to reconcile
    against yet (a brand-new partition — nothing to check the ledger's claim against)."""
    try:
        stem = brief_mod.group_stem(request.group_id)
    except brief_mod.UnknownGroupError:
        return None
    return emit.family_id(stem, request.word)


def plan_requests(requests: "Sequence[FamilyRequest]", ledger: RunLedger, *,
                  families_dir: "Path | None" = None) -> PlanResult:
    """Resume + reconcile over `requests`: a request already marked done in the ledger AND whose
    minted id is still really present in its partition file is skipped; everything else — never
    attempted, or reconciled away because the corpus no longer agrees with the ledger — is
    returned in `to_generate`, in the same order `requests` was given."""
    by_subject = {r.subject_id: r for r in requests}

    def is_valid(subject_id: str, entry: "dict") -> bool:
        request = by_subject.get(subject_id)
        if request is None:
            return True  # not part of THIS plan call; nothing here to reconcile against
        minted_id = entry.get("mintedId")
        if not minted_id:
            return False
        try:
            ctx = brief_mod.load_partition_context(request.group_id, families_dir=families_dir)
        except FileNotFoundError:
            return False
        return minted_id in ctx.existing_ids

    subject_ids = [r.subject_id for r in requests]
    needing = ledger.plan(subject_ids, is_valid=is_valid)
    needing_set = set(needing)
    already_done = tuple(sid for sid in subject_ids if sid not in needing_set)
    return PlanResult(
        to_generate=tuple(by_subject[sid] for sid in needing),
        already_done=already_done,
    )


def mark_family_written(ledger: RunLedger, request: FamilyRequest, minted_id: str) -> None:
    """Records the ledger row `plan_requests`'s own `is_valid` reconciles against. Deliberately a
    thin, explicit wrapper (not a bare `ledger.mark_done` call at the caller site) so the entry
    shape — `mintedId`, `groupId`, `kindId` — is defined in exactly one place."""
    ledger.mark_done(request.subject_id, {
        "mintedId": minted_id, "groupId": request.group_id, "kindId": request.kind_id,
    })


def force_requests(ledger: RunLedger, requests: "Sequence[FamilyRequest]",
                   *, scope: str) -> "list[FamilyRequest]":
    """The real `--overwrite` path: bypasses the ledger's own resume/reconcile state for the named
    requests (or every request, with the literal `scope="all"`), per `RunLedger.force`'s own
    "a typo'd --overwrite fails loudly" contract."""
    by_subject = {r.subject_id: r for r in requests}
    forced_ids = ledger.force([r.subject_id for r in requests], scope=scope)
    return [by_subject[sid] for sid in forced_ids]


def main(argv=None) -> int:
    """`seedsmith items generate --kind affix-family --group <g> --affix-kind <k>` (item-seedgen
    module `affix-families-gen`).

    ⛔ **Real gap, closed 2026-09-08.** This module's ledger/plan machinery (`plan_requests`/
    `force_requests`/`mark_family_written`) is real and tested, and a spec
    (`docs/architecture/item-seedgen/spec-affix-families-gen.md`) documents `items generate --kind
    affix-family --brief <theme-file> --write` as the real invocation — but no CLI entrypoint of
    any kind existed. **One real design fact this module's own brief makes explicit and every
    sibling module does NOT share**: the family's own `word` — the thing every other module's
    ledger key is minted FROM beforehand — is chosen BY THE MODEL, as part of its answer
    (`AffixFamilyBrief.render`'s own "Choose, and nothing else: 1. `word`..."). So there is nothing
    to pre-plan for a brand-new family the way `plan_run` pre-plans N open draw slots elsewhere —
    `plan_requests`'s real value is RECONCILE (did a previously-recorded word's minted id survive a
    hand edit), not discovery. This CLI authors one new family per call, then records it via
    `mark_family_written` so a LATER run's reconcile has something real to check.
    """
    import argparse
    import dataclasses

    ap = argparse.ArgumentParser(description="Author one new affix family for one partition.")
    ap.add_argument("--group", required=True, help="e.g. 'g.armour' — must have a shipped "
                                                    "partition file already")
    ap.add_argument("--affix-kind", dest="affix_kind", required=True,
                    help="the family's fixed kindId, e.g. 'stat.modify'")
    ap.add_argument("--theme", default="", help="an optional theme hint in the brief")
    ap.add_argument("--dry-run", action="store_true", help="assemble the brief, make no model call")
    ap.add_argument("--write", action="store_true", help="write the merged partition back to disk")
    ap.add_argument("--endpoint", default="", help="live model endpoint; enables a real run")
    ap.add_argument("--model", default="", help="overrides load_config()'s own model for this run")
    args = ap.parse_args(argv)

    partition = brief_mod.load_partition_context(args.group)
    free_pairs = brief_mod.free_channel_ops(partition, args.affix_kind)

    if args.dry_run:
        print(json.dumps({"group": args.group, "kindId": args.affix_kind,
                          "existingChannels": list(partition.channels),
                          "freePairs": [f"{c}|{o}" for c, o in free_pairs]},
                         ensure_ascii=False, indent=2))
        if free_pairs:
            brief = brief_mod.build_affix_family_brief(args.group, args.affix_kind,
                                                       theme_note=args.theme)
            print("--- brief ---")
            print(brief.render())
        else:
            print("--- brief ---")
            print("(skipped — no free (channel, op) pair remains)")
        return 0

    if not args.write:
        raise SystemExit(
            "seedsmith: refused — no --write. Use --dry-run to inspect the brief first, "
            "then re-run with --write --endpoint <url> to actually call a model and persist.")

    if not free_pairs:
        print(json.dumps({
            "outcome": "blocked",
            "reason": "no free (channel, op) pair remains in this partition for the requested kind",
        }, ensure_ascii=False, indent=2))
        return 0

    brief = brief_mod.build_affix_family_brief(args.group, args.affix_kind,
                                               theme_note=args.theme)

    from ....pipeline.llm_caller import live_answer_caller, resolve_live_transport

    config = resolve_live_transport(args.endpoint, args.model)
    if not config.endpoint:
        raise SystemExit(
            "seedsmith: --write refused — no live endpoint. Pass --endpoint <url> or set "
            "SEEDSMITH_LLM_ENDPOINT in tools/seedsmith/.env; --dry-run needs neither.")
    def validator(answer: dict, schema: dict) -> list[str]:
        defects = schema_mod.validate_answer(
            answer, schema, channel_ops=brief.partition.channel_ops, kind_id=args.affix_kind,
            free_pairs=free_pairs)
        # The schema constrains the channel/op pair but the minted id also depends on the model's
        # free-form word. Reject a word collision during the shared repair attempt instead of
        # letting emit.assemble_entry abort the whole fill step after the model call returns.
        word = answer.get("word")
        if isinstance(word, str) and word:
            minted_id = emit.family_id(brief.partition.stem, word)
            if minted_id in brief.partition.existing_ids:
                defects.append(
                    f"word {word!r} mints existing id {minted_id!r}; choose a new mechanical word")
        return defects
    answer = live_answer_caller(config, validator=validator)(brief.render(), brief.schema)

    defects = validator(answer, brief.schema)
    if defects:
        print(json.dumps({"outcome": "refused", "reason": "invalid model response: " + "; ".join(defects)},
                         ensure_ascii=False, indent=2))
        return 3

    if answer.get("blocked"):
        print(json.dumps({"outcome": "blocked", "reason": answer["blocked"]},
                         ensure_ascii=False, indent=2))
        return 0

    entry = emit.assemble_entry(answer, brief.partition, args.affix_kind)

    file_name = "g-" + args.group.split(".", 1)[1] + ".json"
    path = brief_mod.FAMILIES_DIR / file_name
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc = emit.merge_into_partition_document(doc, [entry])
    emit.write_document(path, doc)

    ledger = RunLedger(DEFAULT_LEDGER)
    request = FamilyRequest(group_id=args.group, kind_id=args.affix_kind, word=answer["word"])
    mark_family_written(ledger, request, entry["id"])

    print(json.dumps({"outcome": "persisted", "id": entry["id"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
