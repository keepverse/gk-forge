"""seedsmith.adapters.items.materialgen.run — the run plan and the batch driver, wired to
`pipeline.run_ledger.RunLedger` (`generator-harness`, spec-generator-harness.md).

⛔ **Two different "already exists" questions, and the ledger only answers one of them.** The corpus
file (`gk-data/packs/fusion/data/seed/items/materials/materials.json`) already carries hand-authored content for 17 of
the 27 issuable ids — content this generator did not produce and has no ledger record of. Those are
never touched: `plan_run` only ever proposes an id that is EITHER missing from the corpus entirely,
OR present but ledger-managed and no longer valid (a hand edit broke a row this generator produced —
`RunLedger.plan`'s own stated reconcile purpose). An id with real content and no ledger row is left
alone regardless of what `is_valid` would say, because "no ledger row" there means "not ours to
touch," not "not yet done."

**The explicit `--overwrite <id>` path is different on purpose.** `plan_overwrite` bypasses all of
that via `RunLedger.force` — an explicit, named request always wins, on any issuable id, ledger-
managed or not. Never a bare, unscoped overwrite (`force`'s own boundary): a caller passes the exact
ids to replace.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from seedsmith.pipeline import cross_corpus_names
from seedsmith.pipeline.run_ledger import RunLedger

from . import brief as brief_mod
from . import emit
from . import vocab
from ..setgen.answers import schema_defects
from .schema import material_schema, tag_axis_violations
from ....metrics.dedup import minhash_signature as dedup_minhash, shingles as dedup_shingles

REPO_ROOT = Path(__file__).resolve().parents[6]
MATERIALS_PATH = REPO_ROOT / "data" / "seed" / "items" / "materials" / "materials.json"
DEFAULT_LEDGER_PATH = REPO_ROOT / "data" / "seed" / "items" / "_runs" / "materials-gen.ledger.json"


@dataclass(frozen=True)
class Subject:
    """One unit of work: one material id, already confirmed against the closed vocabulary."""

    subject_id: str            # the runtime id, e.g. "shard.chaff" — never a fabricated id
    material: vocab.MaterialId
    brief: str


@dataclass
class RunPlan:
    subjects: "list[Subject]"
    already_present: "list[str]" = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.subjects


def load_entries(path: "Path | None" = None) -> "list[dict]":
    materials_path = path or MATERIALS_PATH
    if not materials_path.exists():
        return []
    doc = json.loads(materials_path.read_text(encoding="utf-8"))
    return list(doc.get("entries") or [])


def _existing_by_runtime_id(entries: "list[dict]") -> "dict[str, dict]":
    return {e["runtimeId"]: e for e in entries if isinstance(e.get("runtimeId"), str)}


def _row_still_matches(by_runtime: "dict[str, dict]"):
    """The `is_valid` callback `RunLedger.plan` calls for every subject its own ledger already
    claims done: true only if the corpus still carries a row for that runtime id whose `id` is the
    exact one this generator minted. False for "row gone" (hand-deleted) and for "row present but
    its `id` changed" (hand-edited) alike — both are the reconcile case."""
    def is_valid(subject_id: str, ledger_entry: dict) -> bool:
        current = by_runtime.get(subject_id)
        return current is not None and current.get("id") == ledger_entry.get("id")
    return is_valid


def plan_run(*, materials_path: "Path | None" = None, ledger: "RunLedger | None" = None) -> RunPlan:
    """Resume/append/reconcile — never overwrite by default. See the module docstring for exactly
    which ids this proposes."""
    entries = load_entries(materials_path)
    have = _existing_by_runtime_id(entries)
    ledger = ledger or RunLedger(DEFAULT_LEDGER_PATH)
    done = ledger.read_done()

    all_ids = [m.runtime_id for m in vocab.ISSUABLE]
    needing_work = set(ledger.plan(all_ids, _row_still_matches(have)))

    subjects = [
        Subject(subject_id=m.runtime_id, material=m, brief=brief_mod.build_material_brief(m))
        for m in vocab.ISSUABLE
        if m.runtime_id in needing_work
        # A row with real content and no ledger record is hand-authored, pre-dating this
        # generator — never ours to regenerate just because `is_valid` was never asked about it.
        and not (m.runtime_id in have and m.runtime_id not in done)
    ]
    return RunPlan(subjects=subjects, already_present=sorted(have))


def plan_overwrite(ids: "list[str]", *, ledger: "RunLedger | None" = None) -> RunPlan:
    """The explicit `--overwrite <id>` path. Every id must be issuable — a typo or a fabricated id
    fails loudly here rather than silently authoring nothing (or, worse, authoring something)."""
    if not ids:
        raise ValueError("plan_overwrite requires at least one id — an unscoped overwrite is refused")
    ledger = ledger or RunLedger(DEFAULT_LEDGER_PATH)
    forced_ids = ledger.force(ids, scope="ids")
    materials = [vocab.require_issuable(i) for i in forced_ids]
    subjects = [
        Subject(subject_id=m.runtime_id, material=m, brief=brief_mod.build_material_brief(m))
        for m in materials
    ]
    return RunPlan(subjects=subjects, already_present=[])


@dataclass(frozen=True)
class Outcome:
    subject_id: str
    outcome: str            # "persisted" | "blocked" | "refused" | "missing_answer"
    defects: "tuple[str, ...]" = ()


@dataclass(frozen=True)
class BatchResult:
    outcomes: "tuple[Outcome, ...]"
    entries: "tuple[dict, ...]"          # the entries this batch actually persisted
    materials_path: Path

    @property
    def persisted(self) -> "tuple[str, ...]":
        return tuple(o.subject_id for o in self.outcomes if o.outcome == "persisted")

    def to_dict(self) -> dict:
        return {
            "outcomes": [{"subjectId": o.subject_id, "outcome": o.outcome,
                         "defects": list(o.defects)} for o in self.outcomes],
            "persisted": list(self.persisted),
        }


def _validate_answer(answer: dict) -> "list[str]":
    if "blocked" in answer:
        return []
    defects = schema_defects(answer, material_schema())
    defects.extend(tag_axis_violations(answer.get("tags") or ()))
    return defects


def _name_key(name: "str | None") -> str:
    """The comparison form of an authored name: whitespace collapsed, casefolded. Case- and
    spacing-variant reuse is the same collision as verbatim reuse for a player reading a list, and the
    defect this gate closes was reported as names "used verbatim", so matching the exact string would
    leave the near-miss variants through.

    Delegates to `pipeline.cross_corpus_names.name_key` so the OTHER corpora are keyed by the same form.
    It used to be written out here, and the two agreeing today was luck: the cross-corpus half compared
    against a differently-normalised map, which finds nothing, which looks exactly like a clean tree.
    """
    return cross_corpus_names.name_key(name)


#: The lexical half of the gate, at the same threshold `seedsmith/metrics/dedup.py`'s `SemanticDedup`
#: uses for names, so "the gate refused it" and "`check` reports it" cannot disagree about the line.
NEAR_DUPLICATE_THRESHOLD = 0.6

#: Cached `name -> (shingles, minhash signature)`. The lexical half is O(kept) per subject and a run
#: compares the same few thousand names against each other repeatedly, so recomputing shingles per
#: comparison is the difference between a gate that runs in seconds and one that does not finish.
_SHINGLE_CACHE: "dict[str, tuple[frozenset, tuple]]" = {}


def _name_signature(name: str) -> "tuple[frozenset, tuple]":
    hit = _SHINGLE_CACHE.get(name)
    if hit is None:
        sh = frozenset(dedup_shingles(name))
        hit = (sh, dedup_minhash(sh))
        _SHINGLE_CACHE[name] = hit
    return hit


def _near_duplicate_defect(answer: dict, subject_id: str, entries: "list[dict]") -> "str | None":
    """Refuse an authored `name` that is LEXICALLY near one already in the corpus.

    ⛔ **The second half of the same measured defect; `check` names both populations.** The key gate is an
    O(1) equality test on `_name_key`, so it closes verbatim and case/spacing reuse and nothing else.
    `SemanticDedup/NearDuplicate` is a different predicate - character 5-gram shingles -> MinHash ->
    Jaccard - and it reports a GAP tier plus a much larger NOTE tier. Measured on the BCU2.11 corpus at the
    **1,776** rows the key gate leaves alone: **0** exact reuse remaining, but **47** near-duplicate pairs
    across **73** rows - `'Blover's Essence'` against `"Sunblover's Essence"`, `'Tallnut Provenance'`
    against `'Ironnut Provenance'`. One token apart, and a player scrolling a list reads them as one name.

    This reuses the capability `seedsmith/metrics/dedup.py` already provides rather than inventing a
    second notion of similarity, and it is **per-subject** like the key gate - not `setgen`'s
    population-level `dedup_report(names).rate_permille`, which cannot work here because `materialgen`
    writes as it goes and a population rate is only evaluable once the batch is on disk. That
    write-as-it-goes shape is the reason the key half is per-subject at all, and this half inherits it.

    **A subject is never compared against its own row**, for the same reason the key half skips it:
    `--overwrite` exists to re-emit an id, and a re-emit that keeps its name is a legitimate overwrite.
    """
    authored = answer.get("name")
    if not authored or not _name_key(authored):
        return None
    mine_shingles, _mine_sig = _name_signature(authored)
    if len(mine_shingles) < 2:
        # Under five characters there is one shingle, so Jaccard is degenerate. The schema's own
        # minimum-length rule is the right place for that, not a similarity score.
        return None
    for entry in entries:
        runtime_id = entry.get("runtimeId")
        if not runtime_id or runtime_id == subject_id:
            continue
        other = entry.get("name")
        if not other:
            continue
        other_shingles, _other_sig = _name_signature(other)
        union = len(mine_shingles | other_shingles)
        if not union:
            continue
        score = len(mine_shingles & other_shingles) / union
        if score >= NEAR_DUPLICATE_THRESHOLD:
            return (f"near-duplicate name {authored!r}: Jaccard {score:.2f} against the name already held "
                    f"by {runtime_id!r} ({other!r}), at or over the {NEAR_DUPLICATE_THRESHOLD} threshold. "
                    f"Author a name that is not a near-variant of an existing one.")
    return None


def _name_collision_defects(answer: dict, subject_id: str, entries: "list[dict]",
                            by_runtime: "dict[str, dict]", claimed: "dict[str, str]") -> "list[str]":
    """Refuse an authored `name` that a DIFFERENT material id already holds.

    ⛔ **This gate is the second half of a measured defect, and it is deterministic on purpose.** A full
    `items fill` run measured **747 `SemanticDedup/NearDuplicate` findings, every one of them a name used
    verbatim by 2 to 35 entries** ('Ancestral Echo' by 35) — the `trophy` population is 3,602 ids minted
    one per species slot, so a few hundred species share a few hundred name constructions. Two things were
    missing, and this is the second:

      * `brief.py` never told the model its name had to differ from its siblings, and
      * `run_batch` validated only schema shape and tag axes, then persisted atomically and
        unconditionally — so nothing between the model's answer and the corpus file could object.

    **Why a per-subject refusal rather than setgen's population-level rate.** `setgen/authored.py:398-413`
    records `dedup_report(names).rate_permille` against `tuning.near_duplicate_rate_max_permille`, which
    needs no threshold to be *reportable* but can only be evaluated once the whole batch is written.
    `materialgen` writes as it goes, so a population gate here would observe the collision and keep the
    rows — which is precisely the sequence that produced the 956-file revert `ea2aeb756`. Verbatim reuse is
    a fact rather than a similarity judgement, so it is checkable per subject in O(1) with no tuning
    value, and refusing the subject is the direction that fails safe: the row is not written and the
    operator re-asks.

    **Not a collision when the id already holds the name.** `plan_overwrite` exists to re-emit an id, and
    a re-emit that keeps the same name is a legitimate overwrite, so a subject is never compared against
    its own current row. Comparing it against itself would make the adapter's own overwrite path
    unrunnable — a regression introduced by the fix rather than caught by it.
    """
    authored = answer.get("name")
    key = _name_key(authored)
    if not key:
        return []
    defects: "list[str]" = []
    for entry in entries:
        runtime_id = entry.get("runtimeId")
        if not runtime_id or runtime_id == subject_id:
            continue
        if _name_key(entry.get("name")) == key:
            defects.append(
                f"duplicate name {authored!r}: already the name of {runtime_id!r}. Every material id "
                f"must hold a distinct name — author a new one rather than reusing another's.")
            break
    holder = claimed.get(key)
    if holder is not None and holder != subject_id:
        defects.append(
            f"duplicate name {authored!r}: already claimed by {holder!r} in this same batch. Two ids in "
            f"one batch may not share a name.")
    return defects


def _write_entries(entries: "list[dict]", path: Path, *, base_doc: "dict | None" = None) -> Path:
    """Atomic replace, mirroring `RunLedger.write_done`'s own temp-file-then-`os.replace` discipline
    so a killed process leaves either the old corpus file or the new one, never half of one.

    ⛔ Real defect, measured 2026-09-28: that discipline was the WHOLE implementation, and on Windows an
    unretried `os.replace` is fatal on a transient handle. A live re-emit lost three batches to
    `PermissionError: [WinError 5] Access is denied` on
    `'...\\materials\\tmp27lz4xai.tmp' -> '...\\materials.json'` raised from exactly this line — and this is
    the write that persists the run's work, so each failure discarded every answer the batch had bought.

    The retry now lives in ONE place, `pipeline/atomic_replace.py`, which this calls. That is not tidiness:
    this function and `write_done` were documented as mirroring each other, one of them received a pasted
    retry, and the one that did not is the one that kept killing batches. **A second copy of the backoff
    here would reproduce that drift on schedule.**
    """
    # Four dots, not three: this module is `seedsmith.adapters.items.materialgen`, so `.` is the package,
    # `..` is `items`, `...` is `adapters`, and `....` is `seedsmith` itself. Three dots resolves to
    # `seedsmith.adapters.pipeline`, which does not exist - and 14 tests said so at once.
    from ....pipeline.atomic_replace import replace_with_retry

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = dict(base_doc) if base_doc is not None else {"schemaVersion": 1, "kind": "material"}
    doc["entries"] = entries
    payload = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(payload)
        replace_with_retry(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return path


def run_batch(plan: RunPlan, answers: "dict[str, dict]", *,
             materials_path: "Path | None" = None,
             ledger: "RunLedger | None" = None) -> BatchResult:
    """Validate each subject's authored answer, mint its entry, and persist.

    `answers` is a plain `{subject_id: draft}` mapping — the model-call transport is out of this
    module's scope (the brief/schema pair is what any transport needs; wiring a live endpoint is a
    separate, later concern the same way `setgen`'s own graph wiring landed after its brief/schema/
    emit modules did).

    Upsert, not append-only: a subject already carrying a corpus row (only reachable here via
    `plan_run`'s reconcile branch or `plan_overwrite`'s explicit request — never via an untouched
    hand-authored row, which never becomes a `Subject` in the first place) REPLACES that row in
    place rather than appending a duplicate.
    """
    materials_path = materials_path or MATERIALS_PATH
    ledger = ledger or RunLedger(DEFAULT_LEDGER_PATH)

    doc: "dict" = {"schemaVersion": 1, "kind": "material"}
    if materials_path.exists():
        doc = json.loads(materials_path.read_text(encoding="utf-8"))
    entries: "list[dict]" = list(doc.get("entries") or [])
    by_runtime = _existing_by_runtime_id(entries)

    # The OTHER corpora's names, gathered ONCE per batch.
    other_owners, items_root = _cross_corpus_owners(materials_path)

    outcomes: "list[Outcome]" = []
    persisted: "list[dict]" = []
    #: normalized name -> the subject_id that claimed it in THIS batch, so a collision inside one
    #: `answers` mapping is caught as well as one against the corpus already on disk.
    claimed: "dict[str, str]" = {}

    for subject in plan.subjects:
        answer = answers.get(subject.subject_id)
        if answer is None:
            outcomes.append(Outcome(subject.subject_id, "missing_answer"))
            continue
        if answer.get("blocked"):
            outcomes.append(Outcome(subject.subject_id, "blocked", (str(answer["blocked"]),)))
            continue
        defects = _validate_answer(answer)
        defects.extend(_name_collision_defects(answer, subject.subject_id, entries, by_runtime, claimed))
        near = _near_duplicate_defect(answer, subject.subject_id, entries)
        if near:
            defects.append(near)
        cross = _cross_corpus_name_defect(answer, other_owners)
        if cross:
            defects.append(cross)
        if defects:
            outcomes.append(Outcome(subject.subject_id, "refused", tuple(defects)))
            continue

        existing = by_runtime.get(subject.subject_id)
        seq = int(existing["id"].rsplit(".", 1)[-1]) if existing is not None else emit.next_seq(entries)
        entry = emit.build_entry(subject.material, answer, seq=seq)

        if existing is not None:
            entries = [entry if e is existing else e for e in entries]
        else:
            entries.append(entry)
        by_runtime[subject.subject_id] = entry
        persisted.append(entry)
        key = _name_key(entry.get("name"))
        if key:
            claimed[key] = subject.subject_id
        ledger.mark_done(subject.subject_id, entry)
        outcomes.append(Outcome(subject.subject_id, "persisted"))

    if persisted:
        _write_entries(entries, materials_path, base_doc=doc)

    return BatchResult(outcomes=tuple(outcomes), entries=tuple(persisted), materials_path=materials_path)


#: Closed prefix for the cross-corpus half of the name gate. It joins `_NAME_DEFECT_PREFIXES` so the
#: existing retry path treats it as a NAME defect and quotes the other holder back to the model - which is
#: the entire repair. A separate prefix rather than reusing "duplicate name " keeps the two populations
#: distinguishable in a refusal tally: one is fixable inside this corpus, the other needs a name that
#: nothing else anywhere holds.
CROSS_CORPUS_DEFECT_PREFIX = "name already used elsewhere: "


#: The name gate's messages, by prefix. `run.py` emits them itself, so this is a closed set - and
#: matching on the PREFIX rather than the substring "name" matters, because a schema defect reads
#: `$.name: expected at least 3 characters`, which contains "name" and would otherwise be mistaken for a
#: name collision and re-asked. The first version of this predicate used `"name" in d.lower()` and the test
#: caught exactly that.
_NAME_DEFECT_PREFIXES = ("duplicate name ", "near-duplicate name ", CROSS_CORPUS_DEFECT_PREFIX)


def _cross_corpus_owners(materials_path: Path) -> "tuple[dict[str, list[str]], Path | None]":
    """The other corpora's names, and the items root they were read from - `({}, None)` when there is none.

    ⛔ **Measured hang, 2026-09-28, from the first version of this.** It derived the items root as
    `materials_path.parent.parent`, which is right ONLY for the real layout
    `<items>/materials/materials.json`. `run_batch(materials_path=...)` is a real parameter and the
    existing suite passes a FLAT `tmp/materials.json`, so the walk became `rglob("*.json")` over the
    system temp tree: 25 tests passed in 3 seconds and the 26th was still running after 15 minutes.

    So the root is derived only when the file really sits in a `materials/` DIRECTORY, and otherwise the
    cross-corpus half is skipped rather than pointed at an arbitrary tree. Skipping is the safe direction -
    it can miss a collision, while the alternative invents them and hangs - and it is not silent: the
    returned `None` is the record, and the corpus's own layout is what makes the check available at all.
    """
    try:
        parent = materials_path.resolve().parent
    except OSError:
        return {}, None
    if parent.name != "materials" or not parent.parent.is_dir():
        return {}, None
    return cross_corpus_names.other_corpus_names(parent.parent, materials_path), parent.parent


def _cross_corpus_name_defect(answer: dict, owners: "dict[str, list[str]]",
                              own_id: "str | None" = None) -> "str | None":
    """⛔ The half of the name gate that used to be missing, and it is the half a re-emit cannot fix without it.

    The gate compared an authored name against the MATERIALS corpus only. A `charm.*` or a `droptable.*`
    holding the same name was invisible to it, so the answer was persisted - and because the re-ask brief is
    built from the same blind view, re-asking returned the same name and re-persisted it. Measured: 4
    entries whose names are held verbatim outside the materials corpus, unchanged across every pass, while
    2,123 other names in the same run did change (584 per mille) - so the model was varying names fine and
    was simply never told these four were taken elsewhere.

    The message NAMES the other holder, because a count is not actionable and the retry brief quotes this
    string back to the model: the whole repair is the model learning which name is unavailable.
    """
    holders = cross_corpus_names.cross_corpus_conflict(answer.get("name"), owners, own_id)
    if not holders:
        return None
    name = str(answer.get("name") or "")
    # The refused WORDS, not just the phrase. Quoting the phrase is what lets a retry escape it - a model
    # told "not 'Primordial Silt'" reaches for "Primordial Loam" - while quoting the two words removes the
    # anchor. Measured: 1 subject of 3,633 refused 20 consecutive times with the phrase quoted and no word
    # ban, so the retry was re-asking a question with the same two words sitting in it.
    words = sorted({w for w in name.replace("-", " ").split() if len(w) > 2})
    return (f"{CROSS_CORPUS_DEFECT_PREFIX}{name!r} is already used by {', '.join(holders)}"
            + (f"; do not use the word(s) {', '.join(words)} in any new name" if words else ""))


def _is_name_defect(defect: str) -> bool:
    """True only for the name gate's own refusal, never for a schema or tag-axis one.

    A schema defect names the FIELD (`$.name: ...`), so a substring test is wrong twice over: it matches
    the wrong gate, and it would re-roll a shape the brief already states correctly - trading a name
    collision for a malformed answer, which is not a repair.
    """
    return defect.strip().startswith(_NAME_DEFECT_PREFIXES)


def _name_retry_brief(brief: str, defects: "tuple[str, ...]") -> str:
    """The subject brief plus the SPECIFIC collision the gate refused, for a second ask.

    ⛔ A re-ask that does not change the question gets the same answer. The reason a name collision
    escalated terminally is that nothing told the model which name was taken - it was asked the identical
    question and produced the identical name, which is exactly what a live pilot showed when 3 torch-themed
    species each returned 'Torch of the Stump'. So the retry quotes the refused name AND the id that holds
    it, which is the only information the model did not already have.

    Wording is deliberately about the NAME and not the whole answer: a re-ask that invites the model to
    change its stats, tags or thresholds as well would re-roll a shape the brief already states correctly
    and risk trading a name collision for a schema defect. Only `name` is named here.

    `setgen` carries the same instruction in `cli.py`'s `--retry-blocked` path, worded for a batch that
    already knows the offending name; this one carries the name itself so it works for either shape.
    """
    name_defects = [d for d in defects if _is_name_defect(d)]
    if not name_defects:
        return brief
    detail = "\n".join(f"  - {d}" for d in name_defects)
    return (
        f"{brief}\n\n"
        f"REJECTED ON THE NAME. Your previous answer for this subject was refused by the corpus's name "
        f"gate:\n{detail}\n"
        f"Author a completely different name. Do not reuse the name above, a close variant of it, or any "
        f"other name already in the corpus - a player scrolling a list reads near-identical names as one. "
        f"If the refusal says the name is used ELSEWHERE, that name belongs to a different item entirely "
        f"(a charm, a drop table), so avoid that word pairing whatever else you change. Where the refusal "
        f"lists word(s) to avoid, none of those words may appear in your new name, in any order and with or "
        f"without other words. "
        f"Change ONLY the name; keep the same flavor, tags and everything else you already wrote."
    )


def main(argv=None) -> int:
    """`seedsmith items generate --kind material` (item-seedgen module `materials-gen`).

    ⛔ **Real gap, closed 2026-09-08.** This module had `plan_run`/`plan_overwrite`/`run_batch` — a
    complete, tested pipeline — and a spec (`docs/architecture/item-seedgen/spec-materials-gen.md`)
    documenting `items generate --kind material --brief <theme-file> --write` as the real
    invocation, but no CLI entrypoint of any kind. `run_batch` takes a pre-built `{subject_id:
    answer}` mapping rather than a `call` callable (a third shape, distinct from both
    `basetypegen`'s `call(brief, schema) -> dict` and `gemgen`'s `answer_fn(subject) -> dict`) — this
    builds that mapping from `live_answer_caller` before calling it, once per plan.

    ⛔ **A raising subject no longer discards the whole batch.** That mapping used to be built by a single
    dict comprehension, so one `RuntimeError` from a wedged endpoint unwound the whole invocation and
    every answer already generated in it was lost — measured on a live probe: 2 attempts spent, **0 rows
    written**. At the 1,081-id batch size the re-emit plan used, an abort at subject 900 would have thrown
    away 900 paid-for generations. The loop now records a failed subject, keeps going, and hands
    `run_batch` the partial mapping — which it has always supported, through its `missing_answer` outcome
    and its per-subject `ledger.mark_done`, so a re-run re-plans only what is still missing.
    `--max-consecutive-call-failures` bounds the opposite failure mode: a *dead* endpoint would otherwise
    be ground down one doomed call per subject, so the run stops after a few in a row — and the counter
    resets on any success, so a merely flaky endpoint is ridden through rather than abandoned.
    """
    import argparse
    import dataclasses

    ap = argparse.ArgumentParser(description="Author the closed, issuable materials corpus.")
    ap.add_argument("--dry-run", action="store_true", help="assemble the plan, make no model calls")
    ap.add_argument("--write", action="store_true", help="write the merged corpus back to disk")
    ap.add_argument("--overwrite", "--force", default="",
                    help="comma-separated issuable ids to regenerate (no bare 'all' — every "
                         "issuable id must be named explicitly, matching plan_overwrite's own "
                         "refusal of an unscoped request)")
    ap.add_argument("--endpoint", default="", help="live model endpoint; enables a real run")
    ap.add_argument("--model", default="", help="overrides load_config()'s own model for this run")
    ap.add_argument("--max-consecutive-call-failures", type=int, default=5,
                    help="stop calling after this many subjects fail back to back (0 = never stop). "
                         "A dead endpoint then costs a few calls instead of the whole batch; a merely "
                         "flaky one is ridden through, because the counter resets on every success.")
    ap.add_argument("--max-name-attempts", type=int, default=3,
                    help="re-ask a subject whose NAME collided, this many times, before giving up on it "
                         "(0 = never re-ask). The retry appends the collision the gate reported to the "
                         "brief, so the model is told what to avoid rather than asked again blind.")
    args = ap.parse_args(argv)

    ledger = RunLedger(DEFAULT_LEDGER_PATH)

    if args.overwrite:
        plan = plan_overwrite([s.strip() for s in args.overwrite.split(",") if s.strip()],
                              ledger=ledger)
    else:
        plan = plan_run(ledger=ledger)

    if args.dry_run:
        print(json.dumps({"toGenerate": len(plan.subjects),
                          "alreadyPresent": len(plan.already_present)},
                         ensure_ascii=False, indent=2))
        if plan.subjects:
            print("--- sample brief ---")
            print(plan.subjects[0].brief)
        return 0

    if not args.write:
        raise SystemExit(
            "seedsmith: refused — no --write. Use --dry-run to inspect the plan first, "
            "then re-run with --write --endpoint <url> to actually call a model and persist.")

    from ....pipeline.llm_caller import live_answer_caller, resolve_live_transport

    config = resolve_live_transport(args.endpoint, args.model)
    if not config.endpoint:
        raise SystemExit(
            "seedsmith: --write refused — no live endpoint. Pass --endpoint <url> or set "
            "SEEDSMITH_LLM_ENDPOINT in tools/seedsmith/.env; --dry-run needs neither.")
    caller = live_answer_caller(config)
    answers: "dict[str, dict]" = {}
    call_failures: "list[tuple[str, str]]" = []
    consecutive = 0
    for subject in plan.subjects:
        try:
            answers[subject.subject_id] = caller(subject.brief, material_schema())
            consecutive = 0
        except Exception as exc:  # a wedged endpoint must not discard the calls already paid for
            call_failures.append((subject.subject_id, f"{type(exc).__name__}: {exc}"))
            consecutive += 1
            if args.max_consecutive_call_failures and consecutive >= args.max_consecutive_call_failures:
                break
    result = run_batch(plan, answers, ledger=ledger)

    # ⛔ Real gap, measured 2026-09-28 by a live pilot against the rescue corpus: a NAME collision was
    # TERMINAL. 16 subjects, 9 persisted, 7 refused - 437 per mille - and every refusal was `name_gate`,
    # not a malformed answer. So the pipeline was healthy and the YIELD was the limit, and the 56% that
    # survived was the FINAL figure: the loop above asks each subject exactly once and `run_batch` records
    # a collision and moves on. Spending the planned 2,176 subjects at that rate buys roughly 1,200 rows
    # and 1,000 escalations, and re-running re-asks the same question and gets the same name, because
    # nothing in the brief changed.
    #
    # `setgen` already solved this shape for the same defect - `cli.py` appends "Previous attempt was
    # rejected because its name duplicated an existing item. Choose a completely new surface name; do not
    # reuse that name or a close variant" to the subject brief - but that re-ask is wired to
    # `--retry-blocked`, which selects only `blocked` subjects, and a name collision ESCALATES terminally,
    # so it never reaches it. It is applied here directly, and only to the name half of a refusal: a
    # schema or tag-axis defect is not the model's to answer differently, and re-asking would spend a call
    # to re-roll a shape the brief already states.
    #
    # Why a second pass and not an inner retry loop: a collision is only detectable against the entries
    # ALREADY WRITTEN, which `run_batch` accumulates as it goes. The first pass establishes that
    # population; only then is "this name is taken" a fact the model can be told about.
    #
    # `run_batch` is re-run over the WHOLE plan rather than a narrowed one: it upserts by `runtimeId` and
    # never calls the model, so re-validating an already-persisted subject is cheap and idempotent, and
    # narrowing the plan would mean reconstructing a `RunPlan` whose `already_present` no longer matches
    # the population on disk.
    name_retries: "list[dict]" = []
    if args.max_name_attempts:
        by_id = {s.subject_id: s for s in plan.subjects}
        for round_index in range(args.max_name_attempts):
            retryable = [
                o for o in result.outcomes
                if o.outcome == "refused" and o.subject_id in by_id
                and any(_is_name_defect(d) for d in o.defects)
            ]
            if not retryable:
                break
            retried: "list[str]" = []
            for outcome in retryable:
                subject = by_id[outcome.subject_id]
                try:
                    answers[outcome.subject_id] = caller(
                        _name_retry_brief(subject.brief, outcome.defects), material_schema())
                    consecutive = 0
                except Exception as exc:  # a wedged endpoint must not discard the passes already paid for
                    call_failures.append((outcome.subject_id, f"{type(exc).__name__}: {exc}"))
                    consecutive += 1
                    if args.max_consecutive_call_failures and consecutive >= args.max_consecutive_call_failures:
                        break
                retried.append(outcome.subject_id)
            if not retried:
                break
            name_retries.append({"round": round_index + 1, "subjects": retried})
            result = run_batch(plan, answers, ledger=ledger)

    payload = result.to_dict()
    payload["callFailures"] = [{"subjectId": sid, "error": err} for sid, err in call_failures]
    payload["nameRetries"] = name_retries
    payload["stoppedEarly"] = bool(
        args.max_consecutive_call_failures and consecutive >= args.max_consecutive_call_failures)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if call_failures else 0


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
