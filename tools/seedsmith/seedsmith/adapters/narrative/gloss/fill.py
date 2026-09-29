"""The gloss-fill pipeline: chunking, one model call per chunk, verify, bounded heal (NS14).

Shape, and why it differs from the vote-based pipelines (`general-propose`, `affix-authoring`):

- **No cross-sample vote.** A gloss is a short phrase judged by whether it carries the meaning; the
  vote machinery exists to resolve a STRUCTURAL pick (which atom family, which name) that one sample
  cannot be trusted with. Here the answer is prose, so the review sample catches a bad gloss instead.
- **The heal budget is explicit.** The loop runs `1 + max_heal` attempts with `max_heal=MAX_HEAL`
  (the transport's own default is 3), because an exhausted heal here must produce an UNRESOLVED motif.
- **An exhausted heal never writes the source.** A motif that never yields a usable gloss is left
  unglossed and listed — the source text is never substituted for a gloss, which is the one
  substitution that would ship raw tokens (`spec-dungeon-generator-repair` §2).

Nothing here writes the registry: `fill.py` returns a result and the commit step decides what reaches
`gk-data/packs/fusion/data/seed/narrative/_registry/**`.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ....pipeline.llm_caller import LlmCallerConfig, call_model, extract_json
from ....workspace_roots import content_root
from ...creatures.anchor.permute import order_for
from .prompt import build_chunk_brief, chunk_schema

__all__ = ["MAX_HEAL", "SENSES", "SYSTEM_PROMPT", "RUNS_REL", "chunk_motifs", "sense_order_for",
           "verify_chunk", "fill_glosses", "gloss_run_id", "write_gloss_run", "load_gloss_run",
           "latest_gloss_run_id"]

#: Where a fill run's scratch document lives. `fill_glosses` returns a result and writes nothing;
#: the CLI persists it here so the commit step reads the run the fill produced, and the registry is
#: still written only by `commit_glosses`.
RUNS_REL = "data/seed/narrative/_runs"
_GLOSS_RUN_PREFIX = "gloss-"

#: The heal budget: one attempt plus this many repairs. Passed by name at the call site below, never
#: left to the transport's own default.
MAX_HEAL = 2

#: `gloss-registry`'s closed sense enum, as a declaration (the registry loader owns the real check).
SENSES: "tuple[str, ...]" = ("concrete", "abstract", "action", "quality", "none")

#: The prompt field the per-motif option permutation is seeded by.
_SENSE_SEED_FIELD = "sense"

SYSTEM_PROMPT = (
    "You gloss creature motifs into English for a game's seed corpus. Each gloss is a short phrase "
    "that carries the motif's meaning so an event brief can use it in place of the raw word. Never "
    "return the motif itself, never a digit, never a full sentence. Pick the sense that describes the "
    "kind of meaning, not a grammar category. Set `blocked` only if the whole chunk cannot be glossed, "
    "and name why. Answer only with the schema's own fields."
)


def chunk_motifs(motifs: "Sequence[str]", chunk_size: int) -> "list[list[str]]":
    """Split `motifs` into chunks of at most `chunk_size`, order-preserving and deterministic."""
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be positive, got {chunk_size}")
    ordered = list(motifs)
    return [ordered[i:i + chunk_size] for i in range(0, len(ordered), chunk_size)]


def sense_order_for(motif: str, senses: "Sequence[str]" = SENSES) -> "list[str]":
    """The sense options in THIS motif's own order — `order_for`'s deterministic permutation, never the
    fixed enum order (a fixed order lets position bias masquerade as a reading)."""
    return order_for(motif, _SENSE_SEED_FIELD, 0, list(senses))


def verify_chunk(items: "Mapping[str, Any]", out: "Mapping[str, Any]") -> "tuple[dict, dict]":
    """Hard defects block a chunk's acceptance and are re-prompted with the defect named per motif. A
    `blocked` reply is a SOFT defect: the model is telling us it cannot answer, so re-prompting would
    only ask it again — the chunk ends unresolved and is listed."""
    hard: "dict[str, str]" = {}
    if str(out.get("blocked") or "").strip():
        return {}, {"blocked": str(out["blocked"]).strip()}
    returned = {str(row.get("motif")): row for row in (out.get("glosses") or [])
                if isinstance(row, dict)}
    for motif in list(items["motifs"]):
        row = returned.get(motif)
        if row is None:
            hard[motif] = "no entry returned for this motif"
            continue
        gloss = str(row.get("gloss") or "").strip()
        if not gloss:
            hard[motif] = "empty gloss"
        elif gloss == motif:
            hard[motif] = "the gloss is the motif itself, not a translation"
        elif any(ch.isdigit() for ch in gloss):
            hard[motif] = "the gloss contains a digit"
    return hard, {}


def gloss_run_id(motifs: "Sequence[str]") -> str:
    """A deterministic run id (no clock): the same batch always names the same run file, so a rerun
    reconciles with the run it repeats instead of littering `_runs/`."""
    digest = hashlib.sha256("|".join(sorted(motifs)).encode("utf-8")).hexdigest()[:12]
    return _GLOSS_RUN_PREFIX + digest


def _runs_dir(runs_dir: "Path | str | None" = None) -> Path:
    return Path(runs_dir) if runs_dir is not None else content_root() / RUNS_REL


def write_gloss_run(document: "Mapping[str, Any]", *, runs_dir: "Path | str | None" = None) -> Path:
    directory = _runs_dir(runs_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{document['runId']}.json"
    path.write_text(json.dumps(dict(document), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def load_gloss_run(run_id: str, *, runs_dir: "Path | str | None" = None) -> "dict[str, Any]":
    """Read a fill run back — what the commit step reads. Refuses a missing or mismatched file rather
    than returning an empty run: committing nothing while reporting success is the failure a commit
    must not have."""
    path = _runs_dir(runs_dir) / f"{run_id}.json"
    if not path.exists():
        raise ValueError(f"no run file {path} — run `narrative gloss fill --write` first")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("runId") != run_id:
        raise ValueError(f"{path}: runId {document.get('runId')!r} does not match {run_id!r}")
    return document


def latest_gloss_run_id(*, runs_dir: "Path | str | None" = None) -> "str | None":
    """The newest fill run's id, or None when there is none. Run ids are clock-free, so "newest" is by
    file mtime — the run a reviewer just filled."""
    directory = _runs_dir(runs_dir)
    if not directory.is_dir():
        return None
    files = sorted(directory.glob(f"{_GLOSS_RUN_PREFIX}*.json"), key=lambda path: path.stat().st_mtime)
    return files[-1].stem if files else None


def fill_glosses(motifs: "Sequence[str]", *, call: "Callable[..., str] | None" = None,
                 config: LlmCallerConfig, exemplars: "Sequence[Mapping[str, str]]",
                 chunk_size: int, already_glossed: "Sequence[str]" = (),
                 senses: "Sequence[str]" = SENSES, max_heal: int = MAX_HEAL,
                 limit: "int | None" = None, dry_run: bool = False) -> "dict[str, Any]":
    """Gloss every motif that is not already glossed, one chunk per call, bounded by `limit` chunks.

    Returns a result document: `glosses` (accepted rows, motif -> {gloss, sense}), `unresolved`
    (motif -> the reason: a `blocked` reply or an exhausted heal), `calls` (the real count), `chunks`.
    A dry run makes NO call and reports the chunk count, so a spend can be approved before it happens.
    """
    done = set(already_glossed)
    chunks = chunk_motifs([m for m in motifs if m not in done], chunk_size)
    if limit is not None:
        if limit < 0:
            raise ValueError("limit must not be negative")
        chunks = chunks[:limit]
    if dry_run:
        return {"dryRun": True, "chunks": len(chunks), "calls": 0, "glosses": {}, "unresolved": {}}

    schema = chunk_schema(senses=senses)
    caller = call or call_model
    glosses: "dict[str, dict]" = {}
    unresolved: "dict[str, str]" = {}
    calls = 0
    for chunk in chunks:
        sense_order = {motif: sense_order_for(motif, senses) for motif in chunk}
        items = {"motifs": list(chunk), "senseOrder": sense_order}
        user = build_chunk_brief(chunk, exemplars=exemplars, senses=senses, sense_order=sense_order)
        out: "dict[str, Any]" = {}
        for _attempt in range(1 + max_heal):
            calls += 1
            try:
                out = extract_json(caller(SYSTEM_PROMPT, user, config=config, schema=schema))
            except (ValueError, RuntimeError) as exc:
                out = {}
                user = (user + "\n\nYour previous reply could not be parsed (" + str(exc)
                        + "). Re-emit ONLY the schema's JSON object.")
                continue
            if str(out.get("blocked") or "").strip():
                break                      # a refusal is not re-prompted
            hard, _soft = verify_chunk(items, out)
            if not hard:
                break
            named = "; ".join(f"{motif}: {reason}" for motif, reason in sorted(hard.items()))
            user = (user + "\n\nYour previous attempt was rejected: " + named
                    + ". Fix exactly these and return the complete object.")
        blocked = str(out.get("blocked") or "").strip()
        if blocked:
            for motif in chunk:
                unresolved[motif] = f"blocked: {blocked}"
            continue
        returned = {str(row.get("motif")): row for row in (out.get("glosses") or [])
                    if isinstance(row, dict)}
        for motif in chunk:
            row = returned.get(motif) or {}
            gloss = str(row.get("gloss") or "").strip()
            if not gloss:
                # Exhausted heal: leave the motif UNRESOLVED. Nothing substitutes the source text for a
                # gloss — that substitution is how raw tokens would ship.
                unresolved[motif] = "unresolved after heal (no usable gloss)"
                continue
            glosses[motif] = {"gloss": gloss, "sense": str(row.get("sense") or "none")}
    return {"dryRun": False, "chunks": len(chunks), "calls": calls, "glosses": glosses,
            "unresolved": unresolved,
            # Justified empty: a gloss is prose judged by review, never a structural pick a vote could
            # resolve (this module's own docstring). The key exists so a caller cannot read the absence
            # of a vote as a missing field.
            "votes": ()}
