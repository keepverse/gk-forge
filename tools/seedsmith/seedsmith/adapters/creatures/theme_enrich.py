"""Enrich name-only creature themes before item generation.

The theme registry is a published snapshot.  This stage only upgrades currently name-basis rows
that are not referenced by item content, and records the model-authored lore as ``basis=enriched``.
It never rewrites a theme already used by the item corpus, never invents motifs, and checkpoints
each subject through the shared atomic run ledger so an interrupted live run resumes safely.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from ...workspace_roots import seed_root  # noqa: E402
from pathlib import Path
from typing import Any, Callable, Mapping

from ...pipeline.llm_caller import LlmCallerConfig, live_answer_caller
from ...pipeline.model import audit_schema
from ...pipeline.run import validate_against_schema
from ...pipeline.run_ledger import RunLedger
#: The placeholder-token pattern moved to the shared leaf `seedsmith.ladders` on 2026-10-04,
#: byte-identical, so the family-label gate in `creatures/anchor/schema.py` can refuse the same
#: labels from ONE declaration. See that leaf for why it is a sibling predicate
#: (`carries_no_identity`) rather than a wider regex — widening this one would change the
#: flavour-prose behaviour right here, which is a different field with different rules.
from seedsmith.ladders import PLACEHOLDER_TOKEN

CREATURES_ROOT = seed_root() / "creatures"
#: species-gear-chain T16: reads v2 (rarity corrected, keys unchanged).
CREATURE_THEME_REGISTRY = CREATURES_ROOT / "_registry" / "themes.v2.json"
DEFAULT_LEDGER = CREATURES_ROOT / "_generated" / "theme-enrich.ledger.json"
PROMPT_VERSION = "theme-enrich/1"

THEME_ENRICH_SCHEMA: dict = {
    "type": "object",
    "required": ["blocked", "flavor"],
    "properties": {
        "blocked": {"type": "boolean"},
        "flavor": {"type": "string"},
        "reason": {"type": "string"},
    },
}

_CITATION = re.compile(r"(?:https?://|www\.|\[[^\]]+\]\([^)]*\))", re.IGNORECASE)
#: `_PLACEHOLDER` used to be declared here; it is `PLACEHOLDER_TOKEN` from the shared leaf now
#: (2026-10-04), so this module and the family-label gate read one definition. Kept under the old
#: name because this module's own call sites use it; the alias is the migration, not a second copy.
_PLACEHOLDER = PLACEHOLDER_TOKEN
_SYNTHETIC_ID = re.compile(r"^(?:enumvalue\d+|extract_(?:single|ten))$", re.IGNORECASE)


def source_can_support_enrichment(
    row: Mapping[str, Any], anchor: Mapping[str, Any] | None = None,
) -> bool:
    """Reject known capture placeholders whose name and id carry no usable identity.

    A model may elaborate a meaningful id such as ``magnetbox``; it may not turn an unnamed enum
    slot into invented anatomy. This is deterministic input classification, not a model judgement.
    """
    display = str(row.get("displayName") or "").strip()
    species_id = str(row.get("speciesId") or "").strip()
    if display in {"", "未命名"} and _SYNTHETIC_ID.fullmatch(species_id):
        # Some enum slots are real runtime species with an anchor-derived trait pool. They are
        # eligible when that independent context exists; a bare unnamed slot remains blocked.
        return bool(anchor and (anchor.get("traitPool") or anchor.get("elementPrimary")))
    return True


def _load_anchor(species_id: str, anchors_root: Path | None = None) -> dict:
    root = anchors_root or (CREATURES_ROOT / ".." / ".." / "generated" / "creatures")
    if not root.is_dir():
        return {}
    wanted = species_id.lower()
    for path in root.glob("*.json"):
        if path.stem.lower() != wanted:
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def build_brief(theme: Mapping[str, Any], anchor: Mapping[str, Any] | None = None) -> str:
    """Build the complete context for one held theme; no hidden corpus lookup is left to the model."""
    motifs = ", ".join(theme.get("motifs") or ()) or "(none)"
    anti = ", ".join(theme.get("antiMotifs") or ()) or "(none)"
    anchor_lines = ""
    if anchor:
        traits = ", ".join(str(x) for x in (anchor.get("traitPool") or ())) or "(none)"
        anchor_lines = (
            f"\nAuthoritative runtime anchor traits: {traits}"
            f"\nAuthoritative runtime element: {anchor.get('elementPrimary') or '(none)'}"
            f"\nAuthoritative deploy mode: {anchor.get('deployMode') or '(none)'}\n"
        )
    return f"""Author a short lore paragraph for this PvZ creature theme.

Species id: {theme.get('speciesId', '')}
Display name: {theme.get('displayName', '')}
Motifs: {motifs}
Anti-motifs to avoid: {anti}
Item expression rule: material and form — what it is made of, what shape it takes
{anchor_lines}

Write one vivid, self-contained paragraph that gives an item generator useful setting context.
Do not mention statistics, costs, tiers, damage, durations, percentages, or any digits. Do not add
citations, markdown, headings, or placeholders. If the supplied context cannot support honest lore,
return blocked=true with a short reason. Otherwise return blocked=false and the lore in `flavor`.

Return ONLY this JSON shape:
{{"blocked": false, "flavor": "...", "reason": ""}}
"""


def validate_answer(value: Mapping[str, Any], _schema: Mapping[str, Any] | None = None) -> list[str]:
    """Local domain gate; schema validation is performed by the shared caller as well."""
    if value.get("blocked"):
        return []
    flavor = value.get("flavor")
    problems: list[str] = []
    if not isinstance(flavor, str) or not flavor.strip():
        problems.append("flavor must be a non-empty string")
        return problems
    if len(flavor.strip()) < 20:
        problems.append("flavor is too short to provide usable context")
    if any(ch.isdigit() for ch in flavor):
        problems.append("flavor contains a digit")
    if _CITATION.search(flavor):
        problems.append("flavor contains a citation")
    if _PLACEHOLDER.search(flavor):
        problems.append("flavor contains a placeholder")
    return problems


def _item_theme_references(items_root: Path) -> set[str]:
    """Return actual machine references plus note references; bound snapshots are immutable."""
    refs: set[str] = set()
    if not items_root.is_dir():
        return refs
    for path in items_root.rglob("*.json"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in re.finditer(r"creature\.[A-Za-z0-9_-]+", text):
            refs.add(match.group(0))
    return refs


def _atomic_write(path: Path, doc: Mapping[str, Any]) -> None:
    """newline="\n" — the same fix, and the same reason, as `generate_themes`'s two writers and
    `setgen/name_repair._atomic_json`: a text-mode write otherwise emits the OS line ending, so a
    one-field change rewrites every line of a committed corpus file on Windows (todo row T51)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def plan(registry_path: Path = CREATURE_THEME_REGISTRY) -> list[str]:
    doc = json.loads(registry_path.read_text(encoding="utf-8"))
    return [key for key, row in sorted(doc.get("themes", {}).items())
            if row.get("basis") == "name" and not row.get("retired")]


def enrich(*, registry_path: Path = CREATURE_THEME_REGISTRY,
           items_root: Path | None = None, ledger_path: Path = DEFAULT_LEDGER,
           config: LlmCallerConfig | None = None,
           caller: Callable[[str, dict], dict] | None = None,
           write: bool = True, anchors_root: Path | None = None) -> dict:
    """Enrich held themes. ``caller`` is injectable for deterministic tests and replay probes."""
    defects = audit_schema(THEME_ENRICH_SCHEMA)
    if defects:
        raise ValueError("theme-enrich schema is unusable: " + "; ".join(map(str, defects)))
    doc = json.loads(registry_path.read_text(encoding="utf-8"))
    themes = doc.get("themes") or {}
    ledger = RunLedger(ledger_path)
    if write:
        # Repair any earlier pass that accepted a synthetic placeholder before this input gate
        # existed. Remove only the generated fields; the published theme itself remains resolvable.
        done = ledger.read_done()
        repaired = False
        for key, row in themes.items():
            anchor = _load_anchor(str(row.get("speciesId") or ""), anchors_root)
            if row.get("basis") == "enriched" and not source_can_support_enrichment(row, anchor):
                row["basis"] = "name"
                row.pop("flavor", None)
                row.pop("lore", None)
                row.pop("flavorProvenance", None)
                done.pop(key, None)
                repaired = True
            elif row.get("basis") == "name" and key in done and source_can_support_enrichment(row, anchor):
                # A prior run may have blocked a placeholder before its runtime anchor was
                # considered. Requeue that terminal row now that authoritative context exists.
                done.pop(key, None)
                repaired = True
        if repaired:
            _atomic_write(registry_path, doc)
            ledger.write_done(done)
    held = plan(registry_path)
    bound = _item_theme_references(items_root or (CREATURES_ROOT.parent / "items"))
    unsafe = sorted(key for key in held if key in bound)
    if unsafe:
        raise ValueError("refusing to rewrite item-bound name themes: " + ", ".join(unsafe))
    if not write:
        return {"planned": len(held), "pending": len(held), "enriched": 0,
                "blocked": 0, "escalated": 0, "remaining": len(held), "complete": not held}
    done = ledger.read_done()
    pending = [key for key in held if key not in done]
    call = caller or live_answer_caller(config, validator=validate_answer)
    enriched = blocked = escalated = 0
    for key in pending:
        row = themes[key]
        subject = key
        anchor = _load_anchor(str(row.get("speciesId") or ""), anchors_root)
        if not source_can_support_enrichment(row, anchor):
            ledger.mark_terminal(subject, outcome="blocked", entry_id=key, attempts=0,
                                 blocked_reason="synthetic unnamed source placeholder")
            blocked += 1
            continue
        try:
            answer = call(build_brief(row, anchor), THEME_ENRICH_SCHEMA)
            schema_problems = validate_against_schema(answer, THEME_ENRICH_SCHEMA)
            schema_problems.extend(validate_answer(answer, THEME_ENRICH_SCHEMA))
            if schema_problems:
                raise ValueError("; ".join(schema_problems))
            if answer.get("blocked"):
                reason = str(answer.get("reason") or "model blocked enrichment")
                ledger.mark_terminal(subject, outcome="blocked", entry_id=key,
                                     attempts=1, blocked_reason=reason)
                blocked += 1
                continue
            lore = str(answer["flavor"]).strip()
            if write:
                row["flavor"] = lore
                row["basis"] = "enriched"
                row["flavorProvenance"] = {
                    "pipeline": "theme-enrich", "model": getattr(config, "model", "unknown"),
                    "promptVersion": PROMPT_VERSION, "finding": f"theme-enrich:{key}",
                }
                _atomic_write(registry_path, doc)
            ledger.mark_done(subject, {
                "outcome": "persisted", "entryId": key, "basis": "enriched",
                "promptVersion": PROMPT_VERSION, "model": getattr(config, "model", "unknown"),
            })
            enriched += 1
        except Exception as exc:  # bounded per-subject failure; resume must not retry successes
            ledger.mark_terminal(subject, outcome="escalated", entry_id=key, attempts=1,
                                 defects=[str(exc)])
            escalated += 1
    if write:
        # The first live pass predated provenance stamping. Backfill that metadata without
        # re-calling the model; this is an idempotent registry repair, not a content rewrite.
        changed = False
        for key, row in themes.items():
            if row.get("basis") == "enriched" and row.get("flavor") and not row.get("flavorProvenance"):
                row["flavorProvenance"] = {
                    "pipeline": "theme-enrich", "model": getattr(config, "model", "unknown"),
                    "promptVersion": PROMPT_VERSION, "finding": f"theme-enrich:{key}",
                }
                changed = True
        if changed:
            _atomic_write(registry_path, doc)
    # Completion is a registry property, not a ledger property: blocked/escalated subjects are
    # terminal for resume but still leave a name-basis theme that the item planner must hold.
    remaining = plan(registry_path)
    return {"planned": len(held), "pending": len(pending), "enriched": enriched,
            "blocked": blocked, "escalated": escalated, "remaining": len(remaining),
            "complete": not remaining}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Enrich name-only creature themes for item generation.")
    ap.add_argument("--dry-run", action="store_true", help="report held themes without calling a model")
    ap.add_argument("--write", action="store_true", help="persist accepted lore and ledger rows")
    ap.add_argument("--endpoint", default="")
    ap.add_argument("--model", default="")
    args = ap.parse_args(argv)
    if args.dry_run or not args.write:
        print(json.dumps({"planned": len(plan()), "write": False}, ensure_ascii=False, indent=2))
        return 0
    from ...pipeline.llm_caller import resolve_live_transport
    transport = resolve_live_transport(args.endpoint, args.model)
    if not transport.endpoint:
        print("theme-enrich refused: no model endpoint", flush=True)
        return 2
    print(json.dumps(enrich(config=transport, write=True), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
