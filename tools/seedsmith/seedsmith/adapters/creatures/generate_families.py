"""Real-run entrypoint for the family sub-pipeline (D2.1 extract + D2.2 consolidate).

**Why this exists.** Until now the family pipeline had *no committed entrypoint at all* — `extract.py`
and `consolidate.py` were library modules whose only callers were tests. The 2026-08-31 real run used
scratch scripts that live nowhere, so `family-candidates.json`, `families.v1.json` and
`family-assignments.json` were committed artifacts **nothing in the repo could reproduce**.

That is the third instance of one defect: G1.3 recorded it for motifs (*"There was no committed
generation entrypoint at all"*) and G4.3 fixed it for commander effects. This closes it for families.

⛔ **The append-only window is CLOSED, and this tool refuses accordingly.**

G1.3's own note said regeneration was safe *"only because nothing is bound to them — all 84 creatures
currently have zero generated content. **This window closes when G4 writes its first row.**"*
G4 has since written 84 commander effects, and the chain below is now load-bearing:

    families → motifs (inherit family pools) → themes (embed motifs) → commander effects
                                                                       (generated FROM motifs)

So a family id that moves or disappears silently invalidates committed, append-only content three
layers downstream. `--write` therefore refuses unless `--i-have-read-the-append-only-note` is also
passed, and consolidation always runs append-only against the existing registry.

Usage:
    python -m seedsmith.adapters.creatures.generate_families --dry-run   # batches + brief, no calls
    python -m seedsmith.adapters.creatures.generate_families             # runs, prints, writes nothing
"""
from __future__ import annotations

import argparse
import json
from ...workspace_roots import seed_root  # noqa: E402
from pathlib import Path

from ...corpus.model import Corpus
from ...pipeline.llm_caller import resolve_live_transport
from .family.consolidate import FamilyCandidateInput, consolidate
from .family.extract import build_brief, extract_family_candidates, form_batches
from .kinds import CREATURE

__all__ = ["run", "CREATURES_ROOT"]

CREATURES_ROOT = seed_root() / "creatures"

#: Artifacts a rewrite would invalidate, and what is bound to them. Named so the refusal can say
#: exactly what is at stake rather than "unsafe".
_DOWNSTREAM = (
    ("_generated/motif-assignments.json", "motifs inherit each family's pool"),
    ("_registry/themes.v1.json", "themes embed the motifs derived from those families"),
    ("_registry/themes.v2.json", "species-gear-chain T16: v2 carries the same embedded motifs under corrected rarities — a family rewrite invalidates both registries"),
    ("commander-effect/all.json", "84 committed effects were generated FROM those motifs"),
)


def bound_artifacts(root: Path = CREATURES_ROOT) -> "list[tuple[str, str]]":
    """Downstream artifacts that already exist, i.e. the reasons a rewrite is no longer free."""
    return [(rel, why) for rel, why in _DOWNSTREAM if (root / rel).exists()]


def load_existing_registry(root: Path) -> "dict[str, dict] | None":
    path = root / "_registry" / "families.v1.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("families") or None


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Extract and consolidate creature families.")
    ap.add_argument("--dry-run", action="store_true",
                    help="show batching and one brief; make no model calls")
    ap.add_argument("--write", action="store_true", help="persist the artifacts (guarded)")
    ap.add_argument("--i-have-read-the-append-only-note", dest="ack", action="store_true",
                    help="required alongside --write once downstream content exists")
    ap.add_argument("--endpoint", default="")
    ap.add_argument("--model", default="")
    args = ap.parse_args(argv)

    corpus = Corpus.load(CREATURES_ROOT)
    entries = sorted(corpus.by_kind("creature"), key=lambda e: e.id)
    batches = form_batches(entries)

    bound = bound_artifacts()
    if args.write and bound and not args.ack:
        print("REFUSING TO WRITE — the append-only window is closed. These already depend on the "
              "current family ids:")
        for rel, why in bound:
            print(f"  - {rel}: {why}")
        print("\nRe-deriving families can move or drop an id, which silently invalidates all of the "
              "above. If that is genuinely intended, re-run with "
              "--i-have-read-the-append-only-note and regenerate the whole chain afterwards:\n"
              "  seedsmith creatures motifs\n"
              "  python -m seedsmith.adapters.creatures.generate_themes --rebuild\n"
              "  seedsmith creatures generate --kind commander-effect --stale")
        return 2

    print(json.dumps({"creatures": len(entries), "batches": len(batches),
                      "boundDownstream": [rel for rel, _ in bound]}, ensure_ascii=False))

    if args.dry_run:
        print("--- sample brief (batch 0) ---")
        print(build_brief(batches[0], creature_expression_rule=CREATURE.motif_expression or ""))
        return 0

    config = resolve_live_transport(args.endpoint, args.model)
    candidates = extract_family_candidates(
        entries, creature_expression_rule=CREATURE.motif_expression or "", config=config)

    flat = [FamilyCandidateInput(species_id=sid, label=c.label, native_label=c.native_label,
                                 basis=c.basis)
            for sid, cs in sorted(candidates.items()) for c in cs]
    result = consolidate(flat, existing_registry=load_existing_registry(CREATURES_ROOT))

    summary = {
        "creaturesWithCandidate": sum(1 for cs in candidates.values() if cs),
        "blocked": sum(1 for cs in candidates.values() if not cs),
        "families": len(result.families),
        "written": bool(args.write),
    }
    if args.write:
        # All THREE artifacts, or none. Writing only the candidates would leave
        # `families.v1.json` / `family-assignments.json` describing a different run than the
        # candidates beside them — exactly the cross-artifact staleness `themes.v1.json` already
        # taught this program once, and `motif-derive` reads all three.
        gen, reg = CREATURES_ROOT / "_generated", CREATURES_ROOT / "_registry"
        gen.mkdir(parents=True, exist_ok=True)
        reg.mkdir(parents=True, exist_ok=True)
        (gen / "family-candidates.json").write_text(
            json.dumps({sid: [c.__dict__ for c in cs] for sid, cs in sorted(candidates.items())},
                       ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (reg / "families.v1.json").write_text(
            json.dumps({"schemaVersion": 1, "registryVersion": 1,
                        "families": {k: result.families[k] for k in result.families}},
                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (gen / "family-assignments.json").write_text(
            json.dumps(result.assignments, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
